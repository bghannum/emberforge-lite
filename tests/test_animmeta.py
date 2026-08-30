"""Manifest model and timing-source parsers (animmeta.py)."""

from __future__ import annotations

import json

import pytest

from emberforge_lite import animmeta
from emberforge_lite.animmeta import Frame, Manifest, ManifestError
from emberforge_lite.providers.fakes import _png, _tiny_gif

README = """# Briar Knight hit recoil

A 16-frame, non-looping reaction.

## Playback timing

- Loop: No.
- Engine base playback speed: `20.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `0.995` seconds.
- Uniform-timing fallback: approximately `15.8` FPS.
- Per-frame delays, in milliseconds: `60, 35, 40, 45, 50, 50, 60, 65, 60, 60, 60, 65, 70, 75, 80, 120`.

Frame 1 is the impact cue. Apply recoil offsets to the visual child, not the combat root.

## Folder contents

- `x_preview.gif`: authored timing preview.
"""

README_DELAYS = [60, 35, 40, 45, 50, 50, 60, 65, 60, 60, 60, 65, 70, 75, 80, 120]


class TestParseReadme:
    def test_full_parse(self):
        t = animmeta.parse_readme(README, 16)
        assert t is not None
        assert t.delays_ms == README_DELAYS
        assert t.loop is False
        assert t.fps == 20.0
        assert t.source == "readme"
        assert t.events["impact_frame"] == 1
        assert "impact cue" in t.events["notes"]
        assert "authored timing preview" not in t.events["notes"]  # next section excluded

    def test_loop_yes(self):
        text = README.replace("- Loop: No.", "- Loop: Yes.")
        assert animmeta.parse_readme(text, 16).loop is True

    def test_count_mismatch_returns_none(self):
        assert animmeta.parse_readme(README, 12) is None

    def test_no_delays_returns_none(self):
        assert animmeta.parse_readme("# nothing here\n", 16) is None

    def test_event_prose_variants(self):
        text = README.replace(
            "Frame 1 is the impact cue.",
            "Frame 10 is the visual peak. Frames 6-8 are the hit window. Frame 7 is the damage event. "
            "The final frame is a resulting-state idle rather than the original idle.",
        )
        t = animmeta.parse_readme(text, 16)
        assert t.events["visual_peak_frame"] == 10
        assert t.events["hit_window"] == [6, 8]
        assert t.events["damage_frame"] == 7
        assert t.resulting_state == "idle"
        assert "impact_frame" not in t.events

    def test_single_frame_hit_window(self):
        text = README.replace("Frame 1 is the impact cue.", "Frame 9 is the hit window.")
        assert animmeta.parse_readme(text, 16).events["hit_window"] == [9, 9]


class TestParseProfile:
    def test_seconds_form(self):
        doc = {
            "schema_version": 1,
            "animation": "hit_recoil",
            "frame_count": 3,
            "loop": False,
            "frame_delays_seconds": [0.06, 0.035, 0.12],
            "impact_frame_zero_based": 1,
            "visual_peak_frame_zero_based": 2,
            "hit_window_frames_zero_based": [1, 2],
            "resulting_visual_state": "canonical_idle",
        }
        t = animmeta.parse_profile(doc)
        assert t.delays_ms == [60, 35, 120]
        assert t.loop is False
        assert t.events == {"impact_frame": 1, "visual_peak_frame": 2, "hit_window": [1, 2]}
        assert t.resulting_state == "canonical_idle"
        assert t.source == "profile"

    def test_multiplier_form(self):
        doc = {"frame_count": 3, "playback_fps": 18.0, "frame_duration_multipliers": [1.5, 1.0, 0.65]}
        t = animmeta.parse_profile(doc)
        assert t.delays_ms == [83, 56, 36]
        assert t.fps == 18.0

    def test_count_mismatch(self):
        assert animmeta.parse_profile({"frame_count": 4, "frame_delays_seconds": [0.1, 0.1]}) is None

    def test_no_timing(self):
        assert animmeta.parse_profile({"frame_count": 2, "loop": True}) is None
        assert animmeta.parse_profile("nope") is None

    def test_bad_values(self):
        assert animmeta.parse_profile({"frame_delays_seconds": ["x"]}) is None
        assert animmeta.parse_profile({"frame_delays_seconds": [0.0]}) is None


class TestGifAndUniform:
    def test_gif_timing_is_centiseconds(self):
        t = animmeta.gif_timing(_tiny_gif((6, 8, 0)))
        assert t.delays_ms == [60, 80, 1]
        assert t.source == "gif"

    def test_gif_timing_none_for_garbage(self):
        assert animmeta.gif_timing(b"not a gif") is None

    def test_uniform(self):
        t = animmeta.uniform_timing(4, fps=8)
        assert t.delays_ms == [125] * 4
        assert t.source == "uniform"


