"""The provider adapter contract.

Every provider — SpriteLab, OpenAI Images, ElevenLabs, and anything added later —
is reached through this one interface, so the core never learns which vendor it is
talking to.

Three properties are load bearing, and all three come from the design constraints (docs/architecture.md).

**Provider fields never reach core objects.** A vendor's response shape lives in
`raw` and `provenance` and stops there. The moment `frame_count` or `sheet_b64`
appears in a manifest, swapping providers becomes a migration.

**Errors are normalised.** A rate limit is a rate limit whether it arrives as a
429, a JSON error code, or a socket timeout. The distinction the core actually
cares about is not which vendor failed but whether a retry is *safe* — and
`AmbiguousOutcome` exists precisely because sometimes it is not.

**Submission is never automatic.** Nothing here retries a generation. A retry is a
second charge for work that may already have succeeded, so the decision belongs to
a human looking at a preflight screen.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

#: What a run is asking a provider to make.
Stage = Literal["source", "animation", "sound"]

#: What came back. `png` and `gif` are images; `wav` and `mp3` are audio.
#: `mp3` is here because ElevenLabs returns MPEG: a contract that could not name
#: the format a provider actually sends forces an adapter to mislabel it.
MediaKind = Literal["png", "gif", "wav", "mp3"]

JobState = Literal["queued", "running", "succeeded", "failed"]


class ProviderError(Exception):
    """Base for every normalised provider failure."""


class AuthenticationFailed(ProviderError):
    """The credential was missing, wrong, or lacks the needed capability.

    Never retried automatically: retrying a bad credential just burns rate limit.
    """


class ProviderRejected(ProviderError):
    """The provider refused the request as malformed or out of bounds.

    Safe to fix and resubmit, because nothing was charged and nothing was made.
    """


class RateLimited(ProviderError):
    """Too many requests. Safe to retry after waiting."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AmbiguousOutcome(ProviderError):
    """The request may or may not have succeeded, and may or may not have cost money.

    The single most dangerous state in the system. A timeout after submission
    means work might be running, might have finished, might have been billed. The
    contract forbids resolving that by resubmitting: the job id is persisted
    before polling starts, and reconciliation is a human action against a ledger
    entry that keeps its reserve until someone establishes what happened.
    """

    def __init__(self, message: str, *, job_id: str | None = None) -> None:
        super().__init__(message)
        self.job_id = job_id


@dataclass(frozen=True)
class GenerationRequest:
    """What the core asks for, in the core's own vocabulary.

    No provider parameter appears here. An adapter translates this into whatever
    its vendor wants, and translates the answer back.
    """

    stage: Stage
    prompt: str
    candidate_count: int = 1
    #: The approved source, for stages that animate one.
    source_png: bytes | None = None
    frames: int | None = None
    #: Target duration for a sound, in milliseconds.
    duration_ms: int | None = None
    #: Deterministic transforms already applied to `source_png`, in order. The
    #: adapter cannot see them -- it receives bytes, not a history -- so the
    #: caller passes them and the adapter carries them into provenance. An
    #: export claiming no transform occurred cannot reproduce what was submitted.
    transforms: tuple[str, ...] = ()


@dataclass(frozen=True)
class Estimate:
    """A bounded maximum, and when its pricing was observed.

    There is no unbounded variant. the design constraints (docs/architecture.md) blocks a request with no
    bounded maximum rather than submitting against an unenforceable budget, and a
    type that cannot express "unknown cost" is how that rule is kept.
    """

    unit: str
    maximum_amount: Decimal
    call_count: int
    pricing_snapshot_at: datetime

    def __post_init__(self) -> None:
        if self.maximum_amount <= 0:
            raise ValueError("an estimate must have a positive bounded maximum")
        if self.call_count < 1:
            raise ValueError("an estimate must cover at least one call")


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    """Take a private, read-only copy.

    `frozen=True` stops attribute assignment and does nothing about the contents
    of a mapping the caller still holds a reference to. A raw response that can
    be edited after the fact is not a record of what the provider said.
    """
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class SubmissionReceipt:
    """Proof that work was handed over, persisted before any polling begins."""

    job_id: str
    submitted_at: datetime
    #: The vendor's response, verbatim and quarantined. Kept for provenance and
    #: never read by the core.
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    state: JobState
    #: Set when the provider says why it failed. Advisory text, not a code.
    detail: str | None = None
    #: Whether the provider returned the money for a failed job. SpriteLab's
    #: terms say it does. This lives here rather than only on a candidate because
    #: a failed job never produces one, and the ledger has to be able to tell
    #: *failed and refunded* from *failed and charged* from *unknown* -- three
    #: states it must never collapse. `None` is unknown, not "no refund".
    refunded: bool | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _freeze(self.raw))

    @property
    def is_terminal(self) -> bool:
        return self.state in ("succeeded", "failed")


