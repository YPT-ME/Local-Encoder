"""Shared utility helpers."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def sanitize_filename(name: str) -> str:
    """Remove characters unsafe for filenames and truncate to 200 chars."""
    # Replace control chars and Windows-forbidden chars
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    # Collapse runs of underscores/spaces
    name = re.sub(r"[_ ]{2,}", " ", name).strip(". ")
    return name[:200] or "video"


def generate_file_id() -> str:
    """Return a 16-character hex string for chunked-upload session IDs."""
    return os.urandom(8).hex()


def probe_duration(file_path: Path, ffprobe_bin: str = "ffprobe") -> float:
    """Return video duration in seconds via ffprobe. Returns 0.0 on failure."""
    try:
        result = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return float(result.stdout.strip() or 0)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError):
        pass
    return 0.0
