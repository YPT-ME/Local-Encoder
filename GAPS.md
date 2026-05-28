# Known Gaps and Assumptions

This document lists AVideo server-side behaviours that were inferred from the
PHP encoder source code but could not be fully verified, along with the
assumptions this tool makes.

---

## 1. `streamers_id` semantics

**What the PHP encoder does:**
The encoder stores each AVideo server ("streamer") in its own database table.
Every API request carries the local `streamers_id` DB row ID.

**Assumption in this tool:**
`streamers_id=0` is sent in all requests.  The AVideo receiver stores it on the
video record but does not appear to enforce a valid non-zero value for uploads
from authenticated users.

**Risk:** Low.  The server still authenticates via `user`/`pass` fields.

---

## 2. `format` must be in AVideo's `allowedExtension` list

**What the PHP encoder does:**
`aVideoEncoder.json.php` rejects uploads whose `format` value is not in the
site-configured `allowedExtension` list.

**Assumption in this tool:**
`mp4` is always sent as the format.  This is the most commonly enabled
extension, but if the target server has disabled `mp4` uploads the request will
be rejected.

**Workaround:** Add `mp4` (and `zip` for HLS) to the AVideo admin panel under
*Settings → Allowed Extensions*.

---

## 3. `resolution` must be in `avideo_possible_resolutions`

**What the PHP encoder does:**
`aVideoEncoder.json.php` validates `resolution` against the server-side list
`$global['avideo_possible_resolutions']`.

**Assumption in this tool:**
Standard resolutions (240, 360, 480, 540, 720, 1080, 1440, 2160) are assumed to
be allowed.  If the server has been configured to restrict this list, an upload
at a non-allowed resolution will fail.

---

## 4. `video_id_hash` generation

**What the PHP encoder does:**
The hash is created server-side when a new video record is inserted and returned
in the `register_video` response.  It can be used in place of `user`/`pass` for
subsequent requests (see `useVideoHashOrLogin` in AVideo's `functions.php`).

**Assumption in this tool:**
The hash is used exactly as returned; no local generation is needed.

---

## 5. Chunked upload temp-file path security

**What the PHP encoder does:**
`aVideoEncoderChunk.json.php` stores chunks in `sys_get_temp_dir()` and returns
the assembled file path.  The finalise POST to `aVideoEncoder.json` must pass
this path back as `chunkFile`; the server validates it is inside the allowed
temp directories using `realpath()`.

**Assumption in this tool:**
The path returned by the server is passed back verbatim.  This is correct
behaviour—the server controls the path; the client just echoes it back.

---

## 6. HLS (ZIP) format not implemented

The PHP encoder supports encoding to multi-resolution HLS playlists packaged as
`.zip` files (`HLSProcessor.php`).  This tool only implements MP4 output.

**Reason:** HLS encoding is significantly more complex (per-resolution FFmpeg
passes, AES-128 key file generation, master playlist, ZIP packaging) and
requires corresponding server-side support.  It can be added in a future
iteration.

---

## 7. Audio-spectrum and other special format orders

The PHP encoder supports special formats (mp3-to-spectrum, WebM, etc.) via
`Format.php` order codes (70, 88, 89, 90, …).  This tool only supports standard
MP4 video encoding.

---

## 8. Parallel / batch encoding

The PHP encoder processes a queue of videos concurrently.  This CLI tool
processes one video per invocation.  Shell-level parallelism (`xargs`, GNU
`parallel`) can be used for batch imports.

---

## 9. OAuth / cookie-based yt-dlp authentication

The PHP encoder supports passing an OAuth token or a cookies file to yt-dlp.
This tool supports a `cookies_file` parameter in `downloader.download_video()`
but does not expose it as a CLI flag yet.  Set the `YTDLP_COOKIES` env var is
not implemented; this is a future improvement.

---

## 10. The `return_vars` payload

The PHP encoder uses `return_vars` to carry per-job context through multiple
round-trips (e.g. `encoder_queue_id`, `streamers_id`, `format`, `resolution`).
This tool always sends `{"encoder_queue_id": 0}`.  The server stores this value
but only uses it for logging and the `notifyIsDone` callback.