@dataclass(frozen=True)
class CandidateProvenance:
    """What every candidate must be able to say about where it came from.

    the threat model (docs/threat-model.md) requires recording the provider, model, account-rights context,
    generation date, terms-review date, transforms, and attribution requirements.
    A free-form mapping cannot be checked for those, so they are fields, and the
    contract suite asserts every adapter fills them.

    Vendor extras keep their own compartment in `vendor`. That separation is the
    whole point: the required half is uniform enough to export, and the vendor
    half can be anything without leaking into a manifest.
    """

    provider: str
    #: `None` when the provider exposes no model choice. SpriteLab's animation
    #: endpoint is one: recording "unknown" would imply we failed to look.
    model: str | None
    generated_at: datetime
    #: What rights the generating account confers, e.g. "free_tier_non_exclusive".
    #: See the provenance format (docs/provenance-format.md).
    account_rights: str
    terms_reviewed_at: date
    attribution_required: bool
    attribution_text: str | None = None
    #: What was asked for, verbatim. The single input that most determines what
    #: came back, and it was recorded nowhere: a pack could hold two candidates
    #: from two different prompts with nothing to say which was which. That
    #: defeats the rule the whole review loop rests on -- a rejection carries a
    #: reason, and the reason is what makes the next attempt different from a
    #: retry -- because the pack could not show what was actually different.
    #:
    #: `None` only where a stage takes no prompt, never as "we did not record it".
    prompt: str | None = None
    #: Deterministic transforms applied on the way in, in order.
    transforms: tuple[str, ...] = ()
    #: Vendor-specific metadata: seeds, returned dimensions, request ids.
    vendor: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("provenance must name its provider")
        if not self.account_rights:
            raise ValueError("provenance must record an account-rights context")
        if self.attribution_required and not self.attribution_text:
            raise ValueError(
                "attribution is required but no text was recorded; the text travels "
                "with every export, so an empty one is useless"
            )
        object.__setattr__(self, "vendor", _freeze(self.vendor))


@dataclass(frozen=True)
class Candidate:
    """One generated result, awaiting human review. Never final."""

    #: An Emberforge stable ID, not the provider's own string. Approvals record
    #: this, and `events` types it as `StableId`, so an adapter that passes a
    #: raw provider identifier straight through produces candidates the journal
    #: cannot record. Adapters mint the stable ID and keep the provider's own
    #: identifier in `provenance.vendor` under `vendor_candidate_id`.
    candidate_id: str
    media: bytes
    media_kind: MediaKind
    provenance: CandidateProvenance
    #: What the provider says it charged, if it says. `None` is not zero — it
    #: means unknown, and the ledger keeps the reserve.
    reported_charge: Decimal | None = None
    charge_unit: str | None = None
    #: True when the provider refunded a failed generation, as SpriteLab does.
    refunded: bool = False
    #: Things a reviewer should know that are not defects in the adapter and not
    #: grounds to refuse the candidate: the provider returned something, it was
    #: paid for, and it is not what was asked for. Reaches `CandidateCollected`
    #: and the review page, which is where a person can act on it.
    #:
    #: Never used to report a transport or parsing problem. Those raise.
    warnings: tuple[str, ...] = ()


@runtime_checkable
class Provider(Protocol):
    """What every adapter must offer.

    Deliberately small. Anything larger tempts the core into vendor-shaped
    thinking, and every method here maps to a step the run lifecycle already has.
    """

    #: Stable identifier, used in records and cost entries.
    name: str
    #: The provider's billing unit. Never summed with another provider's.
    unit: str

    def supports(self, stage: Stage) -> bool:
        """Whether this provider can do this kind of work at all."""
        ...

    def estimate(self, request: GenerationRequest) -> Estimate:
        """Bounded maximum cost. Must not perform paid work."""
        ...

    def submit(self, request: GenerationRequest) -> SubmissionReceipt:
        """Hand over the work and return a job id. May cost money."""
        ...

    def poll(self, job_id: str) -> JobStatus:
        """Ask how a job is doing. Free, and safe to call repeatedly."""
        ...

    def collect(self, job_id: str) -> tuple[Candidate, ...]:
        """Retrieve results for a succeeded job. Free, and safe to repeat."""
        ...
