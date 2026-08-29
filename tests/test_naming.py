"""Characterize slug and filename sanitization (naming.py)."""

from __future__ import annotations

from naming import asset_stem, sanitize_filename, sanitize_slug, unique_path


class TestSanitizeSlug:
    def test_lowercases_and_hyphenates(self):
        assert sanitize_slug("Briar Knight") == "briar-knight"

    def test_collapses_runs_of_illegal_chars(self):
        assert sanitize_slug("a  b__c!!d") == "a-b__c-d"

    def test_strips_leading_and_trailing_hyphens(self):
        assert sanitize_slug("--Evil Treant--") == "evil-treant"

    def test_keeps_allowed_chars(self):
        assert sanitize_slug("grave_scribe-01") == "grave_scribe-01"

    def test_empty_after_stripping(self):
        assert sanitize_slug("!!!") == ""

    def test_unicode_becomes_hyphen(self):
        assert sanitize_slug("café") == "caf"


class TestSanitizeFilename:
    def test_strips_directory_components(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_keeps_dots_and_extension(self):
        assert sanitize_filename("Attack Sheet.png") == "Attack-Sheet.png"

    def test_strips_leading_trailing_dots_and_dashes(self):
        assert sanitize_filename("-.hidden.-") == "hidden"

    def test_preserves_case(self):
        assert sanitize_filename("MixedCase.GIF") == "MixedCase.GIF"

    def test_traversal_windows_style(self):
        # Path().name on posix keeps backslashes; documents current behavior.
        result = sanitize_filename("..\\..\\secret.png")
        assert "/" not in result and "\\" not in result


class TestAssetStem:
    def test_lowercases_underscores_no_ext(self):
        assert asset_stem("Lunge Attack.gif") == "lunge_attack"

    def test_hyphens_become_underscores(self):
        assert asset_stem("fire-breath") == "fire_breath"

    def test_strips_wrapping_separators(self):
        assert asset_stem("__idle__") == "idle"


class TestUniquePath:
    def test_returns_original_when_free(self, tmp_path):
        p = unique_path(tmp_path, "a.png")
        assert p == tmp_path / "a.png"

    def test_appends_counter_on_collision(self, tmp_path):
        (tmp_path / "a.png").write_bytes(b"x")
        p = unique_path(tmp_path, "a.png")
        assert p == tmp_path / "a-2.png"

    def test_counter_increments_past_existing(self, tmp_path):
        (tmp_path / "a.png").write_bytes(b"x")
        (tmp_path / "a-2.png").write_bytes(b"x")
        p = unique_path(tmp_path, "a.png")
        assert p == tmp_path / "a-3.png"
