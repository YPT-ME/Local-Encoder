# local-encoder

A Python 3.11+ tool that downloads a video from any URL supported by yt-dlp,
re-encodes it with FFmpeg, generates thumbnails, and uploads the result to an
[AVideo](https://github.com/WWBN/AVideo) server.

Comes with a **web UI** (`local-encoder serve`) for easy browser-based use,
or a **CLI** (`local-encoder import <url>`) for scripting.

---

## Requirements

| Tool | Minimum version | Notes |
|------|-----------------|-------|
| Python | 3.11 | |
| FFmpeg / FFprobe | 4.x+ | Must be on `PATH` or set via `FFMPEG_BIN` / `FFPROBE_BIN` |
| yt-dlp | latest | Installed automatically as a Python dependency |

---

## Installation

```bash
# Clone / copy the project
cd avideo-local-encoder

# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# Install the package and all dependencies
pip install -e .
```

---

## Web UI

```bash
local-encoder serve
# Open http://localhost:8000 in your browser
```

Server URL, credentials, category and SSL settings are entered in the browser
and saved automatically in `localStorage` — no config file needed.

---

## Configuration (optional)

Only needed if you use the CLI or want to override binary paths.
Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `AVIDEO_KEEP_FILES` | `true` to keep encoded files after upload | `false` |
| `FFMPEG_BIN` | Path to `ffmpeg` binary | `ffmpeg` |
| `FFPROBE_BIN` | Path to `ffprobe` binary | `ffprobe` |
| `YTDLP_BIN` | Path to `yt-dlp` binary | `yt-dlp` |

---

## CLI Usage

```bash
# Basic import (reads server/credentials from CLI flags or .env)
local-encoder import "https://youtu.be/dQw4w9WgXcQ"

# Override server and credentials on the command line
local-encoder import "https://youtu.be/dQw4w9WgXcQ" \
    --server https://myavideo.example.com/ \
    --user admin \
    --password secret

# Encode at 720p instead of the default 1080p
local-encoder import "https://youtu.be/..." --resolution 720

# Assign to category 3, keep temp files, verbose logging
local-encoder import "https://youtu.be/..." \
    --categories-id 3 \
    --keep-files \
    --debug

# Use a self-signed certificate (disables TLS verification)
local-encoder import "https://local.avideo/" --ssl-no-verify
```

---

## Pipeline

```
URL
 │
 ▼
[yt-dlp] ── download ──► raw video file (.mp4 preferred)
 │
 ▼
[FFmpeg] ── encode ────► {title}_{res}p.mp4   (H.264, AVideo bitrate ladder)
 │
 ├─ [FFmpeg] ── thumbnail ──► {title}.jpg  (single frame, 640×360)
 ├─ [FFmpeg] ── thumbnail ──► {title}.gif  (3 s animated, 320×180, palette)
 └─ [FFmpeg] ── thumbnail ──► {title}.webp (3 s animated, 640×360, lossless)
 │
 ▼
[AVideo API]
  1. POST /login               → encrypted session password
  2. POST /aVideoEncoder.json  (first_request=1) → videos_id + video_id_hash
  3. PUT  /aVideoEncoderChunk.json × N           → chunked file upload (500 MB/chunk)
  4. POST /aVideoEncoder.json  (chunkFile=…)     → finalize file on server
  5. POST /objects/aVideoEncoderReceiveImage.json.php → thumbnails
  6. POST /objects/aVideoEncoderNotifyIsDone.json.php → publish video
```

---

## Supported resolutions

`240` | `360` | `480` | `540` | `720` | `1080` | `1440` | `2160`

If you specify a non-listed value (e.g. `--resolution 900`) the nearest
supported resolution is used automatically.

---

## Development

```bash
pip install -e ".[dev]"

# Run tests
pytest

# Lint / format
ruff check .
ruff format .

# Type-check
mypy local_encoder
```

---

## Known Limitations / Gaps

See [GAPS.md](GAPS.md) for a list of AVideo server-side behaviours that could
not be fully verified from the source code.

---

## License

MIT
