"""The OpenAI Images adapter: text to source sprite, billed in dollars.

Third of the live adapters and the first that meters in currency rather than a
provider credit. That difference is not cosmetic. SpriteLab and ElevenLabs both
sell a pool you buy up front, so a run is bounded by a balance somebody topped
up on purpose; OpenAI bills afterwards against whatever the account can pay. A
ceiling here is the only thing standing between a loop and a bill.

Two facts about the endpoint shape the whole adapter, both read from the API
documentation on 2026-08-22:

**It cannot make a small sprite.** Sizes must have both edges a multiple of 16
and a total of at least 655,360 pixels, so 1024x1024 is the smallest square it
offers -- sixteen times the pixel count of a 256px source. Every OpenAI source
therefore meets the scale-and-pad submission contract's nearest-neighbour
downscale, which `SpriteLabSource`'s 256px default exists to avoid entirely.
That is a real asymmetry between the two source adapters and it is recorded
rather than smoothed over: an operator choosing between them is choosing between
a resample and no resample.

**It states no price.** The response carries token usage, not dollars. So a
charge settles `unknown` and keeps its reserve, exactly as SpriteLab's `/animate`
does -- the published per-image price bounds the estimate and is never reported
as though the provider had confirmed it.
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

from emberforge_lite.media import (
    MAX_FILE_BYTES,
    PNG_SIGNATURE,
    Rejected,
    inspect_png,
    png_has_alpha,
)
from emberforge_lite.providers.base import (
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
from emberforge_lite.providers.transport import (
    Response,
    Transport,
    TransportError,
    UrllibTransport,
    redact,
)

UTC = timezone.utc

BASE_URL = "https://api.openai.com/v1"
KEY_ENV_VAR = "OPENAI_API_KEY"

#: `PROJECT_SCOPE.md` names gpt-image-2 as the initial target. The exact model
#: stays adapter configuration recorded in provenance, never a core field.
DEFAULT_MODEL = "gpt-image-2"

#: Published per-image prices, read 2026-08-22. Keyed by (quality, size).
#:
#: Only the sizes and qualities this adapter offers are listed. A price table
#: with entries nobody checked is worse than a short one: an estimate would look
#: authoritative while resting on a figure that was never read.
USD_PER_IMAGE: dict[tuple[str, str], Decimal] = {
    ("low", "1024x1024"): Decimal("0.006"),
    ("low", "1024x1536"): Decimal("0.005"),
}

#: When those prices were read. An estimate stamped "now" can never be
#: recognised as stale, which is the same rule every other adapter follows.
RATE_OBSERVED_AT = datetime(2026, 8, 22, tzinfo=UTC)

#: The smallest square the endpoint offers. Both edges must be multiples of 16
#: and the total must reach 655,360 pixels, so there is nothing smaller.
SMALLEST_SQUARE = "1024x1024"

VALID_SIZES = frozenset(size for _, size in USD_PER_IMAGE)
VALID_QUALITIES = frozenset(quality for quality, _ in USD_PER_IMAGE)

#: What `background` may be. `transparent` is the default because the only thing
#: this adapter makes is a source sprite, and a sprite on an opaque field is not
#: a sprite -- it is a picture of one.
#:
#: The 2026-08-22 live smoke returned an **RGB** image with no alpha channel at
#: all, on a near-white field, from a prompt that asked in words for a
#: transparent background. Asking in the prompt is asking the model; asking here
#: is asking the API. They are not the same request, and only one of them is a
#: parameter the endpoint has to honour.
VALID_BACKGROUNDS = frozenset({"transparent", "opaque", "auto"})

#: OpenAI documents that transparency requires a format that can carry it. PNG
#: is the only output format this adapter asks for, so the combination is always
#: valid -- stated here because a future format field would silently break it.
TRANSPARENT_CAPABLE_FORMATS = frozenset({"png", "webp"})

#: Reviewed 2026-08-22. OpenAI assigns the user all its right, title, and
#: interest in Output. See `PROJECT_SCOPE.md` D17 and `export.RIGHTS_TERMS`.
DEFAULT_ACCOUNT_RIGHTS = "openai_api_assigned_exclusive"
DEFAULT_TERMS_REVIEWED = date(2026, 8, 22)

#: Response headers that must never reach provenance. Dropped rather than
#: redacted: a redacted credential still records that one was present.
_SECRET_HEADERS = frozenset({"authorization", "openai-organization", "set-cookie", "cookie"})


class MissingCredential(ProviderError):
    """The operator credential is not in the environment."""


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
class OpenAIImages:
    """The live adapter. One instance per key.

    Synchronous: `POST /v1/images/generations` returns the image on the same
    call, so `submit` performs the work and holds the result. `poll` and
    `collect` read what it already has, and a job id this process does not hold
    is unrecoverable rather than pending -- the same shape as `ElevenLabs` and
    `SpriteLabSource`, and for the same reason.
    """

    key: str | None = None
    transport: Transport = field(default_factory=UrllibTransport)
    base_url: str = BASE_URL
    account_rights: str = DEFAULT_ACCOUNT_RIGHTS
    terms_reviewed_at: date = DEFAULT_TERMS_REVIEWED
    timeout_seconds: float = 180.0
    model: str | None = DEFAULT_MODEL
    size: str = SMALLEST_SQUARE
    quality: str = "low"
    #: See `VALID_BACKGROUNDS`. Sent as a parameter rather than trusted to the
    #: prompt, and the returned image is checked rather than assumed.
    background: str = "transparent"
    rate_observed_at: datetime = RATE_OBSERVED_AT

    name: str = "openai_images"
    unit: str = "usd"
    stages: tuple[Stage, ...] = ("source",)
    #: request id -> (request, png bytes, vendor metadata).
    _results: dict[str, tuple[GenerationRequest, bytes, dict[str, Any]]] = field(
        default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        if self.background not in VALID_BACKGROUNDS:
            raise ValueError(
                f"background must be one of {sorted(VALID_BACKGROUNDS)}, not {self.background!r}"
            )
        if (self.quality, self.size) not in USD_PER_IMAGE:
            raise ValueError(
                f"no price was read for quality {self.quality!r} at size {self.size!r}. "
                f"Priced combinations are {sorted(USD_PER_IMAGE)}. An estimate against an "
                f"unread price would look authoritative and bound nothing."
            )

    def supports(self, stage: Stage) -> bool:
        return stage in self.stages

    # -- Contract ---------------------------------------------------------

    @property
    def usd_per_image(self) -> Decimal:
        return USD_PER_IMAGE[(self.quality, self.size)]

    def estimate(self, request: GenerationRequest) -> Estimate:
        """The bounded maximum for this batch, at the published price.

        A maximum, not a prediction. This is the only adapter here whose unit is
        money the account has not already paid, so the reserve is the only thing
        bounding what a mistake can cost.
        """
        self._check_stage(request.stage)
        if request.candidate_count < 1:
            raise ProviderRejected("openai_images: a source run must ask for at least one image")
        return Estimate(
            unit=self.unit,
            maximum_amount=self.usd_per_image * request.candidate_count,
            call_count=request.candidate_count,
            pricing_snapshot_at=self.rate_observed_at,
        )

    def submit(self, request: GenerationRequest) -> SubmissionReceipt:
        """Generate one image. Synchronous, so the work is done when this returns."""
        self._check_stage(request.stage)
        if request.candidate_count != 1:
            raise ProviderRejected(
                f"openai_images: this adapter makes one image per call and this asked for "
                f"{request.candidate_count}. `n` would batch them into one billed request "
                f"whose failure modes are per-image, and a partial batch cannot be settled "
                f"against a single reserve."
            )
        if not request.prompt.strip():
            raise ProviderRejected("openai_images: a source sprite needs a prompt")

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": request.prompt,
            "n": 1,
            "size": self.size,
            "quality": self.quality,
            "output_format": "png",
            "background": self.background,
        }
        response = self._send("POST", "/images/generations", payload)
        submitted_at = datetime.now(UTC)
        data = self._decode_submission(response)

        png = self._decode_image(data)
        width, height = self._check_generated(png)
        has_alpha = png_has_alpha(png)
        headers = {k.lower(): v for k, v in response.headers.items()}
        request_id = (
            headers.get("x-request-id")
            or str(data.get("id") or "")
            or f"img_{hashlib.sha256(png).hexdigest()[:16]}"
        )

        vendor: dict[str, Any] = {
            "request_id": request_id,
            "model": str(self.model),
            "size_requested": self.size,
            "quality": self.quality,
            "background_requested": self.background,
            # What came back, not what was asked for. Recording the request and
            # calling it the result is how a pack comes to claim a property its
            # bytes do not have.
            "returned_has_alpha": str(has_alpha),
            "returned_w": str(width),
            "returned_h": str(height),
            "synchronous": "True",
            **{f"usage.{k}": str(v) for k, v in _usage(data).items()},
            **{f"header.{k}": v for k, v in headers.items() if k not in _SECRET_HEADERS},
        }
        if self.background == "transparent" and not has_alpha:
            # A warning, not a refusal. The image exists, the account was billed
            # for it, and throwing it away would destroy the one artefact the
            # charge bought while leaving the charge. A reviewer can see this on
            # the page and decide; an exception here would decide for them.
            vendor["background_disagreement"] = (
                "transparent was requested and the returned PNG has no alpha channel"
            )
        self._results[request_id] = (request, png, vendor)
        return SubmissionReceipt(job_id=request_id, submitted_at=submitted_at, raw=dict(vendor))

    def poll(self, job_id: str) -> JobStatus:
        if job_id not in self._results:
            raise ProviderRejected(
                f"openai_images: {job_id} is not held by this process. Generation is "
                f"synchronous, so there is no job to recover -- if it was billed and its "
                f"bytes were not persisted, the charge stands and the image is gone."
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
        if job_id not in self._results:
            raise ProviderRejected(
                f"openai_images: {job_id} is not held by this process; results are only "
                f"available from the call that produced them"
            )
        request, png, vendor = self._results[job_id]
        return (
            Candidate(
                candidate_id=f"cand_{_slug(job_id)}_00",
                media=png,
                media_kind="png",
                provenance=CandidateProvenance(
                    provider=self.name,
                    model=self.model,
                    generated_at=submitted_at or datetime.now(UTC),
                    account_rights=self.account_rights,
                    terms_reviewed_at=self.terms_reviewed_at,
                    # Not established from the reviewed terms, which cover
                    # ownership and similarity and say nothing about credit.
                    # Recorded as open rather than resolved favourably.
                    attribution_required=False,
                    attribution_text=(
                        "OpenAI's reviewed terms do not address attribution. Confirm before "
                        "relying on this pack requiring none."
                    ),
                    prompt=request.prompt,
                    transforms=transforms,
                    vendor=dict(vendor) | {"vendor_candidate_id": job_id},
                ),
                # The response states token usage, not dollars. Deriving a charge
                # from the published price would report an estimate as though the
                # provider had confirmed it; unknown keeps the reserve instead.
                reported_charge=None,
                charge_unit=None,
                # Carried to the review page. `transparent` was asked of the API
                # and the API is free not to honour it; a reviewer looking at a
                # sprite on an opaque field should be told that is what happened
                # rather than left to notice.
                warnings=(
                    (
                        "openai returned an image with no alpha channel; a transparent "
                        "background was requested. This sprite has an opaque field baked "
                        "into it and is not usable as a source without one being removed.",
                    )
                    if "background_disagreement" in vendor
                    else ()
                ),
            ),
        )

    # -- Internals --------------------------------------------------------

    def _check_stage(self, stage: Stage) -> None:
        if stage not in self.stages:
            raise ProviderRejected(
                f"openai_images: this adapter generates {self.stages}, not {stage!r}"
            )

    def _send(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Response:
        import json

        key = self.key if self.key is not None else load_key()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
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
            # A transport failure on a POST is never safe to retry: the request
            # may have been received and billed, and there is no job id with
            # which to find out. This is the one provider here where that costs
            # money the account has not already set aside.
            if method == "POST":
                raise AmbiguousOutcome(
                    f"openai_images: the request could not be completed and its outcome is "
                    f"unknown ({redact(str(exc))}). Do not resubmit; reconcile against the "
                    f"account's usage.",
                    job_id=None,
                ) from exc
            raise ProviderError(f"openai_images: {redact(str(exc))}") from exc

    def _decode_submission(self, response: Response) -> dict[str, Any]:
        """Decode a POST response, where "failed" and "unknown" differ.

        A 4xx is a refusal that cost nothing. A 5xx or an unreadable body may
        have been billed, so it is ambiguous rather than failed and must never be
        resubmitted automatically.
        """
        if response.status == 401 or response.status == 403:
            raise AuthenticationFailed(
                f"openai_images: the credential was rejected ({response.status}). Check "
                f"{KEY_ENV_VAR} and that the key may reach the Images API."
            )
        if response.status == 429:
            raise RateLimited(
                "openai_images: rate limited",
                retry_after_seconds=_retry_after(response),
            )
        if 400 <= response.status < 500:
            raise ProviderRejected(
                f"openai_images: the request was refused ({response.status}): "
                f"{_body_hint(response)}"
            )
        if response.status >= 500:
            raise AmbiguousOutcome(
                f"openai_images: the endpoint returned {response.status}. It may have been "
                f"billed; reconcile against the account's usage rather than resubmitting.",
                job_id=None,
            )
        try:
            return response.json()
        except TransportError as exc:
            raise AmbiguousOutcome(
                f"openai_images: the response could not be read ({redact(str(exc))}). It may "
                f"have been billed.",
                job_id=None,
            ) from exc

    @staticmethod
    def _decode_image(data: dict[str, Any]) -> bytes:
        items = data.get("data")
        if not isinstance(items, list) or not items:
            raise ProviderRejected(
                f"openai_images: the response carried no image: {redact(str(data))}"
            )
        encoded = items[0].get("b64_json") if isinstance(items[0], dict) else None
        if not isinstance(encoded, str) or not encoded:
            raise ProviderRejected(
                "openai_images: the response carried no b64_json. This adapter never asks "
                "for a URL: an image fetched from a second host is a second request whose "
                "failure would be indistinguishable from the first having produced nothing."
            )
        if len(encoded) > MAX_FILE_BYTES * 2:
            raise ProviderRejected(
                f"openai_images: encoded image is {len(encoded)} characters, over the bound"
            )
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderRejected(f"openai_images: b64_json did not decode: {exc}") from exc

    @staticmethod
    def _check_generated(payload: bytes) -> tuple[int, int]:
        """Bound the returned image before anything decodes it."""
        if len(payload) > MAX_FILE_BYTES:
            raise ProviderRejected(
                f"openai_images: returned {len(payload)} bytes, over the "
                f"{MAX_FILE_BYTES}-byte limit"
            )
        if not payload.startswith(PNG_SIGNATURE):
            raise ProviderRejected("openai_images: the returned image was not a PNG")
        try:
            width, height, frames = inspect_png(payload)
        except Rejected as exc:
            raise ProviderRejected(f"openai_images: generated image rejected: {exc}") from exc
        if frames > 1:
            raise ProviderRejected(
                f"openai_images: a source sprite must be a still image; this PNG declares "
                f"{frames} frames"
            )
        return width, height


def _slug(value: str) -> str:
    """A StableId-safe fragment of a provider identifier.

    Provider ids carry hyphens and underscores in shapes `StableId` refuses, and
    a candidate id that fails validation after the image is billed is the worst
    possible moment to find out.
    """
    kept = "".join(c if c.isalnum() else "_" for c in value.lower()).strip("_")
    collapsed = "_".join(part for part in kept.split("_") if part)
    return (collapsed or "img")[:24]


def _retry_after(response: Response) -> float | None:
    raw = response.headers.get("retry-after") or response.headers.get("Retry-After")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _body_hint(response: Response) -> str:
    """A short, redacted fragment of an error body, for a human to read."""
    return redact(response.body[:200].decode("utf-8", errors="replace"))


def _usage(data: Mapping[str, Any]) -> Mapping[str, Any]:
    usage = data.get("usage")
    return usage if isinstance(usage, Mapping) else {}
