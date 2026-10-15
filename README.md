# Local Encoder

[![Latest release](https://img.shields.io/github/v/release/YPT-ME/Local-Encoder?label=download)](https://github.com/YPT-ME/Local-Encoder/releases/latest)
[![CI](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml/badge.svg)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)

Production-style video ingestion and transcoding pipeline built with Python.

The application downloads videos from external platforms, processes them with FFmpeg, generates thumbnails, and uploads optimized streaming files to an AVideo server — with real-time progress updates streamed to the browser.

It replaces the remote [AVideo Encoder](https://github.com/WWBN/AVideo-Encoder): your own computer does the encoding and sends the result to your [AVideo](https://github.com/WWBN/AVideo) site.

---

## Download

Ready-to-use program, no installation and no Python needed (FFmpeg is included). These links always download the **latest version**:

| System | Download |
| --- | --- |
| Windows 10/11 (64-bit) | [LocalEncoder-windows-x64.zip](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-windows-x64.zip) |
| macOS Apple Silicon (M1/M2/M3/M4) | [LocalEncoder-macos-arm64.zip](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-macos-arm64.zip) |
| macOS Intel | [LocalEncoder-macos-x64.zip](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-macos-x64.zip) |
| Linux (x64) | [LocalEncoder-linux-x64.tar.gz](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-linux-x64.tar.gz) |
| Linux (ARM64) | [LocalEncoder-linux-arm64.tar.gz](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-linux-arm64.tar.gz) |

All versions, checksums and release notes: [Releases](https://github.com/YPT-ME/Local-Encoder/releases).

**How to start**

1. Unzip the download and open **LocalEncoder** (`LocalEncoder.exe` on Windows; on Linux run `./LocalEncoder` in a terminal).
2. Your browser opens the Local Encoder page. Type your AVideo site address, user and password, click **Connect**, and import a video link or file.
3. Keep the Local Encoder window open while you use it.

The program is not digitally signed yet, so the first start shows a warning:

- **Windows**: "Windows protected your PC" → click **More info** → **Run anyway**.
- **macOS**: after the first attempt, open **System Settings → Privacy & Security** and click **Open Anyway** next to the LocalEncoder message.

When a new version is published, the Local Encoder page shows a "New version available" link. New versions are released automatically whenever [yt-dlp](https://github.com/yt-dlp/yt-dlp) is updated, so downloads from YouTube and other sites keep working.

---

## Screenshots

<img width="958" height="548" alt="chrome-capture-2026-05-29 (1)" src="https://github.com/user-attachments/assets/ad9b7e29-2e23-4f40-b3ad-1681af772221" />


---

## Technical Highlights

* FastAPI backend with async endpoints
* Real-time progress streaming using SSE
* Background worker architecture with thread-safe queues
* FFmpeg transcoding pipeline
* Multi-resolution HLS-ready encoding
* Chunked uploads for large files
* HTTP integrations using `httpx`
* Typed Python codebase with strict `mypy`
* Automated CI with GitHub Actions
* Unit tests with `pytest`

---

## Features

* Import videos from:

  * YouTube
  * Vimeo
  * 10,000+ platforms via `yt-dlp`
  * Local files
* Automatic transcoding with FFmpeg
* Thumbnail generation:

  * JPG
  * GIF
  * WebP
* Multi-resolution encoding
* Chunked uploads
* Real-time browser progress updates
* CLI interface
* Web dashboard

---

## Architecture

```text
Browser (React + SSE)
        │
        ▼
FastAPI API Server
        │
        ▼
Thread-safe Job Queue
        │
        ▼
Worker Pipeline
   ├── yt-dlp
   ├── FFmpeg
   └── AVideo API
```

## Quick Start

```bash
git clone https://github.com/YPT-ME/Local-Encoder
cd Local-Encoder

python -m venv .venv
source .venv/bin/activate

pip install -e .

local-encoder serve
```

Your browser opens the page automatically (default address `http://127.0.0.1:47800`; another free port is used if that one is busy).

---

## Development

```bash
pip install -e ".[dev]"

pytest
ruff check .
mypy local_encoder
```

---

## Tech Stack

| Area             | Technologies    |
| ---------------- | --------------- |
| Backend          | FastAPI, httpx  |
| Video Processing | FFmpeg, yt-dlp  |
| Frontend         | React, Tailwind |
| Testing          | pytest          |
| Tooling          | Ruff, mypy      |
| Packaging        | Hatchling       |
| CI/CD            | GitHub Actions  |

---

## Requirements

* Python 3.11+
* FFmpeg + FFprobe — see [External Tools](#external-tools) below

> **yt-dlp** is a Python package and is installed automatically with `pip install -e .` — no manual setup needed.

---

## External Tools

### FFmpeg and FFprobe

The application resolves `ffmpeg` and `ffprobe` in this order:

| Priority | Method | How |
|---|---|---|
| 1 | Bundled binaries | Place `ffmpeg` / `ffprobe` (or `.exe` on Windows) inside a `bin/` folder at the project root |
| 2 | Environment variables | Set `FFMPEG_BIN` and `FFPROBE_BIN` in `.env` |
| 3 | System PATH | Have `ffmpeg` and `ffprobe` available globally |

**Option A — Standalone (recommended for portability):**

```text
Local-Encoder/
└── bin/
    ├── ffmpeg.exe     ← Windows
    └── ffprobe.exe
```

Download static builds from [ffmpeg.org/download.html](https://ffmpeg.org/download.html) or [github.com/BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds).  
Extract and copy only `ffmpeg` and `ffprobe` into the `bin/` folder — no install required.

**Option B — Environment variable:**

```bash
# .env
FFMPEG_BIN=C:/tools/ffmpeg/bin/ffmpeg.exe
FFPROBE_BIN=C:/tools/ffmpeg/bin/ffprobe.exe
```

**Option C — System PATH:**

Install FFmpeg via your package manager and verify:

```bash
ffmpeg -version
ffprobe -version
```

---

## Releasing

Releases are built by [`.github/workflows/release.yml`](.github/workflows/release.yml) for Windows, macOS (Apple Silicon and Intel) and Linux (x64 and ARM64), and published on [GitHub Releases](https://github.com/YPT-ME/Local-Encoder/releases):

- **Manual**: push a tag (`git tag v1.2.3 && git push origin v1.2.3`) or use *Actions → Release → Run workflow* (empty version = next patch version).
- **Automatic**: [`.github/workflows/yt-dlp-update.yml`](.github/workflows/yt-dlp-update.yml) checks yt-dlp every day; when a new version exists it updates `packaging/build-constraints.txt` and publishes a new release.

Details, local builds and the FFmpeg license notes: [docs/releasing.md](docs/releasing.md).

---

## License

Local Encoder is MIT licensed. The downloads also include third-party software under its own licenses — notably **FFmpeg (GPL)**, shipped unmodified, with its source code attached to each release. See `THIRD_PARTY_NOTICES.md` inside each download.

