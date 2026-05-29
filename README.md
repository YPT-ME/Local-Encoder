# Local Encoder

[![CI](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml/badge.svg)](https://github.com/YPT-ME/Local-Encoder/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)

Production-style video ingestion and transcoding pipeline built with Python.

The application downloads videos from external platforms, processes them with FFmpeg, generates thumbnails, and uploads optimized streaming files to an AVideo server — with real-time progress updates streamed to the browser.

---

## Screenshots

### Real-time encoding dashboard

*Add screenshots or GIFs here*

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

---

## Why I built this

I built this project to demonstrate real-world backend engineering skills focused on:

* async APIs
* video processing
* background jobs
* streaming uploads
* third-party integrations
* concurrency
* production-oriented architecture

The project was inspired by real media platform workflows and encoding pipelines.

---

## Quick Start

```bash
git clone https://github.com/YPT-ME/Local-Encoder
cd Local-Encoder

python -m venv .venv
source .venv/bin/activate

pip install -e .

local-encoder serve
```

Open:

```text
http://localhost:8000
```

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
* FFmpeg
* FFprobe
* yt-dlp

---

## License

MIT

