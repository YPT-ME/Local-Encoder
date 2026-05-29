"""Tests for AVideoClient HTTP interactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from local_encoder.avideo_client import (
    AVideoAPIError,
    AVideoClient,
    LoginResult,
    RegisterVideoResult,
    ServerConfig,
)


def _mock_response(body: dict[str, Any] | list[Any], status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# AVideoClient constructor / context manager
# ---------------------------------------------------------------------------


def test_client_adds_trailing_slash() -> None:
    c = AVideoClient("https://example.com")
    assert c._base.endswith("/")


def test_client_keeps_trailing_slash() -> None:
    c = AVideoClient("https://example.com/")
    assert c._base == "https://example.com/"


def test_context_manager_closes() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(c, "close") as mock_close:
        with c:
            pass
        mock_close.assert_called_once()


# ---------------------------------------------------------------------------
# login()
# ---------------------------------------------------------------------------


def test_login_success() -> None:
    c = AVideoClient("https://example.com/")
    resp_body = {
        "isLogged": True,
        "canUpload": True,
        "pass": "enc_pass",
        "user": "alice",
        "id": 7,
        "name": "Alice",
        "isAdmin": True,
    }
    with patch.object(c._http, "post", return_value=_mock_response(resp_body)):
        result = c.login("alice", "secret")

    assert isinstance(result, LoginResult)
    assert result.is_logged is True
    assert result.can_upload is True
    assert result.encrypted_pass == "enc_pass"
    assert result.username == "alice"
    assert result.user_id == 7
    assert result.name == "Alice"
    assert result.is_admin is True
    assert c._username == "alice"
    assert c._encrypted_pass == "enc_pass"


def test_login_raises_on_error_field() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(c._http, "post", return_value=_mock_response({"error": "invalid"})):
        with pytest.raises(AVideoAPIError, match="login error"):
            c.login("alice", "bad")


def test_login_raises_when_not_logged() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(
        c._http,
        "post",
        return_value=_mock_response({"isLogged": False, "canUpload": False}),
    ):
        with pytest.raises(AVideoAPIError, match="rejected"):
            c.login("alice", "bad")


def test_login_raises_when_no_upload_permission() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(
        c._http,
        "post",
        return_value=_mock_response({"isLogged": True, "canUpload": False}),
    ):
        with pytest.raises(AVideoAPIError, match="upload permission"):
            c.login("alice", "pass")


# ---------------------------------------------------------------------------
# get_server_config()
# ---------------------------------------------------------------------------


def test_get_server_config_parses_fields() -> None:
    c = AVideoClient("https://example.com/")
    body = {
        "autoConvertVideosToMP3": True,
        "singleResolution": {"value": "720"},
        "saveOriginalVideoResolution": False,
        "doNotShowEncoderAutomaticHLS": True,
        "doNotShowEncoderAutomaticMP4": False,
    }
    with patch.object(c._http, "get", return_value=_mock_response(body)):
        cfg = c.get_server_config()

    assert isinstance(cfg, ServerConfig)
    assert cfg.auto_convert_to_mp3 is True
    assert cfg.single_resolution == 720
    assert cfg.disable_hls is True
    assert cfg.disable_mp4 is False


def test_get_server_config_returns_defaults_on_error() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(c._http, "get", side_effect=httpx.ConnectError("timeout")):
        cfg = c.get_server_config()

    assert cfg.single_resolution == 0
    assert cfg.auto_convert_to_mp3 is False


def test_get_server_config_integer_single_resolution() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(c._http, "get", return_value=_mock_response({"singleResolution": 1080})):
        cfg = c.get_server_config()
    assert cfg.single_resolution == 1080


# ---------------------------------------------------------------------------
# get_categories()
# ---------------------------------------------------------------------------


def test_get_categories_rows_format() -> None:
    c = AVideoClient("https://example.com/")
    body = {"rows": [{"id": 1, "name": "News"}, {"id": 2, "name": "Sports"}]}
    with patch.object(c._http, "get", return_value=_mock_response(body)):
        cats = c.get_categories()
    assert cats == [{"id": 1, "name": "News"}, {"id": 2, "name": "Sports"}]


def test_get_categories_list_format() -> None:
    c = AVideoClient("https://example.com/")
    body = [{"id": 3, "name": "Music"}]
    with patch.object(c._http, "get", return_value=_mock_response(body)):
        cats = c.get_categories()
    assert cats == [{"id": 3, "name": "Music"}]


def test_get_categories_returns_empty_on_error() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(c._http, "get", side_effect=RuntimeError("fail")):
        cats = c.get_categories()
    assert cats == []


def test_get_categories_filters_incomplete_items() -> None:
    c = AVideoClient("https://example.com/")
    body = {"rows": [{"id": 1, "name": "Valid"}, {"id": 0, "name": ""}, {"name": "no-id"}]}
    with patch.object(c._http, "get", return_value=_mock_response(body)):
        cats = c.get_categories()
    assert len(cats) == 1
    assert cats[0]["id"] == 1


# ---------------------------------------------------------------------------
# register_video()
# ---------------------------------------------------------------------------


def test_register_video_success() -> None:
    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"
    body = {"videos_id": 42, "video_id_hash": "abc123", "error": False, "msg": "ok"}
    with patch.object(c._http, "post", return_value=_mock_response(body)):
        result = c.register_video("My Video", "mp4", 720, 120.0)

    assert isinstance(result, RegisterVideoResult)
    assert result.videos_id == 42
    assert result.video_id_hash == "abc123"


def test_register_video_raises_when_no_id() -> None:
    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"
    body = {"videos_id": 0, "msg": "quota exceeded"}
    with patch.object(c._http, "post", return_value=_mock_response(body)):
        with pytest.raises(AVideoAPIError, match="no videos_id"):
            c.register_video("My Video", "mp4", 720, 120.0)


# ---------------------------------------------------------------------------
# upload_file()
# ---------------------------------------------------------------------------


def test_upload_file_single_chunk(tmp_path: Path) -> None:
    video = tmp_path / "video_720p.mp4"
    video.write_bytes(b"A" * 100)

    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    chunk_resp = _mock_response({"file": "/tmp/assembled.mp4"})
    finalize_resp = _mock_response({"ok": True})

    def fake_put(url: str, **kwargs: object) -> MagicMock:
        return chunk_resp

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        return finalize_resp

    with patch.object(c._http, "put", side_effect=fake_put):
        with patch.object(c._http, "post", side_effect=fake_post):
            result = c.upload_file(
                file_path=video,
                videos_id=1,
                video_id_hash="hash",
                title="Test",
                format_ext="mp4",
                resolution=720,
                duration=10.0,
            )

    assert result == {"ok": True}


def test_upload_file_calls_progress_callback(tmp_path: Path) -> None:
    video = tmp_path / "clip_720p.mp4"
    video.write_bytes(b"B" * 200)

    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    calls: list[tuple[str, int, int]] = []

    def on_progress(fname: str, sent: int, total: int) -> None:
        calls.append((fname, sent, total))

    chunk_resp = _mock_response({"file": "/tmp/out.mp4"})
    finalize_resp = _mock_response({})

    with patch.object(c._http, "put", return_value=chunk_resp):
        with patch.object(c._http, "post", return_value=finalize_resp):
            c.upload_file(
                file_path=video,
                videos_id=1,
                video_id_hash="h",
                title="T",
                format_ext="mp4",
                resolution=720,
                duration=5.0,
                progress_callback=on_progress,
            )

    assert len(calls) >= 1
    assert calls[-1][1] <= calls[-1][2]  # sent <= total


def test_upload_file_raises_when_no_assembled_path(tmp_path: Path) -> None:
    video = tmp_path / "clip_720p.mp4"
    video.write_bytes(b"C" * 50)

    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    # Server returns empty file path
    chunk_resp = _mock_response({"file": ""})

    with patch.object(c._http, "put", return_value=chunk_resp):
        with pytest.raises(AVideoAPIError, match="assembled"):
            c.upload_file(
                file_path=video,
                videos_id=1,
                video_id_hash="h",
                title="T",
                format_ext="mp4",
                resolution=720,
                duration=5.0,
            )


# ---------------------------------------------------------------------------
# notify_done()
# ---------------------------------------------------------------------------


def test_notify_done_success() -> None:
    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    body = {"ok": True}
    with patch.object(c._http, "post", return_value=_mock_response(body)) as mock_post:
        result = c.notify_done(42, "hash123")

    assert result == {"ok": True}
    called_url = mock_post.call_args[0][0]
    assert "aVideoEncoderNotifyIsDone" in called_url


def test_notify_done_failed_flag() -> None:
    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    with patch.object(c._http, "post", return_value=_mock_response({})) as mock_post:
        c.notify_done(1, "h", failed=True)

    posted_data = mock_post.call_args[1]["data"]
    assert posted_data["fail"] == "1"


# ---------------------------------------------------------------------------
# upload_images()
# ---------------------------------------------------------------------------


def test_upload_images_skips_when_no_files() -> None:
    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    result = c.upload_images(videos_id=1, video_id_hash="h", duration=10.0)
    assert result.get("error") is True


def test_upload_images_posts_files(tmp_path: Path) -> None:
    jpg = tmp_path / "thumb.jpg"
    jpg.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    with patch.object(c._http, "post", return_value=_mock_response({"ok": True})) as mock_post:
        result = c.upload_images(videos_id=1, video_id_hash="h", duration=10.0, jpg_path=jpg)

    assert result == {"ok": True}
    mock_post.assert_called_once()
