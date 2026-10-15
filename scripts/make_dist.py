"""Package the PyInstaller executable with its README, licenses and third-party notices.

Usage (after `pyinstaller local-encoder.spec`):
    python scripts/make_dist.py <platform>

Creates dist/LocalEncoder-<platform>.zip (Windows/macOS) or .tar.gz (Linux) with:
    LocalEncoder[.exe]          the application (FFmpeg and deno embedded on macOS)
    ffmpeg, ffprobe, deno       Windows/Linux only, next to the application
    README.txt                  how to start it (packaging/README-dist.txt)
    LICENSE.txt                 Local Encoder (MIT)
    THIRD_PARTY_NOTICES.md      FFmpeg build + source links, Python packages, JS libraries
    licenses/                   GPL texts, FFmpeg build license, Python package licenses, MIT
and dist/ffmpeg-build-info-<platform>.json for the release workflow (FFmpeg source archive).
Requires pip-licenses (pip install -e ".[build]").
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PACKAGING = ROOT / "packaging"
PLATFORMS = {"windows-x64", "linux-x64", "linux-arm64", "macos-arm64", "macos-x64"}


def runtime_packages(name: str = "local-encoder") -> list[str]:
    """The installed distributions *name* needs at runtime, following requested extras such as
    ``yt-dlp[default]`` (no dev/build extras of local-encoder itself, no build tools)."""
    from packaging.requirements import Requirement  # PyInstaller depends on packaging

    seen: dict[str, str] = {}
    pending: list[tuple[str, frozenset[str]]] = [(name, frozenset())]
    while pending:
        current, extras = pending.pop()
        try:
            dist = metadata.distribution(current)
        except metadata.PackageNotFoundError:
            continue
        key = dist.metadata["Name"].lower().replace("_", "-")
        if key in seen and not extras:
            continue
        seen[key] = dist.metadata["Name"]
        for line in dist.requires or []:
            requirement = Requirement(line)
            marker = requirement.marker
            if marker is not None:
                environments = [{"extra": extra} for extra in extras] or [{"extra": ""}]
                if not any(marker.evaluate(env) for env in environments):
                    continue
            pending.append((requirement.name, frozenset(requirement.extras)))
    seen.pop("local-encoder", None)
    return sorted(seen.values(), key=str.lower)


def _pip_licenses(packages: list[str], fmt: str, *extra: str) -> str:
    return subprocess.run(
        [sys.executable, "-m", "piplicenses", f"--format={fmt}", "--packages", *packages, *extra],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def ffmpeg_details(info: dict[str, str]) -> str:
    if not info:
        return "_FFmpeg was not bundled in this build; Local Encoder uses the FFmpeg on your PATH._"
    return "\n".join(
        [
            "| | |",
            "| --- | --- |",
            f"| Version | `{info['version_line']}` |",
            f"| License | {info['license']} |",
            f"| Build provider | {info['provider']} — {info['provider_url']} |",
            f"| Build scripts (all bundled libraries and versions) | {info['build_scripts']} |",
            f"| Binary downloaded from | {', '.join(info['archive_urls'])} |",
            f"| FFmpeg source code | {info['source_url']} |",
        ]
    )


def deno_details(info_file: Path) -> str:
    if not info_file.exists():
        return "_deno was not bundled in this build._"
    info = json.loads(info_file.read_text(encoding="utf-8"))
    return (
        f"Version `{info['version_line']}` ({info['release']}), license {info['license']}, "
        f"downloaded from {info['archive_url']}. Source code: {info['source_url']}."
    )


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in PLATFORMS:
        raise SystemExit(__doc__)
    platform = sys.argv[1]
    exe = ".exe" if platform.startswith("windows") else ""

    sys.path.insert(0, str(ROOT))
    from local_encoder import __version__

    built = DIST / f"local-encoder{exe}"
    if not built.exists():
        raise SystemExit(f"{built} not found – run `pyinstaller local-encoder.spec` first")

    stage = DIST / f"LocalEncoder-{platform}"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "licenses").mkdir(parents=True)

    app = stage / f"LocalEncoder{exe}"
    shutil.copy2(built, app)
    app.chmod(app.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if not platform.startswith("macos"):  # embedded in the executable on macOS (see the spec)
        for tool in ("ffmpeg", "ffprobe", "deno"):
            source = ROOT / "bin" / f"{tool}{exe}"
            if source.exists():
                shutil.copy2(source, stage / source.name)
                target = stage / source.name
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    readme = (PACKAGING / "README-dist.txt").read_text(encoding="utf-8")
    (stage / "README.txt").write_text(readme.replace("{{VERSION}}", __version__), encoding="utf-8")
    shutil.copy2(ROOT / "LICENSE", stage / "LICENSE.txt")
    for license_file in (PACKAGING / "licenses").iterdir():
        shutil.copy2(license_file, stage / "licenses" / license_file.name)

    info_file = ROOT / "bin" / "ffmpeg-build-info.json"
    info: dict[str, str] = (
        json.loads(info_file.read_text(encoding="utf-8")) if info_file.exists() else {}
    )
    if (ROOT / "bin" / "FFmpeg-LICENSE.txt").exists():
        shutil.copy2(ROOT / "bin" / "FFmpeg-LICENSE.txt", stage / "licenses" / "FFmpeg-LICENSE.txt")
    if info:
        shutil.copy2(info_file, DIST / f"ffmpeg-build-info-{platform}.json")

    packages = runtime_packages()
    notices = (PACKAGING / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    notices = notices.replace("{{FFMPEG_BUILD_DETAILS}}", ffmpeg_details(info))
    notices = notices.replace(
        "{{DENO_BUILD_DETAILS}}", deno_details(ROOT / "bin" / "deno-build-info.json")
    )
    notices = notices.replace(
        "{{PYTHON_PACKAGES}}", _pip_licenses(packages, "markdown", "--with-urls").strip()
    )
    (stage / "THIRD_PARTY_NOTICES.md").write_text(notices, encoding="utf-8")
    (stage / "licenses" / "python-packages.txt").write_text(
        _pip_licenses(packages, "plain-vertical", "--with-license-file", "--no-license-path"),
        encoding="utf-8",
    )

    if platform.startswith("linux"):
        archive = DIST / f"LocalEncoder-{platform}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(stage, arcname=stage.name)
    else:
        archive = DIST / f"LocalEncoder-{platform}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    entry = zipfile.ZipInfo.from_file(path, path.relative_to(DIST).as_posix())
                    # Keep the executable bit so macOS can start the app after unzipping.
                    entry.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(entry, path.read_bytes())
    print(f"Created {archive} ({archive.stat().st_size // 1_048_576} MiB)")


if __name__ == "__main__":
    main()
