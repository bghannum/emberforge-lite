#!/usr/bin/env python3
"""Scan actors/ and regenerate gallery.html plus one actor-<slug>.html per
actor. No dependencies, stdlib only.

Convention, per actor folder under actors/<slug>/:
    sprites/            images: png, jpg, jpeg, webp
    animations/         gifs
    sounds/             audio: mp3, wav, ogg, m4a
    sheets/             spritesheets paired with generated animations (not rendered as cards)
    links.json          {"animation_filename": ["sound_filename", ...]}, optional
    generations.jsonl   provider-call ledger written by generate.py, optional

All markup, CSS and JS is templated here (STYLE, SCRIPT, render_actor). The
server imports `build()` and calls it after every change.

Run after dropping files in:
    python3 build.py

Then open gallery.html directly, or run `python3 server.py` for browser
uploads/linking (see README.md).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import media

ROOT = Path(__file__).parent
ACTORS_DIR = ROOT / "actors"
OUTPUT = ROOT / "gallery.html"
ACTOR_PAGE_PREFIX = "actor-"

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
        f'onclick="trimSound(\'{esc_slug}\',\'{esc_sound}\',{duration or 0},\'{html.escape(link_to, quote=True)}\')">'
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
SOUND_PROMPT_PLACEHOLDER = (
    "A short arcane whoosh with a shimmering tail. No metal, no scraping, no music, no voice."
)

STYLE = """
  :root {
    --bg: oklch(15% 0.012 265);
    --surface: oklch(20% 0.014 265);
    --surface-raised: oklch(24.5% 0.017 265);
    --surface-sunken: oklch(12.5% 0.012 265);
    --border: oklch(31% 0.016 265);
    --border-soft: oklch(26% 0.014 265);
    --text: oklch(93% 0.008 265);
    --text-secondary: oklch(68% 0.018 265);
    --text-tertiary: oklch(50% 0.018 265);
    --cyan: oklch(76% 0.13 220);
    --cyan-ink: oklch(18% 0.03 220);
    --cyan-dim: oklch(30% 0.05 220);
    --amber: oklch(78% 0.15 70);
    --amber-ink: oklch(18% 0.03 70);
    --amber-dim: oklch(32% 0.06 70);
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--bg); color: var(--text); }
  a { color: var(--cyan); text-decoration: none; }
  a:hover { color: oklch(85% 0.11 220); }
  button { cursor: pointer; font-family: inherit; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .pixel-art { image-rendering: pixelated; }
  .checker { background: repeating-conic-gradient(var(--surface-sunken) 0% 25%, var(--surface) 0% 50%) 0 0 / 16px 16px; }

  .topbar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 24px;
    padding: 14px 28px; border-bottom: 1px solid var(--border-soft); background: var(--surface); flex-wrap: wrap; }
  .brand { display: flex; align-items: center; gap: 9px; font-size: 16px; font-weight: 700; flex-shrink: 0; }
  .brand svg { color: var(--amber); }
  .brand .dim { color: var(--text-tertiary); font-weight: 500; }
  .divider { width: 1px; height: 20px; background: var(--border); flex-shrink: 0; }
  .nav-pills { display: flex; align-items: center; gap: 4px; flex: 1; flex-wrap: wrap; }
  .pill { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 8px;
    font-size: 13px; font-weight: 600; color: var(--text-secondary); border: 1px solid transparent; }
  .pill:hover { color: var(--text); }
  .pill.active { background: var(--surface-raised); border-color: var(--border); color: var(--text); }
  .pill-count { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: var(--text-tertiary); }

  #new-actor { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
  #new-actor input[type=text] { width: 150px; padding: 7px 10px; border-radius: 7px;
    background: var(--surface-sunken); border: 1px solid var(--border); color: var(--text); font-size: 12.5px; }
  #new-actor input[type=file] { font-size: 11.5px; color: var(--text-secondary); max-width: 130px; }
  .btn-primary { display: flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 7px;
    background: var(--cyan); border: 1px solid var(--cyan); color: var(--cyan-ink); font-size: 12.5px; font-weight: 700; }
  .btn-ghost { display: flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 7px;
    background: transparent; border: 1px solid var(--border); color: var(--text-secondary); font-size: 12.5px; font-weight: 600; }
  .btn-ghost:hover { color: var(--text); border-color: var(--cyan-dim); }

  main { padding: 28px 28px 60px; max-width: 1400px; margin: 0 auto; }
  .actor { padding-top: 20px; }
  .section-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px;
    flex-wrap: wrap; margin-bottom: 26px; }
  .actor h2 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.2px; }
  .section-meta { margin-top: 5px; font-size: 12.5px; color: var(--text-tertiary);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .section-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

  .upload-widget { position: relative; display: flex; align-items: center; gap: 12px; padding: 10px 18px;
    border-radius: 12px; border: 1.5px dashed var(--border); background: var(--surface); min-width: 360px; }
  .upload-widget:hover { border-color: var(--cyan-dim); }
  .upload-icon { display: flex; align-items: center; justify-content: center; width: 34px; height: 34px;
    border-radius: 8px; background: var(--surface-raised); color: var(--amber); flex-shrink: 0; }
  .upload-title { font-size: 12.5px; font-weight: 700; }
  .upload-hint { font-size: 11px; color: var(--text-tertiary); margin-top: 1px; }
  .upload-widget input[type=file] { position: absolute; inset: 0; opacity: 0; cursor: pointer; }

  .group { margin-bottom: 30px; }
  .group-label { display: flex; align-items: baseline; gap: 8px; margin-bottom: 12px;
    font-size: 12.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px; color: var(--text-secondary); }
  .group-label-lg { font-size: 14px; }
  .group-label .count { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11.5px; font-weight: 500; color: var(--text-tertiary); text-transform: none; letter-spacing: 0; }
  .group-label .group-hint { font-size: 11.5px; font-weight: 500; text-transform: none;
    letter-spacing: 0; color: var(--text-tertiary); }
  .group-label .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--amber); }
  .empty { font-size: 12.5px; color: var(--text-tertiary); }

  .asset-actions { display: flex; gap: 4px; flex-shrink: 0; }
  .icon-btn { display: flex; align-items: center; justify-content: center; width: 22px; height: 22px;
    border-radius: 6px; background: transparent; border: 1px solid var(--border); color: var(--text-tertiary); }
  .icon-btn:hover { color: var(--text); border-color: var(--cyan-dim); }
  .icon-btn-danger:hover { color: oklch(72% 0.15 20); border-color: oklch(45% 0.1 20); }

  .sprite-grid { display: flex; flex-wrap: wrap; gap: 14px; }
  .sprite-card { width: 128px; }
  .sprite-thumb { width: 128px; height: 128px; border-radius: 10px; border: 1px solid var(--border-soft);
    display: flex; align-items: center; justify-content: center; overflow: hidden; }
  .sprite-thumb img { max-width: 100%; max-height: 100%; object-fit: contain; }
  .asset-name { margin-top: 6px; font-size: 11px; color: var(--text-tertiary);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; text-align: center;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sprite-card .asset-actions { justify-content: center; margin-top: 4px; }

  .anim-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
  .anim-card { background: var(--surface); border: 1px solid var(--border-soft); border-radius: 14px;
    overflow: hidden; display: flex; flex-direction: column; }
  .anim-thumb { position: relative; height: 200px; display: flex; align-items: center; justify-content: center;
    color: var(--text-tertiary); }
  .anim-thumb img { max-width: 100%; max-height: 100%; object-fit: contain; }
  .badge { position: absolute; display: flex; align-items: center; justify-content: center;
    background: oklch(20% 0.014 265 / 0.85); color: var(--text-secondary); border-radius: 6px; }
  .badge-gif { top: 10px; left: 10px; padding: 3px 8px; font-size: 10px; font-weight: 700; letter-spacing: 0.4px; }
  .badge-loop { top: 10px; right: 10px; width: 22px; height: 22px; color: var(--text-tertiary); }
  .anim-body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 10px; }
  .asset-name-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .anim-body .asset-name { text-align: left; font-size: 12.5px; color: var(--text-secondary); margin: 0; }
  .speed-row { display: flex; align-items: center; gap: 8px; }
  .speed-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px;
    color: var(--text-tertiary); flex-shrink: 0; }
  .speed-row select { flex: 1; min-width: 0; padding: 6px 8px; border-radius: 7px;
    background: var(--surface-sunken); border: 1px solid var(--border); color: var(--text-secondary); font-size: 11.5px; }

  .sound-pills { display: flex; flex-direction: column; gap: 6px; }
  .sound-row { display: flex; align-items: center; gap: 6px; }
  .sound-row .sound-pill { flex: 1; min-width: 0; }
  .sound-dur { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10.5px; font-weight: 500;
    color: var(--text-tertiary); margin-left: 6px; flex-shrink: 0; }
  .sound-pill { display: flex; align-items: center; gap: 9px; padding: 9px 12px; border-radius: 9px;
    background: var(--amber-dim); border: 1px solid oklch(45% 0.09 70); color: var(--amber);
    font-size: 12.5px; font-weight: 700; text-align: left; }
  .sound-pill audio { display: none; }
  .play-dot { display: flex; align-items: center; justify-content: center; width: 18px; height: 18px;
    border-radius: 50%; background: var(--amber); color: var(--amber-ink); flex-shrink: 0; }
  .sound-pill-name { flex: 1; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .no-sound { padding: 9px 12px; border-radius: 9px; background: var(--surface-sunken);
    border: 1px dashed var(--border); font-size: 11.5px; color: var(--text-tertiary); font-style: italic; }

  .link-row { display: flex; gap: 6px; }
  .link-row select { flex: 1; min-width: 0; padding: 7px 8px; border-radius: 7px;
    background: var(--surface-sunken); border: 1px solid var(--border); color: var(--text-secondary); font-size: 11.5px; }
  .link-btn { display: flex; align-items: center; justify-content: center; gap: 5px; padding: 0 12px;
    height: 30px; border-radius: 7px; background: var(--cyan); border: 1px solid var(--cyan);
    color: var(--cyan-ink); font-size: 11.5px; font-weight: 700; flex-shrink: 0; }

  .unlinked-grid { display: flex; flex-wrap: wrap; gap: 14px; }
  .unlinked-card { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 11px;
    background: var(--surface); border: 1px solid var(--border-soft); min-width: 240px; }
  .unlinked-icon { display: flex; align-items: center; justify-content: center; width: 34px; height: 34px;
    border-radius: 8px; background: var(--surface-raised); color: var(--text-tertiary); flex-shrink: 0; }
  .unlinked-info { flex: 1; min-width: 0; }
  .unlinked-info audio { width: 100%; height: 28px; margin-top: 4px; }

  .sheet-link { font-size: 10.5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: var(--text-tertiary); border: 1px solid var(--border); border-radius: 5px; padding: 1px 6px; margin-right: 4px; }
  .sheet-link:hover { color: var(--cyan); border-color: var(--cyan-dim); }

  .gen-panel { background: var(--surface); border: 1px solid var(--border-soft); border-radius: 14px;
    padding: 0 18px; margin-bottom: 30px; }
  .gen-panel summary { display: flex; align-items: center; gap: 12px; padding: 14px 0; cursor: pointer;
    list-style: none; font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px; }
  .gen-panel summary::-webkit-details-marker { display: none; }
  .gen-title { display: flex; align-items: center; gap: 7px; color: var(--amber); }
  .gen-badge { font-size: 11px; font-weight: 600; text-transform: none; letter-spacing: 0; padding: 3px 9px;
    border-radius: 6px; background: var(--surface-sunken); color: var(--text-tertiary); border: 1px solid var(--border-soft); }
  .gen-badge.live { color: var(--amber); border-color: oklch(45% 0.09 70); background: var(--amber-dim); }
  .gen-tabs { display: flex; gap: 4px; padding-bottom: 14px; }
  .gen-tab { padding: 6px 12px; border-radius: 8px; font-size: 12.5px; font-weight: 600; background: transparent;
    border: 1px solid transparent; color: var(--text-secondary); }
  .gen-tab.active { background: var(--surface-raised); border-color: var(--border); color: var(--text); }
  .gen-tab:disabled { opacity: 0.4; cursor: not-allowed; }
  .gen-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; padding-bottom: 14px; }
  .gen-form[hidden] { display: none; }
  .gen-form label { display: flex; flex-direction: column; gap: 5px; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.4px; color: var(--text-tertiary); }
  .gen-form label.wide { grid-column: 1 / -1; }
  .gen-form input, .gen-form select, .gen-form textarea { font: inherit; font-size: 12.5px; text-transform: none;
    letter-spacing: 0; padding: 7px 9px; border-radius: 7px; background: var(--surface-sunken);
    border: 1px solid var(--border); color: var(--text); }
  .gen-form textarea { resize: vertical; font-family: inherit; }
  .gen-note { grid-column: 1 / -1; font-size: 11.5px; color: var(--text-tertiary); }
  .gen-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding-bottom: 14px; }
  .gen-cost { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--amber); }
  .gen-status { font-size: 12px; color: var(--text-secondary); padding-bottom: 14px; min-height: 1em; }
  .gen-status.error { color: oklch(72% 0.15 20); }
  button:disabled { opacity: 0.5; cursor: wait; }

  .actor-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  .actor-card { display: block; background: var(--surface); border: 1px solid var(--border-soft);
    border-radius: 12px; padding: 18px 20px; color: var(--text); }
  .actor-card:hover { border-color: var(--cyan-dim); color: var(--text); }
  .actor-card h2 { margin: 0; font-size: 17px; font-weight: 700; }
