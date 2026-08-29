"""The live SpriteLab adapter.

Talks to `https://spritelab.dev/api/v1` and satisfies the same `Provider`
contract the fakes do, so the core never learns which of them it is holding.

Everything here was verified against the real endpoint during the pre-E1 probe
(`docs/development/spritelab-probe.md`), including the parts that were not what
the design package assumed:

- **The output canvas equals the input canvas.** Framing is decided before
  submission and cannot be fixed afterwards, so this refuses anything that has
  not been through `transforms.prepare_submission`.
- **`fps` is not a request parameter.** The API returns 8 regardless. It is
  recorded as returned, never as requested.
- **Input is capped at 256 px per axis**, enforced here so a request that would
  certainly be refused never becomes a paid call.
- **A per-job charge is not reported.** The probe established its cost from a
  balance delta. `reported_charge` is therefore `None` -- which the ledger reads
  as *unknown*, not as zero, and that is the honest reading.

Nothing here retries a generation. `AmbiguousOutcome` exists so a caller that
cannot establish what happened is forced to decide rather than resubmit, because
a retry is a second charge for work that may already have succeeded.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from media import (
    GIF_SIGNATURES,
    MAX_FILE_BYTES,
    PNG_SIGNATURE,
    Rejected,
    inspect_gif,
    inspect_png,
)
from providers.base import (
    AmbiguousOutcome,
    AuthenticationFailed,
    Candidate,
    CandidateProvenance,
    Estimate,
    GenerationRequest,
    JobState,
    JobStatus,
    MediaKind,
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

BASE_URL = "https://spritelab.dev/api/v1"
KEY_ENV_VAR = "SPRITELAB_API_KEY"

#: Confirmed 2026-08-21 and again by the probe's balance delta. A dated snapshot
#: is evidence of a past price, not authorisation to spend against a current one,
#: so the plan requires re-confirming it live before every run. Both the rate and
#: its observation date are constructor arguments for exactly that reason.
CREDITS_PER_ANIMATION = Decimal(20)
RATE_OBSERVED_AT = datetime(2026, 8, 21, tzinfo=UTC)

#: SpriteLab's /animate produces one animation per job. A batch is therefore N
#: submissions, each with its own job ID and its own reserve -- not one call
#: asking for N results.
CANDIDATES_PER_JOB = 1

#: The documented cap. The real endpoint refuses anything larger.
MAX_INPUT_AXIS = 256

#: Not settable upstream. Recorded as what came back, never as what was asked.
RETURNED_FPS = 8

#: Rights context for the account this key belongs to. Paid-plan output is
#: private by default and SpriteLab claims no ownership of it; free-plan output is
#: public and non-exclusive (scope D17). The account moved to the paid `ranger`
#: tier on 2026-08-22.
#:
#: Configured rather than inferred from the reported tier. A tier-to-rights table
#: has to be maintained as tiers appear, and being out of date fails in the worst
#: direction -- claiming an exclusivity the account does not have. Whoever holds
#: the key states what it confers.
DEFAULT_ACCOUNT_RIGHTS = "spritelab_paid_private_exclusive"
DEFAULT_TERMS_REVIEWED = date(2026, 8, 22)

#: What each tier the API reports is known to confer. Used only to *contradict* a
#: configured value, never to supply one: an unrecognised tier says nothing, and
#: silence has to stay silent rather than defaulting to a grant.
TIER_IS_PAID: dict[str, bool] = {"squire": False, "ranger": True}

#: Rights values that assert exclusivity, and therefore require a paid tier.
EXCLUSIVE_RIGHTS = frozenset({"spritelab_paid_private_exclusive"})

#: Statuses that end a job. Anything else means "still working".
_TERMINAL: dict[str, JobState] = {
    "succeeded": "succeeded",
    "completed": "succeeded",
    "failed": "failed",
    "error": "failed",
    "cancelled": "failed",
    "canceled": "failed",
}


class MissingCredential(ProviderError):
    """No key was supplied and none is in the environment."""


def load_key(env_var: str = KEY_ENV_VAR) -> str:
    """Read the operator credential from the environment.

    Never a parameter with a default, never a file this module reads, and never
    anything the browser can reach. `PROJECT_PLAN.md` §6 is explicit that provider
    keys are local operator credentials rather than application assets.
    """
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise MissingCredential(
            f"{env_var} is not set. It is a local operator credential: export it in "
            f"the shell that runs the command, and never commit it."
        )
    return key


@dataclass
class SpriteLab:
    """The live adapter. One instance per key.

    `transport` is the seam: production gets `UrllibTransport`, the contract
    suite gets a recorded one, and neither changes a line of the logic between
    them.
    """

    key: str | None = None
    transport: Transport = field(default_factory=UrllibTransport)
    base_url: str = BASE_URL
    account_rights: str = DEFAULT_ACCOUNT_RIGHTS
    terms_reviewed_at: date = DEFAULT_TERMS_REVIEWED
    timeout_seconds: float = 60.0
    #: The rate, and when it was actually observed. Both are configurable because
    #: the plan requires re-confirming the live rate before every run: stamping a
    #: rate read weeks ago with today's date is exactly how a stale price comes to
    #: look freshly confirmed, and then bounds a spend it no longer bounds.
    credits_per_animation: Decimal = CREDITS_PER_ANIMATION
    rate_observed_at: datetime = RATE_OBSERVED_AT

    name: str = "spritelab"
    unit: str = "spritelab_credits"
    stages: tuple[Stage, ...] = ("animation",)
    #: /animate exposes no model parameter, so there is no model to record.
    #: "unknown" would imply we failed to look.
    model: str | None = None

    def supports(self, stage: Stage) -> bool:
        return stage in self.stages

    # -- Contract ---------------------------------------------------------

    def estimate(self, request: GenerationRequest) -> Estimate:
        """The bounded maximum for this batch, at the recorded rate.

        A maximum, not a prediction: the ledger reserves this whole figure until
        the work resolves, because money that may already have left counts before
        anyone confirms it did.
        """
        self._check_stage(request.stage)
        self._check_batch(request)
        return Estimate(
            unit=self.unit,
            maximum_amount=self.credits_per_animation * request.candidate_count,
            call_count=request.candidate_count,
            # When the rate was read, not when it was quoted. The ledger stores
            # this alongside the reserve, and a snapshot that always says "now"
            # can never be recognised as stale.
            pricing_snapshot_at=self.rate_observed_at,
        )

    def rights_disagree_with_tier(self) -> str | None:
        """Why the configured rights and the live account disagree, if they do.

        The one thing the reported tier is genuinely good for. Reading rights out
        of it would be wrong -- the table goes stale and stale fails toward
        over-claiming -- but reading it to *contradict* a configured value costs
        nothing and catches the expensive mistake: a pack about to export an
        exclusivity its account cannot support, because the key was pointed at a
        free account or the upgrade lapsed.

        Returns None when they agree, when the tier is unrecognised, or when it
        cannot be read. An unrecognised tier says nothing, and inventing a
        complaint from silence would train people to ignore this.
        """
        try:
            _, tier = self.credits()
        except ProviderError:
            return None
        if tier is None:
            return None

        is_paid = TIER_IS_PAID.get(tier.lower())
        if is_paid is None or is_paid:
            return None
        if self.account_rights in EXCLUSIVE_RIGHTS:
            return (
                f"this key reports tier {tier!r}, which is a free tier, but it is "
                f"configured as {self.account_rights!r}. Output generated now would be "
                f"public and non-exclusive, and the export would claim otherwise."
            )
        return None

    def credits(self) -> tuple[int, str | None]:
        """Balance and tier from the free `/credits` endpoint.

        Free in both senses, so it is the right thing to exercise first: it
        proves the credential works without spending anything to find out.
        """
        response = self._send("GET", "/credits")
        data = self._decode(response)
        balance = data.get("credits")
        if not isinstance(balance, int):
            raise ProviderError(f"spritelab: unexpected /credits shape: {redact(str(data))}")
        tier = data.get("tier")
        return balance, str(tier) if tier is not None else None

    def submit(self, request: GenerationRequest) -> SubmissionReceipt:
        """Start one animation job.

        Every bound the endpoint is known to enforce is checked here first, so a
        request that would certainly be refused never becomes a paid call and
        never has to be reasoned about as a possible charge.
        """
        self._check_stage(request.stage)
        self._check_batch(request)
        if request.source_png is None:
            raise ProviderRejected("spritelab: an animation needs a source image")

        width, height = self._check_source(request.source_png)
        if max(width, height) > MAX_INPUT_AXIS:
            raise ProviderRejected(
                f"spritelab: input is {width}x{height}, over the {MAX_INPUT_AXIS}px "
                f"per-axis limit. Run it through transforms.prepare_submission first: "
                f"the output canvas equals the input canvas, so framing cannot be "
                f"corrected after submission."
            )

        payload: dict[str, Any] = {
            "image_b64": base64.b64encode(request.source_png).decode("ascii"),
            "prompt": request.prompt,
        }
        if request.frames is not None:
            payload["frames"] = request.frames

        response = self._send("POST", "/animate", payload)
        data = self._decode_submission(response)

        job_id = data.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            # The request may well have been accepted and charged. Without an ID
            # there is nothing to poll and nothing to reconcile, so this is
            # ambiguous rather than failed -- and must never be auto-resubmitted.
            raise AmbiguousOutcome(
                "spritelab: the submission returned no job_id, so its outcome cannot be "
                "established. Do not resubmit; reconcile against the credit balance.",
                job_id=None,
            )

        return SubmissionReceipt(
            job_id=job_id,
            submitted_at=datetime.now(UTC),
            raw=self._raw(data),
        )

    def poll(self, job_id: str) -> JobStatus:
        """Ask once. Looping, waiting, and giving up belong to the caller."""
        response = self._send("GET", f"/jobs/{job_id}")
        data = self._decode(response, job_id=job_id)

        status = str(data.get("status", "")).lower()
        state = _TERMINAL.get(status, "running")
        return JobStatus(
            job_id=job_id,
            state=state,
            detail=self._detail(data) if state == "failed" else None,
            # A failed job never produces a candidate, so if the refund only rode
            # on one the ledger could never tell *failed and refunded* from
            # *failed and charged*. `None` stays unknown: absence of the field is
            # not a statement that nothing came back.
            refunded=self._refunded(data),
            raw=self._raw(data),
        )

    def collect(
        self,
        job_id: str,
        *,
        submitted_at: datetime | None = None,
        transforms: tuple[str, ...] = (),
    ) -> tuple[Candidate, ...]:
        """The finished assets, validated before anything decodes them.

        `submitted_at` and `transforms` come from the run record the caller
        persisted, and both exist because the adapter cannot recover them on its
        own. It receives bytes, not the history that produced them, and on a
        recovery it may be a different process entirely. Passing them keeps a
        collected candidate identical whichever process collects it, and keeps an
        export able to say what was actually submitted.
        """
        response = self._send("GET", f"/jobs/{job_id}")
        data = self._decode(response, job_id=job_id)

        status = str(data.get("status", "")).lower()
        state = _TERMINAL.get(status, "running")
        if state != "succeeded":
            raise ProviderRejected(
                f"spritelab: job {job_id} is {status or 'in progress'}; results are only "
                f"available once it succeeds"
            )

        sheet = self._asset(data, "sheet_b64", "png", job_id)
        if sheet is None:
            raise ProviderError(f"spritelab: job {job_id} succeeded but returned no spritesheet")

        return (
            Candidate(
                candidate_id=self._candidate_id(job_id),
                media=sheet,
                media_kind="png",
                provenance=self._provenance(
                    data, job_id, submitted_at=submitted_at, transforms=transforms
                ),
                # SpriteLab states no per-job figure. None is unknown, not zero,
                # and the ledger keeps the reserve until a human reconciles it
                # against the balance.
                reported_charge=None,
                charge_unit=None,
                refunded=bool(self._refunded(data)),
            ),
        )

    def preview_gif(self, job_id: str) -> bytes | None:
        """The optional preview, when the job returned one.

        Not a candidate: the review player is canvas frame-stepping, and a GIF
        gives neither scrubbing nor markers. It is kept for the run record only.
        """
        data = self._decode(self._send("GET", f"/jobs/{job_id}"), job_id=job_id)
        return self._asset(data, "gif_b64", "gif", job_id)

    # -- Internals --------------------------------------------------------

    def _check_stage(self, stage: Stage) -> None:
        if not self.supports(stage):
            raise ProviderRejected(f"spritelab does not perform {stage} work")

    def _check_batch(self, request: GenerationRequest) -> None:
        """One job, one animation.

        `/animate` has no batch parameter and returns a single result, so a
        request for three candidates cannot be served by one call. Accepting it
        silently would reserve three candidates' worth of credits and deliver
        one, and the run would look complete while missing two thirds of what it
        paid to reserve. Three candidates is three runs, each with its own job ID
        to persist and its own reserve to settle.
        """
        if request.candidate_count != CANDIDATES_PER_JOB:
            raise ProviderRejected(
                f"spritelab: /animate returns one animation per job, so "
                f"candidate_count must be {CANDIDATES_PER_JOB}, not "
                f"{request.candidate_count}. Submit {request.candidate_count} runs instead; "
                f"each gets its own job ID to persist and its own reserve."
            )

    def _send(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        accept: str = "application/json",
    ) -> Response:
        import json

        key = self.key if self.key is not None else load_key()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": accept,
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
            # A transport failure on a GET is safe to retry. On a POST it is not:
            # the request may have been received and charged, and the caller has
            # no job ID with which to find out.
            if method == "POST":
                raise AmbiguousOutcome(
                    f"spritelab: the submission could not be completed and its outcome is "
                    f"unknown ({redact(str(exc))}). Do not resubmit; reconcile against the "
                    f"credit balance.",
                    job_id=None,
                ) from exc
            raise ProviderError(f"spritelab: {redact(str(exc))}") from exc

    def _decode_submission(self, response: Response) -> dict[str, Any]:
        """Decode a POST response, where "failed" and "unknown" are different.

        A 4xx is a pre-submission refusal: the request was rejected, nothing was
        made and nothing was charged, so it is safe to fix and resubmit. Anything
        else -- a 5xx, a body that is not JSON, a truncated response -- may have
        been accepted and charged, and carries no job ID to check. Those are
        ambiguous, and an ambiguous outcome must never be auto-resubmitted,
        because a retry is a second charge for work that may already have
        succeeded.
        """
        try:
            return self._decode(response)
        except (ProviderRejected, AuthenticationFailed, RateLimited):
            # Refused before any work began. Nothing was spent.
            raise
        except ProviderError as exc:
            raise AmbiguousOutcome(
                f"spritelab: the submission returned {response.status} and its outcome "
                f"cannot be established ({exc}). Do not resubmit; reconcile against the "
                f"credit balance.",
                job_id=None,
            ) from exc

    def _decode(self, response: Response, *, job_id: str | None = None) -> dict[str, Any]:
        """Map the HTTP status onto the contract's error vocabulary.

        The distinction the core cares about is not which vendor failed but
        whether a retry is safe, so every status is sorted by that question.
        """
        if response.status in (401, 403):
            raise AuthenticationFailed(
                f"spritelab: authentication failed ({response.status}). Check "
                f"{KEY_ENV_VAR} and the key's permissions."
            )
        if response.status == 429:
            raise RateLimited(
                "spritelab: rate limited",
                retry_after_seconds=self._retry_after(response),
            )
        if response.status == 404 and job_id is not None:
            raise ProviderRejected(f"spritelab: unknown job {job_id}")
        if 400 <= response.status < 500:
            raise ProviderRejected(
                f"spritelab: request refused ({response.status}): {self._body_hint(response)}"
            )
        if response.status >= 500:
            raise ProviderError(
                f"spritelab: server error ({response.status}): {self._body_hint(response)}"
            )

        try:
            return response.json()
        except TransportError as exc:
            raise ProviderError(f"spritelab: {redact(str(exc))}") from exc

    @staticmethod
    def _retry_after(response: Response) -> float | None:
        raw = response.header("Retry-After")
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    @staticmethod
    def _body_hint(response: Response) -> str:
        """A short, redacted excerpt. Enough to diagnose, never enough to leak."""
        return redact(response.body[:500].decode("utf-8", "replace"))

    @staticmethod
    def _refunded(data: dict[str, Any]) -> bool | None:
        """What the provider said about a refund, or None for said nothing.

        SpriteLab refunds a provider-side failure automatically, but the probe's
        successful response carried no `refunded` field at all -- so a missing
        field means unknown, and reading it as False would assert a charge the
        provider never confirmed.
        """
        value = data.get("refunded")
        return bool(value) if isinstance(value, bool) else None

    @staticmethod
    def _detail(data: dict[str, Any]) -> str:
        for key in ("error", "detail", "message", "reason"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return redact(value)
        return "generation failed upstream"

    def _asset(
        self, data: dict[str, Any], field_name: str, kind: MediaKind, job_id: str
    ) -> bytes | None:
        """Decode one returned asset, bounding it before anything else reads it.

        The filename is never the provider's: a provider-supplied name can carry
        path separators or traversal segments, so callers name what they write.
        """
        encoded = data.get(field_name)
        if not isinstance(encoded, str) or not encoded:
            return None

        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderError(
                f"spritelab: job {job_id} returned {field_name} that is not valid base64"
            ) from exc

        if len(payload) > MAX_FILE_BYTES:
            raise ProviderError(
                f"spritelab: job {job_id} returned a {kind} of {len(payload)} bytes, over "
                f"the {MAX_FILE_BYTES}-byte media limit"
            )
        signature = PNG_SIGNATURE if kind == "png" else GIF_SIGNATURES
        if not payload.startswith(signature):
            raise ProviderError(
                f"spritelab: job {job_id} returned {field_name} whose bytes are not a {kind}"
            )

        inspect = inspect_png if kind == "png" else inspect_gif
        try:
            inspect(payload)
        except Rejected as exc:
            raise ProviderError(
                f"spritelab: job {job_id} returned a {kind} that failed validation: {exc}"
            ) from exc
        return payload

    @staticmethod
    def _candidate_id(job_id: str) -> str:
        """An Emberforge stable ID, derived from the provider's job.

        The provider's own identifiers are opaque and may begin with anything;
        approvals type `candidate_id` as `StableId`, so the adapter mints the
        stable form and keeps the vendor's identifiers in `provenance.vendor`.
        """
        safe = "".join(c for c in job_id.lower() if c.isalnum())[:16] or "job"
        return f"cand_{safe}_00"

    def _provenance(
        self,
        data: dict[str, Any],
        job_id: str,
        *,
        submitted_at: datetime | None,
        transforms: tuple[str, ...],
    ) -> CandidateProvenance:
        generated_at, basis = self._generated_at(data, submitted_at)
        return CandidateProvenance(
            provider=self.name,
            model=self.model,
            generated_at=generated_at,
            account_rights=self.account_rights,
            terms_reviewed_at=self.terms_reviewed_at,
            attribution_required=False,
            # What was done to the source on the way in. An export claiming no
            # transform occurred cannot reproduce what was actually submitted,
            # and the submission path always scales and pads.
            transforms=transforms,
            vendor=self._raw(data)
            | {
                "job_id": job_id,
                "vendor_candidate_id": job_id,
                "generated_at_basis": basis,
            },
        )

    @staticmethod
    def _generated_at(data: dict[str, Any], submitted_at: datetime | None) -> tuple[datetime, str]:
        """When the work happened, preferring what the provider says.

        Collection time is the wrong answer and the tempting one: it makes the
        same job produce different provenance on every collect, and stamps a job
        recovered next week with next week's date. The provider's own timestamp
        is best, the persisted submission time is next, and falling back to now is
        last -- so the basis is recorded alongside, because a date whose origin is
        unknown cannot be audited.
        """
        for key in ("completed_at", "finished_at", "created_at", "submitted_at"):
            raw = data.get(key)
            if isinstance(raw, str) and raw:
                try:
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
                return (
                    parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC),
                    f"provider.{key}",
                )
        if submitted_at is not None:
            return submitted_at, "run_record.submitted_at"
        return datetime.now(UTC), "collection_time"

    @staticmethod
    def _raw(data: dict[str, Any]) -> dict[str, Any]:
        """The vendor record, without the payloads.

        Base64 assets are megabytes and are already held as decoded media; keeping
        them here too would put the whole spritesheet into every provenance record.
        """
        return {k: v for k, v in data.items() if not k.endswith("_b64")}

    @staticmethod
    def _check_source(payload: bytes) -> tuple[int, int]:
        """The whole source contract, before a byte is base64-expanded and sent.

        Dimensions alone are not the contract. A tiny PNG can still carry
        arbitrarily large ancillary chunks, and an APNG opens happily and hands
        back its first frame -- so a multi-frame file would be silently reduced
        to one on its way to a paid endpoint, and nobody would learn the rest had
        been discarded. Design package §7 accepts only a still PNG.
        """
        if len(payload) > MAX_FILE_BYTES:
            raise ProviderRejected(
                f"spritelab: source is {len(payload)} bytes, over the {MAX_FILE_BYTES}-byte limit"
            )
        if not payload.startswith(PNG_SIGNATURE):
            raise ProviderRejected("spritelab: a source sprite must be a PNG")

        try:
            width, height, frames = inspect_png(payload)
        except Rejected as exc:
            raise ProviderRejected(f"spritelab: source image rejected: {exc}") from exc

        if frames > 1:
            raise ProviderRejected(
                f"spritelab: a source sprite must be a still image; this PNG declares "
                f"{frames} frames, and only the first would reach the provider"
            )
        return width, height


# --------------------------------------------------------------------------
# Source generation: POST /generate
# --------------------------------------------------------------------------

#: What `/generate` charges, by quality. Read from the API documentation on
#: 2026-08-22 alongside the 20 CR animation rate.
CREDITS_PER_SOURCE: dict[str, Decimal] = {"epic": Decimal(1), "mythic": Decimal(6)}

#: The default output height, in pixels.
#:
#: The endpoint's own default is 128 and its range is 16-512. 256 is chosen
#: because `/animate` accepts at most 256 per axis, so a source generated at this
#: height reaches the animation endpoint with **no resample at all** -- and the
#: scale-and-pad submission contract's single nearest-neighbour downscale is the
#: only lossy step in the whole path. A source that never needs it is a source
#: whose palette measurement means something.
DEFAULT_SOURCE_HEIGHT = 256

#: The endpoint's own default is "right". Naming it explicitly matters more than
#: the value does: the E1 brief records `facing`, an export records it, and a
#: source generated in a direction nobody asked for would make that field a
#: guess. There is no "unspecified" here -- omitting it still produces a facing.
DEFAULT_SOURCE_DIRECTION = "right"

#: Response headers that must never reach provenance. Dropped rather than
#: redacted: a redacted credential still records that one was present and how
#: long it was, and neither fact is worth keeping.
_SECRET_HEADERS = frozenset({"authorization", "x-api-key", "set-cookie", "cookie"})

#: `/generate` states the balance it left behind, which `/animate` does not.
CREDITS_REMAINING_HEADER = "x-spritelab-credits-remaining"
SPRITE_ID_HEADER = "x-spritelab-sprite-id"

VALID_QUALITIES = frozenset(CREDITS_PER_SOURCE)
VALID_DIRECTIONS = frozenset({"auto", "front", "left", "right", "back", "top", "angled"})
MIN_SOURCE_HEIGHT, MAX_SOURCE_HEIGHT = 16, 512


@dataclass
class SpriteLabSource(SpriteLab):
    """Text to source sprite, via `POST /generate`.

    A subclass rather than a second stage on `SpriteLab`, because the two
    endpoints behave differently in every way that matters: `/generate` is
    synchronous and returns raw PNG bytes with metadata in headers, while
    `/animate` returns a job to poll. Branching five methods on `stage` would
    hide that difference rather than express it.

    A subclass rather than a sibling, because it really is the same vendor, the
    same key, the same credit pool, and the same rights posture -- `credits()`,
    `rights_disagree_with_tier()`, error normalisation, and the transport seam
    are shared rather than reimplemented, and reimplementing them is how two
    adapters for one vendor come to disagree about what a 429 means.
    """

    stages: tuple[Stage, ...] = ("source",)
    quality: str = "epic"
    height: int = DEFAULT_SOURCE_HEIGHT
    direction: str = DEFAULT_SOURCE_DIRECTION
    detail: int = 1
    #: sprite id -> (request, png bytes, vendor metadata). Synchronous, so the
    #: result exists before there is anything to poll.
    _sprites: dict[str, tuple[GenerationRequest, bytes, dict[str, Any]]] = field(
        default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        if self.quality not in VALID_QUALITIES:
            raise ValueError(
                f"quality must be one of {sorted(VALID_QUALITIES)}, not {self.quality!r}"
            )
        if self.direction not in VALID_DIRECTIONS:
            raise ValueError(
                f"direction must be one of {sorted(VALID_DIRECTIONS)}, not {self.direction!r}"
            )
        if not MIN_SOURCE_HEIGHT <= self.height <= MAX_SOURCE_HEIGHT:
            raise ValueError(
                f"height must be {MIN_SOURCE_HEIGHT}-{MAX_SOURCE_HEIGHT}, not {self.height}"
            )
        if not 1 <= self.detail <= 3:
            raise ValueError(f"detail must be 1-3, not {self.detail}")

    @property
    def credits_per_sprite(self) -> Decimal:
        return CREDITS_PER_SOURCE[self.quality]

    def estimate(self, request: GenerationRequest) -> Estimate:
        self._check_stage(request.stage)
        if request.candidate_count < 1:
            raise ProviderRejected("spritelab: a source run must ask for at least one sprite")
        return Estimate(
            unit=self.unit,
            maximum_amount=self.credits_per_sprite * request.candidate_count,
            call_count=request.candidate_count,
            pricing_snapshot_at=self.rate_observed_at,
        )

    def submit(self, request: GenerationRequest) -> SubmissionReceipt:
        """Generate one sprite. Synchronous, so the work is done when this returns.

        The balance is read first, free, so the charge can be established from
        two figures the provider itself stated rather than from the documented
        rate. `/animate` has no such pair, which is why its charges settle
        `unknown` and needed reconciling by hand afterwards.
        """
        self._check_stage(request.stage)
        if request.candidate_count != 1:
            raise ProviderRejected(
                f"spritelab: /generate makes one sprite per call and this asked for "
                f"{request.candidate_count}. A batch would reserve for a count the "
                f"endpoint cannot deliver."
            )
        if not request.prompt.strip():
            raise ProviderRejected("spritelab: a source sprite needs a prompt")

        before = self._balance_or_none()
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "quality": self.quality,
            "height": self.height,
            "direction": self.direction,
            "detail": self.detail,
        }
        response = self._send("POST", "/generate", payload, accept="image/png")
        submitted_at = datetime.now(UTC)

        if response.status != 200:
            # Reuses the JSON error path: a failure comes back as JSON even when
            # success does not, and the distinctions it draws -- auth, rate
            # limit, rejected, ambiguous -- are the same ones.
            self._decode_submission(response)
            raise AmbiguousOutcome(
                f"spritelab: /generate returned {response.status} with no usable body. "
                f"It may have been charged; reconcile against the credit balance.",
                job_id=None,
            )

        headers = {k.lower(): v for k, v in response.headers.items()}
        sprite_id = headers.get(SPRITE_ID_HEADER, "").strip()
        if not sprite_id:
            # The bytes are here, so this succeeded -- but with nothing to name
            # it by, a candidate id would have to be invented and could collide
            # with a later one. Hashing the bytes is stable and is not a claim.
            sprite_id = f"sprite_{hashlib.sha256(response.body).hexdigest()[:16]}"

        width, height = self._check_generated(response.body)
        vendor: dict[str, Any] = {
            "sprite_id": sprite_id,
            "quality": self.quality,
            "height_requested": str(self.height),
            "direction": self.direction,
            "detail": str(self.detail),
            "returned_w": str(width),
            "returned_h": str(height),
            **{f"header.{k}": v for k, v in headers.items() if k not in _SECRET_HEADERS},
        }
        charge = self._charge_from_balances(before, headers, vendor)
        self._sprites[sprite_id] = (request, response.body, vendor)
        return SubmissionReceipt(
            job_id=sprite_id,
            submitted_at=submitted_at,
            raw={"sprite_id": sprite_id, "charge": str(charge) if charge is not None else None},
        )

    def poll(self, job_id: str) -> JobStatus:
        if job_id not in self._sprites:
            raise ProviderRejected(
                f"spritelab: {job_id} is not held by this process. /generate is synchronous, "
                f"so there is no job to recover -- if it was generated and its bytes were not "
                f"persisted, the credit is spent and unrecoverable."
            )
        _, _, vendor = self._sprites[job_id]
        return JobStatus(job_id=job_id, state="succeeded", refunded=False, raw=dict(vendor))

    def collect(
        self,
        job_id: str,
        *,
        submitted_at: datetime | None = None,
        transforms: tuple[str, ...] = (),
    ) -> tuple[Candidate, ...]:
        if job_id not in self._sprites:
            raise ProviderRejected(
                f"spritelab: {job_id} is not held by this process; results are only "
                f"available from the call that produced them"
            )
        request, png, vendor = self._sprites[job_id]
        charge = vendor.get("_charge")
        return (
            Candidate(
                candidate_id=f"cand_{job_id[:16]}_00",
                media=png,
                media_kind="png",
                provenance=CandidateProvenance(
                    provider=self.name,
                    model=None,
                    generated_at=submitted_at or datetime.now(UTC),
                    account_rights=self.account_rights,
                    terms_reviewed_at=self.terms_reviewed_at,
                    attribution_required=False,
                    prompt=request.prompt,
                    # A generated source is the start of the path, so nothing has
                    # been done to it. An empty tuple here is a fact, not a gap.
                    transforms=transforms,
                    vendor={k: v for k, v in vendor.items() if not k.startswith("_")}
                    | {"vendor_candidate_id": job_id},
                ),
                reported_charge=Decimal(charge) if charge is not None else None,
                charge_unit=self.unit if charge is not None else None,
            ),
        )

    # -- Internals --------------------------------------------------------

    def _balance_or_none(self) -> int | None:
        """The balance before the call, or None if it could not be read.

        Never fatal. A source generation that refused to run because a *free*
        endpoint was briefly unavailable would trade a real capability for a
        nicety, and the charge simply settles `unknown` as `/animate`'s does.
        """
        try:
            return self.credits()[0]
        except (ProviderError, OSError):
            return None

    def _charge_from_balances(
        self, before: int | None, headers: Mapping[str, str], vendor: dict[str, Any]
    ) -> Decimal | None:
        """What the call cost, from two figures the provider stated.

        Reported only when the delta agrees with the documented rate for the
        quality requested. A disagreement is exactly when nothing may be
        asserted: another client may have spent from the same pool between the
        two reads, or the published rate may have moved. Both figures are kept
        in `vendor` either way, so a later reconciliation has the evidence
        without anyone reading a dashboard.
        """
        raw_after = headers.get(CREDITS_REMAINING_HEADER)
        after: int | None = None
        if raw_after is not None:
            try:
                after = int(raw_after.strip())
            except ValueError:
                after = None
        if before is not None:
            vendor["credits_before"] = str(before)
        if after is not None:
            vendor["credits_after"] = str(after)
        if before is None or after is None:
            return None

        delta = Decimal(before - after)
        expected = self.credits_per_sprite
        if delta != expected:
            vendor["charge_disagreement"] = (
                f"balance fell {delta} and {self.quality} is documented at {expected}"
            )
            return None
        vendor["_charge"] = str(delta)
        return delta

    @staticmethod
    def _check_generated(payload: bytes) -> tuple[int, int]:
        """Bound the returned image before anything decodes it."""
        if len(payload) > MAX_FILE_BYTES:
            raise ProviderRejected(
                f"spritelab: /generate returned {len(payload)} bytes, over the "
                f"{MAX_FILE_BYTES}-byte limit"
            )
        if not payload.startswith(PNG_SIGNATURE):
            raise ProviderRejected("spritelab: /generate did not return a PNG")
        try:
            width, height, frames = inspect_png(payload)
        except Rejected as exc:
            raise ProviderRejected(f"spritelab: generated sprite rejected: {exc}") from exc
        if frames > 1:
            raise ProviderRejected(
                f"spritelab: a source sprite must be a still image; this PNG declares "
                f"{frames} frames"
            )
        return width, height
