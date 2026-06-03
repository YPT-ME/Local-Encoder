"""Persistent job history stored as a JSON-lines file."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_HISTORY_FILE = Path.home() / ".local" / "share" / "local-encoder" / "history.jsonl"


@dataclass
class HistoryEntry:
    id: str
    url: str
    server: str
    username: str
    title: str = ""
    status: str = "pending"
    error: str = ""
    videos_id: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def display_time(self) -> str:
        try:
            dt = datetime.fromisoformat(self.created_at)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return self.created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "server": self.server,
            "username": self.username,
            "title": self.title,
            "status": self.status,
            "error": self.error,
            "videos_id": self.videos_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> HistoryEntry:
        return cls(
            id=d.get("id", ""),
            url=d.get("url", ""),
            server=d.get("server", ""),
            username=d.get("username", ""),
            title=d.get("title", ""),
            status=d.get("status", "pending"),
            error=d.get("error", ""),
            videos_id=d.get("videos_id"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


def _ensure_file() -> Path:
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.touch()
    return _HISTORY_FILE


def _read_all() -> list[HistoryEntry]:
    path = _ensure_file()
    entries: list[HistoryEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(HistoryEntry.from_dict(json.loads(line)))
            except Exception:
                pass
    return entries


def _write_all(entries: list[HistoryEntry]) -> None:
    path = _ensure_file()
    path.write_text(
        "\n".join(json.dumps(e.to_dict()) for e in entries) + "\n",
        encoding="utf-8",
    )


def new_entry(url: str, server: str, username: str) -> HistoryEntry:
    entry = HistoryEntry(id=str(uuid.uuid4()), url=url, server=server, username=username)
    entries = _read_all()
    entries.append(entry)
    _write_all(entries)
    return entry


def update_entry(entry: HistoryEntry) -> None:
    entry.updated_at = datetime.now(timezone.utc).isoformat()
    entries = _read_all()
    for i, e in enumerate(entries):
        if e.id == entry.id:
            entries[i] = entry
            break
    else:
        entries.append(entry)
    _write_all(entries)


def list_entries(
    server: str | None = None,
    username: str | None = None,
) -> list[HistoryEntry]:
    entries = _read_all()
    if server:
        entries = [e for e in entries if server in e.server]
    if username:
        entries = [e for e in entries if e.username == username]
    return list(reversed(entries))
