# Local Encoder

[![Latest release](https://img.shields.io/github/v/release/YPT-ME/Local-Encoder?label=download)](https://github.com/YPT-ME/Local-Encoder/releases/latest)
[![CI](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml/badge.svg)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Prepare videos on your own computer and upload them to your [AVideo](https://github.com/WWBN/AVideo) site. Local Encoder converts your videos, creates preview images, and sends the results to your site, with progress shown in your web browser.

**The easiest way to get started is to [download the ready-to-use program for your computer](#download-for-your-computer-recommended).** You do not need a GitHub account, Python, or programming knowledge. The tools needed to process videos are already included.

You will need your **AVideo site address**, an account on that site with permission to upload videos, and a video file or video link. Use the same username and password you use on your AVideo site.

Local Encoder replaces the remote [AVideo Encoder](https://github.com/WWBN/AVideo-Encoder): your own computer prepares the video before uploading it.

---

## Download for your computer (recommended)

**Start here:** click the download link for your computer below. Each link downloads the **latest version** directly, without signing in to GitHub. The file will usually appear in your **Downloads** folder.

| Your computer | Download the program |
| --- | --- |
| Windows 10/11 (64-bit) | **[Download for Windows (.zip)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-windows-x64.zip)** |
| Mac with an Apple chip (M-series) | **[Download for Mac — Apple Silicon (.zip)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-macos-arm64.zip)** |
| Mac with an Intel processor | **[Download for Mac — Intel (.zip)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-macos-x64.zip)** |
| Linux with an Intel or AMD processor (x64) | **[Download for Linux — x64 (.tar.gz)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-linux-x64.tar.gz)** |
| Linux with an ARM64 processor | **[Download for Linux — ARM64 (.tar.gz)](https://github.com/YPT-ME/Local-Encoder/releases/latest/download/LocalEncoder-linux-arm64.tar.gz)** |

To choose the Mac download, open **Apple menu → About This Mac**. If **Chip** shows an Apple M-series chip, choose **Apple Silicon**. If **Processor** shows Intel, choose **Intel**.

The links above contain the program you can open and use. GitHub's green **Code** button and **Source code** downloads are for developers; use the links in this table to get the ready-to-use program.

All versions, checksums and release notes: [Releases](https://github.com/YPT-ME/Local-Encoder/releases).

### 1. Extract the download and open the program

- **Windows:** right-click the downloaded `.zip` file, choose **Extract All**, and open the extracted folder. Double-click **LocalEncoder.exe** (it may appear as **LocalEncoder** if file extensions are hidden).
- **macOS:** double-click the downloaded `.zip` file to extract it, open the extracted folder, and double-click **LocalEncoder**.
- **Linux:** extract the `.tar.gz` file, open a terminal in the extracted folder, and run `./LocalEncoder`.

**Extract the whole download before opening the program. Keep the extracted files together:** the program uses the other tools in that folder to process videos.

A program window opens, then your browser opens the Local Encoder page automatically. This page controls the program running on your computer. If the browser does not open, type the address shown in the program window into your browser (usually `http://127.0.0.1:47800`).

The program is not digitally signed yet, so Windows or macOS may show a warning on the first start:

- **Windows**: "Windows protected your PC" → click **More info** → **Run anyway**.
- **macOS**: after the first attempt, open **System Settings → Privacy & Security** and click **Open Anyway** next to the LocalEncoder message.

### 2. Connect to your AVideo site

1. In **Server URL**, enter your AVideo site's address, for example `https://videos.example.com/`.
2. Enter your AVideo **Username** and **Password**.
3. Click **Connect** and wait for the connection to succeed. If your account cannot upload videos, ask your AVideo site administrator to enable uploads for it.

### 3. Add a video and let the program do the work

1. Under **Import Video**, choose **URL** to paste a video link, or **File Upload** to select a video saved on your computer.
2. Optionally enter a title and choose a category. Leave **Format** set to **Auto** to let the program choose the format for your site.
3. Click **Add to Queue**. The program prepares the video and uploads it automatically; follow the progress on the page.
4. When the job finishes successfully, click **View** to open the video on your AVideo site.

**Keep your computer on and the Local Encoder program window open until the upload finishes.** Closing that window stops the program.

### Updating the program

When the Local Encoder page shows **New version available**, download the new version for your computer using the table above. After any running jobs finish, close the old program, extract the new download, and open the new copy. Keep the new copy's files together too.

New versions are released automatically when [yt-dlp](https://github.com/yt-dlp/yt-dlp), the tool used to download videos, is updated, helping downloads from YouTube and other sites keep working.

---

## Screenshots

<img width="958" height="548" alt="chrome-capture-2026-05-29 (1)" src="https://github.com/user-attachments/assets/ad9b7e29-2e23-4f40-b3ad-1681af772221" />


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

## For developers and advanced users

For everyday use, choose the [ready-to-use download](#download-for-your-computer-recommended). The sections below explain how to run or modify the Python source code and how releases are built.

### Technical Highlights

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

### Architecture

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

### Run from source (optional, for developers)

This option requires **Python 3.11+**, **Git**, and **FFmpeg + FFprobe** (see [External Tools](#external-tools)). The ready-to-use downloads above already include the tools they need.

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

### Development

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)

```bash
pip install -e ".[dev]"

pytest
ruff check .
mypy local_encoder
```

---

### Tech Stack

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

### Requirements for running from source

* Python 3.11+
* FFmpeg + FFprobe — see [External Tools](#external-tools) below

> **yt-dlp** is a Python package and is installed automatically with `pip install -e .` — no manual setup needed.

---

### External Tools

These setup instructions apply when running from source. FFmpeg and FFprobe are already included in the ready-to-use downloads.

#### FFmpeg and FFprobe

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

### Releasing

Releases are built by [`.github/workflows/release.yml`](.github/workflows/release.yml) for Windows, macOS (Apple Silicon and Intel) and Linux (x64 and ARM64), and published on [GitHub Releases](https://github.com/YPT-ME/Local-Encoder/releases):

- **Manual**: push a tag (`git tag v1.2.3 && git push origin v1.2.3`) or use *Actions → Release → Run workflow* (empty version = next patch version).
- **Automatic**: [`.github/workflows/yt-dlp-update.yml`](.github/workflows/yt-dlp-update.yml) checks yt-dlp every day; when a new version exists it updates `packaging/build-constraints.txt` and publishes a new release.

Details, local builds and the FFmpeg license notes: [docs/releasing.md](docs/releasing.md).

---

## License

Local Encoder is MIT licensed. The downloads also include third-party software under its own licenses — notably **FFmpeg (GPL)**, shipped unmodified, with its source code attached to each release. See `THIRD_PARTY_NOTICES.md` inside each download.