"""

SCRIPT = """
// The server injects <meta name="csrf-token"> into every page it serves and
// requires the token on state-changing requests. Wrap fetch once so every
// mutating call carries it; the browser adds the same-origin Origin header
// on its own. When the page is opened directly from disk (no server, no meta)
// the token is empty and the wrapper is a no-op.
const CSRF_TOKEN = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
(function () {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    const method = (init.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD' && CSRF_TOKEN) {
      const headers = new Headers(init.headers || {});
      if (!headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', CSRF_TOKEN);
      init.headers = headers;
    }
    return nativeFetch(input, init);
  };
})();

function setSpeed(imgId, slug, filename, factor) {
  const img = document.getElementById(imgId);
  const base = img.dataset.baseSrc;
  const url = factor === '1'
    ? base
    : `/speed/${encodeURIComponent(slug)}/${encodeURIComponent(filename)}?factor=${encodeURIComponent(factor)}`;
  img.src = '';
  img.onload = null;
  img.src = url;
}

function playWithSound(imgId, audioId) {
  const img = document.getElementById(imgId);
  const audio = document.getElementById(audioId);
  const src = img.src;
  img.src = '';
  audio.currentTime = 0;
  img.onload = () => audio.play();
  img.src = src;
}

async function uploadFiles(slug, fileList) {
  const files = Array.from(fileList);
  if (!files.length) return;
  for (const file of files) {
    const res = await fetch(`/upload/${encodeURIComponent(slug)}/${encodeURIComponent(file.name)}`, {
      method: 'PUT',
      body: file,
    });
    if (!res.ok) {
      alert(`Upload failed for ${file.name}: ${await res.text()}`);
      return;
    }
  }
  location.href = `actor-${encodeURIComponent(slug)}.html`;
}

