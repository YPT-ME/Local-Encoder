---
name: "Local Encoder Python"
description: "Use when writing or changing any Python code in Local Encoder. Covers module layout, typing (mypy strict), ruff, subprocess/FFmpeg calls, logging, errors, configuration, and cross-platform paths."
applyTo: "**/*.py"
---

# Local Encoder — Python Rules

## Module Map (one responsibility each — put new code where it belongs)

| Module | Responsibility |
| --- | --- |
| `local_encoder/avideo_client.py` | Every HTTP call to an AVideo site (login, register, chunk upload, images, notify, config, categories). No other module talks HTTP to AVideo. |
| `local_encoder/encoder.py` | Every FFmpeg command (MP4, HLS, MP3, thumbnails) and FFprobe probing used by encoding (`probe_media`). `ENCODING_SETTINGS` mirrors the PHP Encoder. Hardware encoders (`detect_video_codec`, software fallback), cancel (`cancel_event` → `EncodeCancelled`). |
| `local_encoder/downloader.py` | `yt-dlp` integration (used as a Python library, not the CLI binary). `_external_tools()` gives yt-dlp the bundled FFmpeg and deno, which are not on PATH in the packaged app. |
| `local_encoder/server.py` | FastAPI web UI backend: `Job` objects (state, logs, files kept for “Try again”), single worker thread, one SSE stream for the whole queue (`/api/events`), job actions, preview, report. |
| `local_encoder/errors.py` | Turns any exception into a stable `code` + English message (`classify`); the web UI translates the code (`static/i18n.js`, `err.<code>`). Raise `LocalEncoderError(code)` for problems Local Encoder detects itself. |
| `local_encoder/keep_awake.py` | `inhibit()`: keeps the computer awake while videos are processed (ref-counted, never raises). |
| `local_encoder/tray.py` | Tray icon (pystray + Pillow) used by `serve`; falls back to console mode when no tray is available. |
| `local_encoder/cli.py` | Typer CLI (`import`, `serve`, `logs`). |
| `local_encoder/config.py` | `.env`/environment configuration (`Config`, `load_config`, `default_work_dir`). |
| `local_encoder/_frozen.py` | PyInstaller bundle detection and bundled `ffmpeg`/`ffprobe` resolution (next to the executable, or embedded on macOS). |
| `local_encoder/updates.py` | Checks GitHub Releases for a newer version (packaged app only). |
| `local_encoder/history.py` | JSON-lines job history in `~/.local/share/local-encoder/history.jsonl`. |
| `local_encoder/logging_setup.py` | Rotating log file in `~/.local/share/local-encoder/local-encoder.log`. |
| `local_encoder/progress.py` | Rich progress bars for the CLI. |
| `local_encoder/utils.py` | Small shared helpers (`sanitize_filename`, `probe_duration`, `generate_file_id`). |

- `server.py` and `cli.py` both orchestrate the same pipeline (download → encode → thumbnails →
  login → register → upload → images → notify). When you change pipeline behavior, change **both**
  entry points or move the shared logic into a reusable function — never let the CLI and the web UI
  drift apart silently.
- Search before writing: reuse `AVideoClient`, `encode_*`/`extract_*`, `probe_duration`,
  `sanitize_filename`, `configure_logging` instead of adding parallel versions.

## Style and Typing

- Python `>=3.11` (CI matrix 3.11, 3.12, 3.13). Start modules with `from __future__ import annotations`.
- `mypy --strict` must pass for `local_encoder/`. Type every function signature; prefer
  `X | None`, `list[int]`, `dict[str, Any]`, `collections.abc.Callable`. Use `# type: ignore[code]`
  only with a specific error code and only when unavoidable.
- `ruff check .` (rules `E, F, I, UP, B`; `E501` and `UP017` ignored) and `ruff format --check .`
  must pass. Line length 100.
- Use `@dataclass` for structured results (see `LoginResult`, `RegisterVideoResult`,
  `ServerConfig`); use Pydantic models only for FastAPI request bodies.
