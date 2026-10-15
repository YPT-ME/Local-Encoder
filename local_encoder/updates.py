"""Check GitHub Releases for a newer Local Encoder version.

Releases are published by ``.github/workflows/release.yml`` (also automatically whenever
yt-dlp releases a new version), so users of the packaged app need a nudge to update.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass

import httpx

from local_encoder import __version__

logger = logging.getLogger(__name__)

REPOSITORY = "YPT-ME/Local-Encoder"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
DOWNLOAD_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"


@dataclass
class UpdateInfo:
    current: str
    latest: str
    update_available: bool
    download_url: str = DOWNLOAD_PAGE


def is_frozen() -> bool:
    """True when running from the PyInstaller executable (not from source)."""
    return bool(getattr(sys, "frozen", False))


def parse_version(value: str) -> tuple[int, ...]:
    """``"v1.2.10"`` → ``(1, 2, 10)``; anything that is not a number is ignored."""
    return tuple(int(part) for part in re.findall(r"\d+", value.split("+")[0])[:3])


def check_for_update(current: str = __version__, timeout: float = 5.0) -> UpdateInfo | None:
    """Return the latest published version, or ``None`` when GitHub cannot be reached."""
    try:
        resp = httpx.get(
            LATEST_RELEASE_API,
            timeout=timeout,
            follow_redirects=True,
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        latest = str(resp.json().get("tag_name", "")).lstrip("v")
    except Exception as exc:
        logger.info("Update check skipped: %s", exc)
        return None
    if not latest:
        return None
    return UpdateInfo(
        current=current,
        latest=latest,
        update_available=parse_version(latest) > parse_version(current),
    )
