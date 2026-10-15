"""The web UI's remembered choices, kept in ``~/.local/share/local-encoder/settings.json``.

Kept on disk (not only in the browser) so they survive another port, another browser or a new
version: the saved sites (address and user name, never a password), the language, the last
folder, the format, qualities and other options. Every value is checked; unknown keys are
dropped.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from local_encoder.config import APP_DATA_DIR

logger = logging.getLogger(__name__)

_SETTINGS_FILE = APP_DATA_DIR / "settings.json"
_lock = threading.Lock()

RESOLUTIONS = (240, 360, 480, 540, 720, 1080, 1440, 2160)


def _text(limit: int) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        return value[:limit] if isinstance(value, str) else None

    return check


def _choice(*options: str) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        return value if value in options else None

    return check


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _qualities(value: Any) -> list[int] | None:
    if not isinstance(value, list):
        return None
    return sorted({v for v in value if isinstance(v, int) and v in RESOLUTIONS})


def _sites(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    result: list[dict[str, Any]] = []
    for site in value[:20]:
        if not isinstance(site, dict):
            continue
        url, username = site.get("url"), site.get("username")
        if not isinstance(url, str) or not isinstance(username, str) or not url:
            continue
        result.append(
            {
                "url": url[:500],
                "username": username[:200],
                "sslVerify": site.get("sslVerify") is not False,
            }
        )
    return result


def _folders(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [v[:1000] for v in value if isinstance(v, str) and v][:8]


def _categories(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {
        str(k)[:800]: str(v)[:20]
        for k, v in list(value.items())[:50]
        if isinstance(v, (str, int)) and not isinstance(v, bool)
    }


# key → (validator, default)
SCHEMA: dict[str, tuple[Callable[[Any], Any], Any]] = {
    "lang": (_choice("en", "pt", "es"), None),
    "sites": (_sites, []),
    "active_site": (_text(800), ""),
    "add_tab": (_choice("link", "files", "folder"), "link"),
    "format": (_choice("auto", "hls", "mp4"), "auto"),
    "qualities": (_qualities, []),
    "use_gpu": (_flag, True),
    "show_advanced": (_flag, False),
    "category_by_site": (_categories, {}),
    "folder": (_text(1000), ""),
    "recent_folders": (_folders, []),
    "folder_recursive": (_flag, False),
    "hide_sent": (_flag, False),
}


def _clean(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    result: dict[str, Any] = {}
    for key, (check, _default) in SCHEMA.items():
        if key in data:
            value = check(data[key])
            if value is not None:
                result[key] = value
    return result


def load() -> dict[str, Any]:
    """Every setting, with defaults for the ones never saved."""
    stored: dict[str, Any] = {}
    try:
        stored = _clean(json.loads(_SETTINGS_FILE.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        logger.warning("Could not read the settings (%s); using defaults", exc)
    result = {key: default for key, (_check, default) in SCHEMA.items()}
    result.update(stored)
    result["saved"] = _SETTINGS_FILE.exists()
    return result


def save(changes: Any) -> dict[str, Any]:
    """Merge the valid *changes* into the stored settings and return them all."""
    with _lock:
        current = load()
        current.pop("saved", None)
        current.update(_clean(changes))
        path: Path = _SETTINGS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # never leave a half-written file
        current["saved"] = True
        return current
