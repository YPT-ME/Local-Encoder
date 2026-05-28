"""Unit tests for config loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from avideo_local_encoder.config import Config, load_config


def test_default_config():
    cfg = Config()
    assert cfg.server_url == ""
    assert cfg.ssl_verify is True
    assert cfg.keep_files is False
    assert cfg.categories_id == 0


def test_normalize_server_url_adds_trailing_slash():
    cfg = Config(server_url="https://example.com")
    cfg.normalize_server_url()
    assert cfg.server_url.endswith("/")


def test_normalize_server_url_idempotent():
    cfg = Config(server_url="https://example.com/")
    cfg.normalize_server_url()
    assert cfg.server_url == "https://example.com/"


def test_validate_raises_on_missing_url():
    cfg = Config(username="u", password="p")
    with pytest.raises(ValueError, match="AVIDEO_SERVER_URL"):
        cfg.validate()


def test_validate_raises_on_missing_username():
    cfg = Config(server_url="https://example.com/", password="p")
    with pytest.raises(ValueError, match="AVIDEO_USERNAME"):
        cfg.validate()


def test_validate_raises_on_missing_password():
    cfg = Config(server_url="https://example.com/", username="u")
    with pytest.raises(ValueError, match="AVIDEO_PASSWORD"):
        cfg.validate()


def test_validate_passes_with_all_required(monkeypatch):
    cfg = Config(server_url="https://example.com/", username="u", password="p")
    cfg.validate()  # should not raise


def test_load_config_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AVIDEO_SERVER_URL", "https://mysite.test")
    monkeypatch.setenv("AVIDEO_USERNAME", "testuser")
    monkeypatch.setenv("AVIDEO_PASSWORD", "testpass")
    monkeypatch.setenv("AVIDEO_CATEGORIES_ID", "5")
    monkeypatch.setenv("AVIDEO_KEEP_FILES", "true")
    monkeypatch.setenv("AVIDEO_SSL_VERIFY", "false")

    cfg = load_config()

    assert cfg.server_url == "https://mysite.test/"  # trailing slash added
    assert cfg.username == "testuser"
    assert cfg.password == "testpass"
    assert cfg.categories_id == 5
    assert cfg.keep_files is True
    assert cfg.ssl_verify is False


def test_load_config_from_dotenv_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AVIDEO_SERVER_URL=https://from-file.test\n"
        "AVIDEO_USERNAME=fileuser\n"
        "AVIDEO_PASSWORD=filepass\n"
    )
    cfg = load_config(env_file)
    assert "from-file.test" in cfg.server_url
    assert cfg.username == "fileuser"
