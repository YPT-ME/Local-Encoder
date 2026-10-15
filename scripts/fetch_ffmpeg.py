"""Download a static GPL FFmpeg build (ffmpeg + ffprobe) into ./bin for packaging.

Usage:
    python scripts/fetch_ffmpeg.py <platform>

Platforms: windows-x64, linux-x64, linux-arm64, macos-arm64, macos-x64

Sources (unmodified third-party builds):
  windows / linux : https://github.com/BtbN/FFmpeg-Builds  (newest "nX.Y-latest" release branch)
  macOS           : https://ffmpeg.martin-riedl.de          (latest release build)

Writes bin/ffmpeg-build-info.json, which scripts/make_dist.py turns into the FFmpeg section of
THIRD_PARTY_NOTICES.md and the release workflow uses to attach the matching FFmpeg source code.
Only the standard library is used. Set GH_TOKEN/GITHUB_TOKEN to avoid GitHub API rate limits.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "bin"

BTBN_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest"
BTBN_PLATFORM = {"windows-x64": "win64", "linux-x64": "linux64", "linux-arm64": "linuxarm64"}
RIEDL_PLATFORM = {"macos-arm64": "arm64", "macos-x64": "amd64"}
RIEDL_URL = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/{tool}.zip"


def _get(url: str, api: bool = False) -> bytes:
    headers = {"User-Agent": "local-encoder-release"}
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if api and token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=600) as resp:  # noqa: S310 – fixed https URLs
        data: bytes = resp.read()
        return data


def _btbn_asset(platform: str) -> dict[str, Any]:
    """Newest release-branch GPL build for *platform* (e.g. ffmpeg-n9.0-latest-win64-gpl-9.0.zip)."""
    target = BTBN_PLATFORM[platform]
    pattern = re.compile(rf"^ffmpeg-n(\d+(?:\.\d+)*)-latest-{target}-gpl-[\d.]+\.(zip|tar\.xz)$")
    release = json.loads(_get(BTBN_API, api=True))
    candidates = []
    for asset in release["assets"]:
        match = pattern.match(asset["name"])
        if match:
            version = tuple(int(p) for p in match.group(1).split("."))
            candidates.append((version, asset))
    if not candidates:
        raise SystemExit(f"No BtbN GPL release build found for {platform}")
    return max(candidates, key=lambda c: c[0])[1]


def _write_binary(name: str, data: bytes) -> Path:
    BIN_DIR.mkdir(exist_ok=True)
    target = BIN_DIR / name
    target.write_bytes(data)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def _fetch_btbn(platform: str) -> dict[str, Any]:
    asset = _btbn_asset(platform)
    url = asset["browser_download_url"]
    print(f"Downloading {url}")
    data = _get(url)
    exe = ".exe" if platform.startswith("windows") else ""
    wanted = {f"bin/ffmpeg{exe}", f"bin/ffprobe{exe}", "LICENSE.txt"}
    found: dict[str, bytes] = {}
    if asset["name"].endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                short = name.split("/", 1)[-1]
                if short in wanted:
                    found[short] = archive.read(name)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
            for member in archive.getmembers():
                short = member.name.split("/", 1)[-1]
                extracted = archive.extractfile(member) if member.isfile() else None
                if short in wanted and extracted is not None:
                    found[short] = extracted.read()
    for tool in ("ffmpeg", "ffprobe"):
        _write_binary(f"{tool}{exe}", found[f"bin/{tool}{exe}"])
    if "LICENSE.txt" in found:
        (BIN_DIR / "FFmpeg-LICENSE.txt").write_bytes(found["LICENSE.txt"])
    return {
        "provider": "BtbN/FFmpeg-Builds",
        "provider_url": "https://github.com/BtbN/FFmpeg-Builds",
        "build_scripts": "https://github.com/BtbN/FFmpeg-Builds",
        "archive_urls": [url],
    }


def _fetch_riedl(platform: str) -> dict[str, Any]:
    arch = RIEDL_PLATFORM[platform]
    urls = []
    for tool in ("ffmpeg", "ffprobe"):
        url = RIEDL_URL.format(arch=arch, tool=tool)
        print(f"Downloading {url}")
        with zipfile.ZipFile(io.BytesIO(_get(url))) as archive:
            member = next(n for n in archive.namelist() if Path(n).name == tool)
            _write_binary(tool, archive.read(member))
        urls.append(url)
    return {
        "provider": "Martin Riedl FFmpeg builds",
        "provider_url": "https://ffmpeg.martin-riedl.de",
        "build_scripts": "https://git.martin-riedl.de/ffmpeg/build-script",
        "archive_urls": urls,
    }


def source_url_for(version_line: str) -> str:
    """URL of the FFmpeg source code matching ``ffmpeg -version`` (GPL source offer)."""
    match = re.search(r"-g([0-9a-f]{7,40})\b", version_line)
    if match:  # git snapshot of a release branch, e.g. n9.0.2-28-g669f5ab083-20261015
        return f"https://github.com/FFmpeg/FFmpeg/archive/{match.group(1)}.tar.gz"
    match = re.search(r"ffmpeg version n?(\d+(?:\.\d+)+)\b", version_line)
    if match:  # tagged release, e.g. 9.0.2
        return f"https://ffmpeg.org/releases/ffmpeg-{match.group(1)}.tar.xz"
    return "https://ffmpeg.org/download.html#get-sources"


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {*BTBN_PLATFORM, *RIEDL_PLATFORM}:
        raise SystemExit(__doc__)
    platform = sys.argv[1]
    if BIN_DIR.exists():
        shutil.rmtree(BIN_DIR)
    info = _fetch_btbn(platform) if platform in BTBN_PLATFORM else _fetch_riedl(platform)

    exe = ".exe" if platform.startswith("windows") else ""
    version_output = subprocess.run(
        [str(BIN_DIR / f"ffmpeg{exe}"), "-version"], capture_output=True, text=True, check=True
    ).stdout
    version_line = version_output.splitlines()[0]
    configuration = next(
        (line for line in version_output.splitlines() if line.startswith("configuration:")), ""
    )
    info.update(
        {
            "platform": platform,
            "version_line": version_line,
            "configuration": configuration,
            "license": "GPL-3.0-or-later"
            if "--enable-version3" in configuration
            else "GPL-2.0-or-later",
            "source_url": source_url_for(version_line),
        }
    )
    (BIN_DIR / "ffmpeg-build-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"{version_line}\nsource: {info['source_url']}")


if __name__ == "__main__":
    main()
