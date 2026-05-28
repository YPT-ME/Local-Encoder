# avideo-local-encoder

A Python 3.11+ CLI that downloads a video from any URL supported by yt-dlp,
re-encodes it with FFmpeg at a target resolution, generates thumbnails, and
uploads the result to an [AVideo](https://github.com/WWBN/AVideo) server using
the same encoder API protocol as the built-in PHP encoder.

---

## Requirements

| Tool | Minimum version | Notes |
|------|-----------------|-------|
| Python | 3.11 | |
| FFmpeg / FFprobe | 4.x+ | Must be on `PATH` or configured via env vars |
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

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `AVIDEO_SERVER_URL` | Full URL to your AVideo site (with trailing `/`) | *(required)* |
| `AVIDEO_USERNAME` | AVideo username | *(required)* |
| `AVIDEO_PASSWORD` | AVideo password (plain text; hashed server-side) | *(required)* |
| `AVIDEO_CATEGORIES_ID` | Category ID to assign to imported videos | `0` |
| `AVIDEO_OUTPUT_DIR` | Working directory for temp files | `output` |
| `AVIDEO_KEEP_FILES` | `true` to keep files after upload | `false` |
| `AVIDEO_SSL_VERIFY` | `false` to skip TLS cert verification | `true` |
| `AVIDEO_STREAMERS_ID` | Encoder `streamers_id` sent to the server | `0` |
| `FFMPEG_BIN` | Path to `ffmpeg` binary | `ffmpeg` |
| `FFPROBE_BIN` | Path to `ffprobe` binary | `ffprobe` |
| `YTDLP_BIN` | Path to `yt-dlp` binary (not used directly; Python API is used) | `yt-dlp` |

All variables can also be overridden with CLI flags (see `--help`).

---

## Usage

```bash
# Basic import (reads server/credentials from .env)
avideo-local-encoder import "https://youtu.be/dQw4w9WgXcQ"

# Override server and credentials on the command line
avideo-local-encoder import "https://youtu.be/dQw4w9WgXcQ" \
    --server https://myavideo.example.com/ \
    --user admin \
    --password secret

# Encode at 720p instead of the default 1080p
avideo-local-encoder import "https://youtu.be/..." --resolution 720

# Assign to category 3, keep temp files, verbose logging
avideo-local-encoder import "https://youtu.be/..." \
    --categories-id 3 \
    --keep-files \
    --debug

# Use a self-signed certificate (disables TLS verification)
avideo-local-encoder import "https://local.avideo/" --ssl-no-verify
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
mypy avideo_local_encoder
```

---

## Known Limitations / Gaps

See [GAPS.md](GAPS.md) for a list of AVideo server-side behaviours that could
not be fully verified from the source code.

---

## License

MIT
