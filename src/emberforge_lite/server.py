#!/usr/bin/env python3
"""Serve emberforge-lite: static gallery + browser-based upload, linking,
asset management, and provider generation.

    python3 server.py [port] [--allow-spend]     # default port 8000

Security model (Milestone 1):

* Binds to loopback only, and rejects requests whose Host is not a loopback
  name (a DNS-rebinding defense).
* Serves ONLY generated pages (gallery.html, actor-<slug>.html) and actor
  media under actors/<slug>/<category>/. Everything else -- credentials, Git
  metadata, Python source, prompts and the spend ledger -- returns 404.
* Every state-changing request (PUT/DELETE/POST) must carry a same-origin
  Origin header and a matching X-CSRF-Token. The token is minted at startup
  and injected into each served page.
* Uploads are size-capped, validated before they are committed, and written
  through a temporary file with an atomic rename, so a rejected or partial
  upload leaves nothing behind.

Uploads land in actors/<slug>/<category>/ (category picked from the file
extension, never trusted from the client) and trigger an in-process rebuild.

Generation goes through the provider APIs only when started with
--allow-spend; otherwise deterministic fakes run the identical flow offline.
Every generate call also requires the browser to echo back the exact
estimated amount it was shown.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from emberforge_lite import animmeta, audiotools, build, generate, logs, media, provenance, storage
from emberforge_lite.gifspeed import slow_gif
from emberforge_lite.linking import (
    add_link,
    remove_animation,
    remove_link,
    remove_sound,
    rename_animation,
    rename_sound,
)
from emberforge_lite.naming import sanitize_filename, sanitize_slug, unique_path

ROOT = Path(__file__).parent
ACTORS_DIR = ROOT / "actors"

#: Packaged CSS/JS, served read-only at /static/.
STATIC_DIR = Path(__file__).parent / "static"


def configure_paths(paths) -> None:
    """Serve pages from ``paths.site`` and actor media from ``paths.actors``."""
    global ROOT, ACTORS_DIR
    ROOT = paths.site
    ACTORS_DIR = paths.actors


#: Upload ceiling. Overridable by the environment; the CLI gains a flag in
#: Milestone 2. Lowered from an earlier 200MB: a review asset is small, and a
#: high ceiling only widens what a mistaken or hostile upload can spend on disk.
MAX_UPLOAD_BYTES = int(os.environ.get("EMBERFORGE_MAX_UPLOAD_BYTES", 64 * 1024 * 1024))
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

#: Media the server will serve back over GET, and the content type for each.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}

#: The only actor subdirectories whose files are servable.
SERVABLE_CATEGORIES = {"sprites", "animations", "sounds", "sheets"}

#: Magic-byte signatures for the upload types media.py has no header inspector
#: for. PNG/GIF/WAV/MP3 are validated by their real inspectors instead.
_SNIFF = {
    ".jpg": lambda d: d[:3] == b"\xff\xd8\xff",
    ".jpeg": lambda d: d[:3] == b"\xff\xd8\xff",
    ".webp": lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP",
    ".ogg": lambda d: d[:4] == b"OggS",
    ".m4a": lambda d: d[4:8] == b"ftyp",
}

CSP = (
    "default-src 'none'; "
    "img-src 'self' data:; "
    "media-src 'self'; "
    "style-src 'self'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

# Set at startup by configure_security(). Loopback names and same-origin values
# the guards accept, plus the per-process CSRF token embedded in served pages.
CSRF_TOKEN = ""
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
ALLOWED_ORIGINS: set[str] = set()


def configure_security(port: int) -> None:
    """Mint the CSRF token and compute the same-origin allowlist for `port`."""
    global CSRF_TOKEN, ALLOWED_ORIGINS
    CSRF_TOKEN = secrets.token_urlsafe(32)
    ALLOWED_ORIGINS = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://[::1]:{port}",
    }


def sheet_for(actor_dir: Path, gif_name: str) -> Path | None:
    """The spritesheet a generated preview gif came with, if any."""
    stem = Path(gif_name).stem
    if stem.endswith("_preview"):
        stem = stem[: -len("_preview")]
    candidate = actor_dir / "sheets" / f"{stem}_sheet.png"
    return candidate if candidate.is_file() else None


def _animation_exists(actor_dir: Path, name: str) -> bool:
    path = actor_dir / "animations" / name
    return path.is_file() or animmeta.is_package(path)


def _rename_sheet(actor_dir: Path, old_name: str, new_name: str) -> None:
    """Move an animation's spritesheet along with it, if it has one."""
    sheet = sheet_for(actor_dir, old_name)
    if sheet is None or sheet_for(actor_dir, new_name) is not None:
        return
    stem = Path(new_name).stem
    if stem.endswith("_preview"):
        stem = stem[: -len("_preview")]
    new_sheet_path = actor_dir / "sheets" / f"{stem}_sheet.png"
    sheet.rename(new_sheet_path)
    provenance.rename_asset(actor_dir, f"sheets/{sheet.name}", f"sheets/{new_sheet_path.name}")


