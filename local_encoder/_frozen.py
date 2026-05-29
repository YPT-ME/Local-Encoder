"""Utilities for running inside a PyInstaller frozen executable.

When the app is packaged with PyInstaller, ``sys.frozen`` is set to True and
``sys._MEIPASS`` points to the temp directory where bundled files are extracted.
We use this to locate the bundled ffmpeg/ffprobe binaries automatically.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_dir() -> Path:
    """Return the directory where bundled resources live."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent.parent / "bin"


def resolve_ffmpeg() -> str:
    """Return path to bundled ffmpeg, or 'ffmpeg' if not bundled."""
    suffix = ".exe" if sys.platform == "win32" else ""
    candidate = _bundle_dir() / f"ffmpeg{suffix}"
    return str(candidate) if candidate.exists() else os.getenv("FFMPEG_BIN", "ffmpeg")


def resolve_ffprobe() -> str:
    """Return path to bundled ffprobe, or 'ffprobe' if not bundled."""
    suffix = ".exe" if sys.platform == "win32" else ""
    candidate = _bundle_dir() / f"ffprobe{suffix}"
    return str(candidate) if candidate.exists() else os.getenv("FFPROBE_BIN", "ffprobe")
