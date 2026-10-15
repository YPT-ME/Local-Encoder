"""Tests for the FastAPI server endpoints."""

from __future__ import annotations

import json
import time
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
)
from local_encoder.server import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/jobs
# ---------------------------------------------------------------------------


def test_list_jobs_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_encoder.server._job_order", [])
    monkeypatch.setattr("local_encoder.server._jobs", {})
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_jobs_returns_pending_job(monkeypatch: pytest.MonkeyPatch) -> None:
    import queue as q

    fake_jobs: dict[str, Any] = {
        "abc123": {
            "status": "pending",
            "queue": q.Queue(),
            "runner": lambda jid: None,
            "title": "Test Video",
            "thumbnail": "http://example.com/thumb.jpg",
            "pct": {"download": 0, "encode": 0, "upload": 0},
        }
    }
    monkeypatch.setattr("local_encoder.server._jobs", fake_jobs)
    monkeypatch.setattr("local_encoder.server._job_order", ["abc123"])
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["job_id"] == "abc123"
    assert data[0]["status"] == "pending"
    assert data[0]["title"] == "Test Video"


def test_list_jobs_skips_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_encoder.server._jobs", {})
    monkeypatch.setattr("local_encoder.server._job_order", ["ghost"])
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Helpers – sessions and mocked AVideo client
# ---------------------------------------------------------------------------


def _login(categories: list[dict[str, Any]] | None = None) -> LoginResult:
    return LoginResult(
        is_logged=True,
        can_upload=True,
        encrypted_pass="_user_hash_token",
        username="alice",
        user_id=7,
        name="Alice",
        categories=categories if categories is not None else [{"id": 1, "name": "News"}],
    )


def _mock_client(login: LoginResult | None = None) -> MagicMock:
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.login.return_value = login or _login()
    return mock_client


@pytest.fixture()
def session_id(monkeypatch: pytest.MonkeyPatch) -> str:
    sessions = {
        "sess-1": server._Session(
            server_url="https://avideo.example.com/",
            ssl_verify=True,
            login=_login(),
            created=time.time(),
        )
    }
    monkeypatch.setattr("local_encoder.server._sessions", sessions)
    return "sess-1"


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    out = tmp_path / "output"
    monkeypatch.setattr("local_encoder.server.OUTPUT_DIR", out)
    return out


# ---------------------------------------------------------------------------
# POST /api/test-connection
# ---------------------------------------------------------------------------