function uploadNewActor() {
  const slug = document.getElementById('new-actor-slug').value.trim();
  const files = document.getElementById('new-actor-files').files;
  if (!slug) {
    alert('Enter an actor slug first.');
    return;
  }
  uploadFiles(slug, files);
}

async function linkSound(slug, animation, selectId) {
  const select = document.getElementById(selectId);
  const sound = select.value;
  if (!sound) return;
  const res = await fetch('/link', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({slug, animation, sound}),
  });
  if (!res.ok) {
    alert(`Link failed: ${await res.text()}`);
    return;
  }
  location.reload();
}

async function deleteAsset(slug, filename) {
  if (!confirm(`Delete ${filename}? This can't be undone.`)) return;
  const res = await fetch(`/asset/${encodeURIComponent(slug)}/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    alert(`Delete failed: ${await res.text()}`);
    return;
  }
  location.reload();
}

async function renameAsset(slug, filename) {
  const newName = prompt(`Rename ${filename} to:`, filename);
  if (!newName || newName === filename) return;
  const res = await fetch('/rename', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({slug, filename, new_name: newName}),
  });
  if (!res.ok) {
    alert(`Rename failed: ${await res.text()}`);
    return;
  }
  location.reload();
}

async function unlinkSound(slug, animation, sound) {
  const res = await fetch('/unlink', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({slug, animation, sound}),
  });
  if (!res.ok) {
    alert(`Unlink failed: ${await res.text()}`);
    return;
  }
  location.reload();
}

async function trimSound(slug, sound, durationMs, linkTo) {
  const hint = durationMs ? `${sound} is ${durationMs} ms.` : sound;
  const answer = prompt(`${hint}\nKeep which part? Enter start-end in ms (a new file is written; the original is kept):`,
                        `0-${durationMs || 1000}`);
  if (!answer) return;
  const m = answer.trim().match(/^(\\d+)\\s*-\\s*(\\d+)$/);
  if (!m) { alert('Enter a range like 120-700'); return; }
  const res = await fetch('/trim', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({slug, sound, start_ms: +m[1], end_ms: +m[2], link_to: linkTo || null}),
  });
  if (!res.ok) {
    let msg = await res.text();
    try { msg = JSON.parse(msg).error; } catch (e) {}
    alert(`Trim failed: ${msg}`);
    return;
  }
  location.reload();
}

// ---- Generation panel ---------------------------------------------------

const GEN = { kind: 'animation', estimate: null, slug: null };

function $(id) { return document.getElementById(id); }

function genTab(kind) {
  GEN.kind = kind;
  document.querySelectorAll('.gen-tab').forEach(b => b.classList.toggle('active', b.dataset.kind === kind));
  ['animation', 'sound', 'source'].forEach(k => { $(`gen-form-${k}`).hidden = (k !== kind); });
  genDirty();
}

function genDirty() {
  GEN.estimate = null;
  $('gen-confirm').hidden = true;
  $('gen-cost').textContent = '';
}

function genParams() {
  const form = $(`gen-form-${GEN.kind}`);
  const params = { slug: GEN.slug, kind: GEN.kind };
  new FormData(form).forEach((v, k) => { params[k] = v; });
  return params;
}

function genStatus(text, isError) {
  const el = $('gen-status');
  el.textContent = text;
  el.classList.toggle('error', !!isError);
}

async function genJson(url, body, method) {
  const res = await fetch(url, {
    method: method || 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { data = { error: `HTTP ${res.status}` }; }
  if (!res.ok) throw Object.assign(new Error(data.error || `HTTP ${res.status}`), { status: res.status, data });
  return data;
}

async function genEstimate() {
  genDirty();
  genStatus('');
  const btn = $('gen-estimate');
  btn.disabled = true;
  try {
    const est = await genJson('/estimate', genParams());
    GEN.estimate = est;
    const parts = [est.display];
    if (est.submitted_size) parts.push(`submits ${est.submitted_size[0]}×${est.submitted_size[1]}`);
    parts.push(`writes ${est.output_name}`);
    $('gen-cost').textContent = parts.join(' · ');
    const confirm = $('gen-confirm');
    confirm.textContent = `Confirm & generate (${est.display.split(' · ')[0]})`;
    confirm.hidden = false;
    if (!est.live) genStatus('Offline: a fake provider will answer. Start the server with --allow-spend to use the real API.');
  } catch (err) {
    genStatus(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function genConfirm() {
  if (!GEN.estimate) return;
  const confirm = $('gen-confirm');
  confirm.disabled = true;
  const params = genParams();
  params.confirm_amount = GEN.estimate.amount;
  const kind = GEN.kind;
  try {
    if (kind === 'animation') {
      genStatus('Submitting…');
      const job = await genJson('/generate/animation', params);
      await genPoll(job.job_id, job.output_name);
    } else {
      genStatus('Generating…');
      const result = await genJson(`/generate/${kind}`, params);
      genStatus(`Done: ${result.filename}` + (result.reported_charge ? ` · charged ${result.reported_charge}` : ''));
      setTimeout(() => location.reload(), 600);
    }
  } catch (err) {
    genStatus(err.data && err.data.ambiguous
      ? `Ambiguous: ${err.message}`
      : err.message, true);
    confirm.disabled = false;
  }
}

async function genPoll(jobId, outputName) {
  const started = Date.now();
  for (;;) {
    let job;
    try {
      job = await genJson(`/job/${encodeURIComponent(GEN.slug)}/${encodeURIComponent(jobId)}`, undefined, 'GET');
    } catch (err) {
      genStatus(err.message, true);
      return;
    }
    const elapsed = Math.round((Date.now() - started) / 1000);
    if (job.state === 'running' || job.state === 'queued') {
      genStatus(`Animating ${outputName || ''}… ${elapsed}s (SpriteLab jobs usually take 30–90 s; keep this page open)`);
      await new Promise(r => setTimeout(r, 3000));
      continue;
    }
    if (job.state === 'succeeded') {
      genStatus(`Done: ${(job.outputs && job.outputs.gif) || 'sheet only'}`);
      setTimeout(() => location.reload(), 600);
    } else {
      genStatus(`${job.state}: ${job.error || 'no detail'}`, true);
    }
    return;
  }
}

async function genInit() {
  const panel = document.querySelector('.gen-panel');
  if (!panel) return;
  GEN.slug = panel.dataset.slug;
  try {
    const info = await genJson('/providers', undefined, 'GET');
    const badge = $('gen-badge');
    const p = info.providers;
    if (info.allow_spend) {
      badge.textContent = 'LIVE — spending enabled';
      badge.classList.add('live');
    } else {
      badge.textContent = 'offline — fake providers';
    }
    const usable = {
      animation: !info.allow_spend || p.spritelab.live,
      sound: !info.allow_spend || p.elevenlabs.live,
      source: !info.allow_spend || p.spritelab.live || p.openai.live,
    };
    document.querySelectorAll('.gen-tab').forEach(b => {
      b.disabled = !usable[b.dataset.kind];
      if (b.disabled) b.title = 'no API key configured for this provider';
    });
    const jobs = await genJson(`/jobs/${encodeURIComponent(GEN.slug)}`, undefined, 'GET');
    if (jobs.open && jobs.open.length) {
      const job = jobs.open[jobs.open.length - 1];
      panel.open = true;
      genStatus(`Resuming animation job for "${job.action}"…`);
      genPoll(job.job_id, job.action);
    }
  } catch (err) {
    $('gen-badge').textContent = 'server not running';
  }
}

genInit();
"""


def list_media(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in exts)


def load_links(actor_dir: Path) -> dict[str, list[str]]:
    links_file = actor_dir / "links.json"
    if not links_file.is_file():
        return {}
    return json.loads(links_file.read_text())


def asset_count(actor_dir: Path) -> int:
    return sum(
        len(list_media(actor_dir / cat, exts))
        for cat, exts in (("sprites", IMAGE_EXTS), ("animations", IMAGE_EXTS), ("sounds", AUDIO_EXTS))
    )


def asset_actions_html(esc_slug: str, filename: str, extra: str = "") -> str:
    esc_name = html.escape(filename, quote=True)
    return (
        f'<div class="asset-actions">{extra}'
        f'<button type="button" class="icon-btn" title="Rename" '
        f'onclick="renameAsset(\'{esc_slug}\',\'{esc_name}\')">{PENCIL_ICON}</button>'
        f'<button type="button" class="icon-btn icon-btn-danger" title="Delete" '
        f'onclick="deleteAsset(\'{esc_slug}\',\'{esc_name}\')">{TRASH_ICON}</button>'
        f"</div>"
    )


def render_actor(actor_dir: Path) -> str:
    slug = actor_dir.name
    sprites = list_media(actor_dir / "sprites", IMAGE_EXTS)
    animations = list_media(actor_dir / "animations", IMAGE_EXTS)
    sounds = list_media(actor_dir / "sounds", AUDIO_EXTS)
    links = load_links(actor_dir)
    esc_slug = html.escape(slug, quote=True)

    def rel(p: Path) -> str:
        return html.escape(str(p.relative_to(ROOT)))

    sprite_html = "".join(
        f'<div class="sprite-card">'
        f'<div class="sprite-thumb checker"><img class="pixel-art" src="{rel(p)}" loading="lazy"></div>'
        f'<div class="asset-name">{html.escape(p.name)}</div>'
        f"{asset_actions_html(esc_slug, p.name)}"
        f"</div>"
        for p in sprites
    )

    linked_names = {s for names in links.values() for s in names}
    unlinked_sounds = [p for p in sounds if p.name not in linked_names]
    unlinked_options = "".join(
        f'<option value="{html.escape(p.name, quote=True)}">{html.escape(p.name)}</option>'
        for p in unlinked_sounds
    )

    sprite_options = "".join(
        f'<option value="{html.escape(p.name, quote=True)}">{html.escape(p.name)}</option>' for p in sprites
    )
    anim_options = "".join(
        f'<option value="{html.escape(p.name, quote=True)}">{html.escape(p.name)}</option>' for p in animations
    )

    anim_html = ""
    for i, p in enumerate(animations):
        img_id = f"anim-{esc_slug}-{i}"
        linked = links.get(p.name, [])
        stem = p.stem[: -len("_preview")] if p.stem.endswith("_preview") else p.stem
        sheet = actor_dir / "sheets" / f"{stem}_sheet.png"
        sheet_link = (
            f'<a class="sheet-link" href="{rel(sheet)}" download title="Download spritesheet">sheet</a>'
            if sheet.is_file()
            else ""
        )
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
                f'onclick="playWithSound(\'{img_id}\',\'{audio_id}\')">'
                f'<audio id="{audio_id}" src="{rel(sound_path)}"></audio>'
                f'<span class="play-dot">{PLAY_ICON}</span>'
                f'<span class="sound-pill-name">{html.escape(s)}</span>{dur_html}'
                f"</button>"
                f'<div class="asset-actions">'
                f"{trim_button_html(esc_slug, s, duration, p.name)}"
                f'<button type="button" class="icon-btn icon-btn-danger" title="Unlink from this animation" '
                f'onclick="unlinkSound(\'{esc_slug}\',\'{html.escape(p.name, quote=True)}\',\'{html.escape(s, quote=True)}\')">'
                f"{UNLINK_ICON}</button>"
                f"</div></div>"
            )
        link_control = (
            f'<div class="link-row">'
            f'<select id="link-select-{esc_slug}-{i}">{unlinked_options}</select>'
            f'<button type="button" class="link-btn" '
            f'onclick="linkSound(\'{esc_slug}\',\'{html.escape(p.name, quote=True)}\',\'link-select-{esc_slug}-{i}\')">'
            f"{LINK_ICON} Link</button>"
            f"</div>"
            if unlinked_options
            else ""
        )
        speed_row = (
            f'<div class="speed-row">'
            f'<span class="speed-label">Speed</span>'
            f'<select onchange="setSpeed(\'{img_id}\',\'{esc_slug}\',\'{html.escape(p.name, quote=True)}\',this.value)">'
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
            f'<div class="asset-name-row"><div class="asset-name">{html.escape(p.name)}</div>'
            f"{sheet_link}{asset_actions_html(esc_slug, p.name)}</div>"
            f"{speed_row}"
            f'<div class="sound-pills">{buttons or NO_SOUND_HTML}</div>'
            f"{link_control}"
            f"</div></div>"
        )

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
          <button type="button" class="gen-tab active" data-kind="animation" onclick="genTab('animation')">Animate a sprite</button>
          <button type="button" class="gen-tab" data-kind="sound" onclick="genTab('sound')">Sound</button>
          <button type="button" class="gen-tab" data-kind="source" onclick="genTab('source')">Source sprite</button>
        </div>

        <form class="gen-form" id="gen-form-animation" oninput="genDirty()" onsubmit="return false">
          <label>Sprite <select name="sprite">{sprite_options or '<option value="">(upload a sprite first)</option>'}</select></label>
          <label>Action name <input name="action" placeholder="lunge_attack"></label>
          <label class="wide">Prompt <textarea name="prompt" rows="4">{ANIMATION_PROMPT_TEMPLATE}</textarea></label>
          <label>Frames <input name="frames" type="number" value="16" min="1" max="64"></label>
          <div class="gen-note">SpriteLab returns the canvas it is given: the sprite is fitted to 256&times;256 with a 16px margin first. Fixed 8 fps. 20 credits.</div>
        </form>

        <form class="gen-form" id="gen-form-sound" hidden oninput="genDirty()" onsubmit="return false">
          <label class="wide">Prompt <textarea name="prompt" rows="3" placeholder="{SOUND_PROMPT_PLACEHOLDER}"></textarea></label>
          <label>Duration (ms) <input name="duration_ms" type="number" value="800" min="500" max="30000" step="50"></label>
          <label>Name <input name="name" placeholder="sword_impact"></label>
          <label>Link to animation <select name="link_to"><option value="">(none)</option>{anim_options}</select></label>
          <div class="gen-note">ElevenLabs, 40 credits per second of requested duration.</div>
        </form>

        <form class="gen-form" id="gen-form-source" hidden oninput="genDirty()" onsubmit="return false">
          <label>Provider <select name="provider">
            <option value="spritelab_epic">SpriteLab &middot; epic &middot; 1 credit</option>
            <option value="spritelab_mythic">SpriteLab &middot; mythic &middot; 6 credits</option>
            <option value="openai">OpenAI gpt-image-2 &middot; low &middot; $0.006</option>
          </select></label>
          <label class="wide">Prompt <textarea name="prompt" rows="3" placeholder="A hooded scribe holding a glowing grimoire, pixel art, side view, transparent background"></textarea></label>
          <div class="gen-note">SpriteLab returns a 256px multi-view sheet; OpenAI a 1024&times;1024 transparent PNG. Either lands in sprites/ and is fitted to 256px when animated.</div>
        </form>

        <div class="gen-actions">
          <button type="button" class="btn-ghost" id="gen-estimate" onclick="genEstimate()">Estimate cost</button>
          <div class="gen-cost" id="gen-cost"></div>
          <button type="button" class="btn-primary" id="gen-confirm" hidden onclick="genConfirm()">Confirm &amp; generate</button>
        </div>
        <div class="gen-status" id="gen-status"></div>
      </details>
    """

    return f"""
    <section class="actor" id="{esc_slug}">
      <div class="section-head">
        <div>
          <h2>{html.escape(slug)}</h2>
          <div class="section-meta">{len(sprites)} sprites &middot; {len(animations)} animations &middot;
            {len(sounds)} sounds &middot; {len(unlinked_sounds)} unlinked</div>
        </div>
        <div class="section-actions">
          <div class="upload-widget" data-slug="{esc_slug}">
            <div class="upload-icon">{UPLOAD_ICON}</div>
            <div>
              <div class="upload-title">Drop files, or click to browse</div>
              <div class="upload-hint">Sorted automatically &mdash; .gif to animations, images to sprites, audio to sounds</div>
            </div>
            <input type="file" multiple onchange="uploadFiles('{esc_slug}', this.files)">
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
        <div class="group-label group-label-lg">Animations <span class="count">{len(animations)}</span>
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
    <button type="button" class="btn-primary" onclick="uploadNewActor()">Create &amp; upload</button>
  </div>
</div>
"""


def page_shell(title: str, topbar_html: str, body_html: str) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
</head>
<body>
{topbar_html}
<main>
{body_html}
</main>
<script>{SCRIPT}</script>
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
        f'{len(list_media(d / "animations", IMAGE_EXTS))} animations &middot; '
        f'{len(list_media(d / "sounds", AUDIO_EXTS))} sounds</div>'
        f"</a>"
        for d in actor_dirs
    )
    return f'<div class="actor-cards">{cards}</div>'


def build() -> int:
    ACTORS_DIR.mkdir(exist_ok=True)
    actor_dirs = sorted(p for p in ACTORS_DIR.iterdir() if p.is_dir())
    valid_slugs = {d.name for d in actor_dirs}

    for f in ROOT.glob(f"{ACTOR_PAGE_PREFIX}*.html"):
        if f.stem[len(ACTOR_PAGE_PREFIX):] not in valid_slugs:
            f.unlink()

    for d in actor_dirs:
        topbar = render_topbar(actor_dirs, active_slug=d.name)
        page = page_shell(f"{d.name} — emberforge-lite", topbar, render_actor(d))
        (ROOT / f"{ACTOR_PAGE_PREFIX}{d.name}.html").write_text(page)

    topbar = render_topbar(actor_dirs, active_slug=None)
    OUTPUT.write_text(page_shell("emberforge-lite gallery", topbar, render_index_body(actor_dirs)))
    return len(actor_dirs)


def main() -> None:
    count = build()
    print(f"Wrote {OUTPUT} and {count} actor page(s)")


if __name__ == "__main__":
    main()
