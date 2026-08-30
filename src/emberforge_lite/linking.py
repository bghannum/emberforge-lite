"""Shared logic for linking a sound to an animation, and for keeping
links.json in sync when an animation or sound is deleted/renamed. Used by
link.py (CLI) and server.py (in-browser linking/asset management) so both
stay in sync.
"""

import json
from pathlib import Path

from emberforge_lite import animmeta, storage


def _links_file(actors_dir: Path, slug: str) -> Path:
    return actors_dir / slug / "links.json"


def _load_links(links_file: Path) -> dict[str, list[str]]:
    return json.loads(links_file.read_text()) if links_file.is_file() else {}


def _save_links(links_file: Path, links: dict[str, list[str]]) -> None:
    storage.atomic_write_text(links_file, json.dumps(links, indent=2, sort_keys=True) + "\n")


def add_link(actors_dir: Path, slug: str, anim_name: str, sound_name: str) -> None:
    actor_dir = actors_dir / slug
    anim_path = actor_dir / "animations" / anim_name
    sound_path = actor_dir / "sounds" / sound_name

    if not anim_path.is_file() and not animmeta.is_package(anim_path):
        raise FileNotFoundError(f"no such animation: {anim_path}")
    if not sound_path.is_file():
        raise FileNotFoundError(f"no such sound: {sound_path}")

    links_file = _links_file(actors_dir, slug)
    links = _load_links(links_file)
    linked = links.setdefault(anim_name, [])
    if sound_name not in linked:
        linked.append(sound_name)
    _save_links(links_file, links)


def remove_link(actors_dir: Path, slug: str, anim_name: str, sound_name: str) -> bool:
    """Unlink one sound from one animation. The files are untouched."""
    links_file = _links_file(actors_dir, slug)
    links = _load_links(links_file)
    linked = links.get(anim_name, [])
    if sound_name not in linked:
        return False
    linked.remove(sound_name)
    if not linked:
        del links[anim_name]
    _save_links(links_file, links)
    return True


def remove_animation(actors_dir: Path, slug: str, anim_name: str) -> None:
    links_file = _links_file(actors_dir, slug)
    links = _load_links(links_file)
    if links.pop(anim_name, None) is not None:
        _save_links(links_file, links)


def remove_sound(actors_dir: Path, slug: str, sound_name: str) -> None:
    links_file = _links_file(actors_dir, slug)
    links = _load_links(links_file)
    changed = False
    for anim_name in list(links):
        if sound_name in links[anim_name]:
            links[anim_name].remove(sound_name)
            changed = True
            if not links[anim_name]:
                del links[anim_name]
    if changed:
        _save_links(links_file, links)


def rename_animation(actors_dir: Path, slug: str, old_name: str, new_name: str) -> None:
    links_file = _links_file(actors_dir, slug)
    links = _load_links(links_file)
    if old_name in links:
        links[new_name] = links.pop(old_name)
        _save_links(links_file, links)


def rename_sound(actors_dir: Path, slug: str, old_name: str, new_name: str) -> None:
    links_file = _links_file(actors_dir, slug)
    links = _load_links(links_file)
    changed = False
    for sounds in links.values():
        for i, name in enumerate(sounds):
            if name == old_name:
                sounds[i] = new_name
                changed = True
    if changed:
        _save_links(links_file, links)
