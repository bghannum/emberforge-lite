"""Library import: layout detection, adapters, timing precedence, idempotence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emberforge_lite import animmeta, cli, importer, media, provenance
from emberforge_lite.config import Paths
from emberforge_lite.providers.fakes import _png, _tiny_gif

README_TMPL = """# {title}

## Playback timing

- Loop: {loop}.
- Engine base playback speed: `{fps}` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `x` seconds.
- Uniform-timing fallback: approximately `x` FPS.
- Per-frame delays, in milliseconds: `{delays}`.

{prose}

## Folder contents

- `frames/`: ordered transparent gameplay PNGs.
"""


def make_package(
    folder: Path,
    *,
    frames: int = 3,
    delays: list[int] | None = None,
    loop: str = "No",
    prose: str = "Frame 1 is the impact cue.",
    gif_stem: str | None = None,
    readme: bool = True,
    size: tuple[int, int] = (4, 4),
) -> Path:
    (folder / "frames").mkdir(parents=True)
    for i in range(frames):
        (folder / "frames" / f"frame_{i:02d}.png").write_bytes(_png(*size, f"f{i}".encode()))
    if gif_stem:
        (folder / f"{gif_stem}_preview.gif").write_bytes(_tiny_gif(tuple([7] * frames)))
    if readme:
        delays = delays or [50 + 10 * i for i in range(frames)]
        (folder / "README.md").write_text(
            README_TMPL.format(
                title=folder.name, loop=loop, fps="12.0", delays=", ".join(map(str, delays)), prose=prose
            )
        )
    return folder


@pytest.fixture
def library(tmp_path) -> Path:
    lib = tmp_path / "lib"
    knight = lib / "Briar Knight"
    knight.mkdir(parents=True)
    (knight / "briar_knight_idle_game.png").write_bytes(_png(4, 4, b"idle"))
    (knight / "briar_knight_idle_standing.png").write_bytes(_png(8, 8, b"big"))
    (knight / ".DS_Store").write_bytes(b"junk")
    make_package(knight / "briar_knight_hit_recoil", delays=[60, 35, 120], loop="No")
    make_package(knight / "briar_knight_attack (deprecated)", gif_stem="briar_knight_lunge_attack", frames=2)
    make_package(knight / "briar_knight_battle_idle", loop="Yes", prose="", readme=True)

    scribe = lib / "Gravescribe"
    scribe.mkdir()
    make_package(scribe / "gravescribe_dark_mist", readme=False, gif_stem="gravescribe_dark_mist", frames=2)

    # Archive mirrors the tree; must be ignored, except the opportunistic profile.
    prod = lib / "_production" / "Briar Knight" / "briar_knight_battle_idle"
    prod.mkdir(parents=True)
    (prod / "battle_idle_profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "animation": "battle_idle",
                "frame_count": 3,
                "loop": True,
                "frame_delays_seconds": [0.1, 0.1, 0.1],
                "visual_peak_frame_zero_based": 2,
            }
        )
    )
    stale = lib / "_production" / "Gravescribe" / "gravescribe_dark_mist"
    stale.mkdir(parents=True)
    (stale / "other_profile.json").write_text(
        json.dumps({"animation": "something_else", "frame_delays_seconds": [0.1, 0.1]})
    )
    (lib / "_production" / "_macos_metadata").mkdir()
    (lib / "README.md").write_text("# lib\n")
    return lib


@pytest.fixture
def dest(tmp_path) -> Paths:
    return Paths(tmp_path / "data").ensure()


class TestNames:
    def test_name_from_gif_stem_and_deprecated_strip(self, tmp_path):
        f = make_package(tmp_path / "briar_knight_attack (deprecated)", gif_stem="briar_knight_lunge_attack")
        assert importer.derive_anim_name(f) == "briar_knight_lunge_attack"
        assert importer.is_deprecated(f)

    def test_name_from_folder(self, tmp_path):
        f = make_package(tmp_path / "Rose Bloom (Deprecated)")
        assert importer.derive_anim_name(f) == "rose_bloom"
        assert not importer.is_deprecated(tmp_path)

    def test_unnameable(self, tmp_path):
        f = make_package(tmp_path / "(deprecated)")
        with pytest.raises(importer.ImportFailure):
            importer.derive_anim_name(f)


class TestAdapters:
    def test_frames_folder_detected(self, tmp_path):
        f = make_package(tmp_path / "walk")
        assert isinstance(importer.detect_adapter(f), importer.FramesFolderAdapter)

    def test_atlas_stub(self, tmp_path):
        f = tmp_path / "atlas"
        f.mkdir()
        (f / "walk_16f_aligned.png").write_bytes(_png(8, 8, b"a"))
        adapter = importer.detect_adapter(f)
        assert isinstance(adapter, importer.AtlasGridAdapter)
        with pytest.raises(NotImplementedError):
            adapter.load(f, library_root=tmp_path, warnings=[])

    def test_gif_stub(self, tmp_path):
        f = tmp_path / "gifonly"
        f.mkdir()
        (f / "walk_preview.gif").write_bytes(_tiny_gif((5, 5)))
        adapter = importer.detect_adapter(f)
        assert isinstance(adapter, importer.GifAdapter)
        with pytest.raises(NotImplementedError):
            adapter.load(f, library_root=tmp_path, warnings=[])

    def test_nothing_detected(self, tmp_path):
        f = tmp_path / "empty"
        f.mkdir()
        assert importer.detect_adapter(f) is None


class TestImportLibrary:
    def test_full_library(self, library, dest):
        summary = importer.import_library(library, dest)
        assert summary.actors == 2
        assert summary.animations == 3
        assert summary.frames == 8
        assert summary.sheets == 3
        assert summary.sprites == 1
        assert [s for s in summary.skipped if "deprecated" in s] == [
            "Briar Knight/briar_knight_attack (deprecated) [deprecated]"
        ]
        assert any("something_else" in w for w in summary.warnings)

        knight = dest.actors / "briar-knight"
        assert sorted(p.name for p in (knight / "animations").iterdir()) == [
            "briar_knight_battle_idle",
            "briar_knight_hit_recoil",
        ]
        assert (knight / "sprites" / "briar_knight_idle_game.png").is_file()
        assert not (knight / "sprites" / "briar_knight_idle_standing.png").exists()
        assert not (dest.actors / "_production").exists()

        m = animmeta.load_manifest(knight / "animations" / "briar_knight_hit_recoil")
        assert m.delays() == [60, 35, 120]
        assert m.loop is False
        assert m.fps_hint == 12.0
        assert m.frame_size == (4, 4)
        assert m.events["impact_frame"] == 1
        assert m.source["timing_source"] == "readme"
        assert m.source["kind"] == "frames_folder"
        assert m.source["path"] == "Briar Knight/briar_knight_hit_recoil"
        assert m.source["deprecated"] is False
        assert (knight / "sheets" / "briar_knight_hit_recoil_sheet.png").is_file()

        # README wins delays; profile back-fills the peak event.
        idle = animmeta.load_manifest(knight / "animations" / "briar_knight_battle_idle")
        assert idle.loop is True
        assert idle.source["timing_source"] == "readme"
        assert idle.events["visual_peak_frame"] == 2

        # No README: the preview GIF's centisecond delays are the fallback.
        mist = animmeta.load_manifest(dest.actors / "gravescribe" / "animations" / "gravescribe_dark_mist")
        assert mist.delays() == [70, 70]
        assert mist.source["timing_source"] == "gif"

        prov = provenance.load(knight)["assets"]
        assert prov["animations/briar_knight_hit_recoil"]["source"] == "imported"
        assert prov["sheets/briar_knight_hit_recoil_sheet.png"]["source"] == "imported"
        assert prov["sprites/briar_knight_idle_game.png"]["source"] == "imported"

    def test_include_deprecated(self, library, dest):
        summary = importer.import_library(library, dest, include_deprecated=True)
        assert summary.animations == 4
        m = animmeta.load_manifest(dest.actors / "briar-knight" / "animations" / "briar_knight_lunge_attack")
        assert m.source["deprecated"] is True

    def test_rerun_is_idempotent(self, library, dest):
        importer.import_library(library, dest)
        before = sorted(str(p.relative_to(dest.actors)) for p in dest.actors.rglob("*"))
        # Change a README; the re-run must pick it up and not leave stragglers.
        readme = library / "Briar Knight" / "briar_knight_hit_recoil" / "README.md"
        readme.write_text(readme.read_text().replace("60, 35, 120", "10, 20, 30"))
        importer.import_library(library, dest)
        after = sorted(str(p.relative_to(dest.actors)) for p in dest.actors.rglob("*"))
        assert before == after
        m = animmeta.load_manifest(dest.actors / "briar-knight" / "animations" / "briar_knight_hit_recoil")
        assert m.delays() == [10, 20, 30]
        assert not any(p.name.startswith(".efl-tmp-") for p in dest.actors.rglob("*"))
        assert len(provenance.load(dest.actors / "briar-knight")["assets"]) == 5

    def test_single_character_source_with_actor_slug(self, library, dest):
        summary = importer.import_library(library / "Briar Knight", dest, actor="knight")
        assert summary.actors == 1
        assert (dest.actors / "knight" / "animations" / "briar_knight_hit_recoil").is_dir()

    def test_actor_flag_rejected_for_multi_character(self, library, dest):
        with pytest.raises(importer.ImportFailure):
            importer.import_library(library, dest, actor="x")

    def test_missing_or_empty_source(self, tmp_path, dest):
        with pytest.raises(importer.ImportFailure):
            importer.import_library(tmp_path / "nope", dest)
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(importer.ImportFailure):
            importer.import_library(empty, dest)

    def test_bad_animation_skipped_others_continue(self, tmp_path, dest):
        lib = tmp_path / "lib"
        char = lib / "hero"
        make_package(char / "hero_good")
        bad = make_package(char / "hero_mixed", frames=2)
        (bad / "frames" / "frame_01.png").write_bytes(_png(6, 6, b"odd"))
        unknown = char / "hero_unknown"
        unknown.mkdir()
        (unknown / "notes.txt").write_text("x")
        summary = importer.import_library(lib, dest)
        assert summary.animations == 1
        assert any("hero_mixed" in s and "rejected" in s for s in summary.skipped)
        assert any("hero_unknown" in s and "no recognised layout" in s for s in summary.skipped)
        assert not (dest.actors / "hero" / "animations" / "hero_mixed").exists()

    def test_no_timing_uses_uniform_with_warning(self, tmp_path, dest):
        lib = tmp_path / "lib"
        make_package(lib / "hero" / "hero_walk", readme=False)
        summary = importer.import_library(lib, dest)
        assert any("uniform" in w for w in summary.warnings)
        m = animmeta.load_manifest(dest.actors / "hero" / "animations" / "hero_walk")
        assert m.source["timing_source"] == "uniform"

    def test_too_many_frames_rejected(self, tmp_path, dest, monkeypatch):
        monkeypatch.setattr(media, "MAX_FRAMES", 2)
        lib = tmp_path / "lib"
        make_package(lib / "hero" / "hero_long", frames=3)
        summary = importer.import_library(lib, dest)
        assert summary.animations == 0
        assert any("exceeds" in s for s in summary.skipped)

    def test_idle_dedupe_and_replace(self, library, dest):
        knight = dest.actors / "briar-knight"
        importer.import_library(library, dest)
        target = knight / "sprites" / "briar_knight_idle_game.png"
        stamp = target.stat().st_mtime_ns
        importer.import_library(library, dest)
        assert target.stat().st_mtime_ns == stamp  # identical bytes, not rewritten
        (library / "Briar Knight" / "briar_knight_idle_game.png").write_bytes(_png(4, 4, b"new"))
        importer.import_library(library, dest)
        assert target.read_bytes() == _png(4, 4, b"new")


class TestCli:
    def test_import_command(self, library, tmp_path, capsys):
        rc = cli.main(["import", str(library), "--data-dir", str(tmp_path / "data")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Imported 2 actor(s), 3 animation(s) (8 frames)" in out
        assert "Skipped: Briar Knight/briar_knight_attack (deprecated) [deprecated]" in out
        assert "Warning:" in out
        assert (tmp_path / "data" / "site" / "actor-briar-knight.html").is_file()

    def test_import_command_error(self, tmp_path, capsys):
        rc = cli.main(["import", str(tmp_path / "missing"), "--data-dir", str(tmp_path / "data")])
        assert rc == 1
        assert "error:" in capsys.readouterr().err


@pytest.mark.skipif(not Path("samples/sprites/Briar Knight").is_dir(), reason="sample library not present")
class TestSampleLibrary:
    def test_real_samples(self, tmp_path):
        dest = Paths(tmp_path / "data").ensure()
        summary = importer.import_library("samples/sprites", dest)
        assert summary.actors == 3
        assert summary.animations == 18
        assert len([s for s in summary.skipped if "[deprecated]" in s]) == 3
        m = animmeta.load_manifest(dest.actors / "briar-knight" / "animations" / "briar_knight_hit_recoil")
        assert m.delays() == [60, 35, 40, 45, 50, 50, 60, 65, 60, 60, 60, 65, 70, 75, 80, 120]
        assert m.events["impact_frame"] == 1
        assert m.loop is False
        assert m.frame_size == (314, 314)
        summon = animmeta.load_manifest(dest.actors / "gravescribe" / "animations" / "gravescribe_skeleton_mist_summon")
        assert summon.delays()[-1] == 140 and summon.total_ms() == 1280
        assert any("dark_mist" in w for w in summary.warnings)
        assert media.inspect_png(
            (dest.actors / "briar-knight" / "sheets" / "briar_knight_hit_recoil_sheet.png").read_bytes()
        )[:2] == (1256, 1256)
