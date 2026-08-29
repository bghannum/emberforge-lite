"""Offline, no-credential contract suite for the live provider adapters.

Each real adapter runs through the transport seam against canned responses, so
the actual request shaping, response parsing, and error mapping are exercised
with no network and no keys.
"""

from __future__ import annotations

import base64
import json

import pytest

from emberforge_lite.providers.base import (
    AmbiguousOutcome,
    AuthenticationFailed,
    GenerationRequest,
    ProviderRejected,
    RateLimited,
)
from emberforge_lite.providers.elevenlabs import ElevenLabs
from emberforge_lite.providers.fakes import _png, _source_sheet, _tiny_gif, _wav
from emberforge_lite.providers.openai_images import OpenAIImages
from emberforge_lite.providers.spritelab import SpriteLab, SpriteLabSource
from emberforge_lite.providers.transport import Response, TransportError


class FakeTransport:
    """Returns queued canned responses in order; records the calls made."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def send(self, method, url, *, headers, body=None, timeout=60):
        self.calls.append((method, url))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _drain_to_terminal(provider, job_id, limit=5):
    status = None
    for _ in range(limit):
        status = provider.poll(job_id)
        if status.is_terminal:
            break
    return status


# -- OpenAI Images -----------------------------------------------------------


def _openai_ok_response():
    png = _png(64, 64, b"openai")
    body = json.dumps({"data": [{"b64_json": base64.b64encode(png).decode()}], "usage": {"total_tokens": 10}}).encode()
    return Response(200, body, {"x-request-id": "req_abc"})


class TestOpenAIImages:
    def test_estimate_is_usd(self):
        p = OpenAIImages(key="test", transport=FakeTransport())
        est = p.estimate(GenerationRequest(stage="source", prompt="a knight"))
        assert est.unit == "usd"

    def test_submit_poll_collect(self):
        p = OpenAIImages(key="test", transport=FakeTransport(_openai_ok_response()))
        r = p.submit(GenerationRequest(stage="source", prompt="a knight"))
        assert p.poll(r.job_id).state == "succeeded"
        cand = p.collect(r.job_id)[0]
        assert cand.media_kind == "png"
        assert cand.media.startswith(b"\x89PNG")

    def test_auth_failure(self):
        p = OpenAIImages(key="bad", transport=FakeTransport(Response(401, b"{}")))
        with pytest.raises(AuthenticationFailed):
            p.submit(GenerationRequest(stage="source", prompt="x"))

    def test_rate_limited(self):
        p = OpenAIImages(key="t", transport=FakeTransport(Response(429, b"{}", {"retry-after": "3"})))
        with pytest.raises(RateLimited):
            p.submit(GenerationRequest(stage="source", prompt="x"))

    def test_server_error_is_ambiguous(self):
        p = OpenAIImages(key="t", transport=FakeTransport(Response(500, b"oops")))
        with pytest.raises(AmbiguousOutcome):
            p.submit(GenerationRequest(stage="source", prompt="x"))

    def test_transport_failure_on_post_is_ambiguous(self):
        p = OpenAIImages(key="t", transport=FakeTransport(TransportError("down")))
        with pytest.raises(AmbiguousOutcome):
            p.submit(GenerationRequest(stage="source", prompt="x"))


# -- ElevenLabs --------------------------------------------------------------


class TestElevenLabs:
    def test_estimate_is_credits(self):
        p = ElevenLabs(key="t", transport=FakeTransport())
        est = p.estimate(GenerationRequest(stage="sound", prompt="whoosh", duration_ms=800))
        assert est.unit == "elevenlabs_credits"

    def test_submit_poll_collect_with_reported_charge(self):
        wav = _wav(800, b"11l")
        resp = Response(200, wav, {"character-cost": "32", "Content-Type": "audio/mpeg", "request-id": "req_1"})
        p = ElevenLabs(key="t", transport=FakeTransport(resp))
        r = p.submit(GenerationRequest(stage="sound", prompt="whoosh", duration_ms=800))
        assert p.poll(r.job_id).state == "succeeded"
        cand = p.collect(r.job_id)[0]
        assert str(cand.reported_charge) == "32"

    def test_auth_failure(self):
        p = ElevenLabs(key="bad", transport=FakeTransport(Response(403, b"{}")))
        with pytest.raises(AuthenticationFailed):
            p.submit(GenerationRequest(stage="sound", prompt="x", duration_ms=800))

    def test_empty_body_is_ambiguous(self):
        p = ElevenLabs(key="t", transport=FakeTransport(Response(200, b"", {"Content-Type": "audio/mpeg"})))
        with pytest.raises(AmbiguousOutcome):
            p.submit(GenerationRequest(stage="sound", prompt="x", duration_ms=800))

    def test_duration_out_of_range_refused(self):
        p = ElevenLabs(key="t", transport=FakeTransport())
        with pytest.raises(ProviderRejected):
            p.submit(GenerationRequest(stage="sound", prompt="x", duration_ms=99))


# -- SpriteLab (animation, async) -------------------------------------------


def _fit_source() -> bytes:
    return _png(64, 64, b"src")  # 64px <= 256px cap


class TestSpriteLabAnimation:
    def test_estimate_is_credits(self):
        p = SpriteLab(key="t", transport=FakeTransport())
        est = p.estimate(GenerationRequest(stage="animation", prompt="lunge", source_png=_fit_source(), frames=8))
        assert est.unit == "spritelab_credits"

    def test_submit_poll_collect(self):
        sheet = _png(512, 64, b"sheet")
        gif = _tiny_gif((6, 8))
        submit_resp = Response(200, json.dumps({"job_id": "job1"}).encode())
        running = Response(200, json.dumps({"status": "running"}).encode())
        done = Response(
            200,
            json.dumps(
                {
                    "status": "succeeded",
                    "sheet_b64": base64.b64encode(sheet).decode(),
                    "gif_b64": base64.b64encode(gif).decode(),
                }
            ).encode(),
        )
        # send order: submit, poll(running), poll(done), collect(done)
        p = SpriteLab(key="t", transport=FakeTransport(submit_resp, running, done, done))
        r = p.submit(GenerationRequest(stage="animation", prompt="lunge", source_png=_fit_source(), frames=8))
        assert r.job_id == "job1"
        assert p.poll(r.job_id).state == "running"
        assert p.poll(r.job_id).state == "succeeded"
        cand = p.collect(r.job_id)[0]
        assert cand.media_kind == "png"

    def test_input_over_cap_refused(self):
        p = SpriteLab(key="t", transport=FakeTransport())
        with pytest.raises(ProviderRejected):
            p.submit(GenerationRequest(stage="animation", prompt="lunge", source_png=_png(300, 300, b"big"), frames=8))

    def test_submit_without_job_id_is_ambiguous(self):
        p = SpriteLab(key="t", transport=FakeTransport(Response(200, b"{}")))
        with pytest.raises(AmbiguousOutcome):
            p.submit(GenerationRequest(stage="animation", prompt="lunge", source_png=_fit_source(), frames=8))

    def test_auth_failure(self):
        p = SpriteLab(key="bad", transport=FakeTransport(Response(401, b"{}")))
        with pytest.raises(AuthenticationFailed):
            p.submit(GenerationRequest(stage="animation", prompt="lunge", source_png=_fit_source(), frames=8))


class TestSpriteLabSource:
    def test_submit_poll_collect(self):
        # /generate is synchronous and returns the PNG body directly. submit()
        # first reads the free /credits balance (tolerating failure -> None),
        # then POSTs /generate; poll and collect then read held state.
        sheet = _source_sheet(b"src")
        credits_fail = Response(500, b"{}")
        generate_ok = Response(200, sheet, {"x-spritelab-sprite-id": "spr1"})
        p = SpriteLabSource(key="t", quality="epic", transport=FakeTransport(credits_fail, generate_ok))
        r = p.submit(GenerationRequest(stage="source", prompt="a scribe"))
        assert r.job_id
        status = _drain_to_terminal(p, r.job_id)
        assert status.state == "succeeded"
        cand = p.collect(r.job_id)[0]
        assert cand.media_kind == "png"


# -- More SpriteLab / ElevenLabs branches -----------------------------------


class TestSpriteLabExtras:
    def test_credits_endpoint(self):
        resp = Response(200, json.dumps({"credits": 340, "tier": "ranger"}).encode())
        p = SpriteLab(key="t", transport=FakeTransport(resp))
        assert p.credits() == (340, "ranger")

    def test_poll_failed_with_refund(self):
        submit_resp = Response(200, json.dumps({"job_id": "j1"}).encode())
        failed = Response(200, json.dumps({"status": "failed", "detail": "boom", "refunded": True}).encode())
        p = SpriteLab(key="t", transport=FakeTransport(submit_resp, failed))
        r = p.submit(GenerationRequest(stage="animation", prompt="x", source_png=_fit_source(), frames=8))
        status = p.poll(r.job_id)
        assert status.state == "failed"
        assert status.refunded is True

    def test_collect_while_running_refused(self):
        submit_resp = Response(200, json.dumps({"job_id": "j1"}).encode())
        running = Response(200, json.dumps({"status": "running"}).encode())
        p = SpriteLab(key="t", transport=FakeTransport(submit_resp, running))
        r = p.submit(GenerationRequest(stage="animation", prompt="x", source_png=_fit_source(), frames=8))
        with pytest.raises(ProviderRejected):
            p.collect(r.job_id)

    def test_rate_limited(self):
        p = SpriteLab(key="t", transport=FakeTransport(Response(429, b"{}", {"Retry-After": "5"})))
        with pytest.raises(RateLimited):
            p.submit(GenerationRequest(stage="animation", prompt="x", source_png=_fit_source(), frames=8))


class TestElevenLabsExtras:
    def test_remaining_allowance(self):
        resp = Response(200, json.dumps({"character_count": 8, "character_limit": 40000}).encode())
        p = ElevenLabs(key="t", transport=FakeTransport(resp))
        remaining, why = p.remaining_allowance()
        assert remaining == 39992
        assert "subscription" in why

    def test_currency_estimate_as_overage(self):
        p = ElevenLabs(key="t", transport=FakeTransport())
        est = p.currency_estimate(GenerationRequest(stage="sound", prompt="x", duration_ms=800), included_remaining=0)
        assert est is not None
        assert est.unit == "usd"

    def test_rate_limited(self):
        p = ElevenLabs(key="t", transport=FakeTransport(Response(429, b"{}", {"retry-after": "2"})))
        with pytest.raises(RateLimited):
            p.submit(GenerationRequest(stage="sound", prompt="x", duration_ms=800))


class TestSpriteLabErrorsAndSource:
    def test_submit_server_error_is_ambiguous(self):
        p = SpriteLab(key="t", transport=FakeTransport(Response(500, b"oops")))
        with pytest.raises(AmbiguousOutcome):
            p.submit(GenerationRequest(stage="animation", prompt="x", source_png=_fit_source(), frames=8))

    def test_source_charge_from_balances(self):
        sheet = _source_sheet(b"src")
        credits_before = Response(200, json.dumps({"credits": 340, "tier": "ranger"}).encode())
        generated = Response(200, sheet, {"x-spritelab-sprite-id": "spr1", "x-spritelab-credits-remaining": "339"})
        p = SpriteLabSource(key="t", quality="epic", transport=FakeTransport(credits_before, generated))
        r = p.submit(GenerationRequest(stage="source", prompt="a scribe"))
        cand = p.collect(r.job_id)[0]
        # 340 - 339 = 1 credit, reported from two provider-stated balances.
        assert str(cand.reported_charge) == "1"

    def test_source_auth_failure(self):
        # credits() 500 -> balance None; /generate 401 -> AuthenticationFailed.
        p = SpriteLabSource(
            key="bad", quality="epic", transport=FakeTransport(Response(500, b"{}"), Response(401, b"{}"))
        )
        with pytest.raises(AuthenticationFailed):
            p.submit(GenerationRequest(stage="source", prompt="x"))


class TestElevenLabsSubscription:
    def test_remaining_allowance_auth_failure(self):
        p = ElevenLabs(key="bad", transport=FakeTransport(Response(401, b"{}")))
        remaining, why = p.remaining_allowance()
        assert remaining is None
        assert "Sound Effects" in why

    def test_credit_usage(self):
        resp = Response(200, json.dumps({"character_count": 8, "character_limit": 40000}).encode())
        p = ElevenLabs(key="t", transport=FakeTransport(resp))
        assert p.credit_usage() == (8, 40000)

    def test_currency_estimate_none_when_covered(self):
        p = ElevenLabs(key="t", transport=FakeTransport())
        est = p.currency_estimate(
            GenerationRequest(stage="sound", prompt="x", duration_ms=800), included_remaining=100000
        )
        assert est is None
