"""Import completion must control history, exit status and cleanup in the CLI too."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from local_encoder import cli, history
from local_encoder.avideo_client import (
    AVideoAPIError,
    LoginResult,
    RegisterVideoResult,
    ServerConfig,
)
from local_encoder.config import Config
from local_encoder.encoder import SOFTWARE_CODEC, MediaInfo


@pytest.mark.parametrize("completed", [True, False])
def test_import_only_cleans_files_after_confirmed_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, completed: bool
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    raw, encoded = work / "video.mkv", work / "video_360p.mp4"
    raw.write_bytes(b"raw")
    encoded.write_bytes(b"encoded")
    cfg = Config(
        server_url="https://avideo.example/", username="alice", password="test", output_dir=work
    )
    remote = MagicMock()
    remote.__enter__.return_value = remote
    remote.login.return_value = LoginResult(True, True, "test", "alice", 7)
    remote.get_server_config.return_value = ServerConfig()
    remote.register_video.return_value = RegisterVideoResult(9, "test")
    remote.upload_file.return_value = {}
    if not completed:
        remote.notify_done.side_effect = AVideoAPIError("Not completed", code="completion_failed")
    monkeypatch.setattr(cli, "load_config", lambda *args: cfg)
    monkeypatch.setattr(cli, "AVideoClient", lambda *args, **kwargs: remote)
    monkeypatch.setattr(cli.keep_awake, "inhibit", nullcontext)
    for name, value in {
        "get_video_info": {"title": "Video"},
        "download_video": raw,
        "probe_media": MediaInfo(640, 360, True, True),
        "probe_duration": 1.0,
        "detect_video_codec": SOFTWARE_CODEC,
        "encode_mp4_multi": [encoded],
        "extract_thumbnail_jpg": None,
        "extract_thumbnail_gif": None,
        "extract_thumbnail_webp": None,
    }.items():
        monkeypatch.setattr(cli, name, MagicMock(return_value=value))

    result = CliRunner().invoke(cli.app, ["import", "https://example.com/watch", "--format", "mp4"])

    assert result.exit_code == (0 if completed else 1), result.output
    assert history.list_entries()[0].status == ("success" if completed else "failed")
    assert raw.exists() is not completed
    assert encoded.exists() is not completed
