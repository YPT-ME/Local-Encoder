---
name: "Local Encoder New Feature"
description: "Implement a new Local Encoder feature safely: research the PHP Encoder and the AVideo receiver first, keep compatibility with many AVideo sites/versions, keep it usable by non-technical users, and validate with tests and an end-to-end run."
argument-hint: "Describe the feature to implement"
agent: agent
---

# Local Encoder New Feature Implementation

Implement the following feature in Local Encoder: **{{FEATURE_DESCRIPTION}}**

## Phase 1: Research (Complete Before Writing Any Code)

### 1.1 Does it already exist?
- Search `local_encoder/` for similar logic (pipeline in `server.py` and `cli.py`, `AVideoClient`,
  `encoder.py`, `downloader.py`).
- Check `docs/encoder-parity.md`: is this an official Encoder feature? If yes, this is a parity
  port — also follow `local-encoder-encoder-parity.prompt.md`.

### 1.2 How does AVideo do it?
- PHP Encoder: `D:\git\htdocs\AVideo\.compose\encoder\` (`objects/Encoder.php`, `Format.php`,
  `HLSProcessor.php`, `view/`).
- Streamer receiver: `D:\git\htdocs\AVideo\objects\aVideoEncoder*.php` and helpers it calls.
- Which AVideo versions/plugins/settings does it depend on? What happens on a site that does not
  have them?
- Do not invent endpoints, fields or settings — verify them in the source.

### 1.3 What is affected?
- Modules, the web UI, the CLI, configuration, tests, packaging (PyInstaller), docs.

## Phase 2: Implementation Plan

List before coding:
1. New files (with justification) and modified files.
2. New or changed requests to AVideo (endpoint, method, fields) and how older/other sites react.
3. User-facing changes: new controls, defaults, messages — and why a non-technical user needs them.
4. Backward compatibility: CLI flags, `.env` keys, `localStorage` keys, history file format.
5. Tests to add and the end-to-end check to run.

If the plan changes user-visible behavior, the AVideo protocol, or adds a dependency, present it
and get confirmation before proceeding.

## Phase 3: Implementation

- **AVideo calls** only through `AVideoClient`; mirror the official Encoder's fields.
- **FFmpeg** only through `encoder.py`, argument lists, configured binaries, progress callback.
- **Pipeline**: keep `server.py` and `cli.py` behavior in sync (or share the code).
- **UI/CLI**: plain-language labels, safe defaults, progress, friendly errors.
- **Config**: optional settings with safe defaults; update `.env.example`.
- **Packaging**: anything new the app needs at runtime must work in the PyInstaller build.

## Phase 4: Validation

- Unit tests for the new logic and for the exact request fields sent to AVideo.
- `pytest`, `ruff check .`, `ruff format --check .`, `mypy local_encoder` — real results.
- End-to-end against https://vlu.me/ when the change touches encoding/upload/protocol, or a clear
  "manual verification required" note.
- Edge cases: site without the feature/plugin, self-signed TLS, very large file, very short video,
  audio-only input, vertical video, non-ASCII title/file name, network drop mid-upload.
- Update `docs/encoder-parity.md` and `README.md` when user-facing behavior or parity changes.

## Constraints

- Keep changes minimal; no unrelated refactors or reformatting.
- No new dependencies without explicit approval.
- If unsure something exists, search first; never present an unverified API as real.
