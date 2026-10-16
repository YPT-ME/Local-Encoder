"""Browser links only prepare forms; discovery and OS startup must fail safely."""

from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from local_encoder import desktop, server


def _link(**params: str) -> str:
    return "avideo-local-encoder://open?" + urlencode(params)


@pytest.mark.parametrize(
    "link",
    [
        "https://example.test/open",
        "avideo-local-encoder://import?site=https://example.test/",
        "avideo-local-encoder://open/extra?site=https://example.test/",
        _link(site="file:///etc/passwd"),
        _link(site="https://alice:secret@example.test/"),
        _link(site="https://example.test/?password=secret"),
        _link(site="https://example.test/#fragment"),
        _link(site="https://example.test:99999/"),
        _link(site="https://example.test/", url="C:/private/video.mp4"),
        _link(site="https://example.test/", url="javascript:alert(1)"),
        _link(site="https://example.test/", url="https://user:secret@example.test/video"),
        _link(site="https://example.test/", password="secret"),
        _link(site="https://example.test/", url="https://example.test/\\video"),
        _link(site="https://example.test/", url="https://example.test/a\nb"),
        _link(site="https://example.test/") + "&site=https://other.test/",
        _link(site="https://example.test/") + "#ignored",
        "avideo-local-encoder://open?site=" + "x" * 25000,
    ],
)
def test_reject_untrusted_handoff_without_side_effects(link: str) -> None:
    with pytest.raises(ValueError):
        desktop.parse_link(link)


def test_nested_provider_query_and_site_subdirectory_survive_round_trip() -> None:
    context = {
        "site": "https://example.test:8443/avideo/",
        "url": "https://provider.test/watch?v=a&list=b#t=30",
    }
    parsed = desktop.parse_link(_link(**context))
    assert parsed == context
    page = desktop.page_url("http://127.0.0.1:50123", parsed)
    assert page.startswith("http://127.0.0.1:50123/#avideo=")
    assert "secret" not in page


def test_stale_or_reused_port_does_not_confirm_an_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.setattr(desktop, "DATA_DIR", tmp_path)
    (tmp_path / "instance.json").write_text(
        json.dumps({"url": "http://127.0.0.1:50123", "instance": "old"})
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:50123/api/desktop",
        json={"app": desktop.APP_ID, "instance": "different"},
    )
    assert desktop.running_url() is None


def test_running_instance_on_a_nondefault_port_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.setattr(desktop, "DATA_DIR", tmp_path)
    (tmp_path / "instance.json").write_text(
        json.dumps({"url": "http://127.0.0.1:50123", "instance": "current"})
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:50123/api/desktop",
        json={"app": desktop.APP_ID, "instance": "current"},
    )
    assert desktop.running_url() == "http://127.0.0.1:50123"


@pytest.mark.parametrize(
    "address",
    [
        "https://other.test",
        "http://127.0.0.1:50123/evil",
        "http://user:pass@127.0.0.1:50123",
        "http://127.0.0.1:50123?token=x",
    ],
)
def test_instance_record_cannot_select_an_arbitrary_http_destination(
    address: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desktop, "DATA_DIR", tmp_path)
    (tmp_path / "instance.json").write_text(json.dumps({"url": address, "instance": "current"}))
    assert desktop.running_url() is None


def test_startup_lock_serializes_clicks_and_recovers_after_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desktop, "DATA_DIR", tmp_path)
    first = desktop.StartupLock()
    first.acquire()
    second = desktop.StartupLock()
    with pytest.raises(TimeoutError):
        second.acquire(timeout=0)
    first.release()
    second.acquire(timeout=0)
    second.release()
    second.release()


def test_advertisement_never_deletes_another_instances_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desktop, "DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop, "runtime_url", "http://127.0.0.1:50123")
    path = tmp_path / "instance.json"
    with desktop.advertise():
        assert json.loads(path.read_text())["instance"] == desktop.INSTANCE_ID
        path.write_text(json.dumps({"instance": "someone-else"}))
    assert path.is_file()


