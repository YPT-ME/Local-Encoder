"""Tests for what the packaged app relies on: FFmpeg lookup, work folder, port, updates."""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from local_encoder import _frozen, config, server, updates
from local_encoder.cli import _pick_port

ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# FFmpeg lookup (_frozen.py)
# ---------------------------------------------------------------------------


def test_frozen_app_finds_ffmpeg_next_to_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = ".exe" if sys.platform == "win32" else ""
    (tmp_path / f"ffmpeg{suffix}").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / f"LocalEncoder{suffix}"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)

    assert _frozen.resolve_ffmpeg() == str(tmp_path / f"ffmpeg{suffix}")


def test_frozen_app_finds_embedded_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    suffix = ".exe" if sys.platform == "win32" else ""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / f"ffprobe{suffix}").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "LocalEncoder"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    assert _frozen.resolve_ffprobe() == str(bundle / f"ffprobe{suffix}")


def test_ffmpeg_falls_back_to_env_then_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_frozen, "_bundle_dirs", lambda: [])
    monkeypatch.setenv("FFMPEG_BIN", "/opt/ffmpeg")
    assert _frozen.resolve_ffmpeg() == "/opt/ffmpeg"
    monkeypatch.delenv("FFMPEG_BIN")
    assert _frozen.resolve_ffmpeg() == "ffmpeg"


def test_deno_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_frozen, "_bundle_dirs", lambda: [])
    monkeypatch.delenv("DENO_BIN", raising=False)
    assert _frozen.resolve_deno() is None  # yt-dlp then looks for deno on PATH itself


def test_yt_dlp_gets_bundled_ffmpeg_and_deno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from local_encoder import downloader

    suffix = ".exe" if sys.platform == "win32" else ""
    for tool in ("ffmpeg", "deno"):
        (tmp_path / f"{tool}{suffix}").write_bytes(b"")
    monkeypatch.setattr(_frozen, "_bundle_dirs", lambda: [tmp_path])
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.delenv("DENO_BIN", raising=False)

    opts = downloader._external_tools()

    # Not on PATH in the packaged app: yt-dlp must be told where they are.
    assert opts["ffmpeg_location"] == str(tmp_path / f"ffmpeg{suffix}")
    assert opts["js_runtimes"] == {"deno": {"path": str(tmp_path / f"deno{suffix}")}}


def test_yt_dlp_uses_path_when_nothing_is_bundled(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_encoder import downloader

    monkeypatch.setattr(_frozen, "_bundle_dirs", lambda: [])
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.delenv("DENO_BIN", raising=False)
    assert downloader._external_tools() == {}


# ---------------------------------------------------------------------------
# Work folder
# ---------------------------------------------------------------------------


def test_work_dir_is_per_user_not_current_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_ENCODER_WORK_DIR", raising=False)
    work = config.default_work_dir()
    assert work.is_absolute()
    assert work == config.APP_DATA_DIR / "work"
    assert config.Config().output_dir == work


def test_work_dir_can_be_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_ENCODER_WORK_DIR", str(tmp_path))
    assert config.default_work_dir() == tmp_path


# ---------------------------------------------------------------------------
# Port selection
# ---------------------------------------------------------------------------


def test_pick_port_uses_requested_port_when_free() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert _pick_port("127.0.0.1", free_port) == free_port


def test_pick_port_falls_back_when_busy() -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        chosen = _pick_port("127.0.0.1", taken)
    assert chosen != taken
    assert chosen > 0


# ---------------------------------------------------------------------------
# Update check
# ---------------------------------------------------------------------------


def test_parse_version() -> None:
    assert updates.parse_version("v1.2.10") == (1, 2, 10)
    assert updates.parse_version("0.1.0") < updates.parse_version("0.1.1")
    assert updates.parse_version("1.10.0") > updates.parse_version("1.9.9")


def test_check_for_update_reports_newer_release() -> None:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = {"tag_name": "v0.3.0"}
    with patch("local_encoder.updates.httpx.get", return_value=resp):
        info = updates.check_for_update(current="0.2.9")
    assert info is not None
    assert info.latest == "0.3.0"
    assert info.update_available is True


def test_check_for_update_is_quiet_when_offline() -> None:
    with patch("local_encoder.updates.httpx.get", side_effect=httpx.ConnectError("offline")):
        assert updates.check_for_update(current="0.1.0") is None


def test_version_endpoint_skips_github_when_running_from_source() -> None:
    with patch("local_encoder.updates.check_for_update") as check:
        data = TestClient(server.app).get("/api/version").json()
    check.assert_not_called()
    assert data["version"] == server.__version__
    assert data["update_available"] is False


def test_version_endpoint_announces_update_in_packaged_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_update_cache", {})
    monkeypatch.setattr(updates, "is_frozen", lambda: True)
    info = updates.UpdateInfo(current="0.1.0", latest="9.9.9", update_available=True)
    with patch("local_encoder.updates.check_for_update", return_value=info):
        data = TestClient(server.app).get("/api/version").json()
    assert data["update_available"] is True
    assert data["latest"] == "9.9.9"
    assert data["download_url"].endswith("/releases/latest")


# ---------------------------------------------------------------------------
# Release scripts
# ---------------------------------------------------------------------------


def test_ffmpeg_source_url_matches_bundled_build() -> None:
    fetch = _load_script("fetch_ffmpeg")
    git_build = "ffmpeg version n9.0.2-28-g669f5ab083-20261015 Copyright (c) 2000-2026"
    assert fetch.source_url_for(git_build) == (
        "https://github.com/FFmpeg/FFmpeg/archive/669f5ab083.tar.gz"
    )
    tagged = "ffmpeg version 9.0.2 Copyright (c) 2000-2026 the FFmpeg developers"
    assert fetch.source_url_for(tagged) == "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz"


def test_set_version_stamps_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    set_version = _load_script("set_version")
    init = tmp_path / "__init__.py"
    init.write_text('"""Doc."""\n\n__version__ = "0.1.0"\n', encoding="utf-8")
    monkeypatch.setattr(set_version, "INIT", init)
    monkeypatch.setattr(sys, "argv", ["set_version.py", "1.4.2"])
    set_version.main()
    assert '__version__ = "1.4.2"' in init.read_text(encoding="utf-8")


def test_runtime_packages_exclude_build_tools() -> None:
    make_dist = _load_script("make_dist")
    packages = {p.lower() for p in make_dist.runtime_packages()}
    assert {"yt-dlp", "fastapi", "httpx"} <= packages
    assert "yt-dlp-ejs" in packages  # from yt-dlp[default]: its license must be listed
    assert "pyinstaller" not in packages
    assert "pytest" not in packages