class TestResolve:
    def test_precedence_and_backfill(self):
        readme = animmeta.Timing([10, 20], "readme", loop=None, events={"impact_frame": 1})
        profile = animmeta.Timing([11, 21], "profile", loop=True, fps=12.0, events={"visual_peak_frame": 0})
        gif = animmeta.Timing([30, 30], "gif")
        t = animmeta.resolve_timing([readme, profile, gif], 2)
        assert t.delays_ms == [10, 20]
        assert t.source == "readme"
        assert t.loop is True
        assert t.fps == 12.0
        assert t.events == {"impact_frame": 1, "visual_peak_frame": 0}

    def test_length_mismatch_falls_through(self):
        readme = animmeta.Timing([10, 20, 30], "readme")
        gif = animmeta.Timing([40, 40], "gif")
        t = animmeta.resolve_timing([readme, None, gif], 2)
        assert t.source == "gif"
        assert t.delays_ms == [40, 40]

    def test_uniform_fallback(self):
        t = animmeta.resolve_timing([None], 3)
        assert t.source == "uniform"
        assert len(t.delays_ms) == 3


def _manifest(n=2):
    return Manifest(name="walk", loop=True, frames=[Frame(f"frame_{i:02d}.png", 50 + i) for i in range(n)])


class TestManifest:
    def test_round_trip(self):
        m = _manifest()
        m.fps_hint = 10.0
        m.frame_size = (4, 4)
        m.events = {"impact_frame": 1}
        m.source = {"kind": "frames_folder", "timing_source": "readme"}
        doc = json.loads(json.dumps(m.to_json()))
        back = Manifest.from_json(doc)
        assert back == m
        assert back.total_ms() == 101
        assert back.delays() == [50, 51]
        assert set(doc["events"]) == set(animmeta.EVENT_KEYS)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.update(schema_version=2),
            lambda d: d.update(name=""),
            lambda d: d.update(frames=[]),
            lambda d: d.update(frames="x"),
            lambda d: d["frames"].__setitem__(0, {"file": "../x.png", "delay_ms": 5}),
            lambda d: d["frames"].__setitem__(0, {"file": "a.png", "delay_ms": 0}),
            lambda d: d["frames"].__setitem__(0, {"file": "a.png", "delay_ms": 60001}),
            lambda d: d["frames"].__setitem__(0, {"file": "a.png", "delay_ms": True}),
            lambda d: d["frames"].__setitem__(0, "nope"),
            lambda d: d.update(frame_size=[0, 4]),
            lambda d: d.update(fps_hint=-1),
            lambda d: d.update(events=[]),
            lambda d: d.update(source=[]),
        ],
    )
    def test_rejects_bad_documents(self, mutate):
        doc = _manifest().to_json()
        mutate(doc)
        with pytest.raises(ManifestError):
            Manifest.from_json(doc)

    def test_rejects_non_object_and_too_many_frames(self):
        with pytest.raises(ManifestError):
            Manifest.from_json([])
        with pytest.raises(ManifestError):
            Manifest.from_json(_manifest(65).to_json())

    def test_save_load_and_missing_frame(self, tmp_path):
        anim = tmp_path / "walk"
        (anim / "frames").mkdir(parents=True)
        for i in range(2):
            (anim / "frames" / f"frame_{i:02d}.png").write_bytes(_png(4, 4, b"f"))
        m = _manifest()
        animmeta.save_manifest(anim, m)
        assert animmeta.is_package(anim)
        assert animmeta.list_packages(tmp_path) == [anim]
        assert animmeta.list_packages(tmp_path / "nope") == []
        assert animmeta.load_manifest(anim) == m
        (anim / "frames" / "frame_01.png").unlink()
        with pytest.raises(ManifestError, match="missing"):
            animmeta.load_manifest(anim)

    def test_load_unreadable(self, tmp_path):
        anim = tmp_path / "bad"
        anim.mkdir()
        (anim / "manifest.json").write_text("{not json")
        with pytest.raises(ManifestError):
            animmeta.load_manifest(anim)
        with pytest.raises(ManifestError):
            animmeta.load_manifest(tmp_path / "absent")

    def test_validate_delays(self):
        assert animmeta.validate_delays([1, 2, 3], 3) == [1, 2, 3]
        with pytest.raises(ManifestError):
            animmeta.validate_delays([1, 2], 3)
        with pytest.raises(ManifestError):
            animmeta.validate_delays("x", 1)
        with pytest.raises(ManifestError):
            animmeta.validate_delays([0], 1)
