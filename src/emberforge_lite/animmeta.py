"""Frame-package manifests and the timing sources that feed them.

A *frame package* is an animation stored as ordered PNG frames plus a
``manifest.json`` that records exactly how long each frame is shown::

    actors/<slug>/animations/<name>/
        manifest.json
        frames/frame_00.png ...

The manifest is the source of truth for playback. A GIF cannot be: its delay
field is in centiseconds, so an authored 35 ms frame silently becomes 40 ms.
Libraries that ship per-frame timing do so in a README, a profile JSON, or a
Godot resource; :func:`resolve_timing` picks the most faithful one available.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from emberforge_lite import gifspeed, media, storage

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
FRAMES_DIR = "frames"
MIN_DELAY_MS = 1
MAX_DELAY_MS = 60_000
DEFAULT_UNIFORM_FPS = 20.0

TIMING_SOURCES = ("readme", "profile", "gif", "uniform", "edited")
EVENT_KEYS = ("impact_frame", "damage_frame", "hit_window", "visual_peak_frame", "notes")


class ManifestError(ValueError):
    """The manifest is malformed or disagrees with the files on disk."""


@dataclass
class Frame:
    file: str
    delay_ms: int


@dataclass
class Manifest:
    name: str
    loop: bool
    frames: list[Frame]
    fps_hint: float | None = None
    frame_size: tuple[int, int] | None = None
    events: dict[str, Any] = field(default_factory=dict)
    resulting_state: str | None = None
    source: dict[str, Any] = field(default_factory=dict)

    def total_ms(self) -> int:
        return sum(f.delay_ms for f in self.frames)

    def delays(self) -> list[int]:
        return [f.delay_ms for f in self.frames]

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "loop": self.loop,
            "fps_hint": self.fps_hint,
            "frame_size": list(self.frame_size) if self.frame_size else None,
            "frames": [{"file": f.file, "delay_ms": f.delay_ms} for f in self.frames],
            "events": {k: self.events.get(k) for k in EVENT_KEYS},
            "resulting_state": self.resulting_state,
            "source": dict(self.source),
        }

    @classmethod
    def from_json(cls, doc: Any) -> Manifest:
        if not isinstance(doc, dict):
            raise ManifestError("manifest must be a JSON object")
        if doc.get("schema_version") != SCHEMA_VERSION:
            raise ManifestError(f"unsupported manifest schema_version {doc.get('schema_version')!r}")
        name = doc.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestError("manifest name must be a non-empty string")
        raw_frames = doc.get("frames")
        if not isinstance(raw_frames, list) or not raw_frames:
            raise ManifestError("manifest needs a non-empty frames list")
        if len(raw_frames) > media.MAX_FRAMES:
            raise ManifestError(f"{len(raw_frames)} frames exceeds the {media.MAX_FRAMES}-frame limit")
        frames: list[Frame] = []
        for i, raw in enumerate(raw_frames):
            if not isinstance(raw, dict):
                raise ManifestError(f"frame {i} must be an object")
            file = raw.get("file")
            if not isinstance(file, str) or not file or Path(file).name != file or file.startswith("."):
                raise ManifestError(f"frame {i} has an invalid file name {file!r}")
            frames.append(Frame(file=file, delay_ms=_check_delay(raw.get("delay_ms"), i)))
        size = doc.get("frame_size")
        frame_size = None
        if size is not None:
            if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size)):
                raise ManifestError("frame_size must be [width, height]")
            frame_size = (size[0], size[1])
        fps = doc.get("fps_hint")
        if fps is not None and not (isinstance(fps, (int, float)) and fps > 0):
            raise ManifestError("fps_hint must be a positive number")
        events = doc.get("events")
        if events is not None and not isinstance(events, dict):
            raise ManifestError("events must be an object")
        source = doc.get("source")
        if source is not None and not isinstance(source, dict):
            raise ManifestError("source must be an object")
        return cls(
            name=name,
            loop=bool(doc.get("loop", False)),
            frames=frames,
            fps_hint=float(fps) if fps is not None else None,
            frame_size=frame_size,
            events={k: v for k, v in (events or {}).items() if v is not None},
            resulting_state=doc.get("resulting_state"),
            source=dict(source or {}),
        )


def _check_delay(value: Any, index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"frame {index} delay_ms must be an integer")
    if not MIN_DELAY_MS <= value <= MAX_DELAY_MS:
        raise ManifestError(f"frame {index} delay_ms {value} is outside {MIN_DELAY_MS}..{MAX_DELAY_MS}")
    return value


def validate_delays(raw: Any, expected: int) -> list[int]:
    """Check an edited delay list from the UI. Raises ManifestError."""
    if not isinstance(raw, list):
        raise ManifestError("delays must be a list")
    if len(raw) != expected:
        raise ManifestError(f"expected {expected} delays, got {len(raw)}")
    return [_check_delay(v, i) for i, v in enumerate(raw)]


# -- On-disk helpers -----------------------------------------------------------


def manifest_path(anim_dir: Path) -> Path:
    return anim_dir / MANIFEST_NAME


def is_package(path: Path) -> bool:
    return path.is_dir() and manifest_path(path).is_file()


def list_packages(animations_dir: Path) -> list[Path]:
    if not animations_dir.is_dir():
        return []
    return sorted(p for p in animations_dir.iterdir() if is_package(p))


def load_manifest(anim_dir: Path) -> Manifest:
    """Read and validate a package manifest; every frame file must exist."""
    try:
        doc = json.loads(manifest_path(anim_dir).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read {manifest_path(anim_dir)}: {exc}") from exc
    manifest = Manifest.from_json(doc)
    frames_dir = anim_dir / FRAMES_DIR
    for f in manifest.frames:
        if not (frames_dir / f.file).is_file():
            raise ManifestError(f"frame file missing: {FRAMES_DIR}/{f.file}")
    return manifest


def save_manifest(anim_dir: Path, manifest: Manifest) -> None:
    storage.atomic_write_text(manifest_path(anim_dir), json.dumps(manifest.to_json(), indent=2, sort_keys=True) + "\n")


# -- Timing sources --------------------------------------------------------------


@dataclass
class Timing:
    """Per-frame delays plus whatever else one source happened to declare."""

    delays_ms: list[int]
    source: str
    loop: bool | None = None
    fps: float | None = None
    events: dict[str, Any] = field(default_factory=dict)
    resulting_state: str | None = None


_README_LOOP = re.compile(r"^\s*-\s*Loop:\s*(Yes|No)\b", re.I | re.M)
_README_FPS = re.compile(r"^\s*-\s*Engine base playback speed:\s*`?([\d.]+)`?\s*FPS", re.I | re.M)
_README_DELAYS = re.compile(r"^\s*-\s*Per-frame delays, in milliseconds:\s*`?([\d,\s]+?)`?\.?\s*$", re.I | re.M)
_IMPACT = re.compile(r"\bFrame (\d+) is the impact cue", re.I)
_PEAK = re.compile(r"\bFrame (\d+) is the visual peak", re.I)
_DAMAGE = re.compile(r"\bFrame (\d+) is the damage (?:event|frame)", re.I)
_HIT_WINDOW = re.compile(r"\bFrames? (\d+)(?:\s*(?:-|–|to|through)\s*(\d+))?[^.]*\bhit window", re.I)
_RESULTING = re.compile(r"final frame is a resulting-state ([a-z][a-z _-]*?)(?: rather| idle|\.)", re.I)


def parse_readme(text: str, frame_count: int) -> Timing | None:
    """Timing from a package README's ``## Playback timing`` bullets.

    Returns None when there is no delay list or its length does not match the
    frames on disk, so precedence can fall through to the next source.
    """
    m = _README_DELAYS.search(text)
    if not m:
        return None
    try:
        delays = [int(v.strip()) for v in m.group(1).split(",") if v.strip()]
    except ValueError:
        return None
    if len(delays) != frame_count or any(d < MIN_DELAY_MS or d > MAX_DELAY_MS for d in delays):
        return None
    loop_m = _README_LOOP.search(text)
    fps_m = _README_FPS.search(text)
    events: dict[str, Any] = {}
    notes = _prose_after_timing(text)
    for key, rx in (("impact_frame", _IMPACT), ("visual_peak_frame", _PEAK), ("damage_frame", _DAMAGE)):
        hit = rx.search(notes)
        if hit:
            events[key] = int(hit.group(1))
    hw = _HIT_WINDOW.search(notes)
    if hw:
        start = int(hw.group(1))
        events["hit_window"] = [start, int(hw.group(2)) if hw.group(2) else start]
    if notes:
        events["notes"] = notes
    resulting = None
    rs = _RESULTING.search(notes)
    if rs:
        resulting = rs.group(1).strip().replace(" ", "_")
    return Timing(
        delays_ms=delays,
        source="readme",
        loop=(loop_m.group(1).lower() == "yes") if loop_m else None,
        fps=float(fps_m.group(1)) if fps_m else None,
        events=events,
        resulting_state=resulting,
    )


def _prose_after_timing(text: str) -> str:
    """The free-text paragraph(s) between the timing bullets and the next heading."""
    m = re.search(r"^##\s*Playback timing\s*$", text, re.I | re.M)
    if not m:
        return ""
    body = text[m.end() :]
    nxt = re.search(r"^##\s", body, re.M)
    if nxt:
        body = body[: nxt.start()]
    lines = [ln.strip() for ln in body.splitlines()]
    prose = [ln for ln in lines if ln and not ln.startswith("-")]
    return " ".join(prose)


def parse_profile(doc: Any) -> Timing | None:
    """Timing from a ``*_profile.json`` (schema_version 1) in either encoding."""
    if not isinstance(doc, dict):
        return None
    count = doc.get("frame_count")
    delays: list[int]
    seconds = doc.get("frame_delays_seconds")
    if isinstance(seconds, list) and seconds:
        try:
            delays = [int(round(float(s) * 1000)) for s in seconds]
        except (TypeError, ValueError):
            return None
    else:
        fps = doc.get("playback_fps")
        mults = doc.get("frame_duration_multipliers")
        if not (isinstance(mults, list) and mults and isinstance(fps, (int, float)) and fps > 0):
            return None
        try:
            delays = [int(round(1000.0 * float(m) / float(fps))) for m in mults]
        except (TypeError, ValueError):
            return None
    if isinstance(count, int) and count != len(delays):
        return None
    if any(d < MIN_DELAY_MS or d > MAX_DELAY_MS for d in delays):
        return None
    events: dict[str, Any] = {}
    if isinstance(doc.get("impact_frame_zero_based"), int):
        events["impact_frame"] = doc["impact_frame_zero_based"]
    if isinstance(doc.get("damage_event_frame_zero_based"), int):
        events["damage_frame"] = doc["damage_event_frame_zero_based"]
    if isinstance(doc.get("visual_peak_frame_zero_based"), int):
        events["visual_peak_frame"] = doc["visual_peak_frame_zero_based"]
    hw = doc.get("hit_window_frames_zero_based")
    if isinstance(hw, list) and hw and all(isinstance(v, int) for v in hw):
        events["hit_window"] = [min(hw), max(hw)]
    fps_hint = doc.get("playback_fps")
    return Timing(
        delays_ms=delays,
        source="profile",
        loop=doc["loop"] if isinstance(doc.get("loop"), bool) else None,
        fps=float(fps_hint) if isinstance(fps_hint, (int, float)) else None,
        events=events,
        resulting_state=doc.get("resulting_visual_state")
        if isinstance(doc.get("resulting_visual_state"), str)
        else None,
    )


def gif_timing(data: bytes) -> Timing | None:
    """Centisecond delays from a preview GIF: the lossy last resort."""
    delays = gifspeed.gce_delays(data)
    if not delays:
        return None
    return Timing(delays_ms=[max(MIN_DELAY_MS, d * 10) for d in delays], source="gif")


def uniform_timing(frame_count: int, fps: float = DEFAULT_UNIFORM_FPS) -> Timing:
    delay = max(MIN_DELAY_MS, int(round(1000.0 / fps)))
    return Timing(delays_ms=[delay] * frame_count, source="uniform", fps=fps)


def resolve_timing(candidates: list[Timing | None], frame_count: int) -> Timing:
    """Highest-precedence candidate with a matching delay count wins the delays.

    Loop, fps, events, and resulting state back-fill from lower-precedence
    candidates when the winner did not declare them.
    """
    usable = [c for c in candidates if c is not None]
    winner = next((c for c in usable if len(c.delays_ms) == frame_count), None)
    if winner is None:
        winner = uniform_timing(frame_count)
    merged = Timing(
        delays_ms=list(winner.delays_ms),
        source=winner.source,
        loop=winner.loop,
        fps=winner.fps,
        events=dict(winner.events),
        resulting_state=winner.resulting_state,
    )
    for other in usable:
        if other is winner:
            continue
        if merged.loop is None:
            merged.loop = other.loop
        if merged.fps is None:
            merged.fps = other.fps
        if merged.resulting_state is None:
            merged.resulting_state = other.resulting_state
        for key, value in other.events.items():
            merged.events.setdefault(key, value)
    return merged
