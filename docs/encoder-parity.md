# Feature Parity: PHP Encoder → Local Encoder

Goal: Local Encoder must do **at least everything** the official AVideo Encoder
(`D:\git\htdocs\AVideo\.compose\encoder\`) does for an uploader, but on the user's machine.
This is a living checklist: update the row whenever a change moves a feature forward
(rules: `.github/instructions/local-encoder-avideo-integration.instructions.md`; protocol:
`docs/avideo-encoder-protocol.md`).

Status: ✅ present · 🟡 partial/different · ❌ missing · 🐞 present but broken · ➖ not applicable

Baseline analysis: 2026-10-15 (Local Encoder `0.1.0`, commit `ed4fd75`).

## Known Defects (fix first — they break uploads on current AVideo)

1. 🐞 **Chunked upload has no authentication headers.** `AVideoClient.upload_file` sends a PUT with no `X-Encoder-User`/`X-Encoder-Pass`. Current Streamers reply 403, confirmed on vlu.me. Each 500 MB chunk is also read into RAM, and responses are not validated (`chunk`, `complete`, `filesize`). There is no retry, no resume and no multipart fallback.
2. 🐞 **The User-Agent is not an AVideo encoder UA.** The client sends `avideo-local-encoder/0.1`; it must contain `AVideoEncoder`. On sites that require login, `advancedCustom.json.php` and `status` redirect to the login page instead of answering. `get_server_config()` then silently falls back to defaults: HLS is assumed, and the site's MP3, resolution and other flags are ignored.
3. 🐞 **`duration` is sent as integer seconds.** The Streamer requires `HH:MM:SS` (`Video::isValidDuration`).
4. 🐞 **A failure never notifies the site.** Nothing sends `fail=1` to NotifyIsDone after an error, so the video stays in "encoding" on the site. The web UI also deletes the encoded files in `finally`, which means a failed upload cannot be retried without encoding again.
5. 🐞 **HLS zip resolution is wrong.** The zip is sent with a numeric resolution parsed from the file name; the official Encoder sends an empty resolution. Any parsed resolution can also break when a title ends in `_<digits>`.
6. 🐞 **The frozen executable has no web UI.** `local-encoder.spec` has `datas=[]`, so `static/index.html` and the vendored JS are missing from the PyInstaller build.
7. 🟡 **Credentials are exposed in the browser.** The web UI keeps the plain password in `localStorage` and sends it in the `/api/categories` query string.
8. 🟡 **Too many logins per job.** The web UI logs in for the connection test, again for categories, and again for the upload. Encoder UAs are limited to 10 logins per 5 minutes.

## Ingest

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Upload a local file | 🟡 | Web UI only, and the whole upload is read into RAM. The CLI accepts URLs only. |
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
| Auto WebM | ❌ | |
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
| Title, description, category | ✅ | Categories come from `categories.json.php`; the Encoder uses the login `categories`. |
| Create category (`canCreateCategory`) | ❌ | |
| User groups (`usergroups_id[]`) | ❌ | |
| Override status (a/i/u/s) | ❌ | |
| Release date and timezone (Scheduler) | ❌ | `timezone` is sent as `+0200`; the Encoder sends an IANA name. |
| Replace an existing video (`videos_id` / `update_video_id`) | ❌ | `register_video` accepts `videos_id`, but nothing calls it with one. |
| Playlists (`playlists_id`, `forcePlayLists`) | ❌ | |
| Source link (`videoDownloadedLink`) | ❌ | Always sent empty. |
| Dedup with `encoder_queue_id` | ❌ | Always 0. |

## Queue, Reliability, Notifications

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Persistent queue with statuses | ❌ | The queue lives in memory, with one worker, and is lost on restart. |
| Priority, delete/cancel, re-encode, send again | ❌ | |
| Automatic retry with backoff | ❌ | |
| Resume a transfer without re-encoding | ❌ | |
| Renew credentials when the token expires | ❌ | |
| Notify done (success) | ✅ | |
| Notify `fail=1` on error | ❌ | See defect 4. |
| Encoder log to the site (`aVideoEncoderLog`) | ❌ | |
| Keep or delete local files | 🟡 | CLI only (`--keep-files`); the web UI always deletes. |
| Upload limit / storage check (`status`) | ❌ | |
| Smallest-first upload order | 🟡 | CLI only. |
| Owner e-mail alerts (EncoderMonitor) | ➖ | The local UI shows progress directly; maybe later as desktop notifications. |

## Accounts

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Several sites and accounts | 🟡 | One account at a time in the UI. |
| Login with token reuse | 🟡 | Uses the token, but logs in several times per job. |
| Fallback to `objects/login.json.php` without rewrites | ❌ | |

## Local Encoder-only advantages (keep them)

- Encoding uses the user's own CPU/GPU, so the site needs no encoder server.
- The browser shows progress in real time over SSE.
- A CLI is available for automation.
- Packaging as a single executable (to be completed: see defect 6).
