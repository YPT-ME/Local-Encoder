# Development

[![CI](https://img.shields.io/github/actions/workflow/status/YPT-ME/Local-Encoder/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml)
[![Release build](https://img.shields.io/github/actions/workflow/status/YPT-ME/Local-Encoder/release.yml?style=flat-square&label=release)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/release.yml)
[![yt-dlp updates](https://img.shields.io/github/actions/workflow/status/YPT-ME/Local-Encoder/yt-dlp-update.yml?branch=main&style=flat-square&label=yt-dlp%20updates)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/yt-dlp-update.yml)

For everyday use, [download the app](../README.md#download).

## Run from source

Requires **Python 3.11+**, **Git**, **FFmpeg** and **FFprobe**.
yt-dlp installs with the project; YouTube downloads also use **deno**.

```bash
git clone https://github.com/YPT-ME/Local-Encoder
cd Local-Encoder
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
local-encoder serve
```

The page opens at `http://127.0.0.1:47800`, or another free port.

## Architecture

```text
Browser (React + Tailwind)         CLI (Typer)
         │ JSON + SSE                  │
         ▼                             ▼
    FastAPI → in-memory queue → worker pipeline
                                ├── yt-dlp: download
                                ├── FFmpeg: encode + previews
                                └── httpx: AVideo upload
```

- **Media:** multi-resolution H.264, AES-128 HLS, MP3, JPG/GIF/WebP; hardware encoding with software fallback.
- **Reliability:** chunk retries, retained files after failure and explicit site confirmation before success.
- **Desktop:** tray icon, sleep prevention and per-user browser launch registration.
- **Distribution:** PyInstaller packages for Windows x64, macOS ARM64/x64 and Linux x64/ARM64.

The browser UI and CLI use the same media and AVideo modules. The queue survives page reloads,
not process restarts. [Protocol](avideo-encoder-protocol.md) · [Parity and limitations](encoder-parity.md) · [Browser integration](browser-integration.md)

## CLI

```bash
local-encoder --help
local-encoder import --help
local-encoder logs
local-encoder selftest --allow-system-tools
```

## Checks

```bash
pytest
ruff check .
ruff format --check .
mypy local_encoder
```

[CI](../.github/workflows/ci.yml) tests Python 3.11–3.13 on Linux, plus Python 3.12 on Windows
and macOS. It checks mypy for all three platforms and runs a real FFmpeg self-test.
Changes to encoding or the AVideo protocol also need a real-site integration test.

## External tools

Packaged downloads include the tools. From source, put FFmpeg/FFprobe in `bin/`, set
`FFMPEG_BIN` / `FFPROBE_BIN` in `.env`, or install them on `PATH`.
Use `DENO_BIN` to select deno explicitly.
See [.env.example](../.env.example) for settings.

## Releases

Push a version tag or run **Actions → Release → Run workflow**. The daily yt-dlp workflow
also triggers releases when updates are available.
[Builds, signing and licenses](releasing.md) · [Contributing](../CONTRIBUTING.md)
