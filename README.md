# Local Encoder

[![Latest release](https://img.shields.io/github/v/release/YPT-ME/Local-Encoder?label=download)](https://github.com/YPT-ME/Local-Encoder/releases/latest)
[![Total downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/total?label=total%20downloads)](https://github.com/YPT-ME/Local-Encoder/releases)
[![Latest release downloads](https://img.shields.io/github/downloads/YPT-ME/Local-Encoder/latest/total?label=latest%20release%20downloads)](https://github.com/YPT-ME/Local-Encoder/releases/latest)
[![CI](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml/badge.svg)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Prepare videos on your own computer and upload them to your [AVideo](https://github.com/WWBN/AVideo) site. Local Encoder converts your videos, creates preview images, and sends the results to your site, with progress shown in your web browser.

**The easiest way to get started is to [download the ready-to-use program for your computer](#download-for-your-computer-recommended).** You do not need a GitHub account, Python, or programming knowledge. The tools needed to process videos are already included.

You will need your **AVideo site address**, an account on that site with permission to upload videos, and a video file or video link. Use the same username and password you use on your AVideo site.

Local Encoder complements the [AVideo Web Encoder](https://github.com/WWBN/AVideo-Encoder): your computer can prepare video uploads, while the Web Encoder remains required for AVideo's server-side media services, including live previews, video thumbnails and timeline previews, recordings and playlist-to-live processing. Keep your site's **Encoder URL** pointing to a working Web Encoder. See [which AVideo services still require it](docs/encoder-parity.md#avideo-services-that-still-require-the-web-encoder).

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

The **total downloads** badge sums downloads across all releases; **latest release downloads** counts only the newest release and switches automatically when a new version is published. Both use [Shields.io](https://shields.io/badges/git-hub-downloads-all-assets-all-releases) to read each release asset's `download_count` from [GitHub's public API](https://api.github.com/repos/YPT-ME/Local-Encoder/releases?per_page=100), with automatic, cached updates. They include program packages, checksums and attached source archives. Repeat downloads and updates count again, so these measure file downloads rather than unique users or installations.

Hourly observations are stored in the repository's [`download-stats` branch](https://github.com/YPT-ME/Local-Encoder/tree/download-stats). Its page shows downloads per version, platform, UTC day and collection interval. This history starts with the first collector run; it cannot recover the dates of earlier downloads. See [how collection works](docs/download-statistics.md).

### 1. Extract the download and open the program

- **Windows:** right-click the downloaded `.zip` file, choose **Extract All**, and open the extracted folder. Double-click **LocalEncoder.exe** (it may appear as **LocalEncoder** if file extensions are hidden).
- **macOS:** double-click the downloaded `.zip` file to extract it, open the extracted folder, and double-click **LocalEncoder**.
- **Linux:** extract the `.tar.gz` file, open a terminal in the extracted folder, and run `./LocalEncoder`.

**Extract the whole download before opening the program. Keep the extracted files together:** the program uses the other tools in that folder to process videos.

Your browser opens the Local Encoder page automatically. This page controls the program running on your computer. If the browser does not open, go to `http://127.0.0.1:47800`.

On **Windows** no program window opens: Local Encoder lives in the **icon near the clock** (it may be inside the **^** arrow). Click the icon to open the page again; right-click it and choose **Quit** to stop the program, or use **Stop Local Encoder** at the top of the page. Closing the page also stops Local Encoder when no video is being processed (your browser asks first); videos still in the queue keep going after the page is closed. Double-clicking **LocalEncoder.exe** again also just reopens the page. On macOS the icon is in the menu bar.

The page is in English, Portuguese and Spanish: choose the language at the top.

### Open it from AVideo

After opening a current ready-to-use package once, **Open Local Encoder** on an updated AVideo
site or Web Encoder can launch the program, including when it is closed. Accept the browser's
opening prompt if shown. With current versions of all components, your signed-in account connects
automatically. Review the displayed site, account and video before adding it to the queue;
nothing is added automatically. Older sites/apps or a blocked browser check keep manual sign-in
available.

If the program is already running, the AVideo page can detect it and open its control page.
A browser that blocks the check does not mean the program is missing: **Open Local Encoder**,
**Check again** and **Download Local Encoder** remain available. Keep the extracted package in
its folder; after moving or updating it, open the new copy once to refresh browser opening.
See [browser integration and troubleshooting](docs/browser-integration.md).

The program is not digitally signed yet, so Windows or macOS may show a warning on the first start:

- **Windows**: "Windows protected your PC" → click **More info** → **Run anyway**.
- **macOS**: after the first attempt, open **System Settings → Privacy & Security** and click **Open Anyway** next to the LocalEncoder message.

### 2. Connect to your AVideo site (step 1 on the page)

1. Enter your AVideo **site address** (for example `videos.example.com`), your **user name** and your **password**.
2. Click **Connect**. The page then shows what your site receives (for example *Streaming (HLS) · MP4 video · up to 1080p*). If something is wrong, it tells you what to do.
3. Your sites are remembered (never the password), so you can switch between several sites with one click, or remove a site you no longer use.

Local Encoder remembers your choices on this computer (language, sites, last folder, format, qualities and other options), so you do not have to choose them again next time.

### 3. Add videos (step 2 on the page)

1. Paste a video **link**: the page shows its picture, title and length before you add it. Or choose **Files**, or simply **drag video files onto the page** (several at once). Or choose **Folder**: pick a folder on your computer, see its videos (optionally with sub-folders), tick the ones to send. Videos already sent to the current site are marked, and the videos are read where they are (nothing is copied).
2. Optionally enter a title, a category and a description. Leave everything under **Advanced options** as it is unless you need it: the program picks the format and qualities your site accepts, and uses your graphics card when it can (faster).
3. Click **Add to queue**. Each video shows its progress (download, convert, send). You can close the page and open it again later: the queue is still there. You get a notification when a video is sent.
4. When a video is sent, use **Open video**, **Edit on site** or **Copy link**.

If something goes wrong, the video says why in plain words and what to do next. **Try again** continues where it stopped (the work already done is kept), **Open folder** shows the files, and **Report a problem** prepares a file with the logs (without passwords) for a GitHub issue.

Use the **same site and account** when trying a video again; the account is shown next to each video in the queue. Converted files are reused while their format and qualities still match the site's settings. A video is marked complete only after the site confirms it. If a file cannot be added, it and the remaining files stay selected so you can try again. Folder imports add every selected video, and the same file can be queued for different sites or accounts.

While videos are being processed, the computer does not go to sleep. **Keep the computer on until the queue finishes**; quitting Local Encoder stops the videos in progress.

### Updating the program

When the Local Encoder page shows **New version available**, download the new version for your computer using the table above. After any running videos finish, quit the old program (tray icon → **Quit**), extract the new download, and open the new copy. Keep the new copy's files together too.

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
* Automatic transcoding with FFmpeg, with the graphics card when available (NVIDIA, Intel Quick Sync, AMD, Apple), falling back to the processor
* Formats and qualities chosen from what the site accepts (HLS only when the site can play it, per-user quality limits)
* Thumbnail generation:

  * JPG
  * GIF
  * WebP
* Multi-resolution encoding
* Chunked uploads
* Real-time browser progress updates; the queue survives page reloads
* Cancel, try again without starting over, open the work folder, report a problem
* Link preview, drag and drop of several files, several saved sites
* Send videos from a folder on your computer: pick which ones, see which were already sent
* Your choices are remembered (language, sites, last folder, format, qualities, options)
* Desktop notifications, tray icon, the computer kept awake while working
* English, Portuguese and Spanish
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

# Check a whole installation (FFmpeg, a real conversion, page files; no AVideo site needed)
local-encoder selftest --allow-system-tools
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

