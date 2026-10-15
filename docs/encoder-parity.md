# Feature Parity: PHP Encoder → Local Encoder

Goal: Local Encoder must do **at least everything** the official AVideo Encoder
(`D:\git\htdocs\AVideo\.compose\encoder\`) does for an uploader, but on the user's machine.
This is a living checklist: update the row whenever a change moves a feature forward
(rules: `.github/instructions/local-encoder-avideo-integration.instructions.md`; protocol:
`docs/avideo-encoder-protocol.md`).

Status: ✅ present · 🟡 partial/different · ❌ missing · 🐞 present but broken · ➖ not applicable

Evidence paths: `E/` = `.compose/encoder/` in the AVideo repo, `S/` = the AVideo Streamer root;
paths without a prefix are in this repository. Line numbers drift — re-check before relying on them.

- Baseline analysis: 2026-10-15 (Local Encoder `0.1.0`, commit `ed4fd75`).
- **Full audit (Mode B): 2026-10-15, commit `09d6ff3`.** The PHP Encoder was re-inventoried from
  its UI (`E/view/`) and `Format.php`; every row below was checked against the code, not the
  README. Live flags read from https://vlu.me/ (AVideo 30.2).

## Known Defects

### Open (found in the 2026-10-15 audit)

1. 🐞 **The web UI does not use the bundled FFmpeg.**
   - `server.py:518-522` and `server.py:641-645` build `Config(...)` directly. Its defaults are the
     bare names `ffmpeg`/`ffprobe` (`config.py:44-45`). Only `load_config()` calls
     `resolve_ffmpeg()`/`resolve_ffprobe()` (`config.py:78-79`).
   - The releases keep FFmpeg next to the executable (or inside it on macOS), not on PATH
     (`_frozen.py:6-9`). On a computer without its own FFmpeg, every web UI job fails after the
     download. `probe_duration` does not catch `FileNotFoundError` (`utils.py:37-59`).
   - The CLI and the downloader are not affected (`downloader.py:34`). Earlier "verified with the
     packaged executable" runs passed because the test machine has FFmpeg on PATH.
2. 🐞 **A link that contains a playlist downloads the whole playlist.**
   - `downloader.py:83` and `downloader.py:163` set `"no_playlist": True`. yt-dlp's option is
     `noplaylist` (`yt_dlp/YoutubeDL.py:336`), so the setting is ignored.
   - For a `watch?v=…&list=…` link, the info and the title come from the playlist, and every
     entry is downloaded under the same file name.
   - The PHP Encoder removes `list=` and imports only the single video (`E/objects/functions.php:1781`).
3. 🐞 **"Auto" sends HLS to sites that cannot play it.**
   - The site reports `videoHLS` in the login answer only when the VideoHLS plugin is enabled
     (`S/objects/login.json.php:359-362`). The PHP Encoder hides HLS when it is missing
     (`E/view/index.php:242-266`).
   - Local Encoder does not read `videoHLS` (`avideo_client.py:258-267`). Auto picks HLS unless
     `doNotShowEncoderAutomaticHLS` is set (`server.py:289-290`, `cli.py:275-276`). The site
     accepts the zip as a normal video (`S/objects/aVideoEncoder.json.php:253-256`), but nothing
     plays it there.
   - Not yet reproduced end to end. Needs a site with VideoHLS disabled.
4. 🐞 **Audio-only sources (MP3, M4A, SoundCloud links…) have no audio path.**
   - HLS maps `0:v` (`encoder.py:651-652`), so FFmpeg stops on a file without video.
   - The MP4 path reads "no height" as unknown and requests all 8 resolutions, up to 2160p
     (`encoder.py:165`).
   - The PHP Encoder detects audio by extension (`E/objects/Encoder.php:41`) and turns it into a
     spectrum video (formats 88/89/90; `E/view/upload.php:76-93`).
5. 🟡 **Unknown source height means upscaling.**
   - When ffprobe cannot read the height, Local Encoder encodes every resolution up to 2160p
     (`encoder.py:165`, `encoder.py:537`).
   - The PHP Encoder assumes 1080 (`E/objects/Format.php:460-497`).
6. 🟡 **HLS encode progress can go past 100 %** (suspected, not reproduced).
   - `encoder.py:688-693` counts a rendition as finished when its `index.m3u8` exists. FFmpeg
     writes those playlists while encoding, and all renditions are encoded in the same pass.

### Fixed — re-verified in the 2026-10-15 audit

Found in the 2026-10-15 baseline and fixed the same day. Unit-tested; the audit re-read the code.

1. ✅ **Chunked upload without authentication headers.**
   - Headers: `X-Encoder-User`/`X-Encoder-Pass` (`avideo_client.py:487`, `:518`).
   - Chunks are streamed from disk (`:459-475`).
   - Responses are checked: `chunk` on every reply, plus `complete` + `filesize` on the last one
     (`:546-563`).
   - A failed chunk is retried with the same `file_id`, with backoff 2, 4, 8, 16, 30, 30 s
     (`:565-583`).
   - Fallback to the direct path (`:524-526`). Fallback to a multipart upload on
     401/403/404/413, on a legacy single-PUT site, or when retries run out (`:527-532`,
     `:539-545`, `:566-574`).
2. ✅ **User-Agent** is `AVideoEncoder local-encoder/<version>` (`avideo_client.py:50`, `:121`).
3. ✅ **`duration`** is sent as `HH:MM:SS` (`utils.py:20-29`; used at `avideo_client.py:365`,
   `:431`, `:631`).
4. ✅ **`fail=1` on any error after registration** (`avideo_client.py:698-704`; `server.py:456-458`;
   `cli.py:480-482`). Files are kept after a failure (`server.py:464-481`, `cli.py:516-517`).
5. ✅ **The HLS zip and the MP3 are sent with an empty resolution** (`server.py:352`, `cli.py:334`).
   MP4 resolutions come only from the `_<res>p` suffix Local Encoder adds (`encoder.py:53-64`).
6. ✅ **The executable includes the web UI** (`local-encoder.spec:37-43`). Running it without
   arguments starts `serve` (`main.py:9-10`).
7. ✅ **Credentials stay out of the browser.**
   - The password is kept in memory only (`static/index.html:141-143`).
   - Passwords saved by older versions are removed (`static/index.html:217-220`).
   - The AVideo token stays in a server-side session for 12 h (`server.py:151-175`).
8. ✅ **One login per connection.** Jobs reuse the token (`server.py:197-209`, `server.py:377`).

Fixed while packaging (2026-10-15), re-verified:

- ✅ **`-vsync` was removed in FFmpeg 9.**
  - The WebP command no longer uses it (`encoder.py:432-435`).
  - The PHP Encoder no longer contains `-vsync` either. The code comment there that says
    "Encoder.php still has it" is out of date.
- ✅ **YouTube needs a JavaScript runtime.** deno and FFmpeg are passed to yt-dlp
  (`downloader.py:26-40`), and the app depends on `yt-dlp[default]` (`pyproject.toml:18`).
- ✅ **Other fixes:**
  - Browser file names are sanitized (`server.py:629`).
  - Uploaded files are streamed to disk (`server.py:632-633`).
  - Non-JSON answers give clear errors (`avideo_client.py:180-211`).
  - Requests fall back to `objects/*.json.php` when the short URLs are missing
    (`avideo_client.py:165-178`).

## Ingest

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Upload a local file | 🟡 | Web UI only (`server.py:613-633`). The CLI accepts URLs only. The Encoder's browser upload also resumes and retries (`E/view/jquery-file-upload/js/main.js:38-81`); Local Encoder runs locally, so this is not needed. |
| Import from URL (yt-dlp) | 🐞 | **Defect 2** (playlist links). Local Encoder has 5 strategies (`downloader.py:104-128`). The Encoder has 9, plus a cookies file, OAuth through restream.ypt.me, and a pytube fallback (`E/objects/Encoder.php:4247-4346`, `:949-954`, `:607-733`). `download_video(cookies_file=…)` exists, but nothing exposes it. |
| Title, description and thumbnail from the link | 🟡 | The title and description are used (`server.py:533-534`, `cli.py:223-224`). The link's thumbnail is not uploaded: the Encoder prefers it over a frame grab (`E/objects/Encoder.php:2940-2946`). The Encoder does not use the link's duration either. |
| YouTube channel import (start/end index) | ❌ | Only `youtube.com/channel\|user` links, and only for users with `canBulkEncode` (`E/view/youtubeDl.json.php:39-53`). The Encoder has **no** playlist import. |
| Import over FTP/FTPS | ❌ | Lists a remote folder and queues every `.mp4`/`.mp3` (`E/objects/FTPDownloader.php:86-117`). Low priority. |
| Bulk-encode a folder | ❌ | On the Encoder this is a server folder for admins or `canBulkEncode` users (`E/view/index_shareVideos.php:90-136`). The Local Encoder version would be a local folder. |
| Content keyword filter | ➖ | A policy of the Encoder server (`E/objects/Encoder.php:80-95`). |
| Jobs sent by the site (`queue.php`) | ➖ | The site cannot reach Local Encoder. |
| Encoder API (`submit_video`, queue status/delete/restart/edit) | ❌ | Optional (`E/API/`). The local web API could offer something similar. |

## Formats and Encoding

The Encoder's format tiles show only when `showOnlyEncoderAutomaticResolutions` is on (vlu.me: on).
Otherwise it shows Low/SD/HD checkboxes (`E/view/index_shareVideos.php:5-7`,
`E/view/streamerResources/resolutions.php`).

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Auto HLS: AES-128 video, one rendition per audio track, ladder, zip | 🟡 | `encode_hls` matches the arguments, the key layout and the master playlist (`E/objects/HLSProcessor.php:46-225`). Differences: `-r 30` at every resolution, while the Encoder uses 20 fps at 240p (`E/objects/Format.php:550-563`, `HLSProcessor.php:149`); the master `RESOLUTION` width assumes 16:9, while the Encoder uses the source aspect ratio (`encoder.py:715` vs `HLSProcessor.php:269-295`); no `index.mp4`/`index.mp3` in the zip. Audio segments are not encrypted in either. **Defect 3** (sites without VideoHLS). |
| Auto MP4 ladder (≤ source, no upscale) | ✅ | `encode_mp4_multi` runs one FFmpeg process with several outputs. Like `MP4Processor`, it adds `-minrate/-maxrate/-bufsize`, which the Encoder's dynamic MP4 (format 31) does not. It lacks the Encoder's `-max_muxing_queue_size 1024` (`E/install/database.sql:187`). **Defect 5.** |
| `saveOriginalVideoResolution` | ❌ | Read (`avideo_client.py:308`) but not used. The Encoder adds an unscaled output tagged with the nearest bucket, also when the source is smaller than every bucket (`E/objects/Format.php:880-903`). |
| `singleResolution` | 🟡 | The Encoder makes **one** MP4 at the largest bucket ≤ min(source, value) (`E/objects/MP4Processor.php:6-21`, `Format.php:1112-1114`), on the MP4 path only. Local Encoder uses the value as a cap on the whole ladder, for HLS too (`server.py:301-305`, `cli.py:282-284`). |
| Auto WebM | ❌ | The project owner deferred this (2026-10-15). |
| Auto Audio (video → MP3 + spectrum image) | ❌ | Format 60 (`E/objects/Format.php:1303-1308`; spectrum image at `E/objects/Encoder.php:1766-1768`, `:3566`). |
| Extract audio (MP3 + OGG), video → spectrum | ❌ | Orders 70/71 (`E/objects/Format.php:295-342`). Hidden by `doNotShowExtractAudio`/`doNotShowCreateVideoSpectrum`. |
| Audio input → spectrum MP4/HLS/WebM | 🐞 | **Defect 4.** |
| `autoConvertVideosToMP3` | 🟡 | MP4 path only (`server.py:424`, `cli.py:433`). The Encoder also writes `index.mp3` inside the HLS zip (`E/objects/HLSProcessor.php:35-43`). That is the default path, and vlu.me has the flag on. |
| `autoConvertToMp4` (VideoHLS) | ❌ | Not read. The Encoder puts `index.mp4`, at the nearest bucket ≤ source, in the HLS zip (`E/objects/HLSProcessor.php:25-34`). |
| Legacy Low/SD/HD MP4/WebM, multi-bitrate HLS (order 9) | ❌ | Low priority. Shown only when `showOnlyEncoderAutomaticResolutions` is off, and these upscale (`E/objects/Format.php:174-215`). |
| Per-user `allowedResolutions` (login) | ❌ | Not parsed (`avideo_client.py:258-267`). The Encoder intersects it with its own list, falling back to its own list when they do not overlap (`E/objects/Format.php:734-757`). |
| UI gating by site flags | 🟡 | Only `doNotShowEncoderAutomaticHLS` is used. `doNotShowEncoderAutomaticMP4` is read but unused (`avideo_client.py:310`). The login `videoHLS` is ignored (**defect 3**). |
| Output validation and retry | ❌ | Local Encoder checks only FFmpeg's exit code. The Encoder decodes the first 10 s of each output (`E/objects/Format.php:1206-1264`). It retries the encode once (`:1143-1144`) and re-runs the job up to 4 times (`E/objects/Encoder.php:1750-1757`). |
| Admin-editable FFmpeg command per format | ➖ | `formats.code` is edited by the Encoder admin (`E/view/saveConfig.php:24-38`). The default Auto HLS ignores it. Not an uploader feature. |
| GPU option | ➖ | The Encoder's `ffmpegGPU` only adds `--enable-nvenc`, which is not a valid runtime option (`E/objects/functions.php:32-34`). It does nothing useful. |

## Thumbnails

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| JPG / GIF / WebP | 🟡 | Same commands. Differences: Local Encoder takes the frame at 25 % of the duration (`server.py:274`, `cli.py:252`), the Encoder at 50 %, both capped at 600 s (`E/objects/Encoder.php:2949`). Local Encoder sends them after the video (`server.py:446`); the Encoder sends them before encoding, so the video has a thumbnail while it encodes (`E/objects/Encoder.php:1732-1739`). The link's thumbnail is not used. On failure, Local Encoder skips the image, while the Encoder uploads a "not found" placeholder. |
| Spectrum image (`spectrumimage`) | ❌ | Auto Audio only (`E/objects/Encoder.php:3015-3045`). |

## Metadata

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Title, description, category | ✅ | Categories come from the login response (`avideo_client.py:266`), with `categories.json.php` as a fallback (`server.py:180-182`). |
| Create category (`canCreateCategory`) | ❌ | The Encoder opens the site's `categories` page in an iframe and reloads the list (`E/view/js/main.js:43-79`). A link to the site page would be the local equivalent. |
| User groups (`usergroups_id[n]`) | ❌ | `userGroups` is in the login response. The site reads `usergroups_id` (`S/objects/aVideoEncoder.json.php:442-448`). |
| Override status (a/i/u/s) | ❌ | Hidden by `doNotAllowEncoderOverwriteStatus`. In the Encoder it is used only on the file-upload path (`E/view/upload.php:94-96`), and the site applies it only for admins (`S/objects/video.php:1061-1062`). |
| Release date and timezone (Scheduler) | ❌ | Hidden by `disableReleaseDate`. The site converts `releaseDate` using `timezone` (`S/plugin/Scheduler/Scheduler.php:446-449`), so `timezone` must become an IANA name before the release date is added. Today it is `+0200` (`avideo_client.py:147-149`), which is harmless while no release date is sent. |
| Replace an existing video (`videos_id` / `update_video_id`) | ❌ | Hidden by `doNotAllowUpdateVideoId`. The Encoder searches `S/objects/videos.json.php` (`E/view/streamerResources/videosId.php:15-52`). `register_video(videos_id=…)` exists, but nothing calls it with an ID. |
| "Edit while uploading" (site editor) and playlists | ❌ | The Encoder creates the video through `videoAddNew.json.php` and opens the site editor. `playlists_id` comes only from a deep link (`E/view/jquery-file-upload/js/main.js:194-243`). `aVideoEncoder.json` itself reads no playlist field. Low priority: link to the site's editor after registration. |
| Source link (`videoDownloadedLink`) | ✅ | `avideo_client.py:368`. |
| Dedup with `encoder_queue_id` | ❌ | Sent only inside `return_vars` with value 0 (`avideo_client.py:161-163`). The site reads the top-level field (`S/objects/aVideoEncoder.json.php:642-687`). The Encoder sends it only on the metadata-only create call (`E/objects/Encoder.php:1498-1512`). |

## Queue, Reliability, Notifications

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Persistent queue with statuses | ❌ | The queue lives in memory, with one worker (`server.py:53-91`), and is lost on restart. The Encoder has 9 statuses (`E/objects/Encoder.php:26-34`). |
| Priority, delete/cancel, re-queue, "Recheck" (send again without re-encoding) | ❌ | The Encoder's queue actions are at `E/view/index.php:1048-1267`. "Recheck" = resend the kept files: the natural next step after the files-kept fix. |
| Automatic retry | 🟡 | Only per upload chunk, the same as `sendFileChunk`. The Encoder also re-runs jobs up to 4 times, and retries transient network errors up to 5 times with a wait of `min(120, 5·n)` minutes (`E/objects/Encoder.php:1298-1379`). |
| Resume a transfer without re-encoding | 🟡 | Files are kept after a failure, but nothing sends them again yet. |
| Renew site access when the token expires | ❌ | The Encoder has a manual "Renew site access" action (`E/objects/Streamer.php:163-198`). Local Encoder sessions last 12 h, but a queued job does not re-check its token when it starts. |
| Notify done (success) | 🟡 | Sent. `completion_in_progress` is not retried (`avideo_client.py:668-696`). |
| Notify `fail=1` on error | ✅ | `AVideoClient.notify_failed`. |
| Encoder log to the site (`aVideoEncoderLog`) | ❌ | The Encoder logs every status change and every step (`E/objects/Encoder.php:359-433`, `:4438-4461`). |
| Keep or delete local files | 🟡 | Files are kept after failures in both. `--keep-files` also keeps them after success (CLI only). The Encoder's "Auto remove" is an admin setting. |
| Upload limit / storage check (`status`) | ➖ | The Encoder does not check either (its `status` read is dead code, `E/view/index.php:860-893`). Checking `max_file_size` before uploading would still help Local Encoder users. |
| Smallest-first upload order, MP3 last | ✅ | CLI sorts by size (`cli.py:398-400`). The web UI sends MP4s in ascending resolution (`encoder.py:173-176`). The MP3 is sent after the videos, as in the Encoder's non-auto formats (`E/objects/Encoder.php:2394-2406`). |
| Owner e-mail alerts (EncoderMonitor) | ➖ | Server cron (`E/objects/EncoderMonitor.php`). The local UI shows progress directly. |
| Live queue view (download %, encode %, ETA) | ✅ | SSE progress (`server.py:697-727`). Speed and ETA are not shown. |

## Accounts and UI

| PHP Encoder feature | LE | Notes |
| --- | --- | --- |
| Several sites and accounts | 🟡 | One account at a time in the UI. Sessions are kept per site on the server (`server.py:165`). |
| Login with token reuse | ✅ | One login per connection; jobs reuse the token. |
| Fallback to `objects/*.json.php` without rewrites | ✅ | Covers login, register/finalize and chunk. |
| UI language selector | ❌ | `E/view/index.header.php` (`changeLang`). Local Encoder is English only. |

## Local Encoder-only advantages (keep them)

- Encoding uses the user's own CPU/GPU, so the site needs no encoder server.
- The browser shows progress in real time over SSE.
- A CLI is available for automation.
- Packaging as a single executable that opens the web UI on double-click.
- TLS verification is on by default. The Encoder turns it off (`E/objects/Encoder.php:3164-3165`).

## Prioritized Backlog (audit 2026-10-15)

1. **Defects that break uploads on current AVideo**
   1. Defect 1: web UI jobs must use `resolve_ffmpeg()`/`resolve_ffprobe()`. A one-line fix
      (`Config` field defaults).
   2. Defect 2: `noplaylist`, and drop `list=` like the Encoder.
   3. Defect 3: parse `videoHLS` (and `allowedResolutions`) from login. Auto → MP4 when HLS is
      unavailable. Hide the HLS choice.
   4. Defect 4: detect audio-only sources with ffprobe and give a clear message, or use the
      spectrum path. Defect 5: assume 1080 when the height is unknown.
2. **Features most uploaders use**
   1. HLS parity: `index.mp4` (`autoConvertToMp4`), `index.mp3` (`autoConvertVideosToMP3`),
      20 fps at 240p, source aspect ratio in the master playlist.
   2. Thumbnails: 50 % offset, upload before encoding (register first), use the link thumbnail.
   3. Per-user `allowedResolutions`. `singleResolution` = one MP4. `saveOriginalVideoResolution`.
   4. Output validation (10-s decode check) and one encode retry.
   5. Metadata: user groups, release date (+ IANA timezone), override status, replace an
      existing video, a positive `encoder_queue_id`.
   6. Reliability: "send again" for kept files, encoder log to the site, retry
      `completion_in_progress`, check `max_file_size` before uploading.
3. **The rest**
   - Auto Audio/spectrum, extract audio, Auto WebM (deferred), channel import, local folder bulk
     encode, persistent queue, cookies file, create-category link, language selector.