def test_discovery_does_not_expose_accounts_or_allow_cross_origin_writes() -> None:
    client = TestClient(server.app, base_url="http://127.0.0.1:47800")
    response = client.get("/api/desktop", headers={"Origin": "https://example.test"})
    assert set(response.json()) == {"app", "instance", "protocol"}
    assert "access-control-allow-origin" not in response.headers
    bridge = client.get("/bridge")
    assert bridge.status_code == 200 and bridge.headers["cache-control"] == "no-store"
    assert "event.source !== window.parent" in bridge.text
    assert "event.origin" in bridge.text and "event.data" in bridge.text
    assert client.post("/api/test-connection", json={}).status_code == 403
    assert client.get("/api/desktop", headers={"host": "other.test"}).status_code == 403


def test_linux_registration_uses_one_url_argument_and_no_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(
        desktop, "launch_command", lambda: ["/opt/a $b/100%/LocalEncoder", "open-url"]
    )
    run = MagicMock()
    monkeypatch.setattr(subprocess, "run", run)
    assert desktop.register_handler(explicit=True)
    entry = (tmp_path / "applications" / "avideo-local-encoder.desktop").read_text()
    assert "100%%" in entry and "x-scheme-handler/avideo-local-encoder;" in entry
    assert entry.count("%u") == 1
    assert run.call_args.args[0] == [
        "xdg-mime",
        "default",
        "avideo-local-encoder.desktop",
        "x-scheme-handler/avideo-local-encoder",
    ]
    assert "shell" not in run.call_args.kwargs


@pytest.mark.parametrize("registration_fails_once", [False, True])
def test_macos_quotes_urls_compiles_once_and_refreshes_the_association(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registration_fails_once: bool
) -> None:
    monkeypatch.setattr(desktop, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        desktop, "launch_command", lambda: ['/Applications/My "Local" Encoder', "open-url"]
    )
    calls = []

    def run(args: list[str], **kwargs: Any) -> None:
        calls.append((args, kwargs))
        if args[0].endswith("osacompile"):
            contents = Path(args[2]) / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({}))
        elif args[0].endswith("lsregister") and registration_fails_once and len(calls) == 3:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", run)
    assert desktop.register_handler(explicit=True) is not registration_fails_once
    assert desktop.register_handler(explicit=True)
    assert len(calls) == 5  # compile once, sign and register on both starts
    assert "quoted form of incomingURL" in calls[0][0][-1]
    assert "x-scheme-handler" not in calls[0][0][-1]
    assert calls[1][0][0] == "/usr/bin/codesign"
    assert calls[2][0][-2] == "-f"


def test_registration_failure_does_not_stop_the_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=FileNotFoundError))
    assert desktop.register_handler(explicit=True) is False


def test_windows_registration_quotes_the_program_and_the_single_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = MagicMock()
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        desktop, "launch_command", lambda: [r"C:\My Local Encoder\LocalEncoder.exe", "open-url"]
    )
    assert desktop.register_handler(explicit=True)
    command = registry.SetValueEx.call_args.args[-1]
    assert command == '"C:\\My Local Encoder\\LocalEncoder.exe" open-url "%1"'
    assert registry.CreateKey.call_args.args[1].endswith(r"\shell\open\command")


def test_native_open_reuses_the_confirmed_instance_without_starting_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from local_encoder import cli

    monkeypatch.setattr(desktop, "DATA_DIR", tmp_path)
    monkeypatch.setattr(desktop, "running_url", lambda: "http://127.0.0.1:50123")
    start = MagicMock()
    browser = MagicMock()
    monkeypatch.setattr(cli, "_serve", start)
    monkeypatch.setattr("webbrowser.open", browser)
    result = CliRunner().invoke(cli.app, ["open-url", _link(site="https://example.test/")])
    assert result.exit_code == 0, result.output
    start.assert_not_called()
    assert browser.call_args.args[0].startswith("http://127.0.0.1:50123/#avideo=")
