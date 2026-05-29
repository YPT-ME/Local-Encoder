# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for avideo-local-encoder.

Build (Windows):
    pyinstaller avideo-local-encoder.spec

Build (macOS/Linux):
    pyinstaller avideo-local-encoder.spec

Bundles ffmpeg + ffprobe from the ./bin/ directory if present.
Download static builds:
  Windows : https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
  macOS   : https://evermeet.cx/ffmpeg/
  Linux   : https://johnvansickle.com/ffmpeg/

Place the binaries at:
  bin/ffmpeg.exe  + bin/ffprobe.exe   (Windows)
  bin/ffmpeg      + bin/ffprobe       (macOS/Linux)
"""

import sys
from pathlib import Path

block_cipher = None

HERE = Path(SPECPATH)
BIN_DIR = HERE / "bin"

# Collect bundled FFmpeg binaries (optional – build works without them too)
suffix = ".exe" if sys.platform == "win32" else ""
binaries = []
for name in ("ffmpeg", "ffprobe"):
    candidate = BIN_DIR / f"{name}{suffix}"
    if candidate.exists():
        binaries.append((str(candidate), "."))

a = Analysis(
    ["main.py"],
    pathex=[str(HERE)],
    binaries=binaries,
    datas=[],
    hiddenimports=[
        "yt_dlp",
        "yt_dlp.extractor",
        "yt_dlp.downloader",
        "yt_dlp.postprocessor",
        "keyring",
        "keyring.backends",
        "keyring.backends.fail",
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
    name="avideo-local-encoder",
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
