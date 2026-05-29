"""Tests for the FastAPI server endpoints."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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
# POST /api/test-connection
# ---------------------------------------------------------------------------


def test_test_connection_success() -> None:
    mock_login = MagicMock(name="alice", username="alice")
    mock_login.name = "Alice"
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.login.return_value = mock_login

    with patch("local_encoder.server.AVideoClient", return_value=mock_client):
        resp = client.post(
            "/api/test-connection",
            json={"server_url": "https://example.com", "username": "alice", "password": "secret"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["name"] == "Alice"
    assert "logo_url" in data


def test_test_connection_failure() -> None:
    from local_encoder.avideo_client import AVideoAPIError

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
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
    mock_login = MagicMock()
    mock_login.name = "Bob"
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.login.return_value = mock_login

    with patch("local_encoder.server.AVideoClient") as MockClient:
        MockClient.return_value = mock_client
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


# ---------------------------------------------------------------------------
# GET /api/categories
# ---------------------------------------------------------------------------


def test_list_categories_success() -> None:
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.login.return_value = MagicMock()
    mock_client.get_categories.return_value = [{"id": 1, "name": "News"}]

    with patch("local_encoder.server.AVideoClient", return_value=mock_client):
        resp = client.get(
            "/api/categories",
            params={"server_url": "https://example.com/", "username": "u", "password": "p"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data == [{"id": 1, "name": "News"}]


def test_list_categories_502_on_error() -> None:
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.login.side_effect = RuntimeError("network error")

    with patch("local_encoder.server.AVideoClient", return_value=mock_client):
        resp = client.get(
            "/api/categories",
            params={"server_url": "https://example.com/", "username": "u", "password": "p"},
        )

    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /api/import
# ---------------------------------------------------------------------------


def test_start_import_returns_job_id() -> None:
    with patch("local_encoder.server._enqueue") as mock_enqueue:
        resp = client.post(
            "/api/import",
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "server_url": "https://avideo.example.com/",
                "username": "admin",
                "password": "pass",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert len(data["job_id"]) == 36  # UUID format
    mock_enqueue.assert_called_once()


def test_start_import_enqueues_with_correct_job_id() -> None:
    captured: list[str] = []

    def fake_enqueue(job_id: str, runner: object) -> None:
        captured.append(job_id)

    with patch("local_encoder.server._enqueue", side_effect=fake_enqueue):
        resp = client.post(
            "/api/import",
            json={
                "url": "https://example.com/video",
                "server_url": "https://avideo.example.com/",
                "username": "admin",
                "password": "pass",
            },
        )

    assert resp.json()["job_id"] == captured[0]


# ---------------------------------------------------------------------------
# POST /api/import-file
# ---------------------------------------------------------------------------


def test_start_import_file_returns_job_id() -> None:
    with patch("local_encoder.server._enqueue"):
        resp = client.post(
            "/api/import-file",
            data={
                "server_url": "https://avideo.example.com/",
                "username": "admin",
                "password": "pass",
            },
            files={"file": ("test.mp4", b"\x00" * 16, "video/mp4")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert len(data["job_id"]) == 36


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
