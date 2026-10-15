---
name: "Local Encoder User Experience"
description: "Use when changing anything a user sees or does: web UI (static/index.html), CLI commands/options/output, error messages, defaults, installation and packaging. The target user is non-technical."
applyTo: "local_encoder/static/**,local_encoder/cli.py,local_encoder/server.py,local_encoder/progress.py,README.md,local-encoder.spec"
---

# Local Encoder — User Experience for Non-Technical Users

The person using Local Encoder is usually a video creator or a small site owner, **not** a
developer. They know their AVideo site address, their user and password, and where their video is.
They do not know what FFmpeg, HLS, a bitrate, a chunk, SSL or `videos_id` are. Every change must
keep the app usable by that person without reading documentation.

## Principles

1. **Works with defaults.** URL + user + password + a video is enough. Format `auto`, resolutions
   chosen from the source and the server configuration, thumbnails generated automatically. Any new
   option must have a default that is right for most people; advanced options stay collapsed or
   CLI-only.
2. **The server decides, not the user.** Read what the AVideo site allows (formats, resolutions,
   MP3, HLS, size limits) and adapt automatically instead of asking the user to pick something the
   site may reject.
3. **Never lose the user's work.** A failed upload must not force a re-download or re-encode when
   the encoded files are still on disk. Keep the job and its files until success or explicit removal.
4. **Always show what is happening.** Every long step (download, encode, upload) reports progress
   with a percentage and a plain-language label. Never leave the UI silent for more than a few
   seconds.
5. **Errors explain what to do.** Each error shown to the user says, in plain words, what went
   wrong and the next action. Technical detail goes to the log file (`local-encoder logs`), not to
   the main message.

## Error Message Rules

| Instead of | Write |
| --- | --- |
| `httpx.ConnectError: [Errno 11001] getaddrinfo failed` | "Could not reach the site https://example.com/. Check the address and your internet connection." |
| `AVideoAPIError: Login rejected` | "The user name or password was not accepted by https://example.com/." |
| `canUpload=false` | "This account is not allowed to upload videos on this site. Ask the site administrator to enable uploads for it." |
| `CERTIFICATE_VERIFY_FAILED` | "The site's security certificate could not be verified. If this is your own test server, untick *Verify SSL* and try again." |
| `format not in allowedExtension` | "This site does not accept MP4/HLS uploads. Ask the administrator to allow the extension in the site settings." |
| FFmpeg exit code 1 + stderr | "The video could not be converted. The file may be damaged or use an unsupported format." (+ log details) |

- Map known AVideo `msg` values and HTTP/TLS/FFmpeg failures to these friendly messages in one
  place (near the code that raises them), keep the original text in the log.
- Never show a raw traceback, JSON dump, or HTML error page body in the UI or CLI (except with
  `--debug`/verbose).
- Never show or log the password; never put it in a URL that is printed.

## Web UI (`local_encoder/static/index.html`)

- Single page, React 18 + Tailwind loaded from the **vendored** files in `static/vendor/`
  (`scripts/download_vendor.py`); no CDN, no build step. Match the existing component style
  (`Input`, `Select`, `StepRow`, `useLocalStorage`).
- Site address and user name persist in `localStorage`; the password does not (see the security
  instructions) — the session lets the user reload the page without typing it again. *Connect*
  must give a clear yes/no with the reason.
- The page must fit the existing two-column viewport layout and remain usable on a laptop screen;
  keep labels short and in plain words. Prefer "Video quality" over "Resolution", "Streaming (HLS)"
  over "HLS" in labels, keeping technical terms only as secondary hints.
- All user-visible strings should be easy to find and translate later (keep them as literals in
  JSX/CLI help, not built from fragments).

## CLI (`local_encoder/cli.py`)

- Every option has `help` text in plain language and a safe default. Prompt for missing required
  values interactively rather than failing, when running in a terminal.
- Use `rich` output via `progress.py`; finish with a clear success line that includes the video
  link, or a clear failure line with the next action and the log path.

## Installation and Packaging

- The end goal is "download, double-click, use": a PyInstaller executable with FFmpeg/FFprobe
  bundled (`local-encoder.spec`, `bin/`). Do not introduce anything that requires the user to
  install Python packages, compilers, or system services.
- Any file the running app needs (UI files, vendored JS, bundled binaries) must be included in the
  PyInstaller build and resolved relative to the bundle, not the current working directory.
- Default to binding the web UI to `127.0.0.1` and opening the browser automatically.

## AVideo Multi-Site Reality

The same user may upload to several AVideo sites with different versions, plugins and settings.
Never assume a feature exists on the site: detect it, degrade gracefully, and tell the user in plain
words when the site does not support something ("This site does not have HLS enabled, so the video
was sent as MP4").
