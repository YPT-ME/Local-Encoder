---
name: "Local Encoder AVideo Integration"
description: "Use when changing how Local Encoder talks to AVideo sites or encodes media for them: login, register, chunked upload, images, notify, server config, formats, resolutions, HLS, metadata, and parity with the PHP Encoder. Covers multi-site/multi-version compatibility."
applyTo: "local_encoder/**"
---

# Local Encoder — AVideo Integration and Encoder Parity

Local Encoder replaces the remote PHP **Encoder** of AVideo: the user encodes on their own machine
and uploads the results to an AVideo **Streamer** (the site), exactly as the official Encoder does.
It must offer **at least the same features** as the PHP Encoder and must work with **many
different AVideo installations** (versions, plugins, settings, web servers).

Reference documents (read the one relevant to the task):
- `docs/avideo-encoder-protocol.md` — every Streamer endpoint, method, field and response.
- `docs/encoder-parity.md` — feature-by-feature parity status and known defects.

## Sources of Truth (verify here, never guess)

| What | Where |
| --- | --- |
| PHP Encoder (behavior to match) | `D:\git\htdocs\AVideo\.compose\encoder\` — `objects/Encoder.php`, `Format.php`, `HLSProcessor.php`, `MP4Processor.php`, `Login.php`, `Streamer.php`, `functions.php`, `view/index.php` |
| Streamer receivers (contract to satisfy) | `D:\git\htdocs\AVideo\objects\aVideoEncoder.json.php`, `aVideoEncoderChunk.json.php`, `EncoderChunkAssembler.php`, `aVideoEncoderReceiveImage.json.php`, `aVideoEncoderNotifyIsDone.json.php`, `aVideoEncoderLog.json.php`, `login.json.php`, `status.json.php`, `include_config.php`, `functionsSecurity.php` |
| URL rewrites | `D:\git\htdocs\AVideo\.htaccess` (`login`, `aVideoEncoder.json`, `aVideoEncoderChunk.json`, `status`) |
| AVideo's own AI rules | `D:\git\htdocs\AVideo\AGENTS.md`, `CLAUDE.md`, `.github/` (apply when editing AVideo) |

Never grep the whole AVideo repo: exclude `vendor`, `node_modules`, `.compose`, `.git`, and search
`.compose/encoder` by explicit path. Any endpoint, field or setting you use must be confirmed in
these files — cite `file:line` in your reasoning.

## Protocol Rules (current Streamer)

- **User-Agent**: identify as the AVideo Encoder — the string must contain `AVideoEncoder`
  (official Encoder: `AVideoEncoder <host> `, `functions.php getSelfUserAgent()`). The Streamer
  uses it (`isAVideoUserAgent()`) to exempt encoder traffic from same-origin/CSRF checks, from
  "must be logged in" redirects and from bot blockers. Without it, `advancedCustom.json.php` and
  `status` answer a 302 to the login page and the chunk endpoint is refused.
- **Login** (`login` → `objects/login.json.php`): send the typed password once with
  `encodedPass=false`; store the returned `pass` (`_user_hash_…` token, valid ~1 day, revoked by a
  password change) and send it as `pass` with `encodedPass=1` on later calls. Never compute password
  hashes locally (salted installs break). Use the login response: `canUpload`, `categories`,
  `userGroups`, `allowedResolutions`, `videoHLS`, `isAdmin`, `canCreateCategory`. Login is rate
  limited (encoder user agents: 10 per 5 min per IP) — log in once per job/session and reuse the
  token; handle HTTP 429 and string `error` values (captcha, unverified e-mail, 2FA, too many
  attempts) with a clear message.
- **Register / metadata** (`aVideoEncoder.json`, `first_request=1`, no media): creates or updates
  the video and returns `videos_id`/`video_id`, `video_id_hash`. Send a stable positive
  `encoder_queue_id` per job (deduplication), `videoDownloadedLink` (source URL), `title`,
  `description`, `categories_id`, `usergroups_id[n]`, `releaseDate`, `overrideStatus`, and
  `videos_id` when replacing an existing video — as **top-level fields** (the Streamer does not
  read these from `return_vars`).
- **`duration` must be `HH:MM:SS`** (optionally `.fraction`) — `Video::isValidDuration()`
  rejects plain seconds.
- **`format`** must be in the Streamer's `allowedExtension` (hard-coded in current versions:
  `gif jpg mp4 webm mp3 m4a ogg zip m3u8 webp`). **`resolution`** must be in
  `avideo_possible_resolutions` (`avideo_resolutions` + `HD SD Low`); send the numeric height for
  `_<res>.mp4/.webm` files and an empty resolution for the HLS `zip`. Never derive the resolution by
  parsing a user-controlled file name.
- **Chunked upload** (`PUT aVideoEncoderChunk.json?file_id=<hex>&chunk=<i>&total=<n>`): requires
  auth headers `X-Encoder-User` + `X-Encoder-Pass` (login token), or `X-Encoder-Upload-Token`.
  Stream chunks from disk (do not hold a whole chunk in RAM when avoidable), check the `chunk`
  echo on each response and `complete` + `filesize` on the last one, retry a failed chunk with the
  same `file_id` (re-sending a committed chunk is safe), then POST `aVideoEncoder.json` with
  `chunkFile`. Fall back to a multipart `video` POST on 413, on a legacy single-PUT response, or when
  the endpoint is missing (older Streamers).
- **Images** (`objects/aVideoEncoderReceiveImage.json.php`): `image` (jpg), `gifimage`,
  `webpimage`, `spectrumimage` (audio). The official Encoder sends them right after download,
  before encoding, so the video has a thumbnail while it encodes.
- **Notify** (`objects/aVideoEncoderNotifyIsDone.json.php`): `fail=0` on success. **On any failure
  after a `videos_id` exists, send `fail=1`** so the video does not stay "encoding" forever. Handle
  `completion_in_progress` (retry later) and treat the call as idempotent.
- **Encoder log** (`objects/aVideoEncoderLog.json.php`, `msg`, `type`, `videos_id`): optional
  status messages shown to the site owner; use it like the official Encoder for status changes.
- **Server info**: `plugin/CustomizeAdvanced/advancedCustom.json.php` (encoder flags:
  `doNotShowEncoderAutomaticHLS/MP4/Webm/Audio`, `autoConvertVideosToMP3`, `autoConvertToMp4`,
  `saveOriginalVideoResolution`, `singleResolution`, `disableReleaseDate`, …) and `status`
  (`version`, `max_file_size`, storage limits, enabled plugins). Use them to pick defaults and to
  explain limits before encoding.
- **Rewrites may be missing** (nginx, custom installs): when a rewritten path (`login`,
  `aVideoEncoder.json`, `aVideoEncoderChunk.json`, `status`) returns 404/HTML, retry the direct
  `objects/*.json.php` path.
- **TLS**: verify by default; the official Encoder disables verification, Local Encoder must not
  do so silently (user opt-in only).

## Multi-Site and Multi-Version Compatibility

- One Local Encoder serves many independent AVideo sites. Keep credentials, tokens, server config
  and job state **per site and per job** — never a single global "current site".
- Never assume a plugin or setting exists: VideoHLS (HLS, `autoConvertToMp4`), Scheduler
  (`releaseDate`), CustomizeAdvanced (encoder flags, moderation/default status), UserGroups
  (`allowedResolutions`), storage plugins. Detect, adapt, and degrade gracefully.
- Older Streamers: chunk endpoint without multi-chunk/auth or missing, no dedup by
  `encoder_queue_id`, `aVideoEncoderAlert.json.php` 404. Use `status.version` to branch only when
  necessary, and prefer feature detection.
- Responses can be HTML (login redirect, bot blocker `Bot Found [...]`, PHP warnings, proxies).
  Detect non-JSON and report it clearly instead of crashing on `resp.json()`.
- Never ask for (or make) a change on the AVideo side as the only way for Local Encoder to work:
  existing sites will not have it. If AVideo needs a fix, do it in `D:\git\htdocs\AVideo\` following
  that repository's rules **and** keep a client-side fallback.

## Encoding Parity Rules

- Bitrate ladder and resolution buckets come from `Format.php` (`ENCODING_SETTINGS` in
  `encoder.py` mirrors it): 240, 360, 480, 540, 720, 1080, 1440, 2160; never upscale; intersect with
  the server/user `allowedResolutions`.
- Match the PHP Encoder's FFmpeg choices (codecs, frame rate per resolution, aspect ratio from the
  source, audio-track handling, HLS AES-128 key layout, zip layout including optional `index.mp4` /
  `index.mp3`). A deliberate deviation must be documented in `docs/encoder-parity.md` with the
  reason.
- Audio-only inputs follow the Encoder's audio paths (MP3 + spectrum), not the video ladder.
- Validate outputs before uploading (non-zero duration, decodable), like `videoFileHasErrors()`.
- Upload smaller files first; auto-converted MP3 last.
- Keep encoded outputs after a failure so the user can retry the upload without re-encoding.

## When You Change Integration Code

1. Read the PHP Encoder code for the same step and the Streamer receiver.
2. Assert the exact request (endpoint, method, headers, fields) in a unit test.
3. Run the end-to-end test against https://vlu.me/ (`local-encoder-e2e-test.prompt.md`) or state
   that manual verification is required.
4. Update `docs/encoder-parity.md` / `docs/avideo-encoder-protocol.md` if behavior changed.