- Match the docstring style of the surrounding module (short summary line; numpy-style sections
  where the file already uses them). Keep the existing section-separator comments.
- Use `pathlib.Path` for every filesystem path; never build paths with string concatenation.
  The tool runs on Windows, macOS and Linux — no POSIX-only assumptions (`/tmp`, `:` in file names,
  case-sensitive paths, executable bits).

## Running External Programs (FFmpeg, FFprobe)

- Always pass an **argument list** to `subprocess.run`/`Popen`; never `shell=True`, never build a
  command string. Values from users, file names, URLs, titles and server responses go in as separate
  list items.
- Always use the configured binaries (`cfg.ffmpeg_bin`, `cfg.ffprobe_bin`, resolved by
  `_frozen.resolve_ffmpeg()`/`resolve_ffprobe()`); never hardcode `"ffmpeg"` in a new call path.
- Always set a `timeout` for short calls (probe, thumbnails) and handle `TimeoutExpired`.
  Long encodes use `Popen` with stderr parsing for progress — keep the progress callback contract
  `callback(current_seconds, total_seconds)`.
- Check `returncode`; on failure log the last lines of stderr at DEBUG/ERROR and raise a clear
  exception. Do not swallow failures that would upload a broken file.
- Keep FFmpeg arguments aligned with the PHP Encoder (`Format.php`, `HLSProcessor.php`) unless a
  deliberate, documented deviation exists — see `.github/instructions/local-encoder-avideo-integration.instructions.md`.
- Hardware encoders: FFmpeg lists `h264_amf`/`h264_nvenc`/`h264_qsv` even without the driver or
  GPU, so only a real test encode proves one works (`detect_video_codec`). With HLS
  `split_by_time`, NVENC/QSV need `-forced-idr 1` / `-forced_idr 1` so forced keyframes are IDR.
  Consumer NVIDIA cards limit concurrent sessions: a ladder may need several FFmpeg runs.
- Cover art in MP3/M4A is a video stream with `disposition.attached_pic=1`; ask ffprobe for
  `stream_disposition=attached_pic` and do not count it as video.

## Errors and Logging

- `logger = logging.getLogger(__name__)` per module; never `print()` in library code (the CLI
  prints through `progress.py`/`rich`, the web UI through SSE `emit`).
- Never log passwords, the encrypted `pass`, `video_id_hash`, cookies or full request bodies.
  Log usernames, URLs (without credentials), `videos_id`, sizes and timings.
- Raise `AVideoAPIError` for AVideo-side failures with a message a non-technical user can act on
  (see `.github/instructions/local-encoder-user-experience.instructions.md`). Keep the technical
  detail in the log file.
- No bare `except:`; catch the narrowest exception that makes sense. Best-effort steps (thumbnails,
  MP3) may catch `Exception`, but must log/emit what was skipped.

## Configuration

- Server-side settings come from `.env`/environment through `config.load_config()`. Connection
  credentials for the web UI live in the browser (`localStorage`) and are sent per request.
- A new setting needs: a `Config` field with a safe default, an `os.getenv` line in
  `load_config()`, an entry in `.env.example` (commented if optional), and a CLI flag/UI control
  only if a normal user would ever need to change it.
- Never add a required setting: the app must start and work with zero configuration besides the
  AVideo URL, user and password.

## Dependencies and Packaging

- Do not add a runtime dependency unless the standard library or an existing dependency
  (`httpx`, `typer`, `rich`, `fastapi`, `uvicorn`, `yt-dlp`, `python-dotenv`) cannot cover the need.
  A new dependency must be added to `pyproject.toml` **and** checked with the PyInstaller build
  (`local-encoder.spec` → `hiddenimports` if it imports lazily).
- Frontend libraries are vendored by `scripts/download_vendor.py` into
  `local_encoder/static/vendor/` (gitignored) — never add CDN `<script>` tags.
- Anything that must work inside the frozen executable (bundled binaries, static files, data
  files) must be resolved through `_frozen.py`-style logic, not relative to the current directory.
