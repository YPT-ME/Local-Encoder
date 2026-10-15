"""Tests for `local-encoder selftest` (the real FFmpeg run is in CI's selftest job)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from local_encoder import selftest
from local_encoder.cli import app
from local_encoder.selftest import Check, passed, run_selftest


def _fake_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every external step succeeds without FFmpeg."""
    monkeypatch.setattr(selftest, "_tool_version", lambda binary, flag="-version": "v1")
    monkeypatch.setattr(selftest, "_encoding_checks", lambda runner, ffmpeg, ffprobe, temp: None)


def test_all_ok_from_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_steps(monkeypatch)
    monkeypatch.setattr(selftest._frozen, "resolve_deno", lambda: "/x/deno")
    seen: list[Check] = []

    checks = run_selftest(require_bundled=False, report=seen.append)

    assert passed(checks)
    assert seen == checks
    assert [c.name for c in checks][:3] == ["Local Encoder", "FFmpeg runs", "FFprobe runs"]


def test_tools_from_path_fail_when_bundled_tools_are_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_steps(monkeypatch)
    monkeypatch.setattr(selftest._frozen, "resolve_ffmpeg", lambda: "ffmpeg")  # from PATH
    monkeypatch.setattr(selftest._frozen, "resolve_deno", lambda: None)

    checks = run_selftest(require_bundled=True)

    failed = {c.name for c in checks if not c.ok}
    assert {"FFmpeg is included", "deno is included", "deno runs"} <= failed
    assert not passed(checks)


def test_bundled_tools_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake_steps(monkeypatch)
    for name in ("ffmpeg", "ffprobe", "deno"):
        (tmp_path / name).write_bytes(b"")
    monkeypatch.setattr(selftest._frozen, "_bundle_dirs", lambda: [tmp_path])
    monkeypatch.setattr(selftest._frozen, "resolve_ffmpeg", lambda: str(tmp_path / "ffmpeg"))
    monkeypatch.setattr(selftest._frozen, "resolve_ffprobe", lambda: str(tmp_path / "ffprobe"))
    monkeypatch.setattr(selftest._frozen, "resolve_deno", lambda: str(tmp_path / "deno"))

    assert passed(run_selftest(require_bundled=True))


def test_missing_deno_is_only_a_warning_from_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_steps(monkeypatch)
    monkeypatch.setattr(selftest._frozen, "resolve_deno", lambda: None)
    checks = run_selftest(require_bundled=False)
    deno = next(c for c in checks if c.name == "deno runs")
    assert not deno.ok and not deno.required
    assert passed(checks)


def test_required_download_failure_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_steps(monkeypatch)
    with patch(
        "local_encoder.downloader.get_video_info", side_effect=RuntimeError("HTTP Error 403")
    ):
        checks = run_selftest(
            download_urls=["https://a.example/v.mp4"],
            optional_download_urls=["https://b.example/v"],
            require_bundled=False,
        )
    downloads = [c for c in checks if c.name.startswith("Download")]
    assert [(c.ok, c.required) for c in downloads] == [(False, True), (False, False)]
    assert not passed(checks)


def test_cli_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(**kwargs: Any) -> list[Check]:
        checks = [Check("FFmpeg runs", True, "v1"), Check("Convert to MP4", False, "boom")]
        for check in checks:
            kwargs["report"](check)
        return checks

    monkeypatch.setattr(selftest, "run_selftest", fake)
    result = CliRunner().invoke(app, ["selftest", "--allow-system-tools"])
    assert result.exit_code == 1
    assert "[FAIL] Convert to MP4" in result.output
    assert "Problems found" in result.output


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg on PATH")
def test_real_ffmpeg_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs only where FFmpeg is installed (developer machines, CI's selftest job)."""
    monkeypatch.setattr(selftest._frozen, "resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(selftest._frozen, "resolve_ffprobe", lambda: "ffprobe")
    checks = run_selftest(require_bundled=False)
    failed = [(c.name, c.detail) for c in checks if c.required and not c.ok]
    assert not failed


def test_each_download_gets_its_own_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """yt-dlp returns an existing file of the same name, which would fake a second success."""
    _fake_steps(monkeypatch)
    folders: list[Path] = []

    def fake_download(url: str, output_dir: Path, stem: str) -> Path:
        folders.append(output_dir)
        raise RuntimeError("stop here")

    with (
        patch("local_encoder.downloader.get_video_info", return_value={}),
        patch("local_encoder.downloader.download_video", side_effect=fake_download),
    ):
        run_selftest(
            download_urls=["https://a.example/1"],
            optional_download_urls=["https://b.example/2"],
            require_bundled=False,
        )
    assert len(set(folders)) == 2
