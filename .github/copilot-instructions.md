# Local Encoder — Shared AI Instructions

This file is the canonical, repository-wide guidance for **every** AI agent (GitHub Copilot,
Codex via `AGENTS.md`, Claude Code via `CLAUDE.md`). Detailed rules live in
`.github/instructions/*.instructions.md` and workflows in `.github/prompts/*.prompt.md`. Change
rules here or there — never in a second copy.

## What This Project Is

Local Encoder (`local-encoder`, Python ≥3.11, MIT) is a desktop tool that **replaces the remote
AVideo Encoder**. Instead of sending a video to an Encoder server, the user downloads/selects the
video, encodes it **on their own computer** with FFmpeg, and uploads the results to their AVideo
site through the same Streamer endpoints the official Encoder uses.

Three facts drive every decision:

1. **Feature parity is the minimum.** Everything the PHP Encoder offers an uploader must exist
   here too. Track it in `docs/encoder-parity.md`.
2. **Many different AVideo sites.** The same app talks to any AVideo installation — different
   versions, plugins, settings, web servers, TLS setups. Never assume one site's configuration.
3. **Non-technical users.** It must work with just site URL + user + password + a video, with plain
   language, safe defaults, visible progress and helpful errors.

## Related Code on This Machine

| Component | Path | Notes |
| --- | --- | --- |
| This project | `D:\git\htdocs\avideo-local-encoder\` | |
| AVideo Streamer (the site) | `D:\git\htdocs\AVideo\` | PHP. Has its own `AGENTS.md`, `CLAUDE.md`, `.github/` rules — follow them when editing there |
| AVideo PHP Encoder (what we replace) | `D:\git\htdocs\AVideo\.compose\encoder\` | Separate component; reference implementation for parity |
| Local AVideo test site | https://vlu.me/ (Encoder UI at https://vlu.me/Encoder/) | Docker stack from `D:\git\htdocs\AVideo\docker-compose.yml`; the source folders are bind-mounted, so PHP edits are live |

Never grep the whole AVideo repo: exclude `vendor`, `node_modules`, `.compose`, `.git` (huge) and
search `.compose/encoder` by explicit path.

## Architecture

```
Browser UI (static/index.html, React+Tailwind vendored)   CLI (cli.py, Typer)
            │  JSON + SSE                                        │
            ▼                                                    ▼
   FastAPI server.py (in-memory jobs, 1 worker thread) ── same pipeline ──
            │
            ├─ downloader.py   yt-dlp (Python API)
            ├─ encoder.py      FFmpeg/FFprobe: MP4 ladder, HLS AES-128 zip, MP3, jpg/gif/webp
            └─ avideo_client.py  httpx → AVideo Streamer endpoints
