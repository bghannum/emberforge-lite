"""Characterize the fake providers' contract (providers/fakes.py).

The fakes imitate the real adapters' documented behavior; these tests pin
that the offline path exercises estimate -> submit -> poll -> collect the way
generate.py depends on.
"""

from __future__ import annotations

import pytest

from emberforge_lite import media
from emberforge_lite.providers.base import (
    AuthenticationFailed,
    GenerationRequest,
    ProviderRejected,
)
from emberforge_lite.providers.fakes import (
    FailureScript,
    FakeElevenLabs,
    FakeOpenAIImages,
    FakeSpriteLab,
    FakeSpriteLabSource,
    _png,
    all_fakes,
)


def _fit_source() -> bytes:
    # A 64x64 still that fits SpriteLab's 256px cap.
    return _png(64, 64, b"src")


class TestDeterminism:
    def test_same_request_same_job_id(self):
        req = GenerationRequest(stage="sound", prompt="whoosh", duration_ms=800)
        a = FakeElevenLabs().submit(req).job_id
        b = FakeElevenLabs().submit(req).job_id
        assert a == b

    def test_same_request_same_media(self):
        req = GenerationRequest(stage="sound", prompt="whoosh", duration_ms=800)
        fa, fb = FakeElevenLabs(), FakeElevenLabs()
        ja, jb = fa.submit(req), fb.submit(req)
        for f, j in ((fa, ja), (fb, jb)):
            for _ in range(5):
                if f.poll(j.job_id).is_terminal:
                    break
        assert fa.collect(ja.job_id)[0].media == fb.collect(jb.job_id)[0].media


class TestPollBecomesTerminal:
    @pytest.mark.parametrize("fake", all_fakes(), ids=lambda f: f.name)
    def test_reaches_terminal_after_polls(self, fake):
        req = _request_for(fake)
        receipt = fake.submit(req)
        states = []
        for _ in range(5):
            status = fake.poll(receipt.job_id)
            states.append(status.state)
            if status.is_terminal:
                break
        # One intermediate 'running' then 'succeeded'.
        assert states[-1] == "succeeded"
        assert "running" in states


class TestSpriteLabInputCap:
    def test_rejects_over_256(self):
        big = _png(300, 300, b"big")
        req = GenerationRequest(stage="animation", prompt="lunge", source_png=big, frames=8)
        with pytest.raises(ProviderRejected):
            FakeSpriteLab().submit(req)

    def test_accepts_within_cap(self):
        req = GenerationRequest(stage="animation", prompt="lunge", source_png=_fit_source(), frames=8)
        assert FakeSpriteLab().submit(req).job_id


class TestFailureScript:
    def test_unauthenticated(self):
        f = FakeElevenLabs(script=FailureScript(unauthenticated=True))
        with pytest.raises(AuthenticationFailed):
            f.submit(GenerationRequest(stage="sound", prompt="x", duration_ms=800))

    def test_failed_job_reports_refund(self):
        f = FakeSpriteLab(script=FailureScript(fail_job=True))
        receipt = f.submit(GenerationRequest(stage="animation", prompt="x", source_png=_fit_source(), frames=8))
        status = None
        for _ in range(5):
            status = f.poll(receipt.job_id)
            if status.is_terminal:
                break
        assert status.state == "failed"
        assert status.refunded is True


class TestMediaValidates:
    def test_sound_media_is_valid_wav(self):
        f = FakeElevenLabs()
        req = GenerationRequest(stage="sound", prompt="hum", duration_ms=800)
        r = f.submit(req)
        for _ in range(5):
            if f.poll(r.job_id).is_terminal:
                break
        media.inspect_wav(f.collect(r.job_id)[0].media)

    def test_openai_media_is_valid_png(self):
        f = FakeOpenAIImages()
        req = GenerationRequest(stage="source", prompt="knight")
        r = f.submit(req)
        for _ in range(5):
            if f.poll(r.job_id).is_terminal:
                break
        media.inspect_png(f.collect(r.job_id)[0].media)


def _request_for(fake) -> GenerationRequest:
    if isinstance(fake, FakeSpriteLab):
        return GenerationRequest(stage="animation", prompt="lunge", source_png=_fit_source(), frames=8)
    if isinstance(fake, (FakeSpriteLabSource, FakeOpenAIImages)):
        return GenerationRequest(stage="source", prompt="knight")
    return GenerationRequest(stage="sound", prompt="hum", duration_ms=800)
