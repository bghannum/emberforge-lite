"""Public-showcase invariants (Milestone 5): demo assets, no private refs, skill."""

from __future__ import annotations

from pathlib import Path

import pytest

from emberforge_lite import media, provenance
from emberforge_lite.demo import DEMO_ASSETS, DEMO_SLUG, _install_demo_actor

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "src" / "emberforge_lite"


class TestPackagedDemoActor:
    def test_assets_present_and_valid(self):
        actor = DEMO_ASSETS / DEMO_SLUG
        assert actor.is_dir()
        media.validate(actor / "sprites" / "ember_familiar_source.png")
        media.validate(actor / "animations" / "ember_familiar_idle_preview.gif")
        media.inspect_audio((actor / "sounds" / "ember_familiar_chime.wav").read_bytes())
        assert (actor / "links.json").is_file()
        assert (actor / "generations.jsonl").is_file()
        assert (actor / "provenance.json").is_file()

    def test_install_copies_packaged_assets(self, tmp_path):
        actors = tmp_path / "actors"
        actors.mkdir()
        _install_demo_actor(actors)
        actor = actors / DEMO_SLUG
        assert actor.is_dir()
        entry = provenance.entry_for(actor, "sprites/ember_familiar_source.png")
        assert entry["source"] == "generated"


class TestNoPrivateReferences:
    @pytest.mark.parametrize("token", ["AGENTS.md", "PROJECT_SCOPE", "../emberforge"])
    def test_token_absent_from_package(self, token):
        for path in PKG.rglob("*.py"):
            assert token not in path.read_text(), f"{token} still in {path}"

    def test_readme_has_no_parent_repo_link(self):
        assert "../emberforge" not in (REPO / "README.md").read_text()


class TestEnvExample:
    def test_is_tracked_and_has_no_values(self):
        text = (REPO / ".env.example").read_text()
        for key in ("SPRITELAB_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"):
            assert f"{key}=\n" in text or text.rstrip().endswith(f"{key}="), key


class TestPublicFiles:
    def test_license_is_mit(self):
        assert "MIT License" in (REPO / "LICENSE").read_text()

    @pytest.mark.parametrize("name", ["SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md"])
    def test_community_file_present(self, name):
        assert (REPO / name).is_file()

    @pytest.mark.parametrize("name", [
        "architecture.md", "threat-model.md", "provenance-format.md",
        "providers.md", "releasing.md",
    ])
    def test_doc_present(self, name):
        assert (REPO / "docs" / name).is_file()


class TestCodexSkill:
    def test_skill_md_metadata(self):
        text = (REPO / "skills" / "emberforge-lite" / "SKILL.md").read_text()
        assert "name: emberforge-lite" in text
        assert "$emberforge-lite" in text
        assert "brand_color" in text
        # Offline-by-default and authorization constraints are stated.
        assert "--allow-spend" in text
        assert "without explicit authorization" in text

    def test_agent_yaml_present(self):
        assert (REPO / "skills" / "emberforge-lite" / "agents" / "openai.yaml").is_file()
