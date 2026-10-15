"""Tests for the ``serve`` command (fake uvicorn server and tray; no real sockets or icons)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from local_encoder import cli, tray

runner = CliRunner()


class FakeConfig:
    def __init__(self, app: Any, **kwargs: Any) -> None:
        self.app = app
        self.kwargs = kwargs


class FakeServer:
    instances: list[FakeServer] = []
    stay_running = True

    def __init__(self, config: FakeConfig) -> None:
        self.config = config
        self.started = False
        self.should_exit = False
        self.ran = False
        FakeServer.instances.append(self)

    def run(self) -> None:
        self.ran = True
        self.started = True
        deadline = time.monotonic() + 5
        while FakeServer.stay_running and not self.should_exit and time.monotonic() < deadline:
            time.sleep(0.01)


class FakeTrayApp:
    instances: list[FakeTrayApp] = []
    shown = True

    def __init__(self, pystray: Any, **kwargs: Any) -> None:
        self.pystray = pystray
        self.kwargs = kwargs
        FakeTrayApp.instances.append(self)

    def notify(self, kind: str, title: str) -> None:
        pass

    def run(self) -> bool:
        if FakeTrayApp.shown:
            self.kwargs["on_quit"]()  # the user chose Quit
        return FakeTrayApp.shown


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import uvicorn

    FakeServer.instances = []
    FakeServer.stay_running = True
    FakeTrayApp.instances = []
    FakeTrayApp.shown = True
    state: dict[str, Any] = {"opened": [], "notifier": [], "load_pystray": 0}

    def fake_load() -> Any:
        state["load_pystray"] += 1
        return object()

    monkeypatch.setattr(uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.setattr("webbrowser.open", lambda url: state["opened"].append(url))
    monkeypatch.setattr(cli, "_pick_port", lambda host, port: port)
    monkeypatch.setattr(tray, "load_pystray", fake_load)
    monkeypatch.setattr(tray, "TrayApp", FakeTrayApp)
    monkeypatch.setattr(
        tray, "server_hooks", lambda: (lambda: 0, lambda fn: state["notifier"].append(fn))
    )
    return state


# ---------------------------------------------------------------------------
# Already running
# ---------------------------------------------------------------------------


def test_second_start_opens_running_instance(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_pick_port", lambda host, port: 50123)
    monkeypatch.setattr(cli, "_running_instance_url", lambda host, port: f"http://{host}:{port}")
    result = runner.invoke(cli.app, ["serve"])
    assert result.exit_code == 0, result.output
    assert "already running at http://127.0.0.1:47800" in result.output
    assert env["opened"] == ["http://127.0.0.1:47800"]
    assert FakeServer.instances == []


def test_second_start_respects_no_browser(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_pick_port", lambda host, port: 50123)
    monkeypatch.setattr(cli, "_running_instance_url", lambda host, port: "http://127.0.0.1:47800")
    result = runner.invoke(cli.app, ["serve", "--no-browser"])
    assert result.exit_code == 0
    assert env["opened"] == []


def test_busy_port_used_by_another_program_picks_another(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_pick_port", lambda host, port: 50123)
    monkeypatch.setattr(cli, "_running_instance_url", lambda host, port: None)
    result = runner.invoke(cli.app, ["serve", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert "Port 47800 is busy; using 50123 instead." in result.output
    assert FakeServer.instances[0].config.kwargs["port"] == 50123


def test_running_instance_url_checks_api_version(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="http://127.0.0.1:47800/api/version", json={"version": "1.2.3"})
    assert cli._running_instance_url("127.0.0.1", 47800) == "http://127.0.0.1:47800"


def test_running_instance_url_ignores_other_programs(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="http://127.0.0.1:47800/api/version", text="<html>hello</html>")
    assert cli._running_instance_url("127.0.0.1", 47800) is None


def test_running_instance_url_handles_connection_errors(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    assert cli._running_instance_url("0.0.0.0", 47800) is None


def test_local_url_for_wildcard_hosts() -> None:
    assert cli._local_url("127.0.0.1", 1) == "http://127.0.0.1:1"
    assert cli._local_url("0.0.0.0", 2) == "http://127.0.0.1:2"
    assert cli._local_url("::1", 3) == "http://[::1]:3"


# ---------------------------------------------------------------------------
# Tray mode
# ---------------------------------------------------------------------------


def test_tray_mode_runs_server_in_thread_and_quits(env: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["serve"])
    assert result.exit_code == 0, result.output
    server = FakeServer.instances[0]
    assert server.config.kwargs["host"] == "127.0.0.1"
    assert server.config.kwargs["port"] == cli.DEFAULT_PORT
    assert server.config.kwargs["log_level"] == "warning"
    assert server.ran and server.should_exit
    assert env["opened"] == ["http://127.0.0.1:47800"]
    assert "icon near the clock" in result.output

    tray_app = FakeTrayApp.instances[0]
    assert env["notifier"] == [tray_app.notify, None]
    tray_app.kwargs["open_page"]()
    assert env["opened"][-1] == "http://127.0.0.1:47800"


def test_tray_mode_no_browser(env: dict[str, Any]) -> None:
    result = runner.invoke(cli.app, ["serve", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert env["opened"] == []


def test_tray_failure_falls_back_to_console(env: dict[str, Any]) -> None:
    FakeTrayApp.shown = False
    FakeServer.stay_running = False  # the server thread ends by itself
    result = runner.invoke(cli.app, ["serve", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert "Keep this window open" in result.output
    assert FakeServer.instances[0].ran


# ---------------------------------------------------------------------------
# Console mode
# ---------------------------------------------------------------------------


def test_no_tray_runs_server_in_main_thread(env: dict[str, Any]) -> None:
    FakeServer.stay_running = False
    result = runner.invoke(cli.app, ["serve", "--no-tray"])
    assert result.exit_code == 0, result.output
    assert env["load_pystray"] == 0
    assert FakeTrayApp.instances == []
    assert FakeServer.instances[0].ran
    assert "Keep this window open while you use it." in result.output
    deadline = time.monotonic() + 2
    while not env["opened"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert env["opened"] == ["http://127.0.0.1:47800"]


def test_missing_pystray_runs_console_mode(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeServer.stay_running = False
    monkeypatch.setattr(tray, "load_pystray", lambda: None)
    result = runner.invoke(cli.app, ["serve", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert FakeTrayApp.instances == []
    assert "Keep this window open" in result.output
