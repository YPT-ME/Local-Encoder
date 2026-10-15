"""Download the deno JavaScript runtime into ./bin for packaging.

Usage:
    python scripts/fetch_deno.py <platform>

Platforms: windows-x64, linux-x64, linux-arm64, macos-arm64, macos-x64

yt-dlp needs a JavaScript runtime to solve YouTube's challenges; without one some formats are
missing (https://github.com/yt-dlp/yt-dlp/wiki/EJS). The app passes this binary to yt-dlp
(local_encoder/downloader.py). Source: the latest official release of
https://github.com/denoland/deno (MIT). Writes bin/deno-build-info.json for the notices.
Only the standard library is used. Set GH_TOKEN/GITHUB_TOKEN to avoid GitHub API rate limits.
"""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "bin"
RELEASE_API = "https://api.github.com/repos/denoland/deno/releases/latest"
TARGETS = {
    "windows-x64": "x86_64-pc-windows-msvc",
    "linux-x64": "x86_64-unknown-linux-gnu",
    "linux-arm64": "aarch64-unknown-linux-gnu",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x64": "x86_64-apple-darwin",
}


def _get(url: str, api: bool = False) -> bytes:
    headers = {"User-Agent": "local-encoder-release"}
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if api and token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=600) as resp:  # noqa: S310 – fixed https URLs
        data: bytes = resp.read()
        return data


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        raise SystemExit(__doc__)
    platform = sys.argv[1]
    exe = ".exe" if platform.startswith("windows") else ""

    release = json.loads(_get(RELEASE_API, api=True))
    asset_name = f"deno-{TARGETS[platform]}.zip"
    asset = next((a for a in release["assets"] if a["name"] == asset_name), None)
    if asset is None:
        raise SystemExit(f"{asset_name} not found in deno {release['tag_name']}")
    url = asset["browser_download_url"]
    print(f"Downloading {url}")
    with zipfile.ZipFile(io.BytesIO(_get(url))) as archive:
        data = archive.read(f"deno{exe}")

    BIN_DIR.mkdir(exist_ok=True)
    target = BIN_DIR / f"deno{exe}"
    target.write_bytes(data)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    version_line = subprocess.run(
        [str(target), "--version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()[0]
    info = {
        "platform": platform,
        "version_line": version_line,
        "release": release["tag_name"],
        "archive_url": url,
        "license": "MIT",
        "source_url": f"https://github.com/denoland/deno/tree/{release['tag_name']}",
    }
    (BIN_DIR / "deno-build-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(version_line)


if __name__ == "__main__":
    main()
