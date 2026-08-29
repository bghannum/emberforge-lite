#!/usr/bin/env python3
"""Serve emberforge-lite: static gallery + browser-based upload, linking,
asset management, and provider generation.

    python3 server.py [port] [--allow-spend]     # default port 8000

Uploads land in actors/<slug>/<category>/ (category picked from the file
extension, never trusted from the client) and trigger an in-process rebuild.

Generation goes through the provider APIs only when started with
--allow-spend; otherwise deterministic fakes run the identical flow offline.
Every generate call also requires the browser to echo back the exact
estimated amount it was shown.
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import audiotools
import build
import generate
import media
from gifspeed import slow_gif
from linking import add_link, remove_animation, remove_link, remove_sound, rename_animation, rename_sound
from naming import sanitize_filename, sanitize_slug, unique_path

ROOT = Path(__file__).parent
ACTORS_DIR = ROOT / "actors"

MAX_BODY_BYTES = 200 * 1024 * 1024  # 200MB uploads
MAX_JSON_BYTES = 1024 * 1024

CATEGORY_BY_EXT = {
    ".gif": "animations",
    ".png": "sprites",
    ".jpg": "sprites",
    ".jpeg": "sprites",
    ".webp": "sprites",
    ".mp3": "sounds",
    ".wav": "sounds",
    ".ogg": "sounds",
    ".m4a": "sounds",
}


def sheet_for(actor_dir: Path, gif_name: str) -> Path | None:
    """The spritesheet a generated preview gif came with, if any."""
    stem = Path(gif_name).stem
    if stem.endswith("_preview"):
        stem = stem[: -len("_preview")]
    candidate = actor_dir / "sheets" / f"{stem}_sheet.png"
    return candidate if candidate.is_file() else None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    # -- GET -------------------------------------------------------------

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/gallery.html")
            self.end_headers()
            return
        if path.startswith("/speed/"):
            self._handle_speed(path, parsed.query)
            return
        if path.startswith("/export/"):
            self._handle_export(path)
            return
        if path == "/providers":
            self._respond(200, generate.provider_status())
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path.startswith("/job/"):
            self._guard(self._handle_job, path)
            return
        if path.startswith("/jobs/"):
            self._guard(self._handle_jobs, path)
            return
        super().do_GET()

    def _handle_speed(self, path: str, query: str) -> None:
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 3:
            self._respond(404, {"error": "not found"})
            return
        _, raw_slug, raw_filename = parts
        slug = sanitize_slug(raw_slug)
        filename = sanitize_filename(raw_filename)
        if not slug or not filename or Path(filename).suffix.lower() != ".gif":
            self._respond(400, {"error": "expected a .gif filename"})
            return
        src_path = ACTORS_DIR / slug / "animations" / filename
        if not src_path.is_file():
            self._respond(404, {"error": "no such animation"})
            return
        try:
            factor = float(parse_qs(query).get("factor", ["1"])[0])
        except ValueError:
            factor = 1.0
        out = slow_gif(src_path.read_bytes(), factor)
        self._send_bytes(out, "image/gif")

    def _handle_export(self, path: str) -> None:
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 2:
            self._respond(404, {"error": "not found"})
            return
        slug = sanitize_slug(parts[1])
        actor_dir = ACTORS_DIR / slug
        if not slug or not actor_dir.is_dir():
            self._respond(404, {"error": "no such actor"})
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(actor_dir.rglob("*")):
                if file_path.is_file():
                    zf.write(file_path, arcname=f"{slug}/{file_path.relative_to(actor_dir)}")
        self._send_bytes(
            buf.getvalue(),
            "application/zip",
            extra={"Content-Disposition": f'attachment; filename="{slug}-export.zip"'},
        )

    def _handle_job(self, path: str) -> None:
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 3:
            raise generate.GenerateError(404, "not found")
        slug = sanitize_slug(parts[1])
        job_id = sanitize_filename(parts[2])
        if not slug or not job_id:
            raise generate.GenerateError(400, "invalid slug or job id")
        self._respond(200, generate.advance_job(slug, job_id))

    def _handle_jobs(self, path: str) -> None:
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 2:
            raise generate.GenerateError(404, "not found")
        slug = sanitize_slug(parts[1])
        if not slug:
            raise generate.GenerateError(400, "invalid slug")
        self._respond(200, {"open": generate.open_jobs(slug)})

    # -- PUT (upload) -----------------------------------------------------

    def do_PUT(self):
        parts = [unquote(p) for p in self.path.strip("/").split("/")]
        if len(parts) != 3 or parts[0] != "upload":
            self._respond(404, {"error": "not found"})
            return

        _, raw_slug, raw_filename = parts
        slug = sanitize_slug(raw_slug)
        filename = sanitize_filename(raw_filename)
        if not slug or not filename:
            self._respond(400, {"error": "invalid slug or filename"})
            return

        ext = Path(filename).suffix.lower()
        category = CATEGORY_BY_EXT.get(ext)
        if category is None:
            self._respond(400, {"error": f"unsupported extension: {ext}"})
            return

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._respond(400, {"error": "empty body"})
            return
        if length > MAX_BODY_BYTES:
            self._respond(413, {"error": "file too large"})
            return
        data = self.rfile.read(length)

        target_dir = ACTORS_DIR / slug / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = unique_path(target_dir, filename)
        target_path.write_bytes(data)

        actor_count = build.build()
        self._respond(
            200,
            {"slug": slug, "category": category, "filename": target_path.name, "actors": actor_count},
        )

    # -- DELETE -----------------------------------------------------------

    def do_DELETE(self):
        parts = [unquote(p) for p in self.path.strip("/").split("/")]
        if len(parts) != 3 or parts[0] != "asset":
            self._respond(404, {"error": "not found"})
            return

        _, raw_slug, raw_filename = parts
        slug = sanitize_slug(raw_slug)
        filename = sanitize_filename(raw_filename)
        if not slug or not filename:
            self._respond(400, {"error": "invalid slug or filename"})
            return

        category = CATEGORY_BY_EXT.get(Path(filename).suffix.lower())
        if category is None:
            self._respond(400, {"error": "unsupported extension"})
            return

        actor_dir = ACTORS_DIR / slug
        target = actor_dir / category / filename
        if not target.is_file():
            self._respond(404, {"error": "no such asset"})
            return
        target.unlink()

        if category == "animations":
            remove_animation(ACTORS_DIR, slug, filename)
            sheet = sheet_for(actor_dir, filename)
            if sheet is not None:
                sheet.unlink()
        elif category == "sounds":
            remove_sound(ACTORS_DIR, slug, filename)

        actor_count = build.build()
        self._respond(200, {"deleted": filename, "actors": actor_count})

    # -- POST -------------------------------------------------------------

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/link":
            self._handle_link()
        elif path == "/unlink":
            self._handle_unlink()
        elif path == "/trim":
            self._handle_trim()
        elif path == "/rename":
            self._handle_rename()
        elif path == "/rebuild":
            self._respond(200, {"actors": build.build()})
        elif path == "/estimate":
            self._guard(self._handle_estimate)
        elif path in ("/generate/sound", "/generate/source", "/generate/animation"):
            self._guard(self._handle_generate, path.rsplit("/", 1)[1])
        else:
            self._respond(404, {"error": "not found"})

    def _handle_link(self):
        try:
            payload = self._read_json()
            slug = str(payload["slug"])
            animation = str(payload["animation"])
            sound = str(payload["sound"])
        except (ValueError, KeyError, TypeError):
            self._respond(400, {"error": "expected JSON {slug, animation, sound}"})
            return
        try:
            add_link(ACTORS_DIR, slug, animation, sound)
        except FileNotFoundError as e:
            self._respond(400, {"error": str(e)})
            return
        self._respond(200, {"actors": build.build()})

    def _handle_unlink(self):
        try:
            payload = self._read_json()
            slug = sanitize_slug(str(payload["slug"]))
            animation = sanitize_filename(str(payload["animation"]))
            sound = sanitize_filename(str(payload["sound"]))
        except (ValueError, KeyError, TypeError):
            self._respond(400, {"error": "expected JSON {slug, animation, sound}"})
            return
        if not slug or not animation or not sound:
            self._respond(400, {"error": "invalid slug or filename"})
            return
        if not remove_link(ACTORS_DIR, slug, animation, sound):
            self._respond(404, {"error": f"{sound} is not linked to {animation}"})
            return
        self._respond(200, {"unlinked": sound, "actors": build.build()})

    def _handle_trim(self):
        try:
            payload = self._read_json()
            slug = sanitize_slug(str(payload["slug"]))
            sound = sanitize_filename(str(payload["sound"]))
            start_ms = int(payload.get("start_ms", 0))
            end_ms = int(payload["end_ms"])
            link_to = sanitize_filename(str(payload.get("link_to") or ""))
        except (ValueError, KeyError, TypeError):
            self._respond(400, {"error": "expected JSON {slug, sound, start_ms, end_ms, link_to?}"})
            return
        if not slug or not sound:
            self._respond(400, {"error": "invalid slug or filename"})
            return
        actor_dir = ACTORS_DIR / slug
        src = actor_dir / "sounds" / sound
        if not src.is_file():
            self._respond(404, {"error": "no such sound"})
            return
        try:
            cut = audiotools.trim(src.read_bytes(), start_ms, end_ms)
            duration = media.inspect_audio(cut)[0]
        except (audiotools.TrimError, media.Rejected) as e:
            self._respond(400, {"error": str(e)})
            return

        target = unique_path(actor_dir / "sounds", f"{src.stem}_{start_ms}-{end_ms}{src.suffix}")
        target.write_bytes(cut)
        linked = False
        if link_to and (actor_dir / "animations" / link_to).is_file():
            add_link(ACTORS_DIR, slug, link_to, target.name)
            linked = True
        self._respond(200, {"filename": target.name, "duration_ms": duration, "linked": linked, "actors": build.build()})

    def _handle_rename(self):
        try:
            payload = self._read_json()
            slug = sanitize_slug(str(payload["slug"]))
            old_name = sanitize_filename(str(payload["filename"]))
            new_name = sanitize_filename(str(payload["new_name"]))
        except (ValueError, KeyError, TypeError):
            self._respond(400, {"error": "expected JSON {slug, filename, new_name}"})
            return
        if not slug or not old_name or not new_name:
            self._respond(400, {"error": "invalid slug or filename"})
            return

        category = CATEGORY_BY_EXT.get(Path(old_name).suffix.lower())
        new_category = CATEGORY_BY_EXT.get(Path(new_name).suffix.lower())
        if category is None or new_category != category:
            self._respond(400, {"error": "rename must keep the same file type"})
            return

        actor_dir = ACTORS_DIR / slug
        old_path = actor_dir / category / old_name
        new_path = actor_dir / category / new_name
        if not old_path.is_file():
            self._respond(404, {"error": "no such asset"})
            return
        if new_path.exists():
            self._respond(409, {"error": f"{new_name} already exists"})
            return
        old_path.rename(new_path)

        if category == "animations":
            rename_animation(ACTORS_DIR, slug, old_name, new_name)
            sheet = sheet_for(actor_dir, old_name)
            if sheet is not None:
                new_sheet = sheet_for(actor_dir, new_name)
                if new_sheet is None:
                    stem = Path(new_name).stem
                    if stem.endswith("_preview"):
                        stem = stem[: -len("_preview")]
                    sheet.rename(actor_dir / "sheets" / f"{stem}_sheet.png")
        elif category == "sounds":
            rename_sound(ACTORS_DIR, slug, old_name, new_name)

        self._respond(200, {"filename": new_name, "actors": build.build()})

    def _handle_estimate(self) -> None:
        payload = self._read_json()
        slug, kind = str(payload.get("slug", "")), str(payload.get("kind", ""))
        self._respond(200, generate.estimate(slug, kind, payload))

    def _handle_generate(self, kind: str) -> None:
        payload = self._read_json()
        slug = str(payload.get("slug", ""))
        confirm = payload.get("confirm_amount")
        if confirm is None:
            raise generate.GenerateError(400, "confirm_amount is required: echo the estimate you were shown")
        if kind == "animation":
            self._respond(202, generate.submit_animation(slug, payload, confirm))
        else:
            self._respond(200, generate.run_sync(slug, kind, payload, confirm))

    # -- Helpers ----------------------------------------------------------

    def _guard(self, fn, *args) -> None:
        """Run a generation handler, turning its refusals into JSON responses."""
        try:
            fn(*args)
        except generate.GenerateError as err:
            self._respond(err.status, err.payload)
        except ValueError as err:
            self._respond(400, {"error": str(err)})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_JSON_BYTES:
            raise ValueError("invalid body")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object")
        return payload

    def _send_bytes(self, data: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port", nargs="?", type=int, default=8000)
    parser.add_argument(
        "--allow-spend",
        action="store_true",
        help="use the live provider APIs (reads .env / env vars). Without it, fakes run offline.",
    )
    args = parser.parse_args()

    generate.configure(allow_spend=args.allow_spend)
    status = generate.provider_status()["providers"]
    if args.allow_spend:
        live = [name for name, s in status.items() if s["live"]]
        missing = [name for name, s in status.items() if not s["configured"]]
        print(f"SPEND ENABLED - live providers: {', '.join(live) or 'none'}"
              + (f" (no key: {', '.join(missing)})" if missing else ""), flush=True)
    else:
        print("offline - fake providers (start with --allow-spend to use the real APIs)", flush=True)

    build.build()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Serving emberforge-lite on http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
