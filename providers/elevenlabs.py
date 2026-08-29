"""The live ElevenLabs sound-effect adapter.

Satisfies the same `Provider` contract SpriteLab does, but the provider
underneath behaves differently in two ways that the core has to be told about
rather than shielded from.

**It is synchronous.** `POST /v1/sound-generation` returns the audio in the
response body. There is no job to poll and no ID to recover, so the async shape
of the contract is bridged here: `submit` performs the call and holds the result
in memory, `poll` reports it already finished, and `collect` hands it over. The
consequence is stated plainly in `submit`: a process that dies between the call
returning and the caller persisting the bytes has spent a generation it cannot
get back, because there is nothing left to ask for. Callers persist immediately.

**It bills in credits, by the second.** Ten credits per second of *requested*
duration, measured on 2026-08-22 and reported by the endpoint itself in a
`character-cost` header on every response. The Starter plan includes 40,000 of
them per month.

That rate is why the unit here is credits and not calls. The plan originally
described "150 included generations at $0.04 each", which is the same 40,000
credits divided by an assumed 267 per call -- and 267 credits is a 26.7-second
sound. At the 800 ms the design package actually calls for, the allowance holds
five thousand. An estimate that counted calls would have priced an 800 ms cue and
a 30 s bed identically and been wrong about both by a factor of nearly forty.

`estimate` reports credits, and `currency_estimate` reports dollars only when
dollars can actually be owed -- reserving the worst case whenever the remaining
allowance is unknown, because reporting $0 on the assumption that quota is
available is how a budget stops bounding anything.

**Probed 2026-08-22.** Request and response shapes, the cost model, and the
`character-cost` header are all observed rather than inferred. See
docs/development/elevenlabs-probe.md. What remains unread is the terms, for
attribution and exclusivity, so both are still recorded as unknown.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_UP, Decimal, InvalidOperation
from typing import Any

from media import Rejected, audio_kind, inspect_audio
from providers.base import (
    AmbiguousOutcome,
    AuthenticationFailed,
    Candidate,
    CandidateProvenance,
    Estimate,
    GenerationRequest,
    JobStatus,
    ProviderError,
    ProviderRejected,
    RateLimited,
    Stage,
    SubmissionReceipt,
)
from providers.transport import (
    Response,
    Transport,
    TransportError,
    UrllibTransport,
    redact,
)

UTC = timezone.utc

BASE_URL = "https://api.elevenlabs.io/v1"
KEY_ENV_VAR = "ELEVENLABS_API_KEY"

#: ElevenLabs authenticates with its own header, not a bearer token.
AUTH_HEADER = "xi-api-key"

#: **The published rate, deliberately chosen over our own measurement.**
#:
#: ElevenLabs documents 40 credits per second of requested duration, and its
#: pricing FAQ quotes 200 credits per generation -- consistent with each other at
#: a five-second default. The probe on 2026-08-22 measured a quarter of that: the
#: endpoint reported `character-cost: 8` and `character-cost: 40` for 800 ms and
#: 4000 ms, and the account's own usage counter moved by exactly 56 across both
#: calls, corroborating the headers rather than merely repeating them.
#:
#: Both observations are sound and they disagree by 4x. The product owner chose
#: the published figure on 2026-08-22, and the choice is the safe one in the only
#: direction that matters: an estimate four times the actual charge over-reserves
#: and blocks early, where the reverse would authorise a run it could not pay
#: for. `reported_charge` still records what the header says, so the ledger keeps
#: measuring the truth while the estimate bounds it.
#:
#: **Do not "correct" this back to 10 on the strength of the probe.** The probe is
#: right about what was billed and this constant is not trying to be. See
#: docs/development/elevenlabs-probe.md section 8.
CREDITS_PER_SECOND = Decimal(40)

#: 30,000 from the Starter plan plus 10,000 grandfathered from the free tier at
#: upgrade, confirmed by the product owner on 2026-08-22 -- which is why the
#: account reads 40,000 while the pricing page advertises Starter as 30,000.
#: At the published rate an 800 ms sound costs 32 credits, so the allowance holds
#: 1,250 of them. The plan's original "150 included generations" described a
#: 26.7-second sound, which is not something this product makes.
INCLUDED_CREDITS = 40_000
USD_PER_CREDIT = Decimal("0.00015")
RATE_OBSERVED_AT = datetime(2026, 8, 22, tzinfo=UTC)

#: The header the endpoint reports its own charge in. Recording what a provider
#: states beats inferring it, and this one states it on every response.
COST_HEADER = "character-cost"

#: Confirmed 2026-08-22 by the product owner, from the paid subscription
#: agreement: every paid tier conveys **ownership of the generated files** with a
#: full commercial licence and **no attribution requirement**. The public
#: help-centre page reaches only as far as "subject to the agreement you have
#: with ElevenLabs", so this rests on the agreement itself rather than on that
#: page -- which is exactly the distinction `terms_reviewed_at` exists to carry.
#:
#: Materially exclusive in the sense scope D17 tracks: the provider does not
#: publish these files and does not license them to anyone else. It is not a
#: warranty that no similar audio can ever be generated, and no generative
#: provider offers one.
DEFAULT_ACCOUNT_RIGHTS = "paid_commercial_exclusive"
DEFAULT_TERMS_REVIEWED = date(2026, 8, 22)

#: Carried until someone reads the terms for an attribution clause. Recording
#: `attribution_required=False` would be a claim, and nobody has checked; this
#: travels into the export so a downstream reader sees the gap rather than a
#: reassurance.


#: The API takes seconds; the core speaks milliseconds.
MIN_DURATION_MS = 500
MAX_DURATION_MS = 30_000

MAX_AUDIO_BYTES = 16 * 1024 * 1024


class MissingCredential(ProviderError):
    """No key was supplied and none is in the environment."""


def load_key(env_var: str = KEY_ENV_VAR) -> str:
    """Read the operator credential from the environment.

    Never a file this module reads, never a default, and never anything the
    browser can reach.
    """
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise MissingCredential(
            f"{env_var} is not set. It is a local operator credential: export it in "
            f"the shell that runs the command, and never commit it."
        )
    return key


@dataclass
class ElevenLabs:
    """The live sound-effect adapter. One instance per key."""

    key: str | None = None
    transport: Transport = field(default_factory=UrllibTransport)
    base_url: str = BASE_URL
    account_rights: str = DEFAULT_ACCOUNT_RIGHTS
    terms_reviewed_at: date = DEFAULT_TERMS_REVIEWED
    timeout_seconds: float = 120.0

    credits_per_second: Decimal = CREDITS_PER_SECOND
    usd_per_credit: Decimal = USD_PER_CREDIT
    rate_observed_at: datetime = RATE_OBSERVED_AT

    name: str = "elevenlabs"
    #: Credits, because credits are what the endpoint decrements and reports.
    #: This was `elevenlabs_generations` while a "generation" looked like the
    #: meter; the probe showed it was 40,000 credits divided by an assumption.
    unit: str = "elevenlabs_credits"
    currency_unit: str = "usd"
    stages: tuple[Stage, ...] = ("sound",)
    #: The endpoint selects its own model. Recording "unknown" would imply we
    #: failed to look for a parameter that is not offered.
    model: str | None = None

    #: Results held between `submit` and `collect`, since the provider keeps none.
    _results: dict[str, tuple[GenerationRequest, bytes, dict[str, Any]]] = field(
        default_factory=dict, repr=False
    )

    def supports(self, stage: Stage) -> bool:
        return stage in self.stages

    # -- Contract ---------------------------------------------------------

    def credits_for(self, duration_ms: int | None) -> Decimal:
        """What a sound of this length costs, at `credits_per_second`.

        Priced by requested duration, with no per-call component -- the one thing
        the probe established that nothing since has disputed. A request that
        names no duration is priced at the maximum the endpoint accepts: the
        provider chooses the length in that case, and an estimate has to bound
        what it might choose rather than guess low.
        """
        effective = MAX_DURATION_MS if duration_ms is None else duration_ms
        return (Decimal(effective) / 1000 * self.credits_per_second).quantize(Decimal(1))

    def estimate(self, request: GenerationRequest) -> Estimate:
        """The bounded maximum in credits, which is what the provider meters.

        Credits, not calls. The cost of a sound is proportional to its length, so
        an estimate that counted calls would price an 800 ms cue and a 30 s bed
        identically -- and be wrong about both by a factor of nearly forty.
        """
        self._check_stage(request.stage)
        return Estimate(
            unit=self.unit,
            maximum_amount=self.credits_for(request.duration_ms) * request.candidate_count,
            call_count=request.candidate_count,
            pricing_snapshot_at=self.rate_observed_at,
        )

    def currency_estimate(
        self, request: GenerationRequest, *, included_remaining: int | None = None
    ) -> Estimate | None:
        """Dollars that could actually be owed, or None when none can be.

        `included_remaining` is credits, and is provider-side state, so it is
        passed in rather than assumed. When it is unknown the whole batch is
        priced as overage: reporting no exposure on the assumption that allowance
        is available would make the ceiling stop bounding anything, and an
        included allowance is evidence of an entitlement, not evidence that it is
        still unspent.
        """
        self._check_stage(request.stage)
        credits = self.credits_for(request.duration_ms) * request.candidate_count
        billable = (
            credits
            if included_remaining is None
            else max(Decimal(0), credits - max(0, included_remaining))
        )
        if billable <= 0:
            return None
        return Estimate(
            unit=self.currency_unit,
            # Quantised up: a fraction of a cent is still money, and an estimate
            # that floors it would bound the batch at less than it can cost.
            maximum_amount=max(
                Decimal("0.01"),
                (billable * self.usd_per_credit).quantize(Decimal("0.01"), rounding=ROUND_UP),
            ),
            call_count=request.candidate_count,
            pricing_snapshot_at=self.rate_observed_at,
        )

    def remaining_allowance(self) -> tuple[int | None, str]:
        """Included *credits* left, and why if the answer is unknown.

        This used to say generations, and reported "39,992 generations remaining
        of 150" -- a number in one unit against a limit in another. The widened
        key is what made the nonsense visible.

        A 401 here does not mean the credential is broken. The security guidance
        for this key is to restrict it to Sound Effects, and a key scoped that
        narrowly cannot read `/user/subscription` -- so the safest key produces
        the least readable quota. The two requirements genuinely conflict, and
        the resolution is to price every generation as overage rather than to
        widen the key's permissions for the sake of a nicer estimate.
        """
        try:
            subscription = self.subscription()
        except AuthenticationFailed:
            return None, (
                "the key cannot read /user/subscription. If it is scoped to Sound "
                "Effects only, that is expected and correct: keep the narrow key and "
                "price every generation as overage."
            )
        except ProviderError as exc:
            return None, f"the allowance could not be read ({exc})"

        for used_key, limit_key in (
            ("character_count", "character_limit"),
            ("generations_used", "generations_limit"),
        ):
            used, limit = subscription.get(used_key), subscription.get(limit_key)
            if isinstance(used, int) and isinstance(limit, int):
                return max(0, limit - used), "read from /user/subscription"
        return None, "the subscription response did not report usage in a recognised shape"

    def credit_usage(self) -> tuple[int, int] | None:
        """`(used, limit)` in credits, or None when the key cannot read it.

        The same `/user/subscription` fields `remaining_allowance` derives from,
        returned raw. A cost measurement needs the absolute figures on both sides
        of a call, not the difference between two remainders, because a period
        rollover between them would look like a refund.
        """
        try:
            subscription = self.subscription()
        except ProviderError:
            return None

        for used_key, limit_key in (
            ("character_count", "character_limit"),
            ("credits_used", "credits_limit"),
            ("generations_used", "generations_limit"),
        ):
            used, limit = subscription.get(used_key), subscription.get(limit_key)
            if isinstance(used, int) and isinstance(limit, int):
                return used, limit
        return None

    def subscription(self) -> dict[str, Any]:
        """Plan and usage from the free `/user/subscription` endpoint.

        Costs nothing, so it is the right thing to call first: it proves the
        credential works and reports how much of the included allowance is left,
        which is the one number `currency_estimate` cannot derive on its own.
        """
        return self._decode(self._send("GET", "/user/subscription"))

    def submit(self, request: GenerationRequest) -> SubmissionReceipt:
        """Generate the sound. This call *is* the generation.

        The provider returns audio rather than a job, so there is nothing to
        recover afterwards: if this process dies before the caller persists the
        bytes, a generation has been spent that cannot be asked for again.
        Persist what `collect` returns immediately.
        """
        self._check_stage(request.stage)
        if request.candidate_count != 1:
            raise ProviderRejected(
                f"elevenlabs: /sound-generation returns one sound per call, so "
                f"candidate_count must be 1, not {request.candidate_count}. Submit "
                f"{request.candidate_count} runs instead; each spends its own generation."
            )
        duration_ms = self._check_duration(request.duration_ms)

        payload: dict[str, Any] = {"text": request.prompt}
        if duration_ms is not None:
            payload["duration_seconds"] = round(duration_ms / 1000, 3)

        response = self._send("POST", "/sound-generation", payload)
        audio = self._audio(response)

        submitted_at = datetime.now(UTC)
        job_id = self._job_id(request, submitted_at)
        vendor = {
            "request_id": response.header("request-id") or response.header("x-request-id"),
            "content_type": response.header("Content-Type"),
            "duration_ms_requested": duration_ms,
            "audio_bytes": len(audio),
            # There is no provider-side job. Saying so is better than implying one
            # exists and could be polled.
            "synchronous": True,
            # Every response header, verbatim. This provider has had no probe, so
            # what it reports about cost is not yet known -- and the cheapest way
            # to find out is to keep what it already sends rather than to spend a
            # generation guessing. Authorization is dropped rather than redacted,
            # because it is ours and echoing it back proves nothing.
            **{
                f"header.{name.lower()}": value
                for name, value in response.headers.items()
                if name.lower() not in ("authorization", AUTH_HEADER)
            },
        }
        self._results[job_id] = (request, audio, vendor | {"media_kind": audio_kind(audio)})

        return SubmissionReceipt(
            job_id=job_id,
            submitted_at=submitted_at,
            raw={k: v for k, v in vendor.items() if v is not None},
        )

    def poll(self, job_id: str) -> JobStatus:
        """Already finished, or never started in this process.

        A job ID from an earlier process cannot be polled: the provider kept no
        record of it. That is reported as unknown rather than failed, because a
        generation may well have been spent.
        """
        if job_id not in self._results:
            raise ProviderRejected(
                f"elevenlabs: {job_id} is not held by this process. Sound generation is "
                f"synchronous, so there is no job to recover -- if it was submitted and "
                f"its audio was not persisted, the generation is spent and unrecoverable."
            )
        _, _, vendor = self._results[job_id]
        return JobStatus(job_id=job_id, state="succeeded", refunded=False, raw=dict(vendor))

    def collect(
        self,
        job_id: str,
        *,
        submitted_at: datetime | None = None,
        transforms: tuple[str, ...] = (),
    ) -> tuple[Candidate, ...]:
        """The generated sound, already validated when it arrived."""
        if job_id not in self._results:
            raise ProviderRejected(
                f"elevenlabs: {job_id} is not held by this process; results are only "
                f"available from the call that produced them"
            )
        request, audio, vendor = self._results[job_id]

        return (
            Candidate(
                candidate_id=self._candidate_id(job_id),
                media=audio,
                # What the bytes are, not what was asked for. The endpoint
                # returns MPEG; labelling it wav stores it under an extension its
                # own validator then refuses -- after the generation is paid for.
                media_kind=vendor.get("media_kind", "mp3"),
                provenance=CandidateProvenance(
                    provider=self.name,
                    model=self.model,
                    generated_at=submitted_at or datetime.now(UTC),
                    account_rights=self.account_rights,
                    terms_reviewed_at=self.terms_reviewed_at,
                    # None required, confirmed from the paid subscription
                    # agreement. This was True while the published page left it
                    # "subject to the agreement"; reading the agreement is what
                    # turned an open question into an answer.
                    attribution_required=False,
                    prompt=request.prompt,
                    transforms=transforms,
                    vendor=dict(vendor)
                    | {"job_id": job_id, "vendor_candidate_id": vendor.get("request_id") or job_id},
                ),
                # One generation, metered natively. Whether it also cost dollars
                # depends on allowance the provider does not report per call, so
                # the currency figure is never asserted here.
                # What the endpoint said it charged, from its own header. An
                # inferred figure was never necessary here: it reports one on
                # every response, and nobody had looked.
                reported_charge=self._reported_credits(vendor),
                charge_unit=self.unit,
            ),
        )

    # -- Internals --------------------------------------------------------

    @staticmethod
    def _reported_credits(vendor: dict[str, Any]) -> Decimal | None:
        """The charge the provider stated, or None if this response did not.

        None is unknown, never zero. A response that omits the header has not
        told us the sound was free, and the ledger has to keep its reserve.
        """
        raw = vendor.get(f"header.{COST_HEADER}")
        try:
            return Decimal(str(raw))
        except (InvalidOperation, TypeError):
            return None

    def _check_stage(self, stage: Stage) -> None:
        if not self.supports(stage):
            raise ProviderRejected(f"elevenlabs does not perform {stage} work")

    @staticmethod
    def _check_duration(duration_ms: int | None) -> int | None:
        if duration_ms is None:
            return None
        if not MIN_DURATION_MS <= duration_ms <= MAX_DURATION_MS:
            raise ProviderRejected(
                f"elevenlabs: {duration_ms}ms is outside the accepted "
                f"{MIN_DURATION_MS}-{MAX_DURATION_MS}ms range"
            )
        return duration_ms

    @staticmethod
    def _job_id(request: GenerationRequest, at: datetime) -> str:
        """A local handle, not a provider job. Named so nobody expects to poll it."""
        import hashlib

        digest = hashlib.sha256(
            f"{request.prompt}|{request.duration_ms}|{at.isoformat()}".encode()
        ).hexdigest()[:16]
        return f"local_{digest}"

    @staticmethod
    def _candidate_id(job_id: str) -> str:
        safe = "".join(c for c in job_id.lower() if c.isalnum())[:20] or "sound"
        return f"cand_{safe}_00"

    def _send(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Response:
        import json

        key = self.key if self.key is not None else load_key()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            AUTH_HEADER: key,
            "Accept": "audio/mpeg, application/json",
            **({"Content-Type": "application/json"} if body else {}),
        }
        try:
            return self.transport.send(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                body=body,
                timeout=self.timeout_seconds,
            )
        except TransportError as exc:
            if method == "POST":
                # The generation may have run and been metered. There is no job to
                # ask about, so this is unknown rather than failed, and must never
                # be retried on the assumption that it did not happen.
                raise AmbiguousOutcome(
                    f"elevenlabs: the generation could not be completed and its outcome "
                    f"is unknown ({redact(str(exc))}). Do not resubmit; check the usage "
                    f"reported by /user/subscription.",
                    job_id=None,
                ) from exc
            raise ProviderError(f"elevenlabs: {redact(str(exc))}") from exc

    def _audio(self, response: Response) -> bytes:
        """The returned audio, bounded and sniffed before anything decodes it."""
        self._raise_for_status(response, submitting=True)

        payload = response.body
        if not payload:
            raise AmbiguousOutcome(
                "elevenlabs: the response carried no audio, so it cannot be established "
                "whether a generation was spent. Do not resubmit; check reported usage.",
                job_id=None,
            )
        # Everything below this line is validating a response to a call that has
        # already run. A plain ProviderError would be read as a pre-submission
        # refusal and release the reserve, so these are ambiguous: the generation
        # was almost certainly metered, and the bytes are unusable.
        if len(payload) > MAX_AUDIO_BYTES:
            raise AmbiguousOutcome(
                f"elevenlabs: returned {len(payload)} bytes of audio, over the "
                f"{MAX_AUDIO_BYTES}-byte limit. The generation may already have been "
                f"metered; do not resubmit until reported usage is checked.",
                job_id=None,
            )
        try:
            inspect_audio(payload)
        except Rejected as exc:
            raise AmbiguousOutcome(
                f"elevenlabs: the response body is not usable audio ({exc}). The "
                f"generation may already have been metered; do not resubmit until "
                f"reported usage is checked.",
                job_id=None,
            ) from exc
        return payload

    def _decode(self, response: Response) -> dict[str, Any]:
        self._raise_for_status(response, submitting=False)
        try:
            return response.json()
        except TransportError as exc:
            raise ProviderError(f"elevenlabs: {redact(str(exc))}") from exc

    def _raise_for_status(self, response: Response, *, submitting: bool) -> None:
        """Sort the status by whether a retry is safe, and whether it may have cost."""
        if response.status in (401, 403):
            raise AuthenticationFailed(
                f"elevenlabs: authentication failed ({response.status}). Check "
                f"{KEY_ENV_VAR} and that the key permits Sound Effects."
            )
        if response.status == 429:
            raise RateLimited(
                "elevenlabs: rate limited or out of quota",
                retry_after_seconds=self._retry_after(response),
            )
        if 400 <= response.status < 500:
            # Refused before generating. Nothing was made and nothing was metered.
            raise ProviderRejected(
                f"elevenlabs: request refused ({response.status}): {self._body_hint(response)}"
            )
        if response.status >= 500:
            if submitting:
                raise AmbiguousOutcome(
                    f"elevenlabs: the generation returned {response.status} and its outcome "
                    f"cannot be established. Do not resubmit; check reported usage.",
                    job_id=None,
                )
            raise ProviderError(
                f"elevenlabs: server error ({response.status}): {self._body_hint(response)}"
            )

    @staticmethod
    def _retry_after(response: Response) -> float | None:
        raw = response.header("Retry-After")
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    @staticmethod
    def _body_hint(response: Response) -> str:
        return redact(response.body[:500].decode("utf-8", "replace"))
