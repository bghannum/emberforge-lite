"""Copy a sprite library into the data directory as actors and frame packages.

``emberforge-lite import SOURCE`` walks a library laid out as one folder per
character and one folder per animation::

    Library/
      Briar Knight/
        briar_knight_idle_game.png              -> sprites/
        briar_knight_hit_recoil/
          README.md                             timing contract (preferred)
          briar_knight_hit_recoil_preview.gif   timing of last resort
          frames/frame_00.png ...               -> animations/<name>/frames/
      _production/                              ignored (archive of sources)

Each animation folder is handed to the first *adapter* whose ``detect`` accepts
it. Adapters turn one input layout into a :class:`FramesSource`: the ordered
frame files plus resolved timing. Only the frames-folder layout is implemented;
the atlas and GIF adapters are declared stubs so the slot for slicing a grid
sheet or decoding a GIF is explicit rather than implied.

The import is a one-way copy: the library is never modified, and re-running it
replaces each package in place, so a corrected README lands on the next run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from emberforge_lite import animmeta, media, provenance, sheets, storage
from emberforge_lite.animmeta import Frame, Manifest, Timing
from emberforge_lite.config import Paths
from emberforge_lite.naming import asset_stem, sanitize_slug

#: Directories that hold archives or OS metadata rather than animations.
DEFAULT_SKIP_DIRS = {"_production", "_macos_metadata"}
DEPRECATED_SUFFIX = "(deprecated)"
_DEPRECATED_RE = re.compile(r"\s*\(deprecated\)\s*$", re.I)
_PREVIEW_SUFFIX = "_preview"
_IDLE_SUFFIX = "_idle_game.png"


class ImportFailure(Exception):
    """The library cannot be imported as asked; nothing further is written."""


@dataclass
class FramesSource:
    """What every adapter produces: the frames of one animation, in order."""

    name: str
    frame_paths: list[Path]
    timing: Timing
    deprecated: bool
    source_kind: str
    source_path: Path


class Adapter(Protocol):
    kind: str

    def detect(self, folder: Path) -> bool: ...

    def load(self, folder: Path, *, library_root: Path, warnings: list[str]) -> FramesSource: ...


def is_deprecated(folder: Path) -> bool:
    return folder.name.lower().rstrip().endswith(DEPRECATED_SUFFIX)


def derive_anim_name(folder: Path) -> str:
    """The animation's name: the preview GIF's stem if there is one, else the folder.

    The GIF stem is preferred because a folder can be renamed after export
    (``briar_knight_attack (deprecated)`` holds ``briar_knight_lunge_attack_preview.gif``).
    """
    gifs = sorted(p for p in folder.glob("*.gif") if p.stem.endswith(_PREVIEW_SUFFIX))
    raw = gifs[0].stem[: -len(_PREVIEW_SUFFIX)] if gifs else _DEPRECATED_RE.sub("", folder.name)
    name = asset_stem(raw)
    if not name:
        raise ImportFailure(f"cannot derive an animation name from {folder}")
    return name


def _preview_gif(folder: Path) -> Path | None:
    gifs = sorted(p for p in folder.glob("*.gif") if p.stem.endswith(_PREVIEW_SUFFIX))
    return gifs[0] if gifs else None


def _production_profile(folder: Path, library_root: Path, name: str, warnings: list[str]) -> dict | None:
    """The archived ``*_profile.json`` for this folder, if it names this animation."""
    try:
        rel = folder.relative_to(library_root)
    except ValueError:
        return None
    archive = library_root / "_production" / rel
    if not archive.is_dir():
        return None
    for candidate in sorted(archive.glob("*_profile.json")):
        try:
            doc = json.loads(candidate.read_text())
        except (OSError, json.JSONDecodeError):
            warnings.append(f"{rel}: unreadable {candidate.name}; ignored")
            continue
        declared = doc.get("animation") if isinstance(doc, dict) else None
        if isinstance(declared, str) and declared and f"_{declared}_" in f"_{name}_":
            return doc
        warnings.append(f"{rel}: {candidate.name} names {declared!r}, not this animation; ignored")
    return None


class FramesFolderAdapter:
    """``<folder>/frames/*.png`` with README, profile, or GIF timing."""

    kind = "frames_folder"

    def detect(self, folder: Path) -> bool:
        frames = folder / animmeta.FRAMES_DIR
        return frames.is_dir() and any(p.suffix.lower() == ".png" for p in frames.iterdir())

    def load(self, folder: Path, *, library_root: Path, warnings: list[str]) -> FramesSource:
        frames = sorted(
            p
            for p in (folder / animmeta.FRAMES_DIR).iterdir()
            if p.suffix.lower() == ".png" and not p.name.startswith(".")
        )
        name = derive_anim_name(folder)
        candidates: list[Timing | None] = []
        readme = folder / "README.md"
        if readme.is_file():
            candidates.append(animmeta.parse_readme(readme.read_text(errors="replace"), len(frames)))
        profile = _production_profile(folder, library_root, name, warnings)
        if profile is not None:
            candidates.append(animmeta.parse_profile(profile))
        gif = _preview_gif(folder)
        if gif is not None:
            candidates.append(animmeta.gif_timing(gif.read_bytes()))
        timing = animmeta.resolve_timing(candidates, len(frames))
        if timing.source == "uniform":
            warnings.append(f"{folder.name}: no usable per-frame timing found; using uniform {timing.fps} fps")
        return FramesSource(
            name=name,
            frame_paths=frames,
            timing=timing,
            deprecated=is_deprecated(folder),
            source_kind=self.kind,
            source_path=folder,
        )


class AtlasGridAdapter:
    """A grid-aligned atlas (``*_NNf_aligned.png``) plus a profile ``atlas_grid``.

    Detection is real so the summary can say what was skipped; slicing is not
    implemented yet. Implement ``load`` by cutting ``cell_size_pixels`` cells
    row-major and feeding them through the same :class:`FramesSource`.
    """

    kind = "atlas_grid"

    def detect(self, folder: Path) -> bool:
        return any(re.search(r"_\d+f_aligned\.png$", p.name) for p in folder.glob("*.png"))

    def load(self, folder: Path, *, library_root: Path, warnings: list[str]) -> FramesSource:
        raise NotImplementedError("atlas slicing is not yet supported")


class GifAdapter:
    """A bare animated GIF with no frame files. Needs a GIF decoder; not yet."""

    kind = "gif"

    def detect(self, folder: Path) -> bool:
        return not (folder / animmeta.FRAMES_DIR).is_dir() and _preview_gif(folder) is not None

    def load(self, folder: Path, *, library_root: Path, warnings: list[str]) -> FramesSource:
        raise NotImplementedError("importing frames from a GIF is not yet supported")


ADAPTERS: list[Adapter] = [FramesFolderAdapter(), AtlasGridAdapter(), GifAdapter()]


def detect_adapter(folder: Path) -> Adapter | None:
    return next((a for a in ADAPTERS if a.detect(folder)), None)


# -- Writing ------------------------------------------------------------------------


@dataclass
class ImportSummary:
    actors: int = 0
    animations: int = 0
    frames: int = 0
    sheets: int = 0
    sprites: int = 0
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frame_size(path: Path) -> tuple[int, int]:
    media.validate(path)
    width, height, frames = media.inspect_png(path.read_bytes())
    if frames > 1:
        raise media.Rejected(f"{path.name} is an animated PNG; frames must be still images")
    return width, height


def import_animation(
    src: FramesSource, actor_dir: Path, *, library_root: Path, library_label: str | None = None
) -> Path:
    """Write one package under ``actor_dir/animations/<name>/`` and its sheet."""
    if not src.frame_paths:
        raise media.Rejected("no frames")
    if len(src.frame_paths) > media.MAX_FRAMES:
        raise media.Rejected(f"{len(src.frame_paths)} frames exceeds the {media.MAX_FRAMES}-frame limit")
    size = _frame_size(src.frame_paths[0])
    for p in src.frame_paths[1:]:
        other = _frame_size(p)
        if other != size:
            raise media.Rejected(f"{p.name} is {other[0]}x{other[1]}; expected {size[0]}x{size[1]}")

    animations_dir = actor_dir / "animations"
    animations_dir.mkdir(parents=True, exist_ok=True)
    final = animations_dir / src.name
    staging = animations_dir / f"{storage.TMP_PREFIX}{src.name}-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / animmeta.FRAMES_DIR).mkdir(parents=True)

    frames: list[Frame] = []
    for i, (path, delay) in enumerate(zip(src.frame_paths, src.timing.delays_ms)):
        filename = f"frame_{i:02d}.png"
        shutil.copy2(path, staging / animmeta.FRAMES_DIR / filename)
        frames.append(Frame(file=filename, delay_ms=delay))

    try:
        rel_source = str(src.source_path.relative_to(library_root))
    except ValueError:
        rel_source = str(src.source_path)
    manifest = Manifest(
        name=src.name,
        loop=bool(src.timing.loop),
        frames=frames,
        fps_hint=src.timing.fps,
        frame_size=size,
        events=dict(src.timing.events),
        resulting_state=src.timing.resulting_state,
        source={
            "kind": src.source_kind,
            "path": rel_source,
            "library": library_label or str(library_root),
            "timing_source": src.timing.source,
            "deprecated": src.deprecated,
            "imported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
    )
    animmeta.save_manifest(staging, manifest)

    slug = actor_dir.name
    with storage.actor_lock(slug):
        if final.exists():
            shutil.rmtree(final)
        os.replace(staging, final)
        sheet, _ = sheets.write_sheet(final, actor_dir / "sheets")
        provenance.record_imported(actor_dir, f"animations/{src.name}", library_path=rel_source)
        provenance.record_imported(actor_dir, f"sheets/{sheet.name}", library_path=rel_source)
    return final


def dedupe_idle(character_dir: Path, actor_dir: Path) -> Path | None:
    """Copy the character's canonical ``*_idle_game.png`` into sprites/ once."""
    idles = sorted(p for p in character_dir.glob(f"*{_IDLE_SUFFIX}") if p.is_file())
    if not idles:
        return None
    src = idles[0]
    media.validate(src)
    sprites_dir = actor_dir / "sprites"
    sprites_dir.mkdir(parents=True, exist_ok=True)
    target = sprites_dir / src.name
    if target.is_file() and _sha256(target) == _sha256(src):
        return target
    shutil.copy2(src, target)
    provenance.record_imported(actor_dir, f"sprites/{src.name}", library_path=src.name)
    return target


#: What a browser folder upload may contain: enough for one character or one
#: animation package, nothing an archive would carry.
MAX_UPLOAD_FILES = 512
_UPLOAD_EXTS = {".png", ".gif", ".md", ".json"}


def _safe_component(part: str) -> bool:
    """One path segment from the browser: a plain name, no traversal or control bytes.

    Spaces and parentheses are legitimate (``hero_run (deprecated)``), so this
    is deliberately looser than naming.sanitize_filename, which is for names
    we will write into the actor tree; staged paths never leave tmp/.
    """
    if part in ("", ".", "..") or len(part) > 255:
        return False
    if any(ord(c) < 32 or c in "/\\\x7f" for c in part):
        return False
    return Path(part).name == part


def stage_uploaded_files(files: list[tuple[str, bytes]], staging: Path) -> Path:
    """Materialise browser-uploaded ``(relative path, bytes)`` pairs under `staging`.

    Paths come from the client (``webkitRelativePath``), so every component is
    sanitised and confined; only frame PNGs, preview GIFs, READMEs, and JSON
    are kept, and everything must share one top-level folder, which is returned.
    """
    if not files:
        raise ImportFailure("no files were uploaded")
    if len(files) > MAX_UPLOAD_FILES:
        raise ImportFailure(f"{len(files)} files exceeds the {MAX_UPLOAD_FILES}-file limit for a folder upload")
    top: str | None = None
    for rel, data in files:
        parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or any(not _safe_component(p) for p in parts):
            raise ImportFailure(f"unsafe path in upload: {rel!r}")
        if len(parts) > 4:
            raise ImportFailure(f"path too deep in upload: {rel!r}")
        if top is None:
            top = parts[0]
        elif parts[0] != top:
            raise ImportFailure("upload one folder at a time")
        if any(p.startswith(".") for p in parts) or Path(parts[-1]).suffix.lower() not in _UPLOAD_EXTS:
            continue  # OS metadata, archives, tools: not part of a package
        if len(data) > media.MAX_FILE_BYTES:
            raise ImportFailure(f"{rel} exceeds the {media.MAX_FILE_BYTES}-byte limit")
        target = staging.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if top is None or not (staging / top).is_dir():
        raise ImportFailure("the upload held no importable files")
    return staging / top


def import_folder(
    folder: Path,
    actor_dir: Path,
    *,
    library_root: Path,
    include_deprecated: bool = False,
    summary: ImportSummary,
    library_label: str | None = None,
) -> None:
    """Import `folder` into an existing actor: one animation package, or a character's worth.

    `library_label` replaces the on-disk library path in each manifest's
    ``source.library`` when the folder is a transient staging copy.
    """
    if detect_adapter(folder) is not None:
        _import_animation_folder(
            folder, actor_dir, folder.name, library_root, include_deprecated, summary, library_label=library_label
        )
        return
    if not _looks_like_character(folder):
        raise ImportFailure(f"{folder.name} holds neither an animation (frames/*.png) nor animation folders")
    import_character(
        folder,
        actor_dir.parent,
        slug=actor_dir.name,
        include_deprecated=include_deprecated,
        library_root=library_root,
        summary=summary,
        library_label=library_label,
    )


def _import_animation_folder(
    folder: Path,
    actor_dir: Path,
    rel: str,
    library_root: Path,
    include_deprecated: bool,
    summary: ImportSummary,
    *,
    library_label: str | None = None,
) -> None:
    adapter = detect_adapter(folder)
    if adapter is None:
        summary.skipped.append(f"{rel} [no recognised layout]")
        return
    if is_deprecated(folder) and not include_deprecated:
        summary.skipped.append(f"{rel} [deprecated]")
        return
    try:
        src = adapter.load(folder, library_root=library_root, warnings=summary.warnings)
        import_animation(src, actor_dir, library_root=library_root, library_label=library_label)
    except NotImplementedError as exc:
        summary.skipped.append(f"{rel} [{adapter.kind}: {exc}]")
        return
    except (media.Rejected, animmeta.ManifestError, ImportFailure, OSError) as exc:
        summary.skipped.append(f"{rel} [rejected: {exc}]")
        return
    summary.animations += 1
    summary.frames += len(src.frame_paths)
    summary.sheets += 1


def _animation_folders(character_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in character_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in DEFAULT_SKIP_DIRS
    )


def _looks_like_character(folder: Path) -> bool:
    return any(detect_adapter(p) is not None for p in _animation_folders(folder))


def import_character(
    character_dir: Path,
    actors_dir: Path,
    *,
    slug: str | None = None,
    include_deprecated: bool = False,
    library_root: Path,
    summary: ImportSummary,
    library_label: str | None = None,
) -> str:
    slug = slug or sanitize_slug(character_dir.name)
    if not slug:
        raise ImportFailure(f"cannot derive an actor slug from {character_dir.name!r}")
    actor_dir = actors_dir / slug
    actor_dir.mkdir(parents=True, exist_ok=True)
    label = character_dir.name

    if dedupe_idle(character_dir, actor_dir) is not None:
        summary.sprites += 1

    for folder in _animation_folders(character_dir):
        _import_animation_folder(
            folder,
            actor_dir,
            f"{label}/{folder.name}",
            library_root,
            include_deprecated,
            summary,
            library_label=library_label,
        )
    summary.actors += 1
    return slug


def import_library(
    source: str | Path,
    dest: Paths,
    *,
    include_deprecated: bool = False,
    actor: str | None = None,
) -> ImportSummary:
    """Import every character under `source` (or `source` itself as one actor)."""
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        raise ImportFailure(f"no such directory: {root}")
    dest.ensure()
    summary = ImportSummary()

    if _looks_like_character(root):
        import_character(
            root,
            dest.actors,
            slug=actor,
            include_deprecated=include_deprecated,
            library_root=root.parent,
            summary=summary,
        )
        return summary

    characters = [p for p in _animation_folders(root) if _looks_like_character(p)]
    if not characters:
        raise ImportFailure(f"no animation folders found under {root}")
    if actor and len(characters) > 1:
        raise ImportFailure("--actor applies to a single-character source; this library has several")
    for character in characters:
        import_character(
            character,
            dest.actors,
            slug=actor,
            include_deprecated=include_deprecated,
            library_root=root,
            summary=summary,
        )
    return summary
