"""Tests for the FastAPI server endpoints."""

from __future__ import annotations

import json
import queue
import threading
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from local_encoder import server
from local_encoder.avideo_client import (
    AVideoAPIError,
    LoginResult,
    RegisterVideoResult,
    ServerConfig,
    SiteStatus,
)
from local_encoder.encoder import SOFTWARE_CODEC, MediaInfo
from local_encoder.errors import JobCancelled, LocalEncoderError
from local_encoder.server import app

# The page always sends the custom header; the server refuses state changes without it.
client = TestClient(app, base_url="http://127.0.0.1:47800", headers={"X-Local-Encoder": "1"})


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


def _login(
    categories: list[dict[str, Any]] | None = None,
    video_hls: bool = True,
    allowed: list[int] | None = None,
) -> LoginResult:
    return LoginResult(
        is_logged=True,
        can_upload=True,
        encrypted_pass="_user_hash_token",
        username="alice",
        user_id=7,
        name="Alice",
        categories=categories if categories is not None else [{"id": 1, "name": "News"}],
        video_hls=video_hls,
        allowed_resolutions=allowed or [],
    )


def _mock_client(login: LoginResult | None = None) -> MagicMock:
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.login.return_value = login or _login()
    mock_client.get_server_config.return_value = ServerConfig()
    mock_client.get_site_status.return_value = SiteStatus(version="30.2")
    mock_client.register_video.return_value = RegisterVideoResult(videos_id=9, video_id_hash="h")
    return mock_client