class Handler(BaseHTTPRequestHandler):
    server_version = "emberforge-lite"

    # -- Request guards ---------------------------------------------------

    def _host_ok(self) -> bool:
        """Reject a Host header that is not a loopback name (rebinding defense)."""
        host = self.headers.get("Host", "")
        if not host:
            return True
        hostname = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return hostname in ALLOWED_HOSTS

    def _mutation_ok(self) -> bool:
        """A state-changing request needs a same-origin Origin and CSRF token."""
        origin = self.headers.get("Origin")
        if origin is None or origin not in ALLOWED_ORIGINS:
            return False
        token = self.headers.get("X-CSRF-Token", "")
        return bool(CSRF_TOKEN) and secrets.compare_digest(token, CSRF_TOKEN)

    def _reject_bad_host(self) -> bool:
        if self._host_ok():
            return False
        self._respond(400, {"error": "bad host header"})
        return True

    def _reject_unguarded_mutation(self) -> bool:
        if self._mutation_ok():
            return False
        self._respond(403, {"error": "missing or invalid Origin / CSRF token"})
        return True

    # -- GET -------------------------------------------------------------

    def do_GET(self):
        if self._reject_bad_host():
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/":
            self.send_response(302)
            self._security_headers()
            self.send_header("Location", "/gallery.html")
            self.end_headers()
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self._security_headers()
            self.end_headers()
            return
        if path == "/providers":
            self._respond(200, generate.provider_status())
            return
        if path.startswith("/speed/"):
            self._handle_speed(path, parsed.query)
            return
        if path.startswith("/export/"):
            self._handle_export(path)
            return
        if path.startswith("/job/"):
            self._guard(self._handle_job, path)
            return
        if path.startswith("/jobs/"):
            self._guard(self._handle_jobs, path)
            return
        if path.startswith("/static/"):
            self._serve_static(path)
            return
        if path == "/gallery.html":
            self._serve_page(ROOT / "gallery.html")
            return
        if path.startswith("/actor-") and path.endswith(".html"):
            self._serve_actor_page(path)
            return
        if path.startswith("/actors/"):
            if self._is_package_path(parsed.path):
                self._serve_package(parsed.path)
            else:
                self._serve_media(parsed.path)
            return
        self._respond(404, {"error": "not found"})

    def _serve_actor_page(self, path: str) -> None:
        stem = path[len("/") :][: -len(".html")]  # "actor-<slug>"
        slug = sanitize_slug(stem[len("actor-") :])
        if not slug:
            self._respond(404, {"error": "not found"})
            return
        self._serve_page(ROOT / f"actor-{slug}.html")

    def _serve_page(self, file_path: Path) -> None:
        safe = self._resolved_under(ROOT, file_path)
        if safe is None or not safe.is_file():
            self._respond(404, {"error": "not found"})
            return
        html_text = safe.read_text()
        # Inject the per-process CSRF token so the page's fetches can echo it.
        meta = f'<meta name="csrf-token" content="{CSRF_TOKEN}">'
        if "</head>" in html_text:
            html_text = html_text.replace("</head>", meta + "</head>", 1)
        body = html_text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> None:
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 2 or parts[0] != "static":
            self._respond(404, {"error": "not found"})
            return
        filename = sanitize_filename(parts[1])
        ext = Path(filename).suffix.lower()
        if not filename or ext not in CONTENT_TYPES:
            self._respond(404, {"error": "not found"})
            return
        candidate = STATIC_DIR / filename
        safe = self._resolved_under(STATIC_DIR, candidate)
        if safe is None or not safe.is_file():
            self._respond(404, {"error": "not found"})
            return
        self._send_bytes(safe.read_bytes(), CONTENT_TYPES[ext])

    def _serve_media(self, path: str) -> None:
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 4 or parts[0] != "actors":
            self._respond(404, {"error": "not found"})
            return
        slug = sanitize_slug(parts[1])
        category = parts[2]
        filename = sanitize_filename(parts[3])
        ext = Path(filename).suffix.lower()
        if not slug or category not in SERVABLE_CATEGORIES or not filename or ext not in CONTENT_TYPES:
            self._respond(404, {"error": "not found"})
            return
        candidate = ACTORS_DIR / slug / category / filename
        safe = self._resolved_under(ACTORS_DIR, candidate)
        if safe is None or not safe.is_file():
            self._respond(404, {"error": "not found"})
            return
        self._send_bytes(safe.read_bytes(), CONTENT_TYPES[ext])

    @staticmethod
    def _is_package_path(path: str) -> bool:
        parts = path.strip("/").split("/")
        return len(parts) in (5, 6) and parts[0] == "actors" and parts[2] == "animations"

    def _serve_package(self, path: str) -> None:
        """Frame-package files: ``.../animations/<anim>/manifest.json`` and ``.../frames/<file>.png``.

        Kept apart from _serve_media so JSON is only ever served from inside a
        package and the four-part media route stays exactly as strict as it was.
        """
        parts = [unquote(p) for p in path.strip("/").split("/")]
        slug = sanitize_slug(parts[1])
        anim = sanitize_filename(parts[3])
        if not slug or not anim:
            self._respond(404, {"error": "not found"})
            return
        package = ACTORS_DIR / slug / "animations" / anim
        if len(parts) == 5:
            if parts[4] != animmeta.MANIFEST_NAME:
                self._respond(404, {"error": "not found"})
                return
            candidate, content_type = animmeta.manifest_path(package), "application/json"
        else:
            filename = sanitize_filename(parts[5])
            if parts[4] != animmeta.FRAMES_DIR or not filename or Path(filename).suffix.lower() != ".png":
                self._respond(404, {"error": "not found"})
                return
            candidate, content_type = package / animmeta.FRAMES_DIR / filename, "image/png"
        safe = self._resolved_under(ACTORS_DIR, candidate)
        if safe is None or not safe.is_file() or not animmeta.is_package(package):
            self._respond(404, {"error": "not found"})
            return
        self._send_bytes(safe.read_bytes(), content_type)

    @staticmethod
    def _resolved_under(root: Path, candidate: Path) -> Path | None:
        """Resolve `candidate` and return it only if it stays under `root`."""
        try:
            resolved = media.resolve_within(root, candidate)
        except media.Rejected:
            return None
        if resolved.is_symlink():
            return None
        return resolved

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
        # Build the archive in a temporary file and stream it, rather than
        # holding the whole ZIP in memory.
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in sorted(actor_dir.rglob("*")):
                    if file_path.is_file():
                        zf.write(file_path, arcname=f"{slug}/{file_path.relative_to(actor_dir)}")
            tmp.close()
            size = os.path.getsize(tmp.name)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", f'attachment; filename="{slug}-export.zip"')
            self._security_headers()
            self.end_headers()
            with open(tmp.name, "rb") as fh:
                while chunk := fh.read(1024 * 1024):
                    self.wfile.write(chunk)
        finally:
            os.unlink(tmp.name)

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
        if self._reject_bad_host() or self._reject_unguarded_mutation():
            return
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
        if length > MAX_UPLOAD_BYTES:
            self._respond(413, {"error": "file too large"})
            return
        data = self.rfile.read(length)
        if len(data) > MAX_UPLOAD_BYTES:
            self._respond(413, {"error": "file too large"})
            return

        target_dir = ACTORS_DIR / slug / category
        target_dir.mkdir(parents=True, exist_ok=True)

        # Validate a rejected-upload-safe copy first, then reserve a name and
        # commit atomically -- all under the actor lock so name reservation and
        # provenance can't race a concurrent upload/rename.
        fd, tmp_name = tempfile.mkstemp(dir=target_dir, prefix=storage.TMP_PREFIX, suffix=ext)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            try:
                self._validate_upload(tmp_path, ext)
            except (media.Rejected, ValueError) as exc:
                logs.event("upload", actor=slug, operation="upload", outcome="rejected", error=str(exc))
                # Remove the rejected temp file *before* answering, so a client
                # that lists the directory the moment it sees the 400 never
                # observes the leftover (the finally is only a crash backstop).
                tmp_path.unlink(missing_ok=True)
                self._respond(400, {"error": f"rejected: {exc}"})
                return
            with storage.actor_lock(slug):
                target_path = unique_path(target_dir, filename)
                os.replace(tmp_path, target_path)
                provenance.record_uploaded(ACTORS_DIR / slug, f"{category}/{target_path.name}")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        actor_count = build.build()
        logs.event("upload", actor=slug, operation="upload", outcome="ok", filename=target_path.name)
        self._respond(
            200,
            {"slug": slug, "category": category, "filename": target_path.name, "actors": actor_count},
        )

    @staticmethod
    def _validate_upload(path: Path, ext: str) -> None:
        """Raise media.Rejected / ValueError unless the bytes match the extension."""
        if ext in (".png", ".gif"):
            media.validate(path)
            return
        data = path.read_bytes()
        if ext in (".wav", ".mp3"):
            media.inspect_audio(data)
            return
        sniff = _SNIFF.get(ext)
        if sniff is None or not sniff(data):
            raise media.Rejected(f"content does not match a {ext} file")

    # -- DELETE -----------------------------------------------------------

    def do_DELETE(self):
        if self._reject_bad_host() or self._reject_unguarded_mutation():
            return
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

        actor_dir = ACTORS_DIR / slug
        category = CATEGORY_BY_EXT.get(Path(filename).suffix.lower())
        if category is None:
            if animmeta.is_package(actor_dir / "animations" / filename):
                self._delete_package(slug, filename)
                return
            self._respond(400, {"error": "unsupported extension"})
            return

        target = actor_dir / category / filename
        if not target.is_file():
            self._respond(404, {"error": "no such asset"})
            return

        # Delete the file, its links, its spritesheet, and its provenance as one
        # locked transaction so a reader never sees a half-removed asset.
        with storage.actor_lock(slug):
            target.unlink()
            provenance.remove_asset(actor_dir, f"{category}/{filename}")
            if category == "animations":
                remove_animation(ACTORS_DIR, slug, filename)
                sheet = sheet_for(actor_dir, filename)
                if sheet is not None:
                    sheet.unlink()
                    provenance.remove_asset(actor_dir, f"sheets/{sheet.name}")
            elif category == "sounds":
                remove_sound(ACTORS_DIR, slug, filename)

        actor_count = build.build()
        logs.event("delete", actor=slug, operation="delete", outcome="ok", filename=filename)
        self._respond(200, {"deleted": filename, "actors": actor_count})

    def _delete_package(self, slug: str, name: str) -> None:
        actor_dir = ACTORS_DIR / slug
        with storage.actor_lock(slug):
            shutil.rmtree(actor_dir / "animations" / name)
            provenance.remove_asset(actor_dir, f"animations/{name}")
            remove_animation(ACTORS_DIR, slug, name)
            sheet = sheet_for(actor_dir, name)
            if sheet is not None:
                sheet.unlink()
                provenance.remove_asset(actor_dir, f"sheets/{sheet.name}")
        actor_count = build.build()
        logs.event("delete", actor=slug, operation="delete", outcome="ok", filename=name)
        self._respond(200, {"deleted": name, "actors": actor_count})

    # -- POST -------------------------------------------------------------

    def do_POST(self):
        if self._reject_bad_host() or self._reject_unguarded_mutation():
            return
        path = urlsplit(self.path).path
        if path == "/link":
            self._handle_link()
        elif path == "/unlink":
            self._handle_unlink()
        elif path == "/trim":
            self._handle_trim()
        elif path == "/rename":
            self._handle_rename()
        elif path == "/timing":
            self._guard(self._handle_timing)
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
            slug = sanitize_slug(str(payload["slug"]))
            animation = sanitize_filename(str(payload["animation"]))
            sound = sanitize_filename(str(payload["sound"]))
        except (ValueError, KeyError, TypeError):
            self._respond(400, {"error": "expected JSON {slug, animation, sound}"})
            return
        if not slug or not animation or not sound:
            self._respond(400, {"error": "invalid slug or filename"})
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
        if link_to and _animation_exists(actor_dir, link_to):
            add_link(ACTORS_DIR, slug, link_to, target.name)
            linked = True
        self._respond(
            200, {"filename": target.name, "duration_ms": duration, "linked": linked, "actors": build.build()}
        )

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

        actor_dir = ACTORS_DIR / slug
        if animmeta.is_package(actor_dir / "animations" / old_name):
            self._rename_package(slug, old_name, new_name)
            return
        category = CATEGORY_BY_EXT.get(Path(old_name).suffix.lower())
        new_category = CATEGORY_BY_EXT.get(Path(new_name).suffix.lower())
        if category is None or new_category != category:
            self._respond(400, {"error": "rename must keep the same file type"})
            return

        old_path = actor_dir / category / old_name
        new_path = actor_dir / category / new_name
        if not old_path.is_file():
            self._respond(404, {"error": "no such asset"})
            return
        if new_path.exists():
            self._respond(409, {"error": f"{new_name} already exists"})
            return
        # File, links, spritesheet, and provenance move together under the lock.
        with storage.actor_lock(slug):
            old_path.rename(new_path)
            provenance.rename_asset(actor_dir, f"{category}/{old_name}", f"{category}/{new_name}")
            if category == "animations":
                rename_animation(ACTORS_DIR, slug, old_name, new_name)
                _rename_sheet(actor_dir, old_name, new_name)
            elif category == "sounds":
                rename_sound(ACTORS_DIR, slug, old_name, new_name)

        logs.event("rename", actor=slug, operation="rename", outcome="ok", filename=new_name)
        self._respond(200, {"filename": new_name, "actors": build.build()})

    def _rename_package(self, slug: str, old_name: str, new_name: str) -> None:
        actor_dir = ACTORS_DIR / slug
        new_name = new_name.replace(".", "-")  # a package is a directory, never "x.gif"
        old_path = actor_dir / "animations" / old_name
        new_path = actor_dir / "animations" / new_name
        if new_path.exists():
            self._respond(409, {"error": f"{new_name} already exists"})
            return
        with storage.actor_lock(slug):
            old_path.rename(new_path)
            manifest = animmeta.load_manifest(new_path)
            manifest.name = new_name
            animmeta.save_manifest(new_path, manifest)
            provenance.rename_asset(actor_dir, f"animations/{old_name}", f"animations/{new_name}")
            rename_animation(ACTORS_DIR, slug, old_name, new_name)
            _rename_sheet(actor_dir, old_name, new_name)
        logs.event("rename", actor=slug, operation="rename", outcome="ok", filename=new_name)
        self._respond(200, {"filename": new_name, "actors": build.build()})

    def _handle_timing(self) -> None:
        """Persist edited per-frame delays (and loop) into a package manifest."""
        payload = self._read_json()
        slug = sanitize_slug(str(payload.get("slug", "")))
        name = sanitize_filename(str(payload.get("animation", "")))
        if not slug or not name:
            raise ValueError("invalid slug or animation")
        package = ACTORS_DIR / slug / "animations" / name
        if not animmeta.is_package(package):
            raise generate.GenerateError(404, "no such animation package")
        with storage.actor_lock(slug):
            manifest = animmeta.load_manifest(package)
            delays = animmeta.validate_delays(payload.get("delays"), len(manifest.frames))
            for frame, delay in zip(manifest.frames, delays):
                frame.delay_ms = delay
            if "loop" in payload:
                manifest.loop = bool(payload["loop"])
            manifest.source["timing_source"] = "edited"
            animmeta.save_manifest(package, manifest)
        logs.event("timing", actor=slug, operation="timing", outcome="ok", filename=name)
        self._respond(200, {"animation": name, "total_ms": manifest.total_ms(), "actors": build.build()})

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

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)

    def _send_bytes(self, data: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def serve(paths, port: int = 8000, *, allow_spend: bool = False, env_file: Path | None = None) -> None:
    """Configure paths and providers, build the site, and serve on loopback."""
    configure_paths(paths)
    build.configure_paths(paths)
    generate.configure_paths(paths)
    logs.configure_logging(paths)
    generate.configure(allow_spend=allow_spend, env_file=env_file)

    # Sweep temp files a previous crash left mid-write, and report the recovery.
    stale = storage.clean_stale_temp(paths.actors) + storage.clean_stale_temp(paths.site)
    if stale:
        print(f"recovered: removed {len(stale)} stale temp file(s)", flush=True)
        logs.event("startup", operation="recover", outcome="ok", removed=len(stale))

    status = generate.provider_status()["providers"]
    if allow_spend:
        live = [name for name, s in status.items() if s["live"]]
        missing = [name for name, s in status.items() if not s["configured"]]
        print(
            f"SPEND ENABLED - live providers: {', '.join(live) or 'none'}"
            + (f" (no key: {', '.join(missing)})" if missing else ""),
            flush=True,
        )
    else:
        print("offline - fake providers (start with --allow-spend to use the real APIs)", flush=True)

    build.build()
    configure_security(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving emberforge-lite on http://127.0.0.1:{port}/  (data: {paths.data_dir})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
