"""Tests for the remembered web UI choices."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_encoder import settings


@pytest.fixture(autouse=True)
def _settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "_SETTINGS_FILE", path)
    return path


def test_defaults_when_nothing_saved() -> None:
    data = settings.load()
    assert data["saved"] is False
    assert data["format"] == "auto"
    assert data["use_gpu"] is True
    assert data["sites"] == []


def test_save_merges_and_persists(_settings_file: Path) -> None:
    settings.save({"format": "mp4", "qualities": [720, 360]})
    settings.save({"folder": "D:\\Videos", "folder_recursive": True})

    data = settings.load()
    assert data["saved"] is True
    assert data["format"] == "mp4"
    assert data["qualities"] == [360, 720]
    assert data["folder"] == "D:\\Videos"
    assert json.loads(_settings_file.read_text(encoding="utf-8"))["folder_recursive"] is True


def test_invalid_values_and_unknown_keys_are_dropped() -> None:
    data = settings.save(
        {
            "format": "webm",  # not a choice
            "use_gpu": "yes",  # not a bool
            "qualities": [720, 999, "1080"],
            "lang": "pt",
            "password": "secret",  # never stored
        }
    )
    assert data["format"] == "auto"
    assert data["use_gpu"] is True
    assert data["qualities"] == [720]
    assert data["lang"] == "pt"
    assert "password" not in data


def test_sites_keep_only_address_user_and_tls(_settings_file: Path) -> None:
    settings.save(
        {
            "sites": [
                {
                    "url": "https://a.example/",
                    "username": "ann",
                    "sslVerify": False,
                    "sessionId": "s",
                },
                {"url": "", "username": "x"},
                "junk",
            ]
        }
    )
    assert settings.load()["sites"] == [
        {"url": "https://a.example/", "username": "ann", "sslVerify": False}
    ]
    assert "sessionId" not in _settings_file.read_text(encoding="utf-8")


def test_recent_folders_are_capped() -> None:
    data = settings.save({"recent_folders": [f"C:\\v{i}" for i in range(20)]})
    assert len(data["recent_folders"]) == 8


def test_broken_file_falls_back_to_defaults(_settings_file: Path) -> None:
    _settings_file.write_text("{not json", encoding="utf-8")
    assert settings.load()["format"] == "auto"