```

Pipeline: download/receive → probe → encode → thumbnails → login → register (metadata) → chunk
upload → finalize → images → notify done. Settings: `.env`/env (`config.py`); web UI connection
session id in browser `localStorage` (never the password). Logs, history and the work folder:
`~/.local/share/local-encoder/` (`LOCAL_ENCODER_WORK_DIR` overrides the work folder). The web UI
listens on `127.0.0.1:47800` (another free port if busy; a second start just reopens the page).
`serve` runs in the tray icon (`tray.py`; no console window on Windows) and keeps the computer
awake while videos are processed (`keep_awake.py`). The page is in English, Portuguese and
Spanish (`static/i18n.js`).

Distribution: one-file PyInstaller executables for Windows, macOS (arm64 + Intel) and Linux
(x64 + arm64), with a static GPL FFmpeg and deno (yt-dlp's JavaScript runtime for YouTube),
published on GitHub Releases by
`.github/workflows/release.yml`. A new release goes out automatically whenever yt-dlp updates
(`.github/workflows/yt-dlp-update.yml`). See `docs/releasing.md` for the build, FFmpeg licensing
(GPL notices + source attached to every release) and signing. Anything the running app needs must
work inside the executable, and must not depend on the current directory.

## Topic Instructions (read the ones matching the files you touch)

| File | Applies to |
| --- | --- |
| [local-encoder-python.instructions.md](instructions/local-encoder-python.instructions.md) | `**/*.py` — module map, typing, subprocess, logging, config, dependencies |
| [local-encoder-avideo-integration.instructions.md](instructions/local-encoder-avideo-integration.instructions.md) | `local_encoder/**` — AVideo protocol, Encoder parity, multi-site compatibility |
| [local-encoder-security.instructions.md](instructions/local-encoder-security.instructions.md) | `local_encoder/**` — credentials, TLS, local server, subprocess, files |
| [local-encoder-user-experience.instructions.md](instructions/local-encoder-user-experience.instructions.md) | UI, CLI, server, progress, README, packaging — non-technical users |
| [local-encoder-testing.instructions.md](instructions/local-encoder-testing.instructions.md) | `tests/**` and every "done" claim — checks, mocking, end-to-end on vlu.me |

Reference docs: `docs/avideo-encoder-protocol.md` (endpoints/fields),
`docs/encoder-parity.md` (parity status + known defects) and `docs/releasing.md` (builds,
releases, FFmpeg license). `GAPS.md`, if present locally, is an old
untracked note — the `docs/` files supersede it.

## Workflows (`.github/prompts/`)

| Prompt | Use for |
| --- | --- |
| `local-encoder-new-feature.prompt.md` | Implementing a feature |
| `local-encoder-encoder-parity.prompt.md` | Porting a PHP Encoder feature, or auditing parity |
| `local-encoder-debug.prompt.md` | Any bug or failed import/encode/upload |
| `local-encoder-e2e-test.prompt.md` | End-to-end test against a real AVideo site |
| `local-encoder-pr-review.prompt.md` | Reviewing a PR or diff |
| `local-encoder-security-review.prompt.md` | Security reports and security-sensitive changes |
| `local-encoder-github-issue-answer.prompt.md` | Drafting replies to GitHub issues |

## Critical Rules

- **Search before creating.** Reuse `AVideoClient`, `encoder.py`, `downloader.py`, `utils.py`,
  `config.py`, `logging_setup.py`. Keep `server.py` and `cli.py` pipelines in sync.
- **Do not invent.** Every AVideo endpoint, field, setting, plugin or FFmpeg option you rely on
  must be verified in the AVideo/Encoder source (or this repo). If unsure, search; if still unsure,
  say so — never present an unverified API as real.
- **Match the official Encoder** for protocol and encoding behavior; document any deliberate
  deviation in `docs/encoder-parity.md`.
- **Never weaken AVideo** to make this tool work, and never depend on an AVideo change alone:
  other sites will not have it. Client-side fallbacks first.
- **Security**: never log/print/emit credentials or tokens; TLS verification on by default;
  subprocess argument lists only; paths confined to the work directory; treat every server
  response and media file as untrusted.
- **User experience**: safe defaults, plain-language errors with a next step, visible progress,
  never discard encoded work on a failed upload.
- **Small diffs.** Change only what the task needs; no unrelated refactors/reformatting; no new
  dependency without explicit approval.
- **Cross-platform**: Windows, macOS, Linux; `pathlib`; works inside the PyInstaller build.

## Validation Before Calling a Task Done

```bash
pytest
ruff check .
ruff format --check .
mypy local_encoder
```

All four must pass (CI: `.github/workflows/ci.yml`, Python 3.11/3.12/3.13). Changes to encoding,
HLS, upload, login or any AVideo request also need an end-to-end run against https://vlu.me/ — or
an explicit statement that manual verification against a real AVideo site is still required.
Report real results; never claim a check passed without running it.

## Conventions

- Commits: Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `test:`).
- Code, comments, commit messages and docs in English. Reply to the user in the language they use.
- One PR = one feature or fix, with tests; update `README.md` for user-facing changes and
  `docs/encoder-parity.md` when parity changes.

## Keep This Knowledge Current

When you learn something important and non-obvious (a protocol detail, an AVideo version
difference, a pitfall, a command), record it during the task in the right `.github/` instruction
file or `docs/` file. Verify before writing, never record assumptions, do not duplicate content,
and keep this file short — move long details into `docs/`.
