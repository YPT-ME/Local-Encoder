---
name: "Local Encoder End-to-End Test"
description: "Run an end-to-end test of Local Encoder against a real AVideo site (default: the local Docker site https://vlu.me/), verify the result on the site, and report what works and what does not. Use after changes to encoding, upload, login, metadata, or AVideo itself."
argument-hint: "What to test (format, resolutions, file or URL, CLI or web UI, site) — defaults to the local Docker site"
agent: agent
---

# Local Encoder End-to-End Test

Scope: **{{TEST_SCOPE}}**

## 1. Preconditions

- Unit checks pass first: `pytest`, `ruff check .`, `ruff format --check .`, `mypy local_encoder`.
- Target site: https://vlu.me/ unless another is given. Check it answers:
  `curl -sk -A "AVideoEncoder e2e" -o /dev/null -w "%{http_code}\n" https://vlu.me/status`
  (expect `200`). Plain `curl` is blocked by the bot filter; a browser UA gets a login redirect.
  If the site is down, ask the user to start the Docker stack in `D:\git\htdocs\AVideo\`
  (`docker compose up -d`); do not start/stop containers without asking.
- Credentials: ask the user for a test account (an uploader, and an admin if the test needs it).
  Never print, log, commit or store them in files.
- FFmpeg/FFprobe available (`bin/`, `FFMPEG_BIN`/`FFPROBE_BIN`, or PATH).
- Use a small test input (a few seconds; one landscape, one vertical, one audio-only, one with two
  audio tracks when relevant) so the run is fast.

## 2. Run

CLI (URL import):
```bash
local-encoder import "<url>" --server https://vlu.me/ --user <user> --password <pass> --ssl-no-verify --format <auto|mp4|hls> [--resolution <max>] [--keep-files]
```
Web UI: `local-encoder serve --no-browser`, open the address it prints (default
http://127.0.0.1:47800), untick *Verify SSL* for vlu.me, click *Connect*, then import a URL or a
local file. To test a release build, run the same steps with the packaged `LocalEncoder`
executable (`docs/releasing.md`).

Capture: the CLI/SSE output, `local-encoder logs`, and the `videos_id` returned.

## 3. Verify on the Site

Check each item and record ✅/❌ with evidence:
- The video page `https://vlu.me/video/<videos_id>` exists and plays.
- Title, description, category (and user group, release date, status when tested) are correct.
- Thumbnails: jpg, animated gif, webp are present.
- Formats/resolutions: every expected `_<res>.mp4`, HLS rendition, MP3 is listed; no upscaled
  resolutions; HLS plays and is encrypted when expected.
- Duration shown correctly (not 0:00 / `EE:EE:EE`).
- Status is no longer "encoding" (notify done worked); a forced failure leaves the video in an
  error state instead of "encoding" forever.
- If something is wrong, read the Streamer side: the video's encoder log and AVideo logs
  (`D:\git\htdocs\AVideo\.compose\videos\avideo.log` — read only the tail — or
  `docker compose logs avideo`).

## 4. Compare With the Official Encoder (when testing parity)

Send the same input through https://vlu.me/Encoder/ with equivalent options and compare files,
fields and statuses on the site. Differences go into `docs/encoder-parity.md`.

## 5. Changes in AVideo

If the test requires editing `D:\git\htdocs\AVideo\` (bind-mounted, live without rebuild), follow
that repository's `AGENTS.md`/`CLAUDE.md` rules, keep the change minimal, and re-run this test.
Remember older AVideo sites will not have the change — re-test the Local Encoder fallback path too.

## 6. Report

- Site, AVideo version (`status` → `version`), Local Encoder commit, OS.
- Each scenario: command/action, result, `videos_id`, verification checklist.
- Failures with the relevant log lines (credentials redacted) and the suspected cause.
- What was not tested.
- Clean up: offer to delete test videos from the site (ask before deleting anything).
