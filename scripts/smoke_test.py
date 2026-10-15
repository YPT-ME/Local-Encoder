"""Test the packaged app exactly as users get it (run by .github/workflows/release.yml).

Usage (after `python scripts/make_dist.py <platform>`):
    python scripts/smoke_test.py <platform>

The archive dist/LocalEncoder-<platform>.(zip|tar.gz) is extracted into a temporary folder, and
from there:
  1. `LocalEncoder --version` prints the expected version ($VERSION, when set);
  2. `LocalEncoder selftest --require-bundled`: the FFmpeg, FFprobe and deno shipped in the
     package run, a test clip is converted (MP4, encrypted HLS, thumbnails, MP3), the web page
     files are inside, and every link in $SMOKE_DOWNLOAD_URLS downloads (space-separated;
     $SMOKE_TRY_DOWNLOAD_URLS are only reported);
  3. `LocalEncoder serve --no-browser --no-tray`: the page, its scripts and /api/version answer,
     and a request without the page's header is refused;
  4. `LocalEncoder serve --no-browser` (tray icon): answers too – a failure is only a warning,
     because CI machines may have no desktop.
Standard library only.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def fail(message: str) -> None:
    print(f"::error::{message}")
    raise SystemExit(1)


def extract(platform: str, target: Path) -> Path:
    """Extract the release archive, keeping the executable bits; return the app path."""
    if platform.startswith("linux"):
        with tarfile.open(DIST / f"LocalEncoder-{platform}.tar.gz") as tar:
            tar.extractall(target, filter="tar")  # keeps the executable bits
    else:
        with zipfile.ZipFile(DIST / f"LocalEncoder-{platform}.zip") as zf:
            for info in zf.infolist():
                path = Path(zf.extract(info, target))
                mode = info.external_attr >> 16
                if mode and not platform.startswith("windows"):
                    path.chmod(mode & 0o777)
    folder = target / f"LocalEncoder-{platform}"
    app = folder / ("LocalEncoder.exe" if platform.startswith("windows") else "LocalEncoder")
    if not app.is_file():
        fail(f"{app.name} is missing from the package")
    return app


def run(cmd: list[str], timeout: int) -> str:
    print("$", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )
    print(result.stdout + result.stderr, flush=True)
    if result.returncode != 0:
        fail(f"{' '.join(cmd[1:3])} failed with exit code {result.returncode}")
    return result.stdout


def http(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> int:
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:  # noqa: S310 – local server
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return exc.code


def wait_for_server(base: str, seconds: int) -> str | None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/api/version", timeout=5) as resp:  # noqa: S310
                return resp.read().decode()
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return None


def serve(app: Path, port: int, log: Path, tray: bool) -> subprocess.Popen[bytes]:
    cmd = [str(app), "serve", "--no-browser", "--port", str(port)]
    if not tray:
        cmd.append("--no-tray")
    print("$", " ".join(cmd), flush=True)
    with open(log, "wb") as out:
        return subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT)


def stop(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        # The one-file app is a launcher plus a child process; stop both.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    platform = sys.argv[1]
    version = os.environ.get("VERSION", "")
    downloads = os.environ.get("SMOKE_DOWNLOAD_URLS", "").split()
    try_downloads = os.environ.get("SMOKE_TRY_DOWNLOAD_URLS", "").split()

    with tempfile.TemporaryDirectory(
        prefix="local-encoder-smoke-", ignore_cleanup_errors=True
    ) as tmp:
        work = Path(tmp)
        app = extract(platform, work / "package")

        # 1. Version
        out = run([str(app), "--version"], timeout=120)
        if version and version not in out:
            fail(f"--version printed {out.strip()!r}, expected {version}")

        # 2. Everything the app needs, from the package itself
        cmd = [str(app), "selftest", "--require-bundled"]
        for url in downloads:
            cmd += ["--download", url]
        for url in try_downloads:
            cmd += ["--try-download", url]
        out = run(cmd, timeout=900)
        for line in out.splitlines():
            if "[WARN]" in line:
                print(f"::warning::{line.strip()}")

        # 3. The web page (console mode)
        base = "http://127.0.0.1:47899"
        log = work / "serve.log"
        process = serve(app, 47899, log, tray=False)
        try:
            answer = wait_for_server(base, 90)
            if answer is None:
                print(log.read_text(errors="replace"))
                fail("the web page did not start")
            if version and f'"version":"{version}"' not in answer:
                fail(f"/api/version answered {answer}")
            for path in ("/", "/static/i18n.js", "/static/vendor/react.development.js"):
                if http(base + path) != 200:
                    fail(f"{path} did not load")
            refused = http(
                base + "/api/settings", data=b"{}", headers={"Content-Type": "application/json"}
            )
            if refused != 403:
                fail(f"a request without the page header got HTTP {refused}, expected 403")
            print("Web page OK")
        finally:
            stop(process)

        # 4. The tray icon mode (what a double-click starts)
        log = work / "serve-tray.log"
        process = serve(app, 47898, log, tray=True)
        try:
            if wait_for_server("http://127.0.0.1:47898", 60) is None:
                print(log.read_text(errors="replace"))
                print("::warning::The app did not answer in tray mode on this CI machine.")
            else:
                print("Tray mode OK")
        finally:
            stop(process)

    print("Smoke test passed.")


if __name__ == "__main__":
    main()