def _session(login: LoginResult | None = None) -> server._Session:
    return server._Session("https://avideo.example.com/", True, login or _login(), time.time())


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh job store, a work queue no worker reads, and a temporary work folder."""
    out = tmp_path / "output"
    monkeypatch.setattr("local_encoder.server.OUTPUT_DIR", out)
    monkeypatch.setattr("local_encoder.server.REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("local_encoder.server._jobs", {})
    monkeypatch.setattr("local_encoder.server._job_order", [])
    monkeypatch.setattr("local_encoder.server._subscribers", [])
    monkeypatch.setattr("local_encoder.server._info_cache", {})
    monkeypatch.setattr("local_encoder.server._work_queue", queue.Queue())
    monkeypatch.setattr("local_encoder.server._notifier", None)
    return out


@pytest.fixture()
def session_id(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr("local_encoder.server._sessions", {"sess-1": _session()})
    return "sess-1"


def _job(kind: str = "url", session: server._Session | None = None, **opts: Any) -> server.Job:
    job = server.Job(
        kind,
        "https://example.com/watch" if kind == "url" else "clip.mp4",
        session or _session(),
        server.JobOptions(**opts),
    )
    server._enqueue(job)
    return job


# ---------------------------------------------------------------------------
# Only local requests from the page
# ---------------------------------------------------------------------------


def test_foreign_host_is_refused() -> None:
    other = TestClient(app, base_url="http://attacker.example")
    assert other.get("/api/jobs").status_code == 403


def test_post_without_page_header_is_refused(session_id: str) -> None:
    plain = TestClient(app, base_url="http://127.0.0.1:47800")
    resp = plain.post("/api/session", json={"session_id": session_id})
    assert resp.status_code == 403


def test_localhost_names_are_accepted() -> None:
    assert server._host_name("localhost:47800") == "localhost"
    assert server._host_name("[::1]:47800") == "::1"
    assert server._host_name("127.0.0.1") == "127.0.0.1"


def test_index_returns_html() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "/static/i18n.js" in resp.text


# ---------------------------------------------------------------------------
# GET /api/jobs
# ---------------------------------------------------------------------------


def test_list_jobs_empty() -> None:
    assert client.get("/api/jobs").json() == []


def test_list_jobs_returns_summary() -> None:
    job = _job(title="Test Video")
    data = client.get("/api/jobs").json()
    assert len(data) == 1
    assert data[0]["job_id"] == job.id
    assert data[0]["status"] == "pending"
    assert data[0]["title"] == "Test Video"
    assert data[0]["site"] == "avideo.example.com"
    assert "logs" not in data[0]


def test_active_job_count() -> None:
    _job()
    done = _job()
    done.emit("done", {"videos_id": 1})
    assert server.active_job_count() == 1


# ---------------------------------------------------------------------------
# POST /api/test-connection, /api/session, /api/logout
# ---------------------------------------------------------------------------


def test_test_connection_success_creates_session(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: dict[str, Any] = {}
    monkeypatch.setattr("local_encoder.server._sessions", sessions)

    with patch("local_encoder.server.AVideoClient", return_value=_mock_client()):
        resp = client.post(
            "/api/test-connection",
            json={"server_url": "https://example.com", "username": "alice", "password": "secret"},
        )

    data = resp.json()
    assert data["ok"] is True
    assert data["name"] == "Alice"
    assert data["categories"] == [{"id": 1, "name": "News"}]
    assert data["session_id"] in sessions
    assert data["site"]["hls"] is True
    assert data["site"]["host"] == "example.com"
    assert data["site"]["resolutions"] == [240, 360, 480, 540, 720, 1080, 1440, 2160]
    # The password and the AVideo token are never sent to the page.
    assert "secret" not in resp.text
    assert "_user_hash_" not in resp.text


def test_test_connection_failure_has_error_code() -> None:
    mock_client = _mock_client()
    mock_client.login.side_effect = AVideoAPIError("bad password", code="wrong_password")

    with patch("local_encoder.server.AVideoClient", return_value=mock_client):
        resp = client.post(
            "/api/test-connection",
            json={"server_url": "https://example.com", "username": "a", "password": "wrong"},
        )

    data = resp.json()
    assert data["ok"] is False
    assert data["error_info"]["code"] == "wrong_password"


def test_test_connection_adds_trailing_slash() -> None:
    with patch("local_encoder.server.AVideoClient") as mock_cls:
        mock_cls.return_value = _mock_client()
        client.post(
            "/api/test-connection",
            json={"server_url": "https://example.com", "username": "bob", "password": "pass"},
        )
        assert mock_cls.call_args[0][0] == "https://example.com/"


def test_test_connection_falls_back_to_category_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_encoder.server._sessions", {})
    mock_client = _mock_client(_login(categories=[]))
    mock_client.get_categories.return_value = [{"id": 5, "name": "Music"}]

    with patch("local_encoder.server.AVideoClient", return_value=mock_client):
        resp = client.post(
            "/api/test-connection",
            json={"server_url": "https://example.com/", "username": "u", "password": "p"},
        )

    assert resp.json()["categories"] == [{"id": 5, "name": "Music"}]


def test_site_summary_without_videohls_and_limited_user() -> None:
    session = _session(_login(video_hls=False, allowed=[360, 720]))
    session.config = ServerConfig(single_resolution=480, auto_convert_to_mp3=True)
    session.status = SiteStatus(storage_limit_minutes=100, storage_used_seconds=30 * 60)
    summary = server._site_summary(session)
    assert summary["hls"] is False
    assert summary["mp3"] is True
    assert summary["resolutions"] == [360]
    assert summary["storage_left_minutes"] == 70


def test_session_resumes_without_login(session_id: str) -> None:
    with patch("local_encoder.server.AVideoClient") as mock_cls:
        resp = client.post("/api/session", json={"session_id": session_id})

    assert resp.status_code == 200
    assert resp.json()["name"] == "Alice"
    mock_cls.return_value.login.assert_not_called()


def test_session_unknown_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_encoder.server._sessions", {})
    assert client.post("/api/session", json={"session_id": "nope"}).status_code == 401


def test_session_expired_returns_401(session_id: str) -> None:
    server._sessions[session_id].created -= server.SESSION_TTL_SECONDS + 1
    resp = client.post("/api/session", json={"session_id": session_id})
    assert resp.status_code == 401
    assert session_id not in server._sessions


def test_logout_forgets_session(session_id: str) -> None:
    assert client.post("/api/logout", json={"session_id": session_id}).json()["ok"] is True
    assert session_id not in server._sessions


def test_categories_endpoint_with_password_in_url_is_gone() -> None:
    resp = client.get("/api/categories", params={"username": "u", "password": "p"})
    assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# POST /api/import, /api/import-file
# ---------------------------------------------------------------------------


def test_start_import_queues_a_job(session_id: str) -> None:
    resp = client.post(
        "/api/import",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "session_id": session_id,
            "format": "MP4",
            "resolutions": [720, 360],
            "use_gpu": False,
        },
    )

    job_id = resp.json()["job_id"]
    assert len(job_id) == 36
    job = server._jobs[job_id]
    assert job.kind == "url"
    assert job.options.fmt == "mp4"
    assert job.options.use_gpu is False
    assert server._work_queue.get_nowait() == job_id


def test_start_import_requires_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_encoder.server._sessions", {})
    resp = client.post("/api/import", json={"url": "https://example.com/v", "session_id": "x"})
    assert resp.status_code == 401
    assert server._jobs == {}


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/v.mp4", "not a link"])
def test_start_import_rejects_non_web_links(session_id: str, url: str) -> None:
    resp = client.post("/api/import", json={"url": url, "session_id": session_id})
    assert resp.status_code == 400
    assert server._jobs == {}


def test_start_import_file_saves_file(session_id: str, _isolated_state: Path) -> None:
    resp = client.post(
        "/api/import-file",
        data={"session_id": session_id, "use_gpu": "0"},
        files={"file": ("test.mp4", b"\x00" * 16, "video/mp4")},
    )

    job_id = resp.json()["job_id"]
    saved = _isolated_state / job_id / "test.mp4"
    assert saved.read_bytes() == b"\x00" * 16
    job = server._jobs[job_id]
    assert job.raw_file == saved
    assert job.title == "test"
    assert job.options.use_gpu is False


def test_start_import_file_ignores_path_in_filename(session_id: str, _isolated_state: Path) -> None:
    resp = client.post(
        "/api/import-file",
        data={"session_id": session_id},
        files={"file": ("../../evil.mp4", b"x", "video/mp4")},
    )

    job_dir = _isolated_state / resp.json()["job_id"]
    assert [p.name for p in job_dir.iterdir()] == ["evil.mp4"]
    assert not (_isolated_state.parent / "evil.mp4").exists()


# ---------------------------------------------------------------------------
# POST /api/preview
# ---------------------------------------------------------------------------


def test_preview_returns_link_details() -> None:
    info = {"title": "Clip", "thumbnail": "https://i/x.jpg", "duration": 61, "uploader": "Bob"}
    with patch("local_encoder.server.get_video_info", return_value=info) as mock_info:
        data = client.post("/api/preview", json={"url": "https://example.com/v"}).json()
        client.post("/api/preview", json={"url": "https://example.com/v"})

    assert data == {
        "ok": True,
        "title": "Clip",
        "thumbnail": "https://i/x.jpg",
        "duration_s": 61,
        "uploader": "Bob",
        "source_site": "",
    }
    mock_info.assert_called_once()  # the second preview and the job reuse the cached details


@pytest.mark.parametrize(
    ("info", "code"),
    [
        ({"_type": "playlist", "title": "List"}, "playlist_link"),
        ({"title": "Live", "is_live": True}, "live_link"),
    ],
)
def test_preview_rejects_playlists_and_live(info: dict[str, Any], code: str) -> None:
    with patch("local_encoder.server.get_video_info", return_value=info):
        data = client.post("/api/preview", json={"url": "https://example.com/v"}).json()
    assert data["ok"] is False
    assert data["error"]["code"] == code


def test_preview_rejects_non_web_link() -> None:
    data = client.post("/api/preview", json={"url": "C:\\video.mp4"}).json()
    assert data["error"]["code"] == "invalid_url"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _pipeline_patches(
    mock_client: MagicMock,
    tmp_path: Path,
    media: MediaInfo | None = None,
) -> list[Any]:
    mp4 = tmp_path / "video_720p.mp4"
    mp4.write_bytes(b"x")
    zip_file = tmp_path / "video.zip"
    zip_file.write_bytes(b"x")
    raw = tmp_path / "video.mkv"
    raw.write_bytes(b"raw")
    return [
        patch("local_encoder.server.AVideoClient", return_value=mock_client),
        patch("local_encoder.server.encode_mp4_multi", return_value=[mp4]),
        patch("local_encoder.server.encode_hls", return_value=zip_file),
        patch("local_encoder.server.extract_thumbnail_jpg"),
        patch("local_encoder.server.extract_thumbnail_gif"),
        patch("local_encoder.server.extract_thumbnail_webp"),
        patch("local_encoder.server.probe_duration", return_value=10.0),
        patch(
            "local_encoder.server.probe_media",
            return_value=media or MediaInfo(width=1280, height=720, has_video=True, has_audio=True),
        ),
        patch("local_encoder.server.detect_video_codec", return_value=SOFTWARE_CODEC),
        patch("local_encoder.server.download_video", return_value=raw),
        patch("local_encoder.server.get_video_info", return_value={"title": "Clip"}),
    ]


def _run(job: server.Job, mock_client: MagicMock, tmp_path: Path, **kw: Any) -> dict[str, Any]:
    """Run the pipeline with everything mocked; return the mocks by patched name."""
    mocks: dict[str, Any] = {}
    with ExitStack() as stack:
        for p in _pipeline_patches(mock_client, tmp_path, **kw):
            mocks[p.attribute] = stack.enter_context(p)
        server._pipeline(job)
    return mocks


def test_pipeline_reuses_session_token_without_login(tmp_path: Path) -> None:
    mock_client = _mock_client()
    job = _job(fmt="mp4", resolutions=[720])
    _run(job, mock_client, tmp_path)

    mock_client.login.assert_not_called()
    mock_client.notify_done.assert_called_once_with(9, "h")
    upload_kwargs = mock_client.upload_file.call_args.kwargs
    assert upload_kwargs["resolution"] == 720
    assert upload_kwargs["download_url"] == "https://example.com/watch"
    assert job.status == "done"
    assert job.result is not None
    assert job.result["edit_url"].endswith("view/managerVideosLight.php?videos_id=9")


def test_pipeline_hls_zip_has_no_resolution(tmp_path: Path) -> None:
    mock_client = _mock_client()
    _run(_job(fmt="hls"), mock_client, tmp_path)

    assert mock_client.register_video.call_args.kwargs["resolution"] is None
    assert mock_client.upload_file.call_args.kwargs["resolution"] is None


def test_pipeline_sends_mp4_when_site_cannot_play_hls(tmp_path: Path) -> None:
    mock_client = _mock_client()
    job = _job(session=_session(_login(video_hls=False)), fmt="hls")
    with patch("local_encoder.server.encode_hls") as mock_hls:
        _run(job, mock_client, tmp_path)

    assert mock_client.register_video.call_args.kwargs["format_ext"] == "mp4"
    assert job.encoded_fmt == "mp4"
    assert {"code": "hls_unavailable"} in job.notices
    mock_hls.assert_not_called()


def test_pipeline_auto_uses_hls_when_available(tmp_path: Path) -> None:
    mock_client = _mock_client()
    job = _job()
    _run(job, mock_client, tmp_path)
    assert job.encoded_fmt == "hls"


def test_pipeline_limits_qualities_to_the_user_allowed_list(tmp_path: Path) -> None:
    mock_client = _mock_client()
    job = _job(session=_session(_login(allowed=[360, 720])), fmt="mp4")
    mock_mp4 = _run(job, mock_client, tmp_path)["encode_mp4_multi"]

    assert mock_mp4.call_args.kwargs["resolutions"] == [360, 720]
    assert mock_mp4.call_args.kwargs["codec"] is SOFTWARE_CODEC


def test_pipeline_rejects_audio_only_files(tmp_path: Path) -> None:
    mock_client = _mock_client()
    with pytest.raises(LocalEncoderError) as excinfo:
        _run(
            _job(),
            mock_client,
            tmp_path,
            media=MediaInfo(width=0, height=0, has_video=False, has_audio=True),
        )
    assert excinfo.value.code == "audio_only"
    mock_client.register_video.assert_not_called()


def test_pipeline_rejects_playlist_links(tmp_path: Path) -> None:
    with (
        patch("local_encoder.server.get_video_info", return_value={"_type": "playlist"}),
        patch("local_encoder.server.download_video") as mock_download,
        pytest.raises(LocalEncoderError) as excinfo,
    ):
        server._pipeline(_job())
    assert excinfo.value.code == "playlist_link"
    mock_download.assert_not_called()


def test_pipeline_notifies_failure_when_upload_fails(tmp_path: Path) -> None:
    mock_client = _mock_client()
    mock_client.upload_file.side_effect = AVideoAPIError("boom")

    with pytest.raises(AVideoAPIError):
        _run(_job(fmt="mp4"), mock_client, tmp_path)

    mock_client.notify_failed.assert_called_once_with(9, "h")
    mock_client.notify_done.assert_not_called()


def test_retry_reuses_converted_files_and_the_same_video(tmp_path: Path) -> None:
    mock_client = _mock_client()
    job = _job(fmt="mp4")
    mock_client.upload_file.side_effect = AVideoAPIError("boom")
    with pytest.raises(AVideoAPIError):
        _run(job, mock_client, tmp_path)

    mock_client.upload_file.side_effect = None
    mocks = _run(job, mock_client, tmp_path)

    mocks[
        "encode_mp4_multi"
    ].assert_not_called()  # converted files from the first attempt were reused
    assert mock_client.register_video.call_args.kwargs["videos_id"] == 9


def test_cancel_during_upload_stops_and_notifies_failure(tmp_path: Path) -> None:
    mock_client = _mock_client()
    job = _job(fmt="mp4")

    def fake_upload(**kwargs: Any) -> dict[str, Any]:
        job.cancel_event.set()
        kwargs["progress_callback"]("video_720p.mp4", 1, 2)
        return {}

    mock_client.upload_file.side_effect = fake_upload
    with pytest.raises(JobCancelled):
        _run(job, mock_client, tmp_path)
    mock_client.notify_failed.assert_called_once_with(9, "h")


# ---------------------------------------------------------------------------
# Running a job: final state, files, notifier
# ---------------------------------------------------------------------------


def test_run_job_error_keeps_files_and_has_a_code(tmp_path: Path) -> None:
    job = _job()
    job.work_dir.mkdir(parents=True)
    (job.work_dir / "video_720p.mp4").write_bytes(b"x")
    with patch(
        "local_encoder.server._pipeline", side_effect=LocalEncoderError("no_disk_space", {})
    ):
        server._run_job(job)

    assert job.status == "error"
    assert job.error is not None
    assert job.error["code"] == "no_disk_space"
    assert (job.work_dir / "video_720p.mp4").exists()


def test_run_job_success_deletes_files(tmp_path: Path) -> None:
    job = _job()
    job.work_dir.mkdir(parents=True)

    def done(j: server.Job) -> None:
        j.emit("done", {"videos_id": 1})

    with patch("local_encoder.server._pipeline", side_effect=done):
        server._run_job(job)

    assert job.status == "done"
    assert not job.work_dir.exists()


def test_run_job_cancelled(tmp_path: Path) -> None:
    job = _job()
    with patch("local_encoder.server._pipeline", side_effect=JobCancelled()):
        server._run_job(job)
    assert job.status == "cancelled"


def test_notifier_called_when_no_page_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    server.set_notifier(lambda kind, title: calls.append((kind, title)))
    job = _job(title="My clip")
    with patch("local_encoder.server._pipeline", side_effect=RuntimeError("x")):
        server._run_job(job)
    assert calls == [("error", "My clip")]


def test_notifier_skipped_while_a_page_is_open() -> None:
    calls: list[Any] = []
    server.set_notifier(lambda kind, title: calls.append(kind))
    subscriber = server._subscribe()
    try:
        with patch("local_encoder.server._pipeline", side_effect=RuntimeError("x")):
            server._run_job(_job())
    finally:
        server._unsubscribe(subscriber)
    assert calls == []


# ---------------------------------------------------------------------------
# Event stream
# ---------------------------------------------------------------------------


def _events(subscriber: queue.Queue[str | None]) -> list[tuple[str, Any]]:
    result = []
    while not subscriber.empty():
        msg = subscriber.get_nowait()
        assert msg is not None
        lines = msg.strip().splitlines()
        result.append((lines[0].removeprefix("event: "), json.loads(lines[1][len("data: ") :])))
    return result


def test_subscriber_first_gets_every_job_with_logs() -> None:
    job = _job()
    job.log("hello")
    subscriber = server._subscribe()
    try:
        events = _events(subscriber)
    finally:
        server._unsubscribe(subscriber)

    assert events[0][0] == "jobs"
    snapshot = events[0][1]["jobs"][0]
    assert snapshot["job_id"] == job.id
    assert snapshot["logs"][-1].endswith("hello")


def test_subscriber_receives_job_changes() -> None:
    subscriber = server._subscribe()
    try:
        job = _job()
        job.emit("progress", {"step": "encode", "pct": 140})
        events = _events(subscriber)
    finally:
        server._unsubscribe(subscriber)

    names = [name for name, _ in events]
    assert names == ["jobs", "added", "progress"]
    assert events[2][1] == {"job_id": job.id, "step": "encode", "pct": 140}
    assert job.pct["encode"] == 100  # stored values are capped


def test_events_endpoint_is_registered() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/events" in paths


# ---------------------------------------------------------------------------
# Job actions
# ---------------------------------------------------------------------------


def test_cancel_pending_job() -> None:
    job = _job()
    client.post(f"/api/jobs/{job.id}/cancel")
    assert job.status == "cancelled"


def test_cancel_running_job_sets_the_flag() -> None:
    job = _job()
    job.status = "running"
    client.post(f"/api/jobs/{job.id}/cancel")
    assert job.cancel_event.is_set()


def test_retry_requeues_a_failed_job(session_id: str) -> None:
    job = _job()
    job.emit("error", {"code": "site_timeout"})
    server._work_queue.get_nowait()

    resp = client.post(f"/api/jobs/{job.id}/retry", json={"session_id": session_id})

    assert resp.json()["ok"] is True
    assert job.status == "pending"
    assert job.error is None
    assert job.session is server._sessions[session_id]
    assert server._work_queue.get_nowait() == job.id


def test_retry_refuses_active_job() -> None:
    job = _job()
    assert client.post(f"/api/jobs/{job.id}/retry", json={}).status_code == 409


def test_retry_refuses_a_session_of_another_site(monkeypatch: pytest.MonkeyPatch) -> None:
    other = server._Session("https://other.example/", True, _login(), time.time())
    monkeypatch.setattr("local_encoder.server._sessions", {"s": other})
    job = _job()
    job.emit("error", {"code": "x"})
    assert client.post(f"/api/jobs/{job.id}/retry", json={"session_id": "s"}).status_code == 400


def test_remove_job_deletes_its_files() -> None:
    job = _job()
    job.emit("error", {"code": "x"})
    job.work_dir.mkdir(parents=True)
    (job.work_dir / "a.mp4").write_bytes(b"x")

    client.post(f"/api/jobs/{job.id}/remove", json={"delete_files": True})

    assert job.id not in server._jobs
    assert not job.work_dir.exists()


def test_remove_running_job_is_refused() -> None:
    job = _job()
    job.status = "running"
    assert client.post(f"/api/jobs/{job.id}/remove", json={}).status_code == 409


def test_open_folder_opens_the_job_folder() -> None:
    job = _job()
    job.work_dir.mkdir(parents=True)
    with patch("local_encoder.server._open_path") as mock_open:
        assert client.post(f"/api/jobs/{job.id}/open-folder").status_code == 200
    mock_open.assert_called_once_with(job.work_dir)


def test_unknown_job_is_404() -> None:
    assert client.post("/api/jobs/nope/cancel").status_code == 404


# ---------------------------------------------------------------------------
# Report a problem
# ---------------------------------------------------------------------------


def test_redact_removes_passwords_and_tokens() -> None:
    text = (
        'pass=hunter2&user=bob "video_id_hash": "abc123" token _user_hash_XYZ.9 X-Encoder-Pass: t0k'
    )
    clean = server.redact(text)
    for secret in ("hunter2", "abc123", "XYZ.9", "t0k"):
        assert secret not in clean
    assert "user=bob" in clean


def test_report_zips_redacted_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "local-encoder.log"
    log.write_text("login ok pass=hunter2\n", encoding="utf-8")
    monkeypatch.setattr("local_encoder.server.log_file_path", lambda: log)
    job = _job()
    job.emit("error", {"code": "encode_failed"})

    with (
        patch("local_encoder.server._open_path") as mock_open,
        patch("local_encoder.server._ffmpeg_version", return_value="ffmpeg version test"),
    ):
        data = client.post("/api/report", json={"job_id": job.id}).json()

    with zipfile.ZipFile(data["file"]) as zf:
        names = set(zf.namelist())
        log_text = zf.read("local-encoder.log").decode()
    assert {"system.txt", "video.json", "local-encoder.log"} <= names
    assert "hunter2" not in log_text
    assert data["issue_url"].startswith("https://github.com/")
    assert "encode_failed" in data["issue_url"]
    mock_open.assert_called_once()


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------


def test_system_info_starts_gpu_detection_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "local_encoder.server._gpu", {"status": "idle", "key": "", "label": "", "hardware": False}
    )
    started = threading.Event()
    with patch("local_encoder.server._detect_gpu", side_effect=lambda: started.set()):
        client.get("/api/system")
        client.get("/api/system")
    assert started.wait(2)
    assert server._gpu["status"] == "detecting"


def test_stop_running_jobs_cancels_everything() -> None:
    waiting = _job()
    running = _job()
    running.status = "running"

    def finish() -> None:
        running.cancel_event.wait(2)
        running.status = "cancelled"

    threading.Thread(target=finish).start()
    server.stop_running_jobs(timeout=3)

    assert waiting.status == "cancelled"
    assert running.cancel_event.is_set()
    assert running.status == "cancelled"
