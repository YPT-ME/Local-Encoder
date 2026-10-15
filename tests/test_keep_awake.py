"""Tests for local_encoder.keep_awake (no real OS calls)."""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from local_encoder import keep_awake


class FakeBackend:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def start(self) -> None:
        self.calls.append("start")
        if self.fail:
            raise RuntimeError("boom")

    def stop(self) -> None:
        self.calls.append("stop")
        if self.fail:
            raise RuntimeError("boom")


@pytest.fixture
def fake_backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    backend = FakeBackend()
    monkeypatch.setattr(keep_awake, "_inhibitor", keep_awake._Inhibitor(backend))
    return backend


# ---------------------------------------------------------------------------
# Reference counting
# ---------------------------------------------------------------------------


def test_nested_inhibit_starts_and_stops_once(fake_backend: FakeBackend) -> None:
    with keep_awake.inhibit():
        assert fake_backend.calls == ["start"]
        with keep_awake.inhibit():
            assert fake_backend.calls == ["start"]
        assert fake_backend.calls == ["start"]
    assert fake_backend.calls == ["start", "stop"]

    with keep_awake.inhibit():
        pass
    assert fake_backend.calls == ["start", "stop", "start", "stop"]


def test_inhibit_releases_on_exception(fake_backend: FakeBackend) -> None:
    with pytest.raises(ValueError), keep_awake.inhibit():
        raise ValueError("job failed")
    assert fake_backend.calls == ["start", "stop"]


def test_backend_errors_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeBackend(fail=True)
    monkeypatch.setattr(keep_awake, "_inhibitor", keep_awake._Inhibitor(backend))
    with keep_awake.inhibit():
        pass
    assert backend.calls == ["start", "stop"]


def test_extra_release_is_ignored() -> None:
    backend = FakeBackend()
    inhibitor = keep_awake._Inhibitor(backend)
    inhibitor.release()
    assert inhibitor.count == 0
    assert backend.calls == []


def test_concurrent_inhibit_is_balanced() -> None:
    backend = FakeBackend()
    inhibitor = keep_awake._Inhibitor(backend)

    def worker() -> None:
        for _ in range(200):
            inhibitor.acquire()
            inhibitor.release()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert inhibitor.count == 0
    assert backend.calls.count("start") == backend.calls.count("stop") >= 1
    assert backend.calls[-1] == "stop"


def test_shutdown_stops_active_block() -> None:
    backend = FakeBackend()
    inhibitor = keep_awake._Inhibitor(backend)
    inhibitor.acquire()
    inhibitor.acquire()
    inhibitor.shutdown()
    assert inhibitor.count == 0
    assert backend.calls == ["start", "stop"]
    inhibitor.shutdown()
    assert backend.calls == ["start", "stop"]


# ---------------------------------------------------------------------------
# Platform selection
# ---------------------------------------------------------------------------


def test_macos_uses_caffeinate_bound_to_our_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keep_awake.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(keep_awake.os, "getpid", lambda: 4321)
    backend = keep_awake._make_backend("darwin")
    assert isinstance(backend, keep_awake._ProcessBackend)
    assert backend._argv == ["/usr/bin/caffeinate", "-i", "-w", "4321"]


def test_linux_uses_systemd_inhibit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keep_awake.shutil, "which", lambda name: f"/usr/bin/{name}")
    backend = keep_awake._make_backend("linux")
    assert isinstance(backend, keep_awake._ProcessBackend)
    assert backend._argv == [
        "/usr/bin/systemd-inhibit",
        "--what=sleep:idle",
        "--who=Local Encoder",
        f"--why={keep_awake.REASON}",
        "--mode=block",
        "cat",
    ]
    assert backend._stdin_pipe is True


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_missing_helper_is_a_noop(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(keep_awake.shutil, "which", lambda name: None)
    assert isinstance(keep_awake._make_backend(platform), keep_awake._NoopBackend)


def test_unknown_platform_is_a_noop() -> None:
    assert isinstance(keep_awake._make_backend("freebsd14"), keep_awake._NoopBackend)


def test_windows_platform_uses_thread_backend() -> None:
    assert isinstance(keep_awake._make_backend("win32"), keep_awake._WindowsBackend)


# ---------------------------------------------------------------------------
# Process backend (macOS / Linux)
# ---------------------------------------------------------------------------


def test_process_backend_starts_and_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    popen = MagicMock(return_value=proc)
    monkeypatch.setattr(keep_awake.subprocess, "Popen", popen)

    backend = keep_awake._ProcessBackend(["/usr/bin/systemd-inhibit", "cat"], stdin_pipe=True)
    backend.start()
    backend.start()  # already running: no second process
    assert popen.call_count == 1
    args, kwargs = popen.call_args
    assert args[0] == ["/usr/bin/systemd-inhibit", "cat"]
    assert kwargs["stdin"] == subprocess.PIPE
    assert "shell" not in kwargs

    backend.stop()
    proc.stdin.close.assert_called_once()
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once()
    backend.stop()  # nothing left to stop
    proc.terminate.assert_called_once()


def test_process_backend_kills_when_terminate_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.stdin = None
    proc.wait.side_effect = [subprocess.TimeoutExpired("caffeinate", 5), 0]
    monkeypatch.setattr(keep_awake.subprocess, "Popen", MagicMock(return_value=proc))
    backend = keep_awake._ProcessBackend(["caffeinate"])
    backend.start()
    backend.stop()
    proc.kill.assert_called_once()


def test_process_backend_start_failure_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        keep_awake.subprocess, "Popen", MagicMock(side_effect=FileNotFoundError("nope"))
    )
    backend = keep_awake._ProcessBackend(["caffeinate"])
    backend.start()
    backend.stop()
    assert backend._proc is None


# ---------------------------------------------------------------------------
# Windows backend
# ---------------------------------------------------------------------------


def _wait_for(predicate: Any, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_windows_backend_sets_and_clears_from_one_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    def fake_set(flags: int) -> bool:
        calls.append((flags, threading.get_ident()))
        return True

    monkeypatch.setattr(keep_awake, "_set_thread_execution_state", fake_set)
    backend = keep_awake._WindowsBackend()
    inhibitor = keep_awake._Inhibitor(backend)

    inhibitor.acquire()
    inhibitor.acquire()
    _wait_for(lambda: len(calls) == 1)
    inhibitor.release()
    inhibitor.release()
    _wait_for(lambda: len(calls) == 2)

    continuous = keep_awake._ES_CONTINUOUS
    system_required = keep_awake._ES_SYSTEM_REQUIRED
    assert [flags for flags, _ in calls] == [continuous | system_required, continuous]
    assert calls[0][1] == calls[1][1] != threading.get_ident()


def test_windows_backend_survives_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def failing_set(flags: int) -> bool:
        calls.append(flags)
        raise OSError("denied")

    monkeypatch.setattr(keep_awake, "_set_thread_execution_state", failing_set)
    backend = keep_awake._WindowsBackend()
    backend.start()
    _wait_for(lambda: len(calls) == 1)
    backend.stop()
    _wait_for(lambda: len(calls) == 2)
    assert calls[1] == keep_awake._ES_CONTINUOUS
