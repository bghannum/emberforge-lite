#!/usr/bin/env python3
"""Scan actors/ and regenerate gallery.html plus one actor-<slug>.html per
actor. No dependencies, stdlib only.

Convention, per actor folder under actors/<slug>/:
    sprites/            images: png, jpg, jpeg, webp
    animations/         gifs, plus one directory per frame package (manifest.json + frames/)
    sounds/             audio: mp3, wav, ogg, m4a
    sheets/             spritesheets paired with generated animations (not rendered as cards)
    links.json          {"animation_filename": ["sound_filename", ...]}, optional
    generations.jsonl   provider-call ledger written by generate.py, optional

Markup is templated here (render_actor, page_shell); CSS and JS are packaged
static files under `static/` served at /static/, so generated pages carry no
inline styles, scripts, or event handlers and pass a strict CSP. The server
imports `build()` and calls it after every change.

Use the installed CLI: `emberforge-lite build` and `emberforge-lite serve`.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from emberforge_lite import animmeta, media, provenance, storage

# ROOT is the site directory where generated pages are written; ACTORS_DIR is
# where actor folders live. They are set to a real data-dir layout by
# configure_paths(); the defaults keep import-time attribute access working.
ROOT = Path(__file__).parent
ACTORS_DIR = ROOT / "actors"
OUTPUT = ROOT / "gallery.html"
ACTOR_PAGE_PREFIX = "actor-"


def configure_paths(paths) -> None:
    """Point page output at ``paths.site`` and actors at ``paths.actors``."""
    global ROOT, ACTORS_DIR, OUTPUT
    ROOT = paths.site
    ACTORS_DIR = paths.actors
    OUTPUT = paths.site / "gallery.html"


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a"}

RUNE_ICON = (
    '<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
    'stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 2 L20 12 L12 22 L4 12 Z"/><path d="M12 2 L12 22 M4 12 L20 12"/></svg>'
)
LOOP_ICON = (
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 4v5h5M20 20v-5h-5"/><path d="M4 9a8 8 0 0113.9-5.3M20 15a8 8 0 01-13.9 5.3"/></svg>'
)
PLAY_ICON = '<svg viewBox="0 0 24 24" width="10" height="10" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'
LINK_ICON = (
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M9 15l6-6M8 17l-2 2a3 3 0 01-4-4l4-4a3 3 0 014 0M16 7l2-2a3 3 0 014 4l-4 4a3 3 0 01-4 0"/></svg>'
)
PLUS_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>'
)
UPLOAD_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M7 18a4 4 0 01-.6-7.96A5 5 0 0116.9 8.2 4.5 4.5 0 0117.5 18H7z"/>'
    '<path d="M12 12v6M9.5 14.5L12 12l2.5 2.5"/></svg>'
)
WAVE_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round">'
    '<line x1="7" y1="7" x2="7" y2="17"/><line x1="11" y1="4" x2="11" y2="20"/>'
    '<line x1="15" y1="8" x2="15" y2="16"/><line x1="19" y1="10" x2="19" y2="14"/></svg>'
)
FLAME_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3c3 3.5 5 6.4 5 9.2A5 5 0 017 12.2C7 9.4 9 6.5 12 3z"/><path d="M12 21v-5"/></svg>'
)
PENCIL_ICON = (
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>'
)
TRASH_ICON = (
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>'
)
EXPORT_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/></svg>'
)
NO_SOUND_HTML = '<div class="no-sound">no sound linked yet</div>'
SCISSORS_ICON = (
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12"/></svg>'
)
UNLINK_ICON = (
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>'
)


def sound_duration_ms(path: Path) -> int | None:
    try:
        return media.inspect_audio(path.read_bytes())[0]
    except (media.Rejected, OSError):
        return None


def trim_button_html(esc_slug: str, sound: str, duration: int | None, link_to: str = "") -> str:
    esc_sound = html.escape(sound, quote=True)
    return (
        f'<button type="button" class="icon-btn" title="Trim (writes a new file)" '
        f'data-action="trim" data-slug="{esc_slug}" data-sound="{esc_sound}" '
        f'data-duration="{duration or 0}" data-link-to="{html.escape(link_to, quote=True)}">'
        f"{SCISSORS_ICON}</button>"
    )


SPARK_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/></svg>'
)

#: The prompt shape that produced usable loops in emberforge's real runs: describe
#: the motion, then insist on a return to the exact first pose, feet planted.
ANIMATION_PROMPT_TEMPLATE = (
    "[Describe the motion here.] Then return all the way to the idle: the last frame "
    "must show the same standing pose as the first. Feet stay planted; the body does not travel."
)
#: Sound prompts worked best when they named what must NOT be in the sound.
SOUND_PROMPT_PLACEHOLDER = "A short arcane whoosh with a shimmering tail. No metal, no scraping, no music, no voice."


def list_media(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in exts)


def load_links(actor_dir: Path) -> dict[str, list[str]]:
    links_file = actor_dir / "links.json"
    if not links_file.is_file():
        return {}
    return json.loads(links_file.read_text())


def animation_count(actor_dir: Path) -> int:
    return len(list_media(actor_dir / "animations", IMAGE_EXTS)) + len(animmeta.list_packages(actor_dir / "animations"))


def asset_count(actor_dir: Path) -> int:
    return (
        len(list_media(actor_dir / "sprites", IMAGE_EXTS))
        + animation_count(actor_dir)
        + len(list_media(actor_dir / "sounds", AUDIO_EXTS))
    )


def asset_actions_html(esc_slug: str, filename: str, extra: str = "") -> str:
    esc_name = html.escape(filename, quote=True)
    return (
        f'<div class="asset-actions">{extra}'
        f'<button type="button" class="icon-btn" title="Rename" '
        f'data-action="rename" data-slug="{esc_slug}" data-filename="{esc_name}">{PENCIL_ICON}</button>'
        f'<button type="button" class="icon-btn icon-btn-danger" title="Delete" '
        f'data-action="delete" data-slug="{esc_slug}" data-filename="{esc_name}">{TRASH_ICON}</button>'
        f"</div>"
    )


def provenance_badge(assets: dict, category: str, filename: str) -> str:
    """A small badge marking an asset generated vs uploaded, warning on unknown rights."""
    entry = assets.get(f"{category}/{filename}")
    if entry is None:
        return (
            '<span class="prov-badge prov-unknown" '
            'title="No provenance recorded; rights unknown. Verify before you treat this as your own.">'
            "? rights unknown</span>"
        )
    if entry.get("source") == "generated":
        provider = html.escape(str(entry.get("provider") or "provider"))
        return f'<span class="prov-badge prov-generated" title="Generated via {provider}">generated</span>'
    if entry.get("source") == "imported":
        origin = html.escape(str(entry.get("library_path") or "a local library"), quote=True)
        return f'<span class="prov-badge prov-uploaded" title="Imported from {origin}; rights unknown.">imported</span>'
    return (
        '<span class="prov-badge prov-uploaded" '
        'title="Uploaded by you; rights unknown. Verify before redistribution.">uploaded</span>'
    )


def render_actor(actor_dir: Path) -> str:
    slug = actor_dir.name
    sprites = list_media(actor_dir / "sprites", IMAGE_EXTS)
    animations = list_media(actor_dir / "animations", IMAGE_EXTS)
    packages = animmeta.list_packages(actor_dir / "animations")
    sounds = list_media(actor_dir / "sounds", AUDIO_EXTS)
    links = load_links(actor_dir)
    prov_assets = provenance.load(actor_dir).get("assets", {})
    esc_slug = html.escape(slug, quote=True)

    def rel(p: Path) -> str:
        # Media lives under ACTORS_DIR; emit an "actors/<slug>/..." URL that
        # resolves to the server's /actors/ route regardless of where the page
        # file physically sits (site/ and actors/ are siblings).
        return html.escape(str(p.relative_to(ACTORS_DIR.parent)))

    sprite_html = "".join(
        f'<div class="sprite-card">'
        f'<div class="sprite-thumb checker"><img class="pixel-art" src="{rel(p)}" loading="lazy"></div>'
        f'<div class="asset-name">{html.escape(p.name)} {provenance_badge(prov_assets, "sprites", p.name)}</div>'
        f"{asset_actions_html(esc_slug, p.name)}"
        f"</div>"
        for p in sprites
    )

    linked_names = {s for names in links.values() for s in names}
    unlinked_sounds = [p for p in sounds if p.name not in linked_names]
    unlinked_options = "".join(
        f'<option value="{html.escape(p.name, quote=True)}">{html.escape(p.name)}</option>' for p in unlinked_sounds
    )

    sprite_options = "".join(
        f'<option value="{html.escape(p.name, quote=True)}">{html.escape(p.name)}</option>' for p in sprites
    )
    anim_options = "".join(
        f'<option value="{html.escape(p.name, quote=True)}">{html.escape(p.name)}</option>'
        for p in sorted(animations + packages, key=lambda p: p.name)
    )

    def sheet_link_for(stem: str) -> str:
        sheet = actor_dir / "sheets" / f"{stem}_sheet.png"
        if not sheet.is_file():
            return ""
        return f'<a class="sheet-link" href="{rel(sheet)}" download title="Download spritesheet">sheet</a>'

    def sound_controls(i: int, img_id: str, anim_name: str) -> str:
        """Sound pills + link control for one animation card (GIF or package)."""
        linked = links.get(anim_name, [])
        buttons = ""
        for j, s in enumerate(linked):
            sound_path = actor_dir / "sounds" / s
            if not sound_path.is_file():
                continue
            audio_id = f"sound-{esc_slug}-{i}-{j}"
            duration = sound_duration_ms(sound_path)
            dur_html = f'<span class="sound-dur">{duration} ms</span>' if duration else ""
            buttons += (
                f'<div class="sound-row">'
                f'<button type="button" class="sound-pill" '
                f'data-action="play" data-img="{img_id}" data-audio="{audio_id}">'
                f'<audio id="{audio_id}" src="{rel(sound_path)}"></audio>'
                f'<span class="play-dot">{PLAY_ICON}</span>'
                f'<span class="sound-pill-name">{html.escape(s)}</span>{dur_html}'
                f"</button>"
                f'<div class="asset-actions">'
                f"{trim_button_html(esc_slug, s, duration, anim_name)}"
                f'<button type="button" class="icon-btn icon-btn-danger" title="Unlink from this animation" '
                f'data-action="unlink" data-slug="{esc_slug}" '
                f'data-animation="{html.escape(anim_name, quote=True)}" data-sound="{html.escape(s, quote=True)}">'
                f"{UNLINK_ICON}</button>"
                f"</div></div>"
            )
        link_control = (
            f'<div class="link-row">'
            f'<select id="link-select-{esc_slug}-{i}">{unlinked_options}</select>'
            f'<button type="button" class="link-btn" '
            f'data-action="link" data-slug="{esc_slug}" '
            f'data-animation="{html.escape(anim_name, quote=True)}" data-select="link-select-{esc_slug}-{i}">'
            f"{LINK_ICON} Link</button>"
            f"</div>"
            if unlinked_options
            else ""
        )
        return f'<div class="sound-pills">{buttons or NO_SOUND_HTML}</div>{link_control}'

    anim_html = ""
    for i, p in enumerate(animations):
        img_id = f"anim-{esc_slug}-{i}"
        stem = p.stem[: -len("_preview")] if p.stem.endswith("_preview") else p.stem
        speed_row = (
            f'<div class="speed-row">'
            f'<span class="speed-label">Speed</span>'
            f'<select data-action="speed" data-img="{img_id}" data-slug="{esc_slug}" '
            f'data-filename="{html.escape(p.name, quote=True)}">'
            f'<option value="1">1&times; (original)</option>'
            f'<option value="0.75">0.75&times;</option>'
            f'<option value="0.5">0.5&times;</option>'
            f'<option value="0.35">0.35&times;</option>'
            f'<option value="0.25">0.25&times;</option>'
            f"</select></div>"
        )
        anim_html += (
            f'<div class="anim-card">'
            f'<div class="anim-thumb checker">'
            f'<img id="{img_id}" class="pixel-art" src="{rel(p)}" data-base-src="{rel(p)}" loading="lazy">'
            f'<span class="badge badge-gif">GIF</span>'
            f'<span class="badge badge-loop">{LOOP_ICON}</span>'
            f"</div>"
            f'<div class="anim-body">'
            f'<div class="asset-name-row"><div class="asset-name">{html.escape(p.name)} '
            f"{provenance_badge(prov_assets, 'animations', p.name)}</div>"
            f"{sheet_link_for(stem)}{asset_actions_html(esc_slug, p.name)}</div>"
            f"{speed_row}"
            f"{sound_controls(i, img_id, p.name)}"
            f"</div></div>"
        )

    for j, pkg in enumerate(packages):
        i = len(animations) + j
        anim_html += render_package_card(actor_dir, pkg, esc_slug, i, rel, sheet_link_for, sound_controls, prov_assets)

    sound_html = ""
    for p in unlinked_sounds:
        duration = sound_duration_ms(p)
        dur_html = f'<span class="sound-dur">{duration} ms</span>' if duration else ""
        sound_html += (
            f'<div class="unlinked-card">'
            f'<div class="unlinked-icon">{WAVE_ICON}</div>'
            f'<div class="unlinked-info">'
            f'<div class="asset-name-row"><div class="asset-name">{html.escape(p.name)}{dur_html}</div>'
            f"{asset_actions_html(esc_slug, p.name, trim_button_html(esc_slug, p.name, duration))}</div>"
            f'<audio controls src="{rel(p)}"></audio>'
            f"</div></div>"
        )

    gen_panel = f"""
      <details class="gen-panel" data-slug="{esc_slug}">
        <summary>
          <span class="gen-title">{SPARK_ICON} Generate</span>
          <span class="gen-badge" id="gen-badge">checking providers&hellip;</span>
        </summary>
        <div class="gen-tabs">
          <button type="button" class="gen-tab active" data-kind="animation" data-action="gen-tab">Animate a sprite</button>
          <button type="button" class="gen-tab" data-kind="sound" data-action="gen-tab">Sound</button>
          <button type="button" class="gen-tab" data-kind="source" data-action="gen-tab">Source sprite</button>
        </div>

        <form class="gen-form" id="gen-form-animation">
          <label>Sprite <select name="sprite">{sprite_options or '<option value="">(upload a sprite first)</option>'}</select></label>
          <label>Action name <input name="action" placeholder="lunge_attack"></label>
          <label class="wide">Prompt <textarea name="prompt" rows="4">{ANIMATION_PROMPT_TEMPLATE}</textarea></label>
          <label>Frames <input name="frames" type="number" value="16" min="1" max="64"></label>
          <div class="gen-note">SpriteLab returns the canvas it is given: the sprite is fitted to 256&times;256 with a 16px margin first. Fixed 8 fps. 20 credits.</div>
        </form>

        <form class="gen-form" id="gen-form-sound" hidden>
          <label class="wide">Prompt <textarea name="prompt" rows="3" placeholder="{SOUND_PROMPT_PLACEHOLDER}"></textarea></label>
          <label>Duration (ms) <input name="duration_ms" type="number" value="800" min="500" max="30000" step="50"></label>
          <label>Name <input name="name" placeholder="sword_impact"></label>
          <label>Link to animation <select name="link_to"><option value="">(none)</option>{anim_options}</select></label>
          <div class="gen-note">ElevenLabs, 40 credits per second of requested duration.</div>
        </form>

        <form class="gen-form" id="gen-form-source" hidden>
          <label>Provider <select name="provider">
            <option value="spritelab_epic">SpriteLab &middot; epic &middot; 1 credit</option>
            <option value="spritelab_mythic">SpriteLab &middot; mythic &middot; 6 credits</option>
            <option value="openai">OpenAI gpt-image-2 &middot; low &middot; $0.006</option>
          </select></label>
          <label class="wide">Prompt <textarea name="prompt" rows="3" placeholder="A hooded scribe holding a glowing grimoire, pixel art, side view, transparent background"></textarea></label>
          <div class="gen-note">SpriteLab returns a 256px multi-view sheet; OpenAI a 1024&times;1024 transparent PNG. Either lands in sprites/ and is fitted to 256px when animated.</div>
        </form>

        <div class="gen-actions">
          <button type="button" class="btn-ghost" id="gen-estimate" data-action="gen-estimate">Estimate cost</button>
          <div class="gen-cost" id="gen-cost"></div>
          <button type="button" class="btn-primary" id="gen-confirm" hidden data-action="gen-confirm">Confirm &amp; generate</button>
        </div>
        <div class="gen-status" id="gen-status"></div>
      </details>
    """

    return f"""
    <section class="actor" id="{esc_slug}">
      <div class="section-head">
        <div>
          <h2>{html.escape(slug)}</h2>
          <div class="section-meta">{len(sprites)} sprites &middot; {len(animations) + len(packages)} animations &middot;
            {len(sounds)} sounds &middot; {len(unlinked_sounds)} unlinked</div>
        </div>
        <div class="section-actions">
          <div class="upload-widget" data-slug="{esc_slug}">
            <div class="upload-icon">{UPLOAD_ICON}</div>
            <div>
              <div class="upload-title">Drop files, or click to browse</div>
              <div class="upload-hint">Sorted automatically &mdash; .gif to animations, images to sprites, audio to sounds</div>
            </div>
            <input type="file" multiple data-action="upload-files" data-slug="{esc_slug}">
          </div>
          <a class="btn-ghost" href="/export/{esc_slug}">{EXPORT_ICON} Export</a>
        </div>
      </div>
      {gen_panel}

      <div class="group">
        <div class="group-label">Sprites <span class="count">{len(sprites)}</span></div>
        <div class="sprite-grid">{sprite_html or "<em class='empty'>none yet</em>"}</div>
      </div>

      <div class="group">
        <div class="group-label group-label-lg">Animations <span class="count">{len(animations) + len(packages)}</span>
          <span class="group-hint">&mdash; play a sound against the gif to judge the pairing</span></div>
        <div class="anim-grid">{anim_html or "<em class='empty'>none yet</em>"}</div>
      </div>

      <div class="group">
        <div class="group-label"><span class="dot"></span>Unlinked sounds <span class="count">{len(unlinked_sounds)}</span>
          <span class="group-hint">&mdash; pick these from an animation's link control above</span></div>
        <div class="unlinked-grid">{sound_html or "<em class='empty'>none</em>"}</div>
      </div>
    </section>
    """


def render_package_card(actor_dir, pkg, esc_slug, i, rel, sheet_link_for, sound_controls, prov_assets) -> str:
    """A frame-package card: a canvas the FramePlayer in app.js drives from the manifest.

    Everything the player needs (frame files, delays, loop) is fetched from
    manifest.json at runtime, so the page stays static and carries no inline JS.
    """
    try:
        manifest = animmeta.load_manifest(pkg)
    except animmeta.ManifestError as exc:
        return f'<div class="anim-card anim-card-broken">{html.escape(pkg.name)}: {html.escape(str(exc))}</div>'
    name = pkg.name
    esc_name = html.escape(name, quote=True)
    canvas_id = f"anim-{esc_slug}-{i}"
    width, height = manifest.frame_size or (256, 256)
    n = len(manifest.frames)
    loop_badge = f'<span class="badge badge-loop">{LOOP_ICON}</span>' if manifest.loop else ""
    speed_options = "".join(
        f'<option value="{v}">{label}</option>'
        for v, label in (("1", "1&times;"), ("0.75", "0.75&times;"), ("0.5", "0.5&times;"), ("0.25", "0.25&times;"))
    )
    timing_src = html.escape(str(manifest.source.get("timing_source") or "manifest"))
    return (
        f'<div class="anim-card anim-card-frames" data-player data-slug="{esc_slug}" data-animation="{esc_name}" '
        f'data-manifest="actors/{esc_slug}/animations/{esc_name}/manifest.json" '
        f'data-frames-base="actors/{esc_slug}/animations/{esc_name}/frames/" data-canvas="{canvas_id}">'
        f'<div class="anim-thumb checker">'
        f'<canvas id="{canvas_id}" class="pixel-art" width="{width}" height="{height}"></canvas>'
        f'<span class="badge badge-gif badge-frames">FRAMES</span>{loop_badge}'
        f"</div>"
        f'<div class="anim-body">'
        f'<div class="asset-name-row"><div class="asset-name">{html.escape(name)} '
        f"{provenance_badge(prov_assets, 'animations', name)}</div>"
        f"{sheet_link_for(name)}{asset_actions_html(esc_slug, name)}</div>"
        f'<div class="player-row">'
        f'<button type="button" class="icon-btn fp-toggle" title="Play / pause" data-action="fp-toggle" data-canvas="{canvas_id}">{PLAY_ICON}</button>'
        f'<button type="button" class="icon-btn" title="Previous frame" data-action="fp-step" data-dir="-1" data-canvas="{canvas_id}">&lsaquo;</button>'
        f'<button type="button" class="icon-btn" title="Next frame" data-action="fp-step" data-dir="1" data-canvas="{canvas_id}">&rsaquo;</button>'
        f'<input type="range" class="fp-scrub" min="0" max="{n - 1}" value="0" step="1" data-action="fp-scrub" data-canvas="{canvas_id}">'
        f'<span class="fp-frame" data-role="frame">0 / {n}</span>'
        f"</div>"
        f'<div class="speed-row">'
        f'<span class="speed-label">Speed</span>'
        f'<select data-action="fp-speed" data-canvas="{canvas_id}">{speed_options}</select>'
        f'<label class="fp-loop"><input type="checkbox" data-action="fp-loop" data-canvas="{canvas_id}"{" checked" if manifest.loop else ""}> Loop</label>'
        f'<button type="button" class="btn-ghost fp-edit" data-action="fp-edit" data-canvas="{canvas_id}" title="Edit per-frame delays">Timing</button>'
        f"</div>"
        f'<div class="fp-meta">{n} frames &middot; {manifest.total_ms()} ms &middot; timing: {timing_src}</div>'
        f"{sound_controls(i, canvas_id, name)}"
        f"</div></div>"
    )


def render_topbar(actor_dirs: list[Path], active_slug: str | None) -> str:
    def pill(d: Path) -> str:
        esc = html.escape(d.name, quote=True)
        active = " active" if d.name == active_slug else ""
        return (
            f'<a href="{ACTOR_PAGE_PREFIX}{esc}.html" class="pill{active}">'
            f"{html.escape(d.name)}<span class='pill-count'>{asset_count(d)}</span></a>"
        )

    nav = "".join(pill(d) for d in actor_dirs)
    return f"""