def test_test_connection_success_creates_session(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: dict[str, Any] = {}
    monkeypatch.setattr("local_encoder.server._sessions", sessions)

    with patch("local_encoder.server.AVideoClient", return_value=_mock_client()):
        resp = client.post(
            "/api/test-connection",
            json={"server_url": "https://example.com", "username": "alice", "password": "secret"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["name"] == "Alice"
    assert "logo_url" in data
    assert data["categories"] == [{"id": 1, "name": "News"}]
    assert data["session_id"] in sessions
    # The password is never echoed back.
    assert "secret" not in resp.text


def test_test_connection_failure() -> None:
    mock_client = _mock_client()
    mock_client.login.side_effect = AVideoAPIError("bad password")

    with patch("local_encoder.server.AVideoClient", return_value=mock_client):
        resp = client.post(
            "/api/test-connection",
            json={
                "server_url": "https://example.com",
                "username": "alice",
                "password": "wrongpass",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "bad password" in data["error"]


def test_test_connection_adds_trailing_slash() -> None:
    with patch("local_encoder.server.AVideoClient") as MockClient:
        MockClient.return_value = _mock_client()
        client.post(
            "/api/test-connection",
            json={
                "server_url": "https://example.com",  # no trailing slash
                "username": "bob",
                "password": "pass",
            },
        )
        called_url = MockClient.call_args[0][0]
        assert called_url.endswith("/")


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


# ---------------------------------------------------------------------------
# POST /api/session
# ---------------------------------------------------------------------------


def test_session_resumes_without_login(session_id: str) -> None:
    with patch("local_encoder.server.AVideoClient") as MockClient:
        resp = client.post("/api/session", json={"session_id": session_id})

    assert resp.status_code == 200
    assert resp.json()["name"] == "Alice"
    MockClient.return_value.login.assert_not_called()


def test_session_unknown_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_encoder.server._sessions", {})
    resp = client.post("/api/session", json={"session_id": "nope"})
    assert resp.status_code == 401


def test_session_expired_returns_401(session_id: str) -> None:
    server._sessions[session_id].created -= server.SESSION_TTL_SECONDS + 1
    resp = client.post("/api/session", json={"session_id": session_id})
    assert resp.status_code == 401
    assert session_id not in server._sessions


def test_categories_endpoint_with_password_in_url_is_gone() -> None:
    resp = client.get("/api/categories", params={"username": "u", "password": "p"})
    assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# POST /api/import
# ---------------------------------------------------------------------------


def test_start_import_returns_job_id(session_id: str) -> None:
    with patch("local_encoder.server._enqueue") as mock_enqueue:
        resp = client.post(
            "/api/import",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "session_id": session_id},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert len(data["job_id"]) == 36  # UUID format
    mock_enqueue.assert_called_once()


def test_start_import_enqueues_with_correct_job_id(session_id: str) -> None:
    captured: list[str] = []

    def fake_enqueue(job_id: str, runner: object) -> None:
        captured.append(job_id)

    with patch("local_encoder.server._enqueue", side_effect=fake_enqueue):
        resp = client.post(
            "/api/import",
            json={"url": "https://example.com/video", "session_id": session_id},
        )

    assert resp.json()["job_id"] == captured[0]


def test_start_import_requires_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_encoder.server._sessions", {})
    with patch("local_encoder.server._enqueue") as mock_enqueue:
        resp = client.post(
            "/api/import", json={"url": "https://example.com/v", "session_id": "missing"}
        )
    assert resp.status_code == 401
    mock_enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/import-file
# ---------------------------------------------------------------------------


def test_start_import_file_returns_job_id(session_id: str, _isolated_output: Path) -> None:
    with patch("local_encoder.server._enqueue"):
        resp = client.post(
            "/api/import-file",
            data={"session_id": session_id},
            files={"file": ("test.mp4", b"\x00" * 16, "video/mp4")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["job_id"]) == 36
    saved = _isolated_output / data["job_id"] / "test.mp4"
    assert saved.read_bytes() == b"\x00" * 16


def test_start_import_file_ignores_path_in_filename(
    session_id: str, _isolated_output: Path
) -> None:
    with patch("local_encoder.server._enqueue"):
        resp = client.post(
            "/api/import-file",
            data={"session_id": session_id},
            files={"file": ("../../evil.mp4", b"x", "video/mp4")},
        )

    job_dir = _isolated_output / resp.json()["job_id"]
    assert [p.name for p in job_dir.iterdir()] == ["evil.mp4"]
    assert not (_isolated_output.parent / "evil.mp4").exists()


# ---------------------------------------------------------------------------
# Job cleanup
# ---------------------------------------------------------------------------


def test_finish_job_keeps_files_after_failure(tmp_path: Path) -> None:
    encoded = tmp_path / "video_720p.mp4"
    encoded.write_bytes(b"x")
    logs: list[Any] = []

    server._finish_job({"status": "error"}, lambda e, d: logs.append(d), [encoded], tmp_path)

    assert encoded.exists()
    assert any("kept" in d["msg"] for d in logs)


def test_finish_job_deletes_files_after_success(tmp_path: Path) -> None:
    work = tmp_path / "job"
    work.mkdir()
    encoded = work / "video_720p.mp4"
    encoded.write_bytes(b"x")

    server._finish_job({"status": "done"}, lambda e, d: None, [encoded], work)

    assert not work.exists()


# ---------------------------------------------------------------------------
# _run_pipeline – upload phase
# ---------------------------------------------------------------------------


def _pipeline_patches(mock_client: MagicMock, tmp_path: Path, fmt: str) -> list[Any]:
    encoded = tmp_path / ("video.zip" if fmt == "hls" else "video_720p.mp4")
    encoded.write_bytes(b"x")
    return [
        patch("local_encoder.server.AVideoClient", return_value=mock_client),
        patch("local_encoder.server.encode_mp4_multi", return_value=[encoded]),
        patch("local_encoder.server.encode_hls", return_value=encoded),
        patch("local_encoder.server.extract_thumbnail_jpg"),
        patch("local_encoder.server.extract_thumbnail_gif"),
        patch("local_encoder.server.extract_thumbnail_webp"),
        patch("local_encoder.server.probe_duration", return_value=10.0),
    ]


def _run(tmp_path: Path, mock_client: MagicMock, fmt: str) -> None:
    from contextlib import ExitStack

    mock_client.get_server_config.return_value = ServerConfig()
    mock_client.register_video.return_value = RegisterVideoResult(videos_id=9, video_id_hash="h")
    session = server._Session("https://avideo.example.com/", True, _login(), time.time())
    with ExitStack() as stack:
        for p in _pipeline_patches(mock_client, tmp_path, fmt):
            stack.enter_context(p)
        server._run_pipeline(
            emit=lambda e, d: None,
            raw_file=tmp_path / "video.mkv",
            work_dir=tmp_path,
            files_to_clean=[],
            session=session,
            categories_id=0,
            video_title="T",
            video_description="",
            duration=10.0,
            fmt=fmt,
            resolutions=[720],
            cfg=server.Config(),
            source_url="https://example.com/watch",
        )


def test_pipeline_reuses_session_token_without_login(tmp_path: Path) -> None:
    mock_client = _mock_client()
    _run(tmp_path, mock_client, "mp4")

    mock_client.login.assert_not_called()
    mock_client.use_login.assert_called_once()
    mock_client.notify_done.assert_called_once_with(9, "h")
    upload_kwargs = mock_client.upload_file.call_args.kwargs
    assert upload_kwargs["resolution"] == 720
    assert upload_kwargs["download_url"] == "https://example.com/watch"


def test_pipeline_hls_zip_has_no_resolution(tmp_path: Path) -> None:
    mock_client = _mock_client()
    _run(tmp_path, mock_client, "hls")

    assert mock_client.register_video.call_args.kwargs["resolution"] is None
    assert mock_client.upload_file.call_args.kwargs["resolution"] is None


def test_pipeline_notifies_failure_when_upload_fails(tmp_path: Path) -> None:
    mock_client = _mock_client()
    mock_client.upload_file.side_effect = AVideoAPIError("boom")

    with pytest.raises(AVideoAPIError):
        _run(tmp_path, mock_client, "mp4")

    mock_client.notify_failed.assert_called_once_with(9, "h")
    mock_client.notify_done.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/import/{job_id}/progress (SSE)
# ---------------------------------------------------------------------------


def test_progress_stream_404_for_unknown_job() -> None:
    resp = client.get("/api/import/nonexistent-job-id/progress")
    assert resp.status_code == 404


def test_progress_stream_sends_connected_and_done(monkeypatch: pytest.MonkeyPatch) -> None:
    import queue as q

    msg_queue: q.Queue[str | None] = q.Queue()
    msg_queue.put(f"event: done\ndata: {json.dumps({'videos_id': 42})}\n\n")
    msg_queue.put(None)  # signal end

    fake_jobs: dict[str, Any] = {
        "test-job-1": {
            "status": "done",
            "queue": msg_queue,
            "runner": lambda jid: None,
            "title": "",
            "thumbnail": "",
            "pct": {"download": 0, "encode": 0, "upload": 0},
        }
    }
    monkeypatch.setattr("local_encoder.server._jobs", fake_jobs)

    with client.stream("GET", "/api/import/test-job-1/progress") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.read().decode()

    assert ": connected" in body
    assert "event: status" in body
    assert '"status": "done"' in body
    assert "event: done" in body


def test_progress_stream_sends_pending_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import queue as q

    msg_queue: q.Queue[str | None] = q.Queue()
    msg_queue.put(None)  # end immediately

    fake_jobs: dict[str, Any] = {
        "test-job-pending": {
            "status": "pending",
            "queue": msg_queue,
            "runner": lambda jid: None,
            "title": "",
            "thumbnail": "",
            "pct": {"download": 0, "encode": 0, "upload": 0},
        }
    }
    monkeypatch.setattr("local_encoder.server._jobs", fake_jobs)

    with client.stream("GET", "/api/import/test-job-pending/progress") as resp:
        body = resp.read().decode()

    assert '"status": "pending"' in body


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


def test_index_returns_html() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
