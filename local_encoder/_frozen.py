"""Utilities for running inside a PyInstaller frozen executable.

When the app is packaged with PyInstaller, ``sys.frozen`` is set to True and
``sys._MEIPASS`` points to the temp directory where bundled files are extracted.

Where the release packages put ffmpeg/ffprobe (see scripts/make_dist.py):
  * Windows / Linux: next to the executable (not embedded, so the ~300 MB of FFmpeg is not
    extracted to a temp folder on every start);
  * macOS: embedded in the executable (one Gatekeeper approval for the whole app).
When running from source, ``<project>/bin`` is used (filled by scripts/fetch_ffmpeg.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_dirs() -> list[Path]:
    """Return the directories where bundled binaries may live, in priority order."""
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
        return [app_dir, app_dir / "bin", Path(getattr(sys, "_MEIPASS", app_dir))]
    return [Path(__file__).parent.parent / "bin"]


def _resolve(name: str, env_var: str) -> str:
    suffix = ".exe" if sys.platform == "win32" else ""
    for directory in _bundle_dirs():
        candidate = directory / f"{name}{suffix}"
        if candidate.exists():
            return str(candidate)
    return os.getenv(env_var, name)


def resolve_ffmpeg() -> str:
    """Return path to bundled ffmpeg, or 'ffmpeg' if not bundled."""
    return _resolve("ffmpeg", "FFMPEG_BIN")


def resolve_ffprobe() -> str:
    """Return path to bundled ffprobe, or 'ffprobe' if not bundled."""
    return _resolve("ffprobe", "FFPROBE_BIN")
