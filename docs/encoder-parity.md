# Feature Parity: PHP Encoder → Local Encoder

Goal: Local Encoder must do **at least everything** the official AVideo Encoder
(`D:\git\htdocs\AVideo\.compose\encoder\`) does for an uploader, but on the user's machine.
This is a living checklist: update the row whenever a change moves a feature forward
(rules: `.github/instructions/local-encoder-avideo-integration.instructions.md`; protocol:
`docs/avideo-encoder-protocol.md`).

Status: ✅ present · 🟡 partial/different · ❌ missing · 🐞 present but broken · ➖ not applicable

Baseline analysis: 2026-10-15 (Local Encoder `0.1.0`, commit `ed4fd75`).

## Known Defects

Found in the 2026-10-15 baseline and **fixed on 2026-10-15** (unit-tested; the full upload still
needs the end-to-end run in `.github/prompts/local-encoder-e2e-test.prompt.md`):

1. ✅ **Chunked upload had no authentication headers** (403 on current Streamers). It now:
   - sends `X-Encoder-User`/`X-Encoder-Pass`;
   - streams each chunk from disk;
   - validates `chunk` on every response, and `complete` + `filesize` on the last one;
   - retries a failed chunk with the same `file_id` (backoff 2, 4, 8, 16, 30, 30 s);
   - falls back to the direct `objects/aVideoEncoderChunk.json.php` path when there are no rewrites;
   - falls back to a multipart `video` POST on 401/403/404/413, on a legacy single-PUT server, or when retries run out.
2. ✅ **The User-Agent was not an AVideo encoder UA.** It is now `AVideoEncoder local-encoder/<version>`. Confirmed on vlu.me: `get_server_config()` now reads the real flags; before, it fell back to defaults.
3. ✅ **`duration` was sent as integer seconds.** It is now `HH:MM:SS` (`utils.format_duration`).
4. ✅ **A failure never notified the site.** Any error after registration now sends `fail=1` (`AVideoClient.notify_failed`). The CLI and the web UI keep the downloaded/encoded files after a failure and say where they are; they are deleted only after success.
5. ✅ **HLS zip resolution was wrong.** The zip and the MP3 are now sent with an empty resolution. MP4 resolutions come from `encoder.output_resolution()`, which reads only the `_<res>p` suffix it adds and only allowed values.
6. ✅ **The frozen executable had no web UI.** `local-encoder.spec` now bundles `local_encoder/static` (and stops if the vendored JS is missing). Running the executable without arguments starts `serve`.
7. ✅ **Credentials were exposed in the browser.** The password is kept in memory and sent once to log in. The local server keeps the AVideo token in an in-memory session (12 h), and the browser stores only the session id. Passwords saved by older versions are removed from `localStorage`. `GET /api/categories?password=…` was removed.
8. ✅ **Too many logins per job.** The web UI logs in once per connection. Jobs reuse the token (`AVideoClient.use_login`), and categories come from the login response.

Also fixed:
- Uploaded file names from the browser are sanitized, so they cannot escape the job folder.
- The local file is copied to disk instead of read into memory.
- Non-JSON answers (bot blocker, login redirect, PHP warnings, HTTP 429) now give clear messages.
- `login`/`aVideoEncoder.json` fall back to `objects/*.json.php` on sites without rewrites.

## Ingest

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Upload a local file | 🟡 | Web UI only (streamed to disk). The CLI accepts URLs only. |
| Import from URL (yt-dlp) | 🟡 | LE has 5 strategies; the Encoder has 9, plus a cookies file, OAuth (restream.ypt.me), JS runtime and pytube fallback. The `cookies_file` parameter exists but nothing exposes it. |
| Use the source thumbnail, title, description and duration from the link | 🟡 | The title is used. The source thumbnail is not. |
| Import a channel or playlist (start/end index) | ❌ | `no_playlist: True`. |
| Import over FTP/FTPS (file or folder) | ❌ | |
| Bulk-encode a folder | ❌ | A local folder pick would be the natural Local Encoder version. |
| Jobs sent by the site to the encoder (`queue.php`) | ➖ | Local Encoder is not reachable from the site. |
| Encoder API (`submit_video`, queue status/edit/delete/restart) | ❌ | Optional; the local web API could expose an equivalent. |

## Formats and Encoding

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Auto HLS: AES-128, renditions per audio track, ladder, zip | 🟡 | `encode_hls`. Fixed `-r 30` (Encoder: 20 fps at 240p), 16:9 width assumed, no `index.mp4`/`index.mp3` inside the zip. |
| Auto MP4 ladder (≤ source, no upscale) | ✅ | `encode_mp4_multi`. |
| `saveOriginalVideoResolution` | ❌ | Parsed but unused. |
| `singleResolution` (one MP4 at the closest bucket) | 🟡 | Used as a cap on the ladder instead of producing a single file. |
| Auto WebM | ❌ | Deferred by the project owner (2026-10-15) — not a priority now. |
| Auto Audio (MP3 + spectrum image) | ❌ | |
| Extract audio (mp3 + ogg) | ❌ | |
| Video → spectrum | ❌ | |
| Audio input → spectrum MP4/HLS/WebM | ❌ | An MP3 input goes into the video ladder. |
| `autoConvertVideosToMP3` | 🟡 | MP4 path only, not HLS. |
| `autoConvertToMp4` (VideoHLS) | ❌ | |
| Legacy Low/SD/HD and MP4+WebM formats | ❌ | Low priority; the "Auto" formats are the current default. |
| Per-user `allowedResolutions` (from login) | ❌ | Only the user's checkboxes are used. |
| UI gating by `advancedCustom` flags | 🟡 | Only `doNotShowEncoderAutomaticHLS` is used. |
| Output validation and one encode retry | ❌ | Only the exit code is checked. |
| Admin-editable FFmpeg command per format | ➖ / ❌ | Possibly as an advanced setting later. |

## Thumbnails

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| JPG / GIF / WebP | 🟡 | Present, but taken at 25% of the video instead of 50% (capped at 600 s), and uploaded after the video instead of before encoding. |
| Spectrum image (`spectrumimage`) | ❌ | |

## Metadata

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Title, description, category | ✅ | Categories come from the login response, with `categories.json.php` as a fallback. |
| Create category (`canCreateCategory`) | ❌ | |
| User groups (`usergroups_id[]`) | ❌ | |
| Override status (a/i/u/s) | ❌ | |
| Release date and timezone (Scheduler) | ❌ | `timezone` is sent as `+0200`; the Encoder sends an IANA name. |
| Replace an existing video (`videos_id` / `update_video_id`) | ❌ | `register_video` accepts `videos_id`, but nothing calls it with one. |
| Playlists (`playlists_id`, `forcePlayLists`) | ❌ | |
| Source link (`videoDownloadedLink`) | ✅ | The imported URL is sent. |
| Dedup with `encoder_queue_id` | ❌ | Always 0. |

## Queue, Reliability, Notifications

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Persistent queue with statuses | ❌ | The queue lives in memory, with one worker, and is lost on restart. |
| Priority, delete/cancel, re-encode, send again | ❌ | |
| Automatic retry with backoff | 🟡 | Per upload chunk only (same as `sendFileChunk`); no job-level retry. |
| Resume a transfer without re-encoding | 🟡 | Files are kept after a failure, but there is no "send again" action yet. |
| Renew credentials when the token expires | ❌ | |
| Notify done (success) | ✅ | |
| Notify `fail=1` on error | ✅ | `AVideoClient.notify_failed`. |
| Encoder log to the site (`aVideoEncoderLog`) | ❌ | |
| Keep or delete local files | 🟡 | Kept after failures in both; `--keep-files` (CLI only) also keeps them after success. |
| Upload limit / storage check (`status`) | ❌ | |
| Smallest-first upload order | 🟡 | CLI only. |
| Owner e-mail alerts (EncoderMonitor) | ➖ | The local UI shows progress directly; maybe later as desktop notifications. |

## Accounts

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Several sites and accounts | 🟡 | One account at a time in the UI. |
| Login with token reuse | ✅ | One login per connection; jobs reuse the token. |
| Fallback to `objects/*.json.php` without rewrites | ✅ | login, register/finalize, chunk. |

## Local Encoder-only advantages (keep them)

- Encoding uses the user's own CPU/GPU, so the site needs no encoder server.
- The browser shows progress in real time over SSE.
- A CLI is available for automation.
- Packaging as a single executable that opens the web UI on double-click.
