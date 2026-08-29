"""Structured, local, redacting event log.

One JSON object per line under ``<data-dir>/logs/emberforge.jsonl`` with a fixed
shape: timestamp, event, actor, operation, duration_ms, outcome, and a redacted
error. Prompts are never logged (they may be sensitive), and credential values
never appear anywhere -- errors pass through the provider redactor first.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from emberforge_lite.providers.transport import redact

_lock = threading.Lock()
_log_path: Path | None = None


def configure_logging(paths) -> None:
    """Point the event log at ``<data-dir>/logs/emberforge.jsonl``."""
    global _log_path
    logs_dir = paths.data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    _log_path = logs_dir / "emberforge.jsonl"


def event(
    name: str,
    *,
    actor: str | None = None,
    operation: str | None = None,
    duration_ms: float | None = None,
    outcome: str | None = None,
    error: str | None = None,
    **extra: Any,
) -> None:
    """Append one structured event. A no-op until configure_logging() runs."""
    if _log_path is None:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": name,
        "actor": actor,
        "operation": operation,
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        "outcome": outcome,
        "error": redact(error) if error else None,
    }
    record.update(extra)
    line = json.dumps({k: v for k, v in record.items() if v is not None}, sort_keys=True)
    with _lock:
        with _log_path.open("a") as fh:
            fh.write(line + "\n")
