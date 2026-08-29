"""Generate assets through the provider APIs, landing them in `actors/<slug>/`.

Three kinds of work:
    animation  SpriteLab /animate  -- async: submit, poll, collect
    sound      ElevenLabs          -- sync
    source     SpriteLab /generate or OpenAI Images -- sync

Live adapters exist only when the server was started with --allow-spend *and*
the provider's key is configured; otherwise the fakes stand in and the whole
flow -- estimate, confirm, submit, poll, write, ledger -- runs offline and
deterministically. `select_providers` is the one place that choice is made.

Every submission is recorded in `actors/<slug>/generations.jsonl`, append-only,
one line per event, before and after the provider is called. That file is the
audit trail for spend and the resume point for an animation job whose poll was
interrupted.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import build
import credentials
import gifspeed
import media
import pngtools
from linking import add_link
from naming import asset_stem, sanitize_filename, sanitize_slug, unique_path
from providers.base import (
    AmbiguousOutcome,
    AuthenticationFailed,
    GenerationRequest,
    ProviderError,
    ProviderRejected,
    RateLimited,
)
from providers.transport import redact

ROOT = Path(__file__).parent
ACTORS_DIR = ROOT / "actors"
LEDGER_NAME = "generations.jsonl"

DEFAULT_FRAMES = 16
MAX_FRAMES = 64
DEFAULT_SOUND_MS = 800
MIN_SOUND_MS = 500
MAX_SOUND_MS = 30_000

#: How a request names a source provider -> the PROVIDERS key it maps to.
SOURCE_PROVIDERS = {
    "spritelab_epic": "spritelab_source_epic",
    "spritelab_mythic": "spritelab_source_mythic",
    "openai": "openai",
}

#: Seconds within which a second animation submit for the same actor is
#: treated as a double-click rather than a decision.
RESUBMIT_GUARD_SECONDS = 10

PROVIDERS: dict[str, Any] = {}
LIVE = False

_ledger_lock = threading.Lock()
_job_locks: dict[tuple[str, str], threading.Lock] = {}
_job_locks_guard = threading.Lock()
_fit_cache: dict[tuple[str, float], tuple[bytes, dict[str, Any]]] = {}


class GenerateError(Exception):
    """A refusal or failure with an HTTP status and a JSON-safe payload."""

    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.payload = {"error": message, **extra}


# -- Provider selection ------------------------------------------------------


def select_providers(allow_spend: bool) -> dict[str, Any]:
    """Fakes when spend is not allowed; otherwise live, for configured keys only."""
    if not allow_spend:
        from providers.fakes import (
            FakeElevenLabs,
            FakeOpenAIImages,
            FakeSpriteLab,
            FakeSpriteLabSource,
        )

        return {
            "spritelab_animate": FakeSpriteLab(),
            "spritelab_source_epic": FakeSpriteLabSource(),
            "spritelab_source_mythic": FakeSpriteLabSource(per_call=Decimal(6)),
            "openai": FakeOpenAIImages(),
            "elevenlabs": FakeElevenLabs(),
        }

    credentials.load_env_file()
    have = credentials.configured()
    chosen: dict[str, Any] = {}
    if have["spritelab"]:
        from providers.spritelab import SpriteLab, SpriteLabSource

        chosen["spritelab_animate"] = SpriteLab()
        chosen["spritelab_source_epic"] = SpriteLabSource(quality="epic")
        chosen["spritelab_source_mythic"] = SpriteLabSource(quality="mythic")
    if have["openai"]:
        from providers.openai_images import OpenAIImages

        chosen["openai"] = OpenAIImages()
    if have["elevenlabs"]:
        from providers.elevenlabs import ElevenLabs

        chosen["elevenlabs"] = ElevenLabs()
    return chosen


def configure(allow_spend: bool) -> None:
    global PROVIDERS, LIVE
    LIVE = allow_spend
    PROVIDERS = select_providers(allow_spend)


def provider_status() -> dict[str, Any]:
    have = credentials.configured() if LIVE else {"spritelab": True, "openai": True, "elevenlabs": True}
    return {
        "allow_spend": LIVE,
        "providers": {
            "spritelab": {"configured": have["spritelab"], "live": LIVE and "spritelab_animate" in PROVIDERS},
            "openai": {"configured": have["openai"], "live": LIVE and "openai" in PROVIDERS},
            "elevenlabs": {"configured": have["elevenlabs"], "live": LIVE and "elevenlabs" in PROVIDERS},
        },
    }


def _provider(key: str) -> Any:
    provider = PROVIDERS.get(key)
    if provider is None:
        raise GenerateError(403, f"provider {key} is not available (no key configured)")
    return provider


# -- Requests ----------------------------------------------------------------


@dataclass
class Prepared:
    kind: str
    provider_key: str
    provider: Any
    request: GenerationRequest
    settings: dict[str, Any]
    slug: str


def _actor_dir(slug: str) -> Path:
    clean = sanitize_slug(slug)
    if not clean:
        raise GenerateError(400, "invalid actor slug")
    return ACTORS_DIR / clean


def _prompt(params: dict[str, Any]) -> str:
    prompt = str(params.get("prompt", "")).strip()
    if not prompt:
        raise GenerateError(400, "a prompt is required")
    return prompt


def _int(params: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    raw = params.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise GenerateError(400, f"{key} must be a whole number") from None
    if not lo <= value <= hi:
        raise GenerateError(400, f"{key} must be between {lo} and {hi}")
    return value


def fitted_source(actor_dir: Path, sprite: str) -> tuple[bytes, dict[str, Any]]:
    """The sprite as it will be submitted, cached on (path, mtime)."""
    name = sanitize_filename(sprite)
    path = actor_dir / "sprites" / name
    if not name or not path.is_file():
        raise GenerateError(404, f"no such sprite: {sprite}")
    key = (str(path), path.stat().st_mtime)
    hit = _fit_cache.get(key)
    if hit is not None:
        return hit
    try:
        result = pngtools.fit_png(path.read_bytes())
    except (pngtools.PngUnsupported, media.Rejected) as exc:
        raise GenerateError(400, f"{name}: {exc}") from None
    _fit_cache[key] = result
    return result


def prepare(slug: str, kind: str, params: dict[str, Any]) -> Prepared:
    """Validate params and build the provider request. Never calls the network."""
    actor_dir = _actor_dir(slug)
    clean_slug = actor_dir.name
    prompt = _prompt(params)

    if kind == "animation":
        sprite = str(params.get("sprite", ""))
        action = asset_stem(str(params.get("action", "")))
        if not action:
            raise GenerateError(400, "an action name is required (e.g. lunge_attack)")
        frames = _int(params, "frames", DEFAULT_FRAMES, 1, MAX_FRAMES)
        png, plan = fitted_source(actor_dir, sprite)
        request = GenerationRequest(
            stage="animation",
            prompt=prompt,
            source_png=png,
            frames=frames,
            transforms=("nearest_fit_256_margin_16",),
        )
        settings = {
            "sprite": sanitize_filename(sprite),
            "action": action,
            "frames": frames,
            "plan": plan,
            "submitted_size": plan["canvas"],
        }
        return Prepared(kind, "spritelab_animate", _provider("spritelab_animate"), request, settings, clean_slug)

    if kind == "sound":
        duration = _int(params, "duration_ms", DEFAULT_SOUND_MS, MIN_SOUND_MS, MAX_SOUND_MS)
        name = asset_stem(str(params.get("name", ""))) or asset_stem("_".join(prompt.split()[:3]))
        link_to = sanitize_filename(str(params.get("link_to", "") or ""))
        if link_to and not (actor_dir / "animations" / link_to).is_file():
            raise GenerateError(404, f"no such animation to link: {link_to}")
        request = GenerationRequest(stage="sound", prompt=prompt, duration_ms=duration)
        settings = {"duration_ms": duration, "name": name, "link_to": link_to or None}
        return Prepared(kind, "elevenlabs", _provider("elevenlabs"), request, settings, clean_slug)

    if kind == "source":
        choice = str(params.get("provider", "spritelab_epic"))
        key = SOURCE_PROVIDERS.get(choice)
        if key is None:
            raise GenerateError(400, f"provider must be one of {sorted(SOURCE_PROVIDERS)}")
        request = GenerationRequest(stage="source", prompt=prompt)
        settings = {"provider_choice": choice}
        return Prepared(kind, key, _provider(key), request, settings, clean_slug)

    raise GenerateError(400, "kind must be animation, sound, or source")


# -- Estimates ---------------------------------------------------------------


def _amount(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


def output_name(prepared: Prepared, media_kind: str = "") -> str:
    slug_us = prepared.slug.replace("-", "_")
    s = prepared.settings
    if prepared.kind == "animation":
        return f"{slug_us}_{s['action']}_preview.gif"
    if prepared.kind == "sound":
        return f"{slug_us}_{s['name']}.{media_kind or 'mp3'}"
    short = s["provider_choice"].split("_")[0]
    return f"{slug_us}_source_{short}.png"


def estimate(slug: str, kind: str, params: dict[str, Any]) -> dict[str, Any]:
    prepared = prepare(slug, kind, params)
    provider = prepared.provider
    try:
        est = provider.estimate(prepared.request)
    except ProviderError as exc:
        raise _from_provider_error(exc) from None

    amount = _amount(est.maximum_amount)
    unit = est.unit
    display = _display(unit, amount)
    result: dict[str, Any] = {
        "kind": kind,
        "provider": prepared.provider_key,
        "unit": unit,
        "amount": amount,
        "display": display,
        "live": LIVE and not prepared.provider.__class__.__name__.startswith("Fake"),
        "output_name": output_name(prepared),
        "balance": None,
    }
    if kind == "animation":
        result["submitted_size"] = prepared.settings["submitted_size"]
        result["plan"] = prepared.settings["plan"]
    if kind == "sound" and hasattr(provider, "currency_estimate"):
        usd = provider.currency_estimate(prepared.request, included_remaining=None)
        if usd is not None:
            result["usd_if_over_allowance"] = _amount(usd.maximum_amount)
            result["display"] += f" (up to ${_amount(usd.maximum_amount)} if over the included allowance)"
    if hasattr(provider, "credits"):
        try:
            balance, tier = provider.credits()
            result["balance"] = balance
            result["tier"] = tier
            result["display"] += f" · balance {balance}"
        except (ProviderError, OSError):
            pass
    return result


def _display(unit: str, amount: str) -> str:
    if unit == "usd":
        return f"${amount}"
    label = {"spritelab_credits": "SpriteLab credits", "elevenlabs_credits": "ElevenLabs credits"}.get(unit, unit)
    return f"{amount} {label}"


# -- Ledger ------------------------------------------------------------------


def _ledger_path(slug: str) -> Path:
    return _actor_dir(slug) / LEDGER_NAME


def read_ledger(slug: str) -> list[dict[str, Any]]:
    path = _ledger_path(slug)
    if not path.is_file():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _append(slug: str, record: dict[str, Any]) -> None:
    path = _ledger_path(slug)
    with _ledger_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(prepared: Prepared, event: str, est: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "id": fields.pop("id", uuid.uuid4().hex),
        "ts": _now(),
        "event": event,
        "kind": prepared.kind,
        "provider": prepared.provider.name,
        "provider_key": prepared.provider_key,
        "live": LIVE and not prepared.provider.__class__.__name__.startswith("Fake"),
        "prompt": prepared.request.prompt,
        "settings": prepared.settings,
        "estimate": {"unit": est["unit"], "amount": est["amount"]},
        **fields,
    }


def open_jobs(slug: str) -> list[dict[str, Any]]:
    """Submitted animation jobs with no terminal line yet."""
    terminal = {r.get("job_id") for r in read_ledger(slug) if r.get("event") in ("succeeded", "failed", "ambiguous")}
    return [
        {"id": r["id"], "job_id": r["job_id"], "action": r["settings"].get("action"), "ts": r["ts"]}
        for r in read_ledger(slug)
        if r.get("event") == "submitted" and r.get("kind") == "animation" and r.get("job_id") and r["job_id"] not in terminal
    ]


def _terminal_for(slug: str, job_id: str) -> dict[str, Any] | None:
    for r in reversed(read_ledger(slug)):
        if r.get("job_id") == job_id and r.get("event") in ("succeeded", "failed", "ambiguous"):
            return r
    return None


# -- Errors ------------------------------------------------------------------


def _from_provider_error(exc: ProviderError) -> GenerateError:
    message = redact(str(exc))
    if isinstance(exc, AuthenticationFailed):
        return GenerateError(401, message)
    if isinstance(exc, RateLimited):
        return GenerateError(429, message, retry_after=exc.retry_after_seconds)
    if isinstance(exc, AmbiguousOutcome):
        return GenerateError(
            502,
            message + " This call may have been charged; check the provider balance. It was not retried.",
            ambiguous=True,
            job_id=exc.job_id,
        )
    if isinstance(exc, ProviderRejected):
        return GenerateError(400, message)
    return GenerateError(502, message)


def check_confirmation(est: dict[str, Any], confirm_amount: Any) -> None:
    if str(confirm_amount) != est["amount"]:
        raise GenerateError(409, f"estimate changed to {est['display']}; re-confirm", estimate=est)


# -- Sync generation (sound, source) ----------------------------------------


def _write(actor_dir: Path, category: str, filename: str, data: bytes) -> Path:
    target_dir = actor_dir / category
    target_dir.mkdir(parents=True, exist_ok=True)
    path = unique_path(target_dir, filename)
    path.write_bytes(data)
    return path


def run_sync(slug: str, kind: str, params: dict[str, Any], confirm_amount: Any) -> dict[str, Any]:
    if kind not in ("sound", "source"):
        raise GenerateError(400, "run_sync handles sound and source only")
    est = estimate(slug, kind, params)
    check_confirmation(est, confirm_amount)
    prepared = prepare(slug, kind, params)
    actor_dir = _actor_dir(slug)
    submitted = _record(prepared, "submitted", est, job_id=None)
    _append(slug, submitted)

    try:
        receipt = prepared.provider.submit(prepared.request)
        # Sync providers finish inside submit; poll settles the state (the fakes
        # deliberately answer "running" once so nothing assumes instant results).
        status = None
        for _ in range(5):
            status = prepared.provider.poll(receipt.job_id)
            if status.is_terminal:
                break
        if status is None or status.state != "succeeded":
            detail = redact((status.detail if status else None) or "generation did not complete")
            _append(slug, _record(prepared, "failed", est, id=submitted["id"], job_id=receipt.job_id,
                                  refunded=status.refunded if status else None, error=detail))
            raise GenerateError(502, detail)
        candidates = prepared.provider.collect(receipt.job_id)
    except ProviderError as exc:
        err = _from_provider_error(exc)
        event = "ambiguous" if isinstance(exc, AmbiguousOutcome) else "failed"
        _append(slug, _record(prepared, event, est, id=submitted["id"], job_id=getattr(exc, "job_id", None), error=err.payload["error"]))
        raise err from None

    if not candidates:
        _append(slug, _record(prepared, "failed", est, id=submitted["id"], job_id=receipt.job_id, error="provider returned no result"))
        raise GenerateError(502, "provider returned no result")
    cand = candidates[0]

    outputs: dict[str, Any] = {}
    if kind == "sound":
        path = _write(actor_dir, "sounds", output_name(prepared, cand.media_kind), cand.media)
        outputs["sound"] = path.name
        link_to = prepared.settings.get("link_to")
        if link_to:
            add_link(ACTORS_DIR, actor_dir.name, link_to, path.name)
            outputs["linked_to"] = link_to
    else:
        path = _write(actor_dir, "sprites", output_name(prepared), cand.media)
        outputs["sprite"] = path.name

    _append(
        slug,
        _record(
            prepared,
            "succeeded",
            est,
            id=submitted["id"],
            job_id=receipt.job_id,
            reported_charge=_amount(cand.reported_charge) if cand.reported_charge is not None else None,
            charge_unit=cand.charge_unit,
            refunded=cand.refunded,
            outputs=outputs,
            warnings=list(cand.warnings),
        ),
    )
    actors = build.build()
    return {
        "filename": path.name,
        "outputs": outputs,
        "reported_charge": _amount(cand.reported_charge) if cand.reported_charge is not None else None,
        "warnings": list(cand.warnings),
        "actors": actors,
    }


# -- Async generation (animation) -------------------------------------------


def submit_animation(slug: str, params: dict[str, Any], confirm_amount: Any) -> dict[str, Any]:
    est = estimate(slug, "animation", params)
    check_confirmation(est, confirm_amount)
    prepared = prepare(slug, "animation", params)

    recent = [r for r in open_jobs(slug)]
    if recent:
        last = datetime.fromisoformat(recent[-1]["ts"])
        age = (datetime.now(timezone.utc) - last).total_seconds()
        if age < RESUBMIT_GUARD_SECONDS:
            raise GenerateError(409, "an animation was submitted a moment ago; wait for it", open=recent)

    submitted = _record(prepared, "submitted", est, job_id=None)
    try:
        receipt = prepared.provider.submit(prepared.request)
    except ProviderError as exc:
        err = _from_provider_error(exc)
        event = "ambiguous" if isinstance(exc, AmbiguousOutcome) else "failed"
        _append(slug, submitted)
        _append(slug, _record(prepared, event, est, id=submitted["id"], job_id=getattr(exc, "job_id", None), error=err.payload["error"]))
        raise err from None

    submitted["job_id"] = receipt.job_id
    _append(slug, submitted)
    return {"id": submitted["id"], "job_id": receipt.job_id, "state": "queued", "output_name": est["output_name"]}


def _job_lock(slug: str, job_id: str) -> threading.Lock:
    with _job_locks_guard:
        return _job_locks.setdefault((slug, job_id), threading.Lock())


def advance_job(slug: str, job_id: str) -> dict[str, Any]:
    """Poll once; on success fetch, write, record, rebuild. Idempotent."""
    with _job_lock(slug, job_id):
        done = _terminal_for(slug, job_id)
        if done is not None:
            return {"state": done["event"], "outputs": done.get("outputs", {}), "error": done.get("error")}

        submitted = next(
            (r for r in read_ledger(slug) if r.get("job_id") == job_id and r.get("event") == "submitted"), None
        )
        if submitted is None:
            raise GenerateError(404, "unknown job")
        provider = _provider("spritelab_animate")
        actor_dir = _actor_dir(slug)

        def terminal(event: str, **fields: Any) -> dict[str, Any]:
            rec = dict(submitted, ts=_now(), event=event, **fields)
            _append(slug, rec)
            return rec

        try:
            status = provider.poll(job_id)
            if status.state in ("queued", "running"):
                return {"state": "running"}
            if status.state == "failed":
                rec = terminal("failed", refunded=status.refunded, error=redact(status.detail or "generation failed"))
                return {"state": "failed", "error": rec["error"], "refunded": status.refunded}

            candidates = provider.collect(job_id)
            gif = provider.preview_gif(job_id) if hasattr(provider, "preview_gif") else None
        except ProviderError as exc:
            err = _from_provider_error(exc)
            if isinstance(exc, (AmbiguousOutcome, ProviderRejected)):
                event = "ambiguous" if isinstance(exc, AmbiguousOutcome) else "failed"
                terminal(event, error=err.payload["error"])
            raise err from None

        action = submitted["settings"]["action"]
        slug_us = actor_dir.name.replace("-", "_")
        outputs: dict[str, Any] = {}
        if candidates:
            sheet = _write(actor_dir, "sheets", f"{slug_us}_{action}_sheet.png", candidates[0].media)
            outputs["sheet"] = sheet.name
        if gif:
            gif = gifspeed.set_fps(gif, gifspeed.NATIVE_FPS)
            path = _write(actor_dir, "animations", f"{slug_us}_{action}_preview.gif", gif)
            outputs["gif"] = path.name
        cand = candidates[0] if candidates else None
        terminal(
            "succeeded",
            outputs=outputs,
            reported_charge=_amount(cand.reported_charge) if cand and cand.reported_charge is not None else None,
            charge_unit=cand.charge_unit if cand else None,
            refunded=cand.refunded if cand else None,
            warnings=list(cand.warnings) if cand else [],
        )
        build.build()
        return {"state": "succeeded", "outputs": outputs}