<div class="topbar">
  <a class="brand" href="gallery.html">{FLAME_ICON}emberforge<span class="dim">-lite</span></a>
  <div class="divider"></div>
  <nav class="nav-pills">{nav}</nav>
  <div id="new-actor">
    <input type="text" id="new-actor-slug" placeholder="new actor slug, e.g. gravescribe">
    <input type="file" multiple id="new-actor-files">
    <button type="button" class="btn-primary" data-action="new-actor">Create &amp; upload</button>
  </div>
</div>
"""


def page_shell(title: str, topbar_html: str, body_html: str) -> str:
    # CSS and JS are packaged static files served at /static/. No inline <style>
    # or <script>, and no inline event handlers anywhere in the body, so pages
    # pass a strict Content-Security-Policy. The server injects the CSRF token as
    # a <meta> tag into <head> at serve time.
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
{topbar_html}
<main>
{body_html}
</main>
<div id="efl-toast" role="status" aria-live="polite" hidden></div>
<script src="/static/app.js" defer></script>
</body>
</html>
"""


def render_index_body(actor_dirs: list[Path]) -> str:
    if not actor_dirs:
        return "<p>No actors yet. Create one above, or add a folder under actors/, e.g. actors/gravescribe/sprites/, then re-run build.py.</p>"
    cards = "".join(
        f'<a class="actor-card" href="{ACTOR_PAGE_PREFIX}{html.escape(d.name, quote=True)}.html">'
        f"<h2>{html.escape(d.name)}</h2>"
        f'<div class="section-meta">{len(list_media(d / "sprites", IMAGE_EXTS))} sprites &middot; '
        f"{animation_count(d)} animations &middot; "
        f"{len(list_media(d / 'sounds', AUDIO_EXTS))} sounds</div>"
        f"</a>"
        for d in actor_dirs
    )
    return f'<div class="actor-cards">{cards}</div>'


def build() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    ACTORS_DIR.mkdir(parents=True, exist_ok=True)
    actor_dirs = sorted(p for p in ACTORS_DIR.iterdir() if p.is_dir())
    valid_slugs = {d.name for d in actor_dirs}

    for f in ROOT.glob(f"{ACTOR_PAGE_PREFIX}*.html"):
        if f.stem[len(ACTOR_PAGE_PREFIX) :] not in valid_slugs:
            f.unlink()

    for d in actor_dirs:
        topbar = render_topbar(actor_dirs, active_slug=d.name)
        page = page_shell(f"{d.name} — emberforge-lite", topbar, render_actor(d))
        storage.atomic_write_text(ROOT / f"{ACTOR_PAGE_PREFIX}{d.name}.html", page)

    topbar = render_topbar(actor_dirs, active_slug=None)
    storage.atomic_write_text(OUTPUT, page_shell("emberforge-lite gallery", topbar, render_index_body(actor_dirs)))
    return len(actor_dirs)


def main() -> None:
    count = build()
    print(f"Wrote {OUTPUT} and {count} actor page(s)")


if __name__ == "__main__":
    main()
