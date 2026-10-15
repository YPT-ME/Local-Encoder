"""Tests for AVideoClient HTTP interactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from local_encoder.avideo_client import (
    MAX_CHUNK_RETRIES,
    USER_AGENT,
    AVideoAPIError,
    AVideoClient,
    LoginResult,
    RegisterVideoResult,
    ServerConfig,
    SiteStatus,
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


def test_upload_file_falls_back_to_multipart_after_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip_720p.mp4"
    video.write_bytes(b"C" * 50)
    monkeypatch.setattr("local_encoder.avideo_client._sleep", lambda s: None)

    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    # Server keeps answering without an assembled file path
    chunk_resp = _mock_response({"file": "", "chunk": 0})

    with patch.object(c._http, "put", return_value=chunk_resp) as mock_put:
        with patch.object(c._http, "post", return_value=_mock_response({"error": False})) as mp:
            c.upload_file(
                file_path=video,
                videos_id=1,
                video_id_hash="h",
                title="T",
                format_ext="mp4",
                resolution=720,
                duration=5.0,
            )

    assert mock_put.call_count == 1 + MAX_CHUNK_RETRIES
    assert "video" in mp.call_args.kwargs["files"]
    assert "chunkFile" not in mp.call_args.kwargs["data"]


# ---------------------------------------------------------------------------
# notify_done()
# ---------------------------------------------------------------------------


def test_notify_done_success() -> None:
    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    body = {"error": False, "video_id": 42}
    with patch.object(c._http, "post", return_value=_mock_response(body)) as mock_post:
        result = c.notify_done(42, "hash123")

    assert result == body
    called_url = mock_post.call_args[0][0]
    assert "aVideoEncoderNotifyIsDone" in called_url


def test_notify_done_failed_flag() -> None:
    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "enc"

    with patch.object(c._http, "post", return_value=_mock_response({"error": False})) as mock_post:
        c.notify_done(1, "h", failed=True)

    posted_data = mock_post.call_args[1]["data"]
    assert posted_data["fail"] == "1"


@pytest.mark.parametrize("body", [{"error": True, "code": "completion_failed"}, {}, []])
def test_notify_done_requires_confirmation(body: dict[str, Any] | list[Any]) -> None:
    with AVideoClient("https://example.com/") as c:
        with patch.object(c._http, "post", return_value=_mock_response(body)):
            with pytest.raises(AVideoAPIError) as excinfo:
                c.notify_done(42, "h")
    assert excinfo.value.code == "completion_failed"


def test_notify_done_retries_completion_in_progress() -> None:
    busy = _mock_response({"error": True, "code": "completion_in_progress"})
    success = _mock_response({"error": False, "video_id": 42})
    with AVideoClient("https://example.com/") as c:
        with (
            patch.object(c._http, "post", side_effect=[busy, success]) as post,
            patch("local_encoder.avideo_client._sleep") as sleep,
        ):
            assert c.notify_done(42, "h") == {"error": False, "video_id": 42}
    assert post.call_count == 2
    assert post.call_args_list[0].kwargs["data"] == post.call_args_list[1].kwargs["data"]
    sleep.assert_called_once()


def test_notify_done_stops_retrying_a_busy_site() -> None:
    with AVideoClient("https://example.com/") as c:
        with (
            patch.object(
                c._http,
                "post",
                return_value=_mock_response({"error": True, "code": "completion_in_progress"}),
            ) as post,
            patch("local_encoder.avideo_client._sleep"),
            pytest.raises(AVideoAPIError) as excinfo,
        ):
            c.notify_done(42, "h")
    assert excinfo.value.code == "completion_in_progress"
    assert post.call_count == 4


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


# ---------------------------------------------------------------------------
# Protocol compatibility with the AVideo Streamer
# (see docs/avideo-encoder-protocol.md)
# ---------------------------------------------------------------------------


def _html_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.side_effect = ValueError("not json")
    resp.text = text
    return resp


def _client() -> AVideoClient:
    c = AVideoClient("https://example.com/")
    c._username = "alice"
    c._encrypted_pass = "_user_hash_token"
    return c


def test_user_agent_identifies_as_avideo_encoder() -> None:
    # isAVideoUserAgent() on the Streamer matches "AVideoEncoder"
    assert "AVideoEncoder" in USER_AGENT
    assert AVideoClient("https://example.com/")._http.headers["User-Agent"] == USER_AGENT


def test_register_video_sends_streamer_formats() -> None:
    c = _client()
    body = {"videos_id": 42, "video_id_hash": "abc"}
    with patch.object(c._http, "post", return_value=_mock_response(body)) as mock_post:
        c.register_video("T", "zip", None, 3725.4, download_url="https://youtu.be/x")

    data = mock_post.call_args.kwargs["data"]
    assert data["duration"] == "01:02:05"  # Video::isValidDuration() needs HH:MM:SS
    assert data["resolution"] == ""  # HLS zip is stored without a resolution
    assert data["videoDownloadedLink"] == "https://youtu.be/x"
    # downloadURL would make the site download the source page itself
    assert "downloadURL" not in data


def test_login_falls_back_to_direct_endpoint_without_rewrites() -> None:
    c = AVideoClient("https://example.com/")
    not_found = _html_response("<h1>Not Found</h1>", status_code=404)
    ok = _mock_response({"isLogged": True, "canUpload": True, "pass": "t", "user": "alice"})
    with patch.object(c._http, "post", side_effect=[not_found, ok]) as mock_post:
        c.login("alice", "secret")

    urls = [call.args[0] for call in mock_post.call_args_list]
    assert urls == ["https://example.com/login", "https://example.com/objects/login.json.php"]


def test_login_reads_categories_from_response() -> None:
    c = AVideoClient("https://example.com/")
    body = {
        "isLogged": True,
        "canUpload": True,
        "pass": "t",
        "user": "alice",
        "categories": [
            {"id": 2, "name": "Kids", "hierarchyAndName": "Main / Kids"},
            {"id": 0, "name": "invalid"},
        ],
    }
    with patch.object(c._http, "post", return_value=_mock_response(body)):
        result = c.login("alice", "secret")
    assert result.categories == [{"id": 2, "name": "Main / Kids"}]


def test_use_login_sets_token_without_request() -> None:
    c = AVideoClient("https://example.com/")
    login = LoginResult(True, True, "_user_hash_tok", "alice", 7)
    with patch.object(c._http, "post") as mock_post:
        c.use_login(login)
    mock_post.assert_not_called()
    assert c._auth_fields()["pass"] == "_user_hash_tok"


def test_bot_blocker_page_gives_clear_error() -> None:
    c = AVideoClient("https://example.com/")
    page = _html_response("Bot Found [python] 2026-10-15 python-httpx")
    with patch.object(c._http, "post", return_value=page):
        with pytest.raises(AVideoAPIError, match="robot"):
            c.login("alice", "secret")


def test_rate_limit_gives_clear_error() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(c._http, "post", return_value=_html_response("", status_code=429)):
        with pytest.raises(AVideoAPIError, match="Wait a few minutes"):
            c.login("alice", "secret")


def test_json_after_php_warning_is_accepted() -> None:
    c = _client()
    page = _html_response('Warning: something\n{"videos_id": 5, "video_id_hash": "h"}')
    with patch.object(c._http, "post", return_value=page):
        assert c.register_video("T", "mp4", 720, 1.0).videos_id == 5


def test_chunk_upload_sends_auth_headers_and_validates(tmp_path: Path) -> None:
    video = tmp_path / "v_720p.mp4"
    video.write_bytes(b"0123456789")
    c = _client()

    responses = [
        _mock_response({"file": "/tmp/YTPChunk_x", "chunk": 0, "total": 2, "complete": False}),
        _mock_response(
            {"file": "/tmp/YTPChunk_x", "chunk": 1, "total": 2, "complete": True, "filesize": 10}
        ),
    ]
    with patch.object(c._http, "put", side_effect=responses) as mock_put:
        with patch.object(c._http, "post", return_value=_mock_response({"error": False})) as mp:
            c.upload_file(video, 1, "h", "T", "mp4", 720, 5.0, chunk_size=6)

    first, second = mock_put.call_args_list
    for call in (first, second):
        headers = call.kwargs["headers"]
        assert headers["X-Encoder-User"] == "alice"
        assert headers["X-Encoder-Pass"] == "_user_hash_token"
    assert first.kwargs["headers"]["Content-Length"] == "6"
    assert second.kwargs["headers"]["Content-Length"] == "4"
    assert "chunk=0&total=2" in first.args[0]
    assert "chunk=1&total=2" in second.args[0]
    assert mp.call_args.kwargs["data"]["chunkFile"] == "/tmp/YTPChunk_x"


def test_chunk_body_streams_the_right_bytes(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0123456789")
    seen: list[int] = []
    body = b"".join(_client()._chunk_body(video, 6, 4, seen.append))
    assert body == b"6789"
    assert sum(seen) == 4


def test_chunk_retry_keeps_same_file_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "v_720p.mp4"
    video.write_bytes(b"0123456789")
    monkeypatch.setattr("local_encoder.avideo_client._sleep", lambda s: None)
    c = _client()

    responses = [
        _mock_response({"error": True, "msg": "conflict"}, status_code=409),
        _mock_response(
            {"file": "/tmp/YTPChunk_y", "chunk": 0, "total": 1, "complete": True, "filesize": 10}
        ),
    ]
    with patch.object(c._http, "put", side_effect=responses) as mock_put:
        with patch.object(c._http, "post", return_value=_mock_response({"error": False})):
            c.upload_file(video, 1, "h", "T", "mp4", 720, 5.0)

    urls = [call.args[0] for call in mock_put.call_args_list]
    assert len(urls) == 2
    assert urls[0] == urls[1]


def test_chunk_last_response_must_match_file_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "v_720p.mp4"
    video.write_bytes(b"0123456789")
    monkeypatch.setattr("local_encoder.avideo_client._sleep", lambda s: None)
    c = _client()

    truncated = _mock_response(
        {"file": "/tmp/YTPChunk_z", "chunk": 0, "total": 1, "complete": True, "filesize": 3}
    )
    with patch.object(c._http, "put", return_value=truncated) as mock_put:
        with patch.object(c._http, "post", return_value=_mock_response({"error": False})) as mp:
            c.upload_file(video, 1, "h", "T", "mp4", 720, 5.0)

    assert mock_put.call_count == 1 + MAX_CHUNK_RETRIES
    assert "video" in mp.call_args.kwargs["files"]  # fell back to a multipart upload


def test_chunk_forbidden_falls_back_to_multipart(tmp_path: Path) -> None:
    video = tmp_path / "v_720p.mp4"
    video.write_bytes(b"abc")
    c = _client()

    forbidden = _mock_response({"error": True, "msg": "Forbidden"}, status_code=403)
    with patch.object(c._http, "put", return_value=forbidden) as mock_put:
        with patch.object(c._http, "post", return_value=_mock_response({"error": False})) as mp:
            c.upload_file(video, 1, "h", "T", "mp4", 720, 5.0)

    assert mock_put.call_count == 1
    assert mp.call_args.kwargs["data"]["format"] == "mp4"
    assert "video" in mp.call_args.kwargs["files"]


def test_chunk_uses_direct_endpoint_when_rewrite_missing(tmp_path: Path) -> None:
    video = tmp_path / "v_720p.mp4"
    video.write_bytes(b"abc")
    c = _client()

    responses = [
        _html_response("Not Found", status_code=404),
        _mock_response(
            {"file": "/tmp/YTPChunk_w", "chunk": 0, "total": 1, "complete": True, "filesize": 3}
        ),
    ]
    with patch.object(c._http, "put", side_effect=responses) as mock_put:
        with patch.object(c._http, "post", return_value=_mock_response({"error": False})):
            c.upload_file(video, 1, "h", "T", "mp4", 720, 5.0)

    assert "objects/aVideoEncoderChunk.json.php" in mock_put.call_args_list[1].args[0]


def test_legacy_server_cannot_assemble_several_chunks(tmp_path: Path) -> None:
    video = tmp_path / "v_720p.mp4"
    video.write_bytes(b"0123456789")
    c = _client()

    legacy = _mock_response({"file": "/tmp/YTPChunk_old", "filesize": 6})  # no "chunk" echo
    with patch.object(c._http, "put", return_value=legacy):
        with patch.object(c._http, "post", return_value=_mock_response({"error": False})) as mp:
            c.upload_file(video, 1, "h", "T", "mp4", 720, 5.0, chunk_size=6)

    assert "video" in mp.call_args.kwargs["files"]


def test_finalize_error_raises(tmp_path: Path) -> None:
    video = tmp_path / "v_720p.mp4"
    video.write_bytes(b"abc")
    c = _client()

    chunk = _mock_response({"file": "/tmp/f", "chunk": 0, "complete": True, "filesize": 3})
    with patch.object(c._http, "put", return_value=chunk):
        with patch.object(
            c._http, "post", return_value=_mock_response({"error": True, "msg": "disk full"})
        ):
            with pytest.raises(AVideoAPIError, match="disk full"):
                c.upload_file(video, 1, "h", "T", "mp4", 720, 5.0)


def test_notify_failed_never_raises() -> None:
    c = _client()
    with patch.object(c._http, "post", side_effect=httpx.ConnectError("down")) as mock_post:
        c.notify_failed(1, "h")
    assert mock_post.call_args.kwargs["data"]["fail"] == "1"


# ---------------------------------------------------------------------------
# Login fields used to pick formats, site status, error codes
# ---------------------------------------------------------------------------


def _login_body(**extra: Any) -> dict[str, Any]:
    return {"isLogged": True, "canUpload": True, "id": 1, "user": "a", "pass": "t", **extra}


def test_login_reads_videohls_and_allowed_resolutions() -> None:
    c = AVideoClient("https://example.com/")
    body = _login_body(videoHLS=True, allowedResolutions=["720", 360, "bad", 720])
    with patch.object(c._http, "post", return_value=_mock_response(body)):
        result = c.login("a", "p")
    assert result.video_hls is True
    assert result.allowed_resolutions == [360, 720]


def test_login_without_videohls_means_no_hls() -> None:
    # The site sends videoHLS only when the VideoHLS plugin is enabled.
    c = AVideoClient("https://example.com/")
    with patch.object(c._http, "post", return_value=_mock_response(_login_body())):
        result = c.login("a", "p")
    assert result.video_hls is False
    assert result.allowed_resolutions == []


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"error": "Captcha required"}, "login_error"),
        ({"isLogged": False}, "wrong_password"),
        ({"isLogged": True, "canUpload": False}, "cannot_upload"),
    ],
)
def test_login_errors_have_codes(body: dict[str, Any], code: str) -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(c._http, "post", return_value=_mock_response(body)):
        with pytest.raises(AVideoAPIError) as excinfo:
            c.login("a", "p")
    assert excinfo.value.code == code


def test_rate_limit_has_code() -> None:
    c = AVideoClient("https://example.com/")
    with patch.object(c._http, "post", return_value=_mock_response({}, status_code=429)):
        with pytest.raises(AVideoAPIError) as excinfo:
            c.login("a", "p")
    assert excinfo.value.code == "rate_limited"


def test_get_site_status_reads_limits() -> None:
    c = AVideoClient("https://example.com/")
    body = {
        "version": "30.2",
        "file_upload_max_size": 10737418240,
        "videoStorageLimitMinutes": "60",
        "currentStorageUsage": 120,
    }
    with patch.object(c._http, "get", return_value=_mock_response(body)) as mock_get:
        status = c.get_site_status()
    assert status == SiteStatus(
        version="30.2",
        max_file_size=10737418240,
        storage_limit_minutes=60,
        storage_used_seconds=120,
    )
    assert mock_get.call_args.args[0] == "https://example.com/status"


def test_get_site_status_falls_back_and_never_raises() -> None:
    c = AVideoClient("https://example.com/")
    responses = [_mock_response({}, status_code=404), _mock_response({"version": "9"})]
    with patch.object(c._http, "get", side_effect=responses) as mock_get:
        assert c.get_site_status().version == "9"
    assert mock_get.call_args.args[0].endswith("objects/status.json.php")
    with patch.object(c._http, "get", side_effect=httpx.ConnectError("down")):
        assert c.get_site_status() == SiteStatus()
