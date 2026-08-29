"""Shared fixtures for the characterization suite.

These tests pin the *current* behavior of Emberforge Lite before it is
restructured, so the packaging and refactoring milestones cannot change it
by accident. Deterministic media bytes come from the fake providers' own
generators, which are the same bytes the offline path produces in practice.
"""

from __future__ import annotations

import pytest

# Media generators reused from the fakes so fixtures match real offline output.
# The package is installed (editable) via `pip install -e .[dev]`.
from emberforge_lite.providers.fakes import (
    FAKE_PREVIEW_GIF,
    _png,
    _source_sheet,
    _tiny_gif,
    _wav,
)


@pytest.fixture
def png_bytes() -> bytes:
    """A small, valid, still RGBA PNG (64x64)."""
    return _png(64, 64, b"fixture-png")


@pytest.fixture
def wide_sheet_png() -> bytes:
    """A horizontal spritesheet PNG (256x64)."""
    return _png(256, 64, b"fixture-sheet")


@pytest.fixture
def source_sheet_png() -> bytes:
    """A multi-view source sheet with a transparent gutter."""
    return _source_sheet(b"fixture-source")


@pytest.fixture
def wav_bytes() -> bytes:
    """A valid 800ms mono 44.1kHz PCM WAV."""
    return _wav(800, b"fixture-wav")


@pytest.fixture
def gif_bytes() -> bytes:
    """A valid two-frame GIF89a with 6cs/8cs delays."""
    return FAKE_PREVIEW_GIF


@pytest.fixture
def slow_gif_bytes() -> bytes:
    """A GIF89a whose frames each declare a 50cs delay."""
    return _tiny_gif((50, 50, 50, 50))
