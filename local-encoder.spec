# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Local Encoder (one-file executable).

Release builds run in .github/workflows/release.yml on every platform. Local build:
    pip install -e ".[build]"
    python scripts/download_vendor.py          # web UI libraries
    python scripts/fetch_ffmpeg.py <platform>  # static FFmpeg into ./bin (optional)
    python scripts/fetch_deno.py <platform>    # deno (YouTube JS runtime) into ./bin (optional)
    pyinstaller local-encoder.spec
    python scripts/make_dist.py <platform>     # zip/tar.gz with licenses

FFmpeg (./bin, from fetch_ffmpeg.py) is embedded on macOS only; make_dist.py places it next to
the executable on Windows/Linux. These are unmodified third-party GPL builds; make_dist.py ships
their licenses and notices.
"""

import sys
from pathlib import Path

block_cipher = None

HERE = Path(SPECPATH)
BIN_DIR = HERE / "bin"

# FFmpeg and deno are embedded only on macOS (one Gatekeeper approval for the whole app). On
# Windows and Linux scripts/make_dist.py ships bin/ffmpeg*, bin/deno next to the executable
# instead, so ~400 MB are not extracted to a temp folder on every start.
# See local_encoder/_frozen.py.
binaries = []
if sys.platform == "darwin":
    for name in ("ffmpeg", "ffprobe", "deno"):
        candidate = BIN_DIR / name
        if candidate.exists():
            binaries.append((str(candidate), "."))

# The web UI (index.html + vendored React/Tailwind) must ship inside the executable.
# server.py resolves it as <bundle>/local_encoder/static.
STATIC_DIR = HERE / "local_encoder" / "static"
if not (STATIC_DIR / "vendor").is_dir():
    raise SystemExit(
        "local_encoder/static/vendor is missing – run `python scripts/download_vendor.py` first."
    )
datas = [(str(STATIC_DIR), "local_encoder/static")]

a = Analysis(
    ["main.py"],
    pathex=[str(HERE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "yt_dlp",
        "yt_dlp.extractor",
        "yt_dlp.downloader",
        "yt_dlp.postprocessor",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="local-encoder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
