"""Browser handoff: public discovery, validated links and per-user OS registration.

An external link only prepares the interface. Browser authorization uses a separate,
proof-key-bound exchange; native links never contain credentials or submit jobs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import plistlib
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

import httpx

from local_encoder.config import APP_DATA_DIR

SCHEME = "avideo-local-encoder"
APP_ID = "avideo-local-encoder"
INSTANCE_ID = secrets.token_hex(16)
DATA_DIR = APP_DATA_DIR
runtime_url = ""
startup_guard: StartupLock | None = None
logger = logging.getLogger(__name__)
_LOGIN_KEY = secrets.token_bytes(32)


def login_verifier(state: str) -> str:
    """A different proof key per discovery, known only to this application instance."""
    if not re.fullmatch(r"[a-f0-9]{32}", state):
        raise ValueError("Invalid browser login state")
    return (
        base64.urlsafe_b64encode(hmac.digest(_LOGIN_KEY, state.encode(), "sha256"))
        .decode()
        .rstrip("=")
    )


def login_challenge(state: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(login_verifier(state).encode()).digest())
        .decode()
        .rstrip("=")
    )


def web_url(value: str, *, site: bool = False) -> str:
    """Accept HTTP(S) only; a site is a base address, never credentials or a query."""
    if (
        not value
        or len(value) > 8192
        or any(ord(c) < 33 or c.isspace() for c in value)
        or "\\" in value
    ):
        raise ValueError("Invalid web address")
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("Expected an HTTP or HTTPS address")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Credentials are not allowed in links")
    _ = parts.port  # reject invalid ports
    if site and (parts.query or parts.fragment):
        raise ValueError("The site address must not contain a query or fragment")
    path = parts.path.rstrip("/") + "/" if site else parts.path
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, parts.query, parts.fragment))


def parse_link(value: str) -> dict[str, str]:
    if len(value) > 24000 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid Local Encoder link")
    parts = urlsplit(value)
    if (
        parts.scheme != SCHEME
        or parts.netloc != "open"
        or parts.path not in ("", "/")
        or parts.fragment
    ):
        raise ValueError("Invalid Local Encoder link")
    params = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
    if not params or set(params) - {"site", "url"} or "site" not in params:
        raise ValueError("A Local Encoder link needs a site address")
    if any(len(values) != 1 for values in params.values()):
        raise ValueError("Duplicate link parameters")
    result = {"site": web_url(params["site"][0], site=True)}
    if params.get("url", [""])[0]:
        result["url"] = web_url(params["url"][0])
    return result


def page_url(base: str, request: dict[str, str] | None = None) -> str:
    if not request:
        return base
    link = f"{SCHEME}://open?{urlencode(request)}"
    return f"{base}/#avideo={quote(link, safe='')}"


class StartupLock:
    """Serialize starts, including two browser clicks arriving before HTTP is ready."""

    def __init__(self) -> None:
        self.stream: BinaryIO | None = None

    def acquire(self, timeout: float = 30.0) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stream = (DATA_DIR / "startup.lock").open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            stream.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                if time.monotonic() >= deadline:
                    stream.close()
                    raise TimeoutError(
                        "Local Encoder is still starting; try opening it again"
                    ) from None
                time.sleep(0.1)
            else:
                self.stream = stream
                return

    def release(self) -> None:
        if self.stream:
            self.stream.close()  # the OS also releases this lock after a crash
            self.stream = None

    def __enter__(self) -> StartupLock:
        self.acquire()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.release()


def running_url() -> str | None:
    """Verify the saved instance identity; stale records never mean 'running'."""
    try:
        record = json.loads((DATA_DIR / "instance.json").read_text(encoding="utf-8"))
        url = record["url"]
        parts = urlsplit(url)
        if parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port:
            return None
        if (
            parts.username is not None
            or parts.password is not None
            or parts.path
            or parts.query
            or parts.fragment
        ):
            return None
        # The lifespan publishes its record just before uvicorn starts accepting requests.
        for attempt in range(5):
            try:
                response = httpx.get(f"{url}/api/desktop", timeout=1, trust_env=False)
                data = response.json()
                if (
                    response.status_code == 200
                    and data.get("app") == APP_ID
                    and data.get("instance") == record["instance"]
                ):
                    return str(url)
                return None
            except httpx.ConnectError:
                if attempt == 4:
                    return None
                time.sleep(0.1)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, httpx.HTTPError):
        return None
    return None


def supports_handoff(url: str) -> bool:
    """An older Local Encoder may be running but cannot consume a browser request."""
    try:
        response = httpx.get(f"{url}/api/desktop", timeout=1, trust_env=False)
        data = response.json()
        return bool(
            response.status_code == 200 and data.get("app") == APP_ID and data.get("protocol") == 1
        )
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


@contextmanager
def advertise() -> Iterator[None]:
    """Publish only the ready loopback instance; clean up only our own record."""
    path = DATA_DIR / "instance.json"
    temporary: Path | None = None
    try:
        if runtime_url.startswith("http://127.0.0.1:"):
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=DATA_DIR, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump({"url": runtime_url, "instance": INSTANCE_ID}, stream)
            temporary.chmod(0o600)
            temporary.replace(path)
    except OSError:
        logger.warning("Could not record the running desktop instance")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not remove a temporary instance record")
        if startup_guard:
            startup_guard.release()
    try:
        yield
    finally:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("instance") == INSTANCE_ID:
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass  # no record, or another instance now owns it


def launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "open-url"]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "main.py"), "open-url"]


def _desktop_exec(command: list[str]) -> str:
    # Desktop Entry quoting has two layers; %u is appended separately as the sole field code.
    def escape(value: str) -> str:
        if any(c in value for c in "\r\n\0"):
            raise ValueError("Invalid application path")
        value = value.replace("%", "%%")
        for character in ("\\", '"', "`", "$"):
            value = value.replace(character, "\\" + character)
        return '"' + value.replace("\\", "\\\\") + '"'

    return " ".join(escape(arg) for arg in command) + " %u"


def _register_macos(command: list[str]) -> None:
    # A small AppleScript app receives the OS's open-location event and starts our binary.
    bundle = DATA_DIR / "browser" / "Local Encoder.app"
    marker = bundle / "Contents" / "Info.plist"
    signature = json.dumps(command)
    previous: dict[str, Any] = {}
    if marker.exists():
        try:
            saved = plistlib.loads(marker.read_bytes())
            if isinstance(saved, dict):
                previous = saved
        except (ValueError, plistlib.InvalidFileException):
            logger.warning("Rebuilding the damaged browser launcher")
    bundle.parent.mkdir(parents=True, exist_ok=True)
    shell_command = shlex.join(command) + " "
    literal = shell_command.replace("\\", "\\\\").replace('"', '\\"')
    source = (
        "on open location incomingURL\n"
        f'  do shell script "{literal}" & quoted form of incomingURL & " > /dev/null 2>&1 &"\n'
        "end open location\n"
    )
    if previous.get("LocalEncoderCommand") != signature:
        subprocess.run(
            ["/usr/bin/osacompile", "-o", str(bundle), "-e", source],
            text=True,
            check=True,
            capture_output=True,
            timeout=30,
        )
        info = plistlib.loads(marker.read_bytes())
        info.update(
            {
                "CFBundleIdentifier": "me.ypt.local-encoder.launcher",
                "CFBundleURLTypes": [
                    {
                        "CFBundleTypeRole": "Viewer",
                        "CFBundleURLName": APP_ID,
                        "CFBundleURLSchemes": [SCHEME],
                    }
                ],
                "LSUIElement": True,
                "LocalEncoderCommand": signature,
            }
        )
        marker.write_bytes(plistlib.dumps(info))
    # Changing Info.plist requires a fresh local signature. Refresh the association even
    # when compilation is unnecessary, including after a failed earlier registration.
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)],
        check=True,
        capture_output=True,
        timeout=15,
    )
    subprocess.run(
        [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
            "-f",
            str(bundle),
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )


def register_handler(*, explicit: bool = False) -> bool:
    """Register for this OS user; a failed association must never stop video processing."""
    if not explicit and not getattr(sys, "frozen", False):
        return False
    command = launch_command()
    try:
        if sys.platform == "win32":
            import winreg

            key_path = rf"Software\Classes\{SCHEME}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:AVideo Local Encoder")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, key_path + r"\shell\open\command"
            ) as key:
                winreg.SetValueEx(
                    key, "", 0, winreg.REG_SZ, subprocess.list2cmdline(command) + ' "%1"'
                )
        elif sys.platform == "darwin":
            _register_macos(command)
        elif sys.platform.startswith("linux"):
            directory = (
                Path(os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share"))
                / "applications"
            )
            directory.mkdir(parents=True, exist_ok=True)
            entry = directory / "avideo-local-encoder.desktop"
            entry.write_text(
                "[Desktop Entry]\nType=Application\nName=Local Encoder\nNoDisplay=true\n"
                f"Exec={_desktop_exec(command)}\nMimeType=x-scheme-handler/{SCHEME};\nTerminal=false\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["xdg-mime", "default", entry.name, f"x-scheme-handler/{SCHEME}"],
                check=True,
                capture_output=True,
                timeout=15,
            )
        else:
            return False
    except (OSError, ValueError, subprocess.SubprocessError, plistlib.InvalidFileException):
        logger.warning(
            "Could not enable browser opening; the application can still be opened manually"
        )
        return False
    return True
