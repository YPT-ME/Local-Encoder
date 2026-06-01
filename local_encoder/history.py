"""Persistent history of import jobs.

Stored in ``~/.local-encoder/history.json`` as a JSON array so it survives
across invocations and is human-readable.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

_HISTORY_DIR = Path.home() / ".local-encoder"
_HISTORY_FILE = _HISTORY_DIR / "history.json"

JobStatus = Literal["pending", "success", "failed"]


@dataclass
class HistoryEntry:
    id: str
    timestamp: str  # ISO-8601 UTC
    url: str
    server: str
    username: str
    title: str
    status: JobStatus
    videos_id: int | None = None
    error: str | None = None

    @property
    def dt(self) -> datetime:
        return datetime.fromisoformat(self.timestamp)

    def display_time(self) -> str:
        return self.dt.astimezone().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Low-level persistence
# ---------------------------------------------------------------------------


def _load_raw() -> list[dict[str, object]]:
    if not _HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_raw(entries: list[dict[str, object]]) -> None:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def new_entry(url: str, server: str, username: str) -> HistoryEntry:
    """Create and persist a *pending* entry. Returns it so callers can update it."""
    entry = HistoryEntry(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(tz=UTC).isoformat(),
        url=url,
        server=server.rstrip("/"),
        username=username,
        title=url,  # will be updated once yt-dlp resolves the title
        status="pending",
    )
    raw = _load_raw()
    raw.append(asdict(entry))
    _save_raw(raw)
    return entry


def update_entry(entry: HistoryEntry) -> None:
    """Persist changes to an existing entry (matched by id)."""
    raw = _load_raw()
    for i, item in enumerate(raw):
        if item.get("id") == entry.id:
            raw[i] = asdict(entry)
            break
    else:
        raw.append(asdict(entry))
    _save_raw(raw)


def list_entries(
    server: str | None = None,
    username: str | None = None,
) -> list[HistoryEntry]:
    """Return entries sorted newest-first, optionally filtered."""
    raw = _load_raw()
    entries: list[HistoryEntry] = []
    for item in raw:
        try:
            e = HistoryEntry(**{k: item.get(k) for k in HistoryEntry.__dataclass_fields__})  # type: ignore[arg-type]
            entries.append(e)
        except TypeError:
            continue
    if server:
        needle = server.rstrip("/")
        entries = [e for e in entries if e.server == needle]
    if username:
        entries = [e for e in entries if e.username == username]
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries
