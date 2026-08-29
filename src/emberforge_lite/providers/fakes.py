"""Fake providers. No network, no credentials, no spend.

These are not stubs that return a fixed blob. Each one imitates the behaviour its
real counterpart is documented to have — SpriteLab's 256 px input cap and its
automatic refund on failure, ElevenLabs producing audio rather than images — so
that code exercised against a fake is exercised against the shape of the real
thing.

Everything is deterministic, seeded by the request. The same request always
produces the same bytes, which is what lets a test assert on output at all, and
what lets the whole offline path satisfy the scope's determinism rule.

Failures are injectable. The interesting paths in this system are the ugly ones —
an ambiguous timeout, a refunded failure, a charge the provider will not state —
and a fake that only ever succeeds cannot exercise any of them.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from emberforge_lite.providers.base import (
    AmbiguousOutcome,
    AuthenticationFailed,
    Candidate,
    CandidateProvenance,
    Estimate,
    GenerationRequest,
    JobState,
    JobStatus,
    ProviderRejected,
    Stage,
    SubmissionReceipt,
)
from emberforge_lite.providers.elevenlabs import CREDITS_PER_SECOND as ELEVENLABS_CREDITS_PER_SECOND
from emberforge_lite.providers.elevenlabs import DEFAULT_ACCOUNT_RIGHTS as ELEVENLABS_RIGHTS
from emberforge_lite.providers.openai_images import DEFAULT_ACCOUNT_RIGHTS as OPENAI_RIGHTS
from emberforge_lite.providers.openai_images import SMALLEST_SQUARE, USD_PER_IMAGE
from emberforge_lite.providers.spritelab import CREDITS_PER_ANIMATION as SPRITELAB_CREDITS_PER_ANIMATION
from emberforge_lite.providers.spritelab import CREDITS_PER_SOURCE

UTC = timezone.utc

#: The live adapter's default combination.
OPENAI_USD_PER_IMAGE = USD_PER_IMAGE[("low", SMALLEST_SQUARE)]

#: What `/generate` charges at the quality `SpriteLabSource` defaults to.
SPRITELAB_CREDITS_PER_SOURCE = CREDITS_PER_SOURCE["epic"]


def _square(size: str) -> tuple[int, int]:
    """ "1024x1024" -> (1024, 1024). Parsed rather than retyped."""
    width, _, height = size.partition("x")
    return int(width), int(height)


#: Fixed so fixtures do not shift under a clock.
FAKE_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
FAKE_TERMS_REVIEWED = date(2026, 8, 21)


@dataclass
class FailureScript:
    """How a fake should misbehave, so the ugly paths get exercised.

    Every field defaults off. A fake that never fails is the least useful kind.
    """

    #: Raise AuthenticationFailed on the next submit.
    unauthenticated: bool = False
    #: Raise ProviderRejected on the next submit.
    reject_reason: str | None = None
    #: Raise AmbiguousOutcome while polling. The job id is still returned first,
    #: exactly as a real timeout after a successful submission behaves.
    ambiguous_on_poll: bool = False
    #: Resolve the job as failed rather than succeeded.
    fail_job: bool = False
    #: Whether a failed job refunds. SpriteLab's terms say it does.
    refund_on_failure: bool = True
    #: Return candidates with no stated charge, so the ledger must record unknown.
    silent_about_charges: bool = False
    #: Poll forever without resolving. A slow job and a lost job look identical
    #: from the caller's side, which is the whole reason an unresolved outcome
    #: has to be a distinct state from a failure.
    never_finishes: bool = False
    #: Candidate slots the provider does not return. A batch is not all-or-nothing:
    #: some slots land and some do not, and a failed slot yields no media and no
    #: charge rather than a candidate that merely says it failed.
    failed_candidates: tuple[int, ...] = ()


def _png(width: int, height: int, seed: bytes) -> bytes:
    """A small, valid, deterministic PNG.

    Real bytes rather than a placeholder string, because the media validator will
    be asked to check these and a fake that cannot pass validation would hide
    exactly the bug that matters.
    """
    tint = hashlib.sha256(seed).digest()

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    # Built a band at a time rather than a pixel at a time. The checkerboard
    # repeats every eight pixels in both directions, so there are exactly two
    # distinct rows in the whole image -- and a per-pixel loop over the 1024
    # square the OpenAI fake now returns costs a second of test time to produce
    # bytes that were already known. The output is identical either way.
    light = bytes((tint[0], tint[1], tint[2], 255))
    dark = bytes((tint[3], tint[4], tint[5], 255))
    even_row = bytearray(b"\x00")
    odd_row = bytearray(b"\x00")
    for x in range(width):
        first, second = (light, dark) if (x // 8) % 2 == 0 else (dark, light)
        even_row += first
        odd_row += second

    rows = bytearray()
    for y in range(height):
        rows += even_row if (y // 8) % 2 == 0 else odd_row

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


#: The geometry the live `POST /generate` smoke actually returned, measured
#: rather than invented: a 486x256 sheet holding two views separated by one
#: 47-column fully transparent gutter, with a narrow transparent margin at each
#: edge. See docs/development/e2-live-smokes.md.
#:
#: The fake reproduces it because the shape *is* the finding. A fake that
#: returned one tidy square would let a rehearsal of the crop pass while proving
#: nothing about the sheet the crop exists for.
SOURCE_SHEET_SIZE = (486, 256)
SOURCE_SHEET_MARGIN = 4
SOURCE_SHEET_GUTTER = 47
SOURCE_VIEW_WIDTHS = (279, 152)


def _source_sheet(seed: bytes) -> bytes:
    """A multi-view source sheet with a real transparent gutter in it.

    Transparent columns, not merely differently coloured ones: `find_views`
    measures the split from full transparency, and a gutter painted in a
    background colour would be invisible to it -- which is exactly the failure a
    rehearsal is supposed to be able to catch.
    """
    width, height = SOURCE_SHEET_SIZE
    tint = hashlib.sha256(seed).digest()

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    clear = bytes(4)
    starts = (
        SOURCE_SHEET_MARGIN,
        SOURCE_SHEET_MARGIN + SOURCE_VIEW_WIDTHS[0] + SOURCE_SHEET_GUTTER,
    )
    assert len(starts) == len(SOURCE_VIEW_WIDTHS)
    spans = tuple(zip(starts, SOURCE_VIEW_WIDTHS))

    row = bytearray(b"\x00") + clear * width
    for view, (start, span) in enumerate(spans):
        for x in range(start, start + span):
            offset = 1 + x * 4
            shade = tint[view * 3 : view * 3 + 3] if (x // 8) % 2 else tint[3:6]
            row[offset : offset + 4] = bytes(shade) + b"\xff"

    rows = bytearray()
    for _ in range(height):
        rows += row

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


def _wav(duration_ms: int, seed: bytes) -> bytes:
    """A deterministic WAV whose content varies with the seed.

    Silence would be simpler and wrong: two different sound prompts would return
    byte-identical audio, so nothing downstream — a waveform in review, a hash in
    provenance, a test comparing candidates — could tell them apart. The point of
    a fake is to be distinguishable in the ways the real thing is.
    """
    rate = 44100
    samples = max(1, int(rate * duration_ms / 1000))
    digest = hashlib.sha256(seed).digest()

    # A decaying tone, with pitch and amplitude derived from the seed. Integer
    # arithmetic throughout, so the bytes are identical on every platform.
    period = 40 + digest[0] % 160
    peak = 6000 + digest[1] * 40

    frames = bytearray()
    for index in range(samples):
        decay = (samples - index) * peak // samples
        value = decay if (index // (period // 2 or 1)) % 2 == 0 else -decay
        frames += struct.pack("<h", max(-32768, min(32767, value)))
    data = bytes(frames)

    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


@dataclass
class FakeProvider:
    """Shared machinery for the fakes.

    Public because tests need the parts a real `Provider` does not have: the
    failure script, and `refunded_for`. Those are properties of being a fake, not
    of being a provider, so they stay off the protocol.
    """

    name: str = "fake"
    unit: str = "fake_credits"
    per_call: Decimal = Decimal(1)
    stages: tuple[Stage, ...] = ()
    script: FailureScript = field(default_factory=FailureScript)

    #: Rights context the generating account confers, in the vocabulary scope D17
    #: uses. Each fake that stands in for a real adapter overrides this with that
    #: adapter's own value, for the same reason `per_call` matches the real
    #: metering: a rehearsal that reports rights the live run would not record
    #: makes the review screen quietly wrong about the one thing a reviewer
    #: cannot check by looking. This base value is the generic default for fakes
    #: that stand in for nothing in particular.
    account_rights: str = "spritelab_paid_private_exclusive"
    terms_reviewed_at: date = FAKE_TERMS_REVIEWED
    attribution_required: bool = False
    attribution_text: str | None = None
    #: What the adapter reports as its model. None where none is selectable.
    model: str | None = None

    _jobs: dict[str, tuple[GenerationRequest, JobState]] = field(default_factory=dict)
    _polls: dict[str, int] = field(default_factory=dict)
    #: Where this instance's job numbering starts. A real endpoint mints job IDs
    #: server-side, so two processes submitting the same request get different
    #: jobs; a fake counting from zero in each process gets the same one, and the
    #: second run collides on a candidate ID that is already in the journal. A
    #: caller resuming work on a pack passes the count already recorded there,
    #: which keeps IDs unique across processes and still deterministic.
    submissions_before: int = 0
    _submissions: int = 0

    def supports(self, stage: Stage) -> bool:
        return stage in self.stages

    def estimate(self, request: GenerationRequest) -> Estimate:
        self._check_stage(request.stage)
        return Estimate(
            unit=self.unit,
            maximum_amount=self.per_call * request.candidate_count,
            call_count=request.candidate_count,
            pricing_snapshot_at=FAKE_NOW,
        )

    def submit(self, request: GenerationRequest) -> SubmissionReceipt:
        self._check_stage(request.stage)
        if self.script.unauthenticated:
            raise AuthenticationFailed(f"{self.name}: credential missing or invalid")
        if self.script.reject_reason:
            raise ProviderRejected(f"{self.name}: {self.script.reject_reason}")

        # The submission counter is what makes two identical requests two distinct
        # jobs. Without it the digest collides, and since approvals and the review
        # join both key on `candidate_id`, a replacement run would resolve to the
        # previous run's media. Deterministic per instance, so a fresh provider
        # replaying the same script still reproduces the same IDs and bytes.
        self._submissions += 1
        job_id = hashlib.sha256(
            f"{self.name}|{request.stage}|{request.prompt}|{request.candidate_count}|"
            f"{self.submissions_before + self._submissions}".encode()
        ).hexdigest()[:32]

        self._jobs[job_id] = (request, "queued")
        self._polls[job_id] = 0
        return SubmissionReceipt(
            job_id=job_id,
            submitted_at=FAKE_NOW,
            raw={"job_id": job_id, "status": "queued", "provider": self.name},
        )

    def poll(self, job_id: str) -> JobStatus:
        if job_id not in self._jobs:
            raise ProviderRejected(f"{self.name}: unknown job {job_id}")
        if self.script.ambiguous_on_poll:
            raise AmbiguousOutcome(
                f"{self.name}: job {job_id} did not resolve; do not resubmit", job_id=job_id
            )

        request, _ = self._jobs[job_id]
        self._polls[job_id] += 1
        # One intermediate poll, so callers cannot assume instant completion.
        if self.script.never_finishes or self._polls[job_id] < 2:
            self._jobs[job_id] = (request, "running")
            return JobStatus(job_id=job_id, state="running", raw={"status": "running"})

        state: JobState = "failed" if self.script.fail_job else "succeeded"
        self._jobs[job_id] = (request, state)
        return JobStatus(
            job_id=job_id,
            state=state,
            detail="generation failed upstream" if state == "failed" else None,
            # Only meaningful on a failure, and only when the provider says. A
            # fake that reported False for "said nothing" would let the ledger
            # pass a test the real adapter would fail.
            refunded=self.script.refund_on_failure if state == "failed" else None,
            raw={"status": state},
        )

    def collect(self, job_id: str) -> tuple[Candidate, ...]:
        if job_id not in self._jobs:
            raise ProviderRejected(f"{self.name}: unknown job {job_id}")

        request, state = self._jobs[job_id]
        if state != "succeeded":
            raise ProviderRejected(
                f"{self.name}: job {job_id} is {state}; results are only available once it succeeds"
            )

        charge = None if self.script.silent_about_charges else self.per_call
        return tuple(
            Candidate(
                candidate_id=f"cand_{job_id[:8]}_{index:02d}",
                media=self._media(request, index),
                media_kind=self._media_kind(request),
                provenance=CandidateProvenance(
                    provider=self.name,
                    model=self.model,
                    generated_at=FAKE_NOW,
                    account_rights=self.account_rights,
                    terms_reviewed_at=self.terms_reviewed_at,
                    attribution_required=self.attribution_required,
                    attribution_text=self.attribution_text,
                    prompt=request.prompt,
                    transforms=self._transforms(request),
                    vendor=self._vendor(request, job_id, index),
                ),
                reported_charge=charge,
                charge_unit=None if charge is None else self.unit,
            )
            for index in range(request.candidate_count)
            if index not in self.script.failed_candidates
        )

    def refunded_for(self, job_id: str) -> bool:
        """Whether a failed job returned its credits."""
        _, state = self._jobs.get(job_id, (None, "queued"))
        return state == "failed" and self.script.refund_on_failure

    def _check_stage(self, stage: Stage) -> None:
        if not self.supports(stage):
            raise ProviderRejected(f"{self.name} does not perform {stage} work")

    def _media(self, request: GenerationRequest, index: int) -> bytes:
        raise NotImplementedError

    def _media_kind(self, request: GenerationRequest) -> Any:
        raise NotImplementedError

    def _transforms(self, request: GenerationRequest) -> tuple[str, ...]:
        return ()

    def _vendor(self, request: GenerationRequest, job_id: str, index: int) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class FakeSpriteLab(FakeProvider):
    """Imitates SpriteLab, including the constraints that bit us in the probe."""

    name: str = "spritelab"
    unit: str = "spritelab_credits"
    per_call: Decimal = SPRITELAB_CREDITS_PER_ANIMATION
    #: Animation only. This used to claim the source stage too, at the animation
    #: rate -- so a source rehearsal reserved twenty credits for something the
    #: real endpoint charges one for, and a ceiling that passed here would have
    #: blocked live or the reverse. `FakeSpriteLabSource` answers for that stage,
    #: at that stage's price, because they are two endpoints and always were.
    stages: tuple[Stage, ...] = ("animation",)

    #: Documented cap. The real endpoint refuses anything larger, and so does this.
    max_input_axis: int = 256
    #: Not settable upstream; the real API returns this regardless of what is asked.
    fixed_fps: int = 8
    #: /animate exposes no model parameter, so there is no model to record.
    model: str | None = None

    #: What the fake account holds. The live adapter's `credits()` is a free
    #: endpoint the lite orchestrator calls to show a balance; the fake answers
    #: with a fixed figure so that code path runs offline.
    fake_balance: int = 340

    def credits(self) -> tuple[int, str | None]:
        return (self.fake_balance, "ranger")

    def preview_gif(self, job_id: str) -> bytes | None:
        """The preview the live `/jobs/{id}` carries alongside the sheet.

        A real, tiny GIF89a with two frames and 6 cs delays -- the encoded rate
        the web UI's preview exports actually use -- so that the ingest step
        which normalises delays to 8 fps has something genuine to rewrite.
        """
        if job_id not in self._jobs or self._jobs[job_id][1] != "succeeded":
            return None
        return FAKE_PREVIEW_GIF

    def submit(self, request: GenerationRequest) -> SubmissionReceipt:
        if request.stage == "animation":
            if request.source_png is None:
                raise ProviderRejected("spritelab: an animation needs a source image")
            width, height = _png_size(request.source_png)
            if max(width, height) > self.max_input_axis:
                raise ProviderRejected(
                    f"spritelab: input is {width}x{height}, over the "
                    f"{self.max_input_axis}px per-axis limit"
                )
        return super().submit(request)

    def _media(self, request: GenerationRequest, index: int) -> bytes:
        width, height = _png_size(request.source_png) if request.source_png else (64, 64)
        frames = request.frames or 8
        # A horizontal spritesheet, exactly as the real endpoint returns.
        return _png(width * frames, height, f"{request.prompt}|{index}".encode())

    def _media_kind(self, request: GenerationRequest) -> Any:
        return "png"

    def _transforms(self, request: GenerationRequest) -> tuple[str, ...]:
        return ("nearest_downscale_to_fit_256", "pad_to_square_with_motion_margin")

    def _vendor(self, request: GenerationRequest, job_id: str, index: int) -> dict[str, Any]:
        width, height = _png_size(request.source_png) if request.source_png else (64, 64)
        return {
            "job_id": job_id,
            "vendor_candidate_id": f"{job_id[:8]}_{index:02d}",
            "frame_count": request.frames or 8,
            # Returned, not requested: the caller asked for something else and
            # this is what it got.
            "fps": self.fixed_fps,
            "frame_w": width,
            "frame_h": height,
        }


@dataclass
class FakeSpriteLabSource(FakeProvider):
    """Imitates SpriteLab's `POST /generate`, including what it returns.

    A separate fake because it is a separate endpoint with a separate price: one
    credit at `epic`, against twenty for an animation. Deriving both from the
    live adapter's tables rather than typing them is the same rule the ElevenLabs
    rate change taught -- a fake that meters differently from the real endpoint
    lets a ceiling pass here and block there, which is the opposite of its job.

    What it returns is a **two-view sheet**, because that is what the live smoke
    got. A rehearsal against one tidy sprite would sail through a step the real
    output cannot take, and the crop that makes it submittable would be exercised
    by nothing until it was exercised by a paid run.
    """

    name: str = "spritelab"
    unit: str = "spritelab_credits"
    per_call: Decimal = SPRITELAB_CREDITS_PER_SOURCE
    stages: tuple[Stage, ...] = ("source",)
    #: /generate exposes no model parameter, so there is no model to record.
    model: str | None = None

    def _media(self, request: GenerationRequest, index: int) -> bytes:
        return _source_sheet(f"spritelab_source|{request.prompt}|{index}".encode())

    def _media_kind(self, request: GenerationRequest) -> Any:
        return "png"

    def _vendor(self, request: GenerationRequest, job_id: str, index: int) -> dict[str, Any]:
        width, height = SOURCE_SHEET_SIZE
        return {
            "sprite_id": f"spr_{job_id[:12]}",
            "vendor_candidate_id": f"{job_id[:8]}_{index:02d}",
            "width": width,
            "height": height,
            # Stated because the real header states it, and because a two-view
            # sheet that did not say so would read as one wide sprite.
            "views": len(SOURCE_VIEW_WIDTHS),
        }


@dataclass
class FakeOpenAIImages(FakeProvider):
    """Imitates the OpenAI Images API for source-sprite generation."""

    name: str = "openai_images"
    unit: str = "usd"
    #: Reviewed 2026-08-22. OpenAI assigns the user all its interest in Output,
    #: so a pack containing one is exclusive in the sense D17 tracks. Taken from
    #: the live adapter rather than typed, like every other value here.
    account_rights: str = OPENAI_RIGHTS
    #: What the live adapter's default size and quality actually cost. It was
    #: 0.04 -- a figure from the plan's early arithmetic, seven times the real
    #: price -- which is exactly the drift the ElevenLabs rate change taught us
    #: to remove by deriving rather than retyping.
    per_call: Decimal = OPENAI_USD_PER_IMAGE
    stages: tuple[Stage, ...] = ("source",)
    #: PROJECT_SCOPE.md names gpt-image-2 as the initial target. The exact model
    #: stays adapter configuration recorded in provenance, never a core field.
    model: str | None = "gpt-image-2"

    def _media(self, request: GenerationRequest, index: int) -> bytes:
        return _png(*_square(SMALLEST_SQUARE), f"openai|{request.prompt}|{index}".encode())

    def _media_kind(self, request: GenerationRequest) -> Any:
        return "png"

    def _vendor(self, request: GenerationRequest, job_id: str, index: int) -> dict[str, Any]:
        return {
            "request_id": f"req_{job_id[:12]}",
            "vendor_candidate_id": f"{job_id[:8]}_{index:02d}",
            "size": SMALLEST_SQUARE,
        }


@dataclass
class FakeElevenLabs(FakeProvider):
    """Imitates ElevenLabs sound-effect generation."""

    name: str = "elevenlabs"
    unit: str = "elevenlabs_credits"
    #: ElevenLabs' own rights context, not the inherited SpriteLab one. Without
    #: this a rehearsal export credits the sound to a SpriteLab account.
    account_rights: str = ELEVENLABS_RIGHTS
    #: What an 800 ms sound costs at the live adapter's rate -- the length the
    #: design package asks for. Derived rather than typed: a fake that meters
    #: differently from the real endpoint lets a ceiling pass here and block
    #: there, which is the opposite of its job, and a hardcoded 8 is exactly what
    #: went stale when the rate moved to the published 40 per second.
    per_call: Decimal = ELEVENLABS_CREDITS_PER_SECOND * 800 / 1000
    stages: tuple[Stage, ...] = ("sound",)

    def _media(self, request: GenerationRequest, index: int) -> bytes:
        return _wav(request.duration_ms or 800, f"11l|{request.prompt}|{index}".encode())

    def _media_kind(self, request: GenerationRequest) -> Any:
        return "wav"

    def _vendor(self, request: GenerationRequest, job_id: str, index: int) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "vendor_candidate_id": f"{job_id[:8]}_{index:02d}",
            "duration_ms": request.duration_ms or 800,
            "sample_rate": 44100,
        }


def _tiny_gif(delays_cs: tuple[int, ...]) -> bytes:
    """A minimal valid GIF89a: 2x2, 2-colour global palette, one GCE per frame.

    Each frame is an uncompressed-friendly LZW stream (min code size 2, four
    literal pixels, EOI). Deterministic and a few dozen bytes, which is all a
    delay-rewrite rehearsal needs.
    """
    header = b"GIF89a" + struct.pack("<HHBBB", 2, 2, 0x80, 0, 0) + bytes((0, 0, 0, 255, 255, 255))
    loop = b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    frames = b""
    for index, delay in enumerate(delays_cs):
        gce = b"\x21\xf9\x04" + bytes((0x08,)) + struct.pack("<H", delay) + b"\x00\x00"
        descriptor = b"\x2c" + struct.pack("<HHHHB", 0, 0, 2, 2, 0)
        # LZW min code size 2: clear=4, EOI=5. Pixels alternate by frame parity.
        pixel = 1 if index % 2 else 0
        codes = [4, pixel, pixel, pixel, pixel, 5]
        bits = 0
        nbits = 0
        out = bytearray()
        for code in codes:
            bits |= code << nbits
            nbits += 3
            while nbits >= 8:
                out.append(bits & 0xFF)
                bits >>= 8
                nbits -= 8
        if nbits:
            out.append(bits & 0xFF)
        data = b"\x02" + bytes((len(out),)) + bytes(out) + b"\x00"
        frames += gce + descriptor + data
    return header + loop + frames + b"\x3b"


#: Delays the web-UI previews were observed to carry (median 6-8 cs), so the
#: 8 fps normaliser has real work to do on the fake path.
FAKE_PREVIEW_GIF = _tiny_gif((6, 8))


def _png_size(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ProviderRejected("source is not a PNG")
    width, height = struct.unpack(">II", payload[16:24])
    return width, height


def all_fakes() -> tuple[FakeProvider, ...]:
    """Every fake, for the shared contract suite to run against."""
    return (FakeSpriteLab(), FakeSpriteLabSource(), FakeOpenAIImages(), FakeElevenLabs())
