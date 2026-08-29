"""Redaction and the HTTP transport seam (providers/transport.py)."""

from __future__ import annotations

import io

import pytest

from emberforge_lite.providers.transport import (
    Response,
    TransportError,
    UrllibTransport,
    redact,
)


class TestRedact:
    def test_bearer_token(self):
        out = redact("Authorization: Bearer sk-abc123DEF")
        assert "sk-abc123DEF" not in out
        assert "[redacted]" in out

    def test_api_key_field(self):
        out = redact('{"api_key": "abcdEFGH1234"}')
        assert "abcdEFGH1234" not in out
        assert "[redacted]" in out

    def test_token_assignment(self):
        assert "supersecretvalue" not in redact("token=supersecretvalue")

    def test_plain_text_untouched(self):
        assert redact("nothing secret here") == "nothing secret here"


class TestResponse:
    def test_json_object(self):
        r = Response(200, b'{"a": 1}')
        assert r.json() == {"a": 1}

    def test_json_non_object_raises(self):
        with pytest.raises(TransportError):
            Response(200, b"[1, 2, 3]").json()

    def test_json_invalid_raises(self):
        with pytest.raises(TransportError):
            Response(200, b"not json").json()

    def test_header_case_insensitive(self):
        r = Response(200, b"{}", {"Content-Type": "application/json"})
        assert r.header("content-type") == "application/json"
        assert r.header("missing") is None


class _FakeResp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class _FakeOpener:
    def __init__(self, resp):
        self._resp = resp

    def open(self, fullurl, data=None, timeout=None):
        return self._resp


class TestUrllibTransport:
    def test_non_https_refused(self):
        t = UrllibTransport()
        with pytest.raises(TransportError):
            t.send("GET", "http://example.com", headers={})

    def test_success_via_fake_opener(self):
        t = UrllibTransport()
        t._opener = _FakeOpener(_FakeResp(b'{"ok": true}', 200, {"X-Test": "1"}))
        resp = t.send("GET", "https://example.com", headers={})
        assert resp.status == 200
        assert resp.json() == {"ok": True}
        assert resp.header("x-test") == "1"

    def test_oversized_body_refused(self):
        t = UrllibTransport(max_response_bytes=8)
        t._opener = _FakeOpener(_FakeResp(b"x" * 100))
        with pytest.raises(TransportError):
            t.send("GET", "https://example.com", headers={})
