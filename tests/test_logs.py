"""Structured, redacting event log (logs.py)."""

from __future__ import annotations

import json

from emberforge_lite import logs
from emberforge_lite.config import Paths


def test_event_noop_before_configure(monkeypatch):
    monkeypatch.setattr(logs, "_log_path", None)
    logs.event("x", actor="a")  # must not raise


def test_event_writes_jsonl(tmp_path):
    paths = Paths(tmp_path / "data").ensure()
    logs.configure_logging(paths)
    logs.event("upload", actor="hero", operation="upload", outcome="ok", duration_ms=12.34)
    logs.event("delete", actor="hero", operation="delete", outcome="ok")
    lines = (paths.data_dir / "logs" / "emberforge.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "upload"
    assert first["actor"] == "hero"
    assert first["duration_ms"] == 12.3


def test_error_is_redacted(tmp_path):
    paths = Paths(tmp_path / "data").ensure()
    logs.configure_logging(paths)
    logs.event("fail", actor="hero", outcome="error", error="Authorization: Bearer sk-secret123")
    rec = json.loads((paths.data_dir / "logs" / "emberforge.jsonl").read_text().strip())
    assert "sk-secret123" not in rec["error"]
    assert "[redacted]" in rec["error"]


def test_none_fields_omitted(tmp_path):
    paths = Paths(tmp_path / "data").ensure()
    logs.configure_logging(paths)
    logs.event("plain")
    rec = json.loads((paths.data_dir / "logs" / "emberforge.jsonl").read_text().strip())
    assert "actor" not in rec
    assert rec["event"] == "plain"
