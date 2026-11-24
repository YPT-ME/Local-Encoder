# AVideo Encoder ↔ Streamer Protocol (reference)

How the official PHP Encoder talks to an AVideo site (the "Streamer"), and therefore what
Local Encoder must send. Paths: Encoder = `D:\git\htdocs\AVideo\.compose\encoder\`,
Streamer = `D:\git\htdocs\AVideo\`. Line numbers drift — re-check them before relying on details.
Rules derived from this document live in
`.github/instructions/local-encoder-avideo-integration.instructions.md`.

## Common to every call

Official Encoder (`objects/Encoder.php` `sendToStreamer()`):

- POST multipart. It follows redirects (up to 5).
- User-Agent is `AVideoEncoder <encoder-host> ` (`objects/functions.php` `getSelfUserAgent()`). The Streamer
  recognizes any UA containing `AVideoEncoder` (`$AVideoEncoder_UA`, `objects/functionsAVideo.php`
  `isAVideoUserAgent()`).
- Timeout is 180 s, or 7200 s for media transfers and notify.
- Fields added automatically:
  - auth: `streamers_id`, `user`, `pass` (the login token);
  - `return_vars` (JSON);
  - `releaseDate`/`releaseTime`;
  - `videos_id`/`video_id_hash`;
  - `timezone`, an IANA name.
- The Encoder turns off TLS verification. Local Encoder keeps it on by default.
- Error codes in responses: `streamer_access_denied`, `destination_unavailable`,
  `completion_in_progress`, `completion_failed`.
- A response that contains `video_id`, `videos_id` or `video_id_hash` updates the job's IDs.
- `timezone` is read only by the Scheduler plugin, to convert `releaseDate` into the site's time
  (`plugin/Scheduler/Scheduler.php:446-449`). Send an IANA name whenever a release date is sent.
- `encoder_queue_id` must be a top-level field. The Encoder sends it only on the metadata-only
  `first_request` call (`.compose/encoder/objects/Encoder.php:1498-1512`).

Verified on the local Docker site (https://vlu.me/, 2026-10-15):

- With a browser User-Agent, `advancedCustom.json.php` and `status` answer **302 → /user** (login required). With an `AVideoEncoder …` UA they answer 200.
- `curl`'s default UA gets `Bot Found [curl]` (`$global['stopBotsList']`).
- `aVideoEncoderChunk.json` without auth headers answers **403 `{"error":true,"msg":"Forbidden"}`**.

## Endpoints

| # | Endpoint (rewrite → file) | Method | Request | Response / notes |
| --- | --- | --- | --- | --- |
| A | `login` → `objects/login.json.php` | POST | `user`, `pass`, `encodedPass` (`false` with the typed password; `1` with the token) | Failure: `error` string (blank credentials, unverified e-mail, captcha, too many attempts, 2FA). Success: `id, user, name, pass` (`_user_hash_…` token, ~1 day, revoked when the password changes), `email, isLogged, isAdmin, canUpload, canComment, canCreateCategory, canStream, categories[], userGroups[] (id, group_name), allowedResolutions, videoHLS`. Rate limits: 30 per 5 min per IP; 10 per 5 min for Encoder/Mobile UAs (HTTP 429) |
| B | `aVideoEncoder.json` → `objects/aVideoEncoder.json.php` | POST | See [field list B](#field-list-b) | `error, video_id, videos_id, video_id_hash, releaseDate, releaseTime, msg, code`. See [behavior notes B](#behavior-notes-b) |
| C | `aVideoEncoderChunk.json` → `objects/aVideoEncoderChunk.json.php` | PUT raw body to `?file_id=<hex ≤64>&chunk=<i>&total=<n>` | Auth headers **required**: `X-Encoder-Upload-Token`, or `X-Encoder-User` + `X-Encoder-Pass` (token) | `{file, filesize, chunk, total, complete}`. Errors: 409 out-of-order/corrupt, 413, 400 size mismatch, 500. Re-sending a committed chunk returns `replay` (safe). Temp file is `sys_get_temp_dir()/YTPChunk_<id>`, removed after 4 h. Max 32 GB (`encoderChunkMaxTotalBytes`). Older servers: single PUT without `file_id` → `{file, filesize}` |
| D | `objects/aVideoEncoderReceiveImage.json.php` | POST multipart | `videos_id`, `duration`, `image` (jpg), `gifimage`, `webpimage`, `spectrumimage`, or `downloadURL_*` (the Streamer downloads it). `update_video_id` is needed to overwrite existing images | `error, video_id, video_id_hash, jpgDest, gifDest, webpDest` |
| E | `objects/aVideoEncoderNotifyIsDone.json.php` | POST | `videos_id`, `fail` (0/1), `overrideStatus`, `releaseDate`/`releaseTime` | `error, video_id, code`. A successful-completion marker protects subsequent calls; interrupted hooks can repeat side effects. Returns `completion_in_progress` while locked. Applies the final status (moderation → scheduled → overrideStatus → releaseDate → default) and fires plugin hooks |
| F | `objects/aVideoEncoderLog.json.php` | POST | `msg`, `type` (`StatusObs`, `StatusChanged`, `error`, `info`), `videos_id` | Appended to the video's encoder log |
| G | `objects/aVideoEncoderAlert.json.php` | POST | owner alerts (`waiting`, `processing`, `error`, `*_reminder`) or `type=system` | 404 on older Streamers. Used by the Encoder's cron monitor |
| H | `status` → `objects/status.json.php` | GET | — | `max_file_size, file_upload_max_size, videoStorageLimitMinutes, currentStorageUsage, version, plugins{}` |
| I | `plugin/CustomizeAdvanced/advancedCustom.json.php` | GET | — | Encoder flags: see [the flags list under I](#flags-from-endpoint-i) |
| J | UI helpers | various | `objects/categories.json.php`; `objects/videos.json.php` (search the user's videos, for "replace existing video"); `objects/usersGroups.json.php`; `objects/videoAddNew.json.php` (create/edit metadata, playlists) | — |

Login (A) adds `videoHLS: true` only when the VideoHLS plugin is enabled
(`objects/login.json.php:359-362`). Without it the site cannot play an HLS zip, so do not send
one; the PHP Encoder hides HLS in that case.

The rewrites for A, B, C and H live in `.htaccess`. On installs without rewrites, use the `objects/*.json.php` paths directly.

### Field list B

The media source is one of:

- `video` (multipart file);
- `downloadURL` (the Streamer downloads it);
- `chunkFile` (the path that C returned).

The other fields:

- `format` must be in `allowedExtension`. Current list: `gif jpg mp4 webm mp3 m4a ogg zip m3u8 webp`.
- `resolution` must be in `avideo_possible_resolutions`: 240 … 2160, `offline`, `HD`, `SD`, `Low`. Send it empty for an HLS zip.
- `duration` is `HH:MM:SS[.f]`.
- Metadata: `title`, `description`, `categories_id`, `usergroups_id[n]`.
- Source and encoder: `videoDownloadedLink`, `encoderURL`.
- Status: `keepEncoding`, `overrideStatus`.
- Bootstrap: `first_request=1`, `encoder_queue_id`.

### Behavior notes B

- A request without media and with `first_request` is **metadata-only**: it creates or updates the record and deduplicates on `encoder_queue_id`.
- Title and description are set only if the video does not already have them.
- The file is stored as `{filename}_{resolution}.{format}`. A zip is unzipped into the video folder.
- `first_request` + `downloadURL` on an existing video deletes its old files.
- An invalid resolution triggers `forbiddenPage`.

### Flags from endpoint I

- `doNotShowEncoderAutomaticHLS`, `doNotShowEncoderAutomaticMP4`, `doNotShowEncoderAutomaticWebm`, `doNotShowEncoderAutomaticAudio`
- `showOnlyEncoderAutomaticResolutions`
- `doNotShowEncoderHLS`
- `doNotShowEncoderResolutionLow`, `doNotShowEncoderResolutionSD`, `doNotShowEncoderResolutionHD`
- `doNotShowExtractAudio`, `doNotShowCreateVideoSpectrum`
- `autoConvertVideosToMP3`, `autoConvertToMp4` (from VideoHLS)
- `saveOriginalVideoResolution`, `singleResolution`
- `disableReleaseDate` (from Scheduler)
- `doNotAllowEncoderOverwriteStatus`, `doNotAllowUpdateVideoId`

## Official send order (`Encoder.php`)

1. Send a metadata-only bootstrap (B) and receive `videos_id` and `video_id_hash`.
2. Download the source.
3. Send the images (D). This happens **before** encoding: JPG at duration/2 (capped at 600 s), or the yt-dlp thumbnail for imports.
4. Encode.
5. For audio, send the spectrum image.
6. Send each output file, smallest first, with the auto-converted MP3 last:
   - The Encoder first offers `downloadURL` so the Streamer pulls the file. Local Encoder cannot be reached from the site, so it skips this.
   - Otherwise it sends chunk PUTs (C). It validates every response and, if a chunk fails, resumes with the same `file_id` (backoff 2, 4, 8, 16, 30, 30 s).
   - Then it sends B with `chunkFile`.
   - On 413 or when retries run out, it falls back to a multipart `video` POST.
7. Notify (E): `fail=0` on success, `fail=1` on failure. Local Encoder requires an explicit
   `error: false` response before marking the job successful or deleting its local files.
   - `completion_in_progress` is polled (2, 4, 8, 16, 32 s, then every minute) for up to 4 hours:
     storage hooks such as CDNStorage move every HLS segment inside this request and can run for
     hours (4,305 files, about 2 h ETA, for a 6 GB movie on flixhouse.com).
   - A dropped connection, a read/write timeout or HTTP 502/503/504 is retried up to 8 times
     (15, 30, 60, 120 s…). Connection/TLS failures keep their original diagnosis immediately.
     HTTP 500 is not automatically retried: the completion marker only protects an operation
     that finished successfully; an interrupted hook may already have sent a notification.
     Even transport/gateway recovery cannot guarantee exactly-once plugin side effects.
   - The web UI can cancel backoff, busy polling and an in-flight completion request. Cancellation
     stops local waiting; it does not roll back a storage hook already running on the site.
     The 4-hour busy deadline includes time spent making requests, rather than just sleep time.
   - `fail=1` is sent only before primary video media receipt is acknowledged. `setAutoStatus()` turns `fail=1` into
     status `x` (encoding error) and reruns the hooks, so it must never follow a complete upload.
     After video media arrived, failed MP3/image transfers keep their files and can be retried
     without sending the video again. MP3 extraction remains best effort. After auxiliary uploads
     also succeed, "Try again" repeats only completion and skips the
     register call, because register (B without media) sets status `e` and a request that hits
     the completion marker does not set the final status again. This checkpoint is resumed before
     probing or choosing a new format, even if the source was removed or site settings changed.
     Retried callbacks use the current same-account login, without persisting/replaying an old
     `video_id_hash`. Access/destination errors retain their codes: reconnect/restore permission
     before retrying; if the destination was deleted, add a new video explicitly. A permission
     error never silently recreates the destination.
     A lost response from the media-save POST itself remains a pre-existing ambiguity: until
     `upload_file()` returns, the client has no receipt checkpoint. This completion recovery
     does not establish exactly-once media-save acknowledgements across arbitrary sites.
   - Pitfall: `opcache_reset()` (the admin **Clear cache** button → full `clearCache()`) kills every
     PHP request still running `opcache.force_restart_timeout` (default 180 s) later. Apache logs
     `(<pid>): Error Cannot kill process <pid>!` and the client sees "Server disconnected without
     sending a response". OPcache is shared by every site on the same Apache/PHP-FPM pool.
     The reviewed AVideo change invalidates this site's cached scripts individually on a full
     clear instead of calling `opcache_reset()`, including when timestamp checks are disabled.
     Preloaded code still requires a separately managed PHP restart; file-cache-only/restricted
     OPcache configurations need deployment-specific verification. Older sites may still reset
     the pool, so the client retains transport recovery.
   Other failures are surfaced to the user and the converted files are kept.

## Authentication details

- Updated Streamers optionally provide `plugin/CustomizeAdvanced/localEncoderLogin.json.php`:
  POST `action=issue,challenge,globalToken` from an authenticated uploader, or verified Encoder
  `user,pass,encodedPass=1` instead of browser CSRF. POST `action=redeem,code,verifier` exchanges
  the 120-second single-use S256 grant for the normal `user,pass` token. Local Encoder validates
  that token through the existing login endpoint with `encodedPass=1`; it never weakens normal
  login or upload checks. See [browser integration](browser-integration.md) for transport and
  fallback behavior. Older Streamers keep the normal username/password connection flow.

- The token from A is the only "already encoded" password current Streamers accept; pass-the-hash was removed. Always reuse the exact `pass` value returned by login.
- A current `video_id_hash` authenticates as its issuer (legacy hashes without `issuedTo` use the
  owner). It expires after 24 hours and is bound to the owner/issuer passwords. Without a hash,
  `useVideoHashOrLogin()` authenticates the request's current `user`/`pass` credentials.
- Every `*.json.php` goes through `autoCSRFGuard`.
  - Bypassed by path: `aVideoEncoder.json.php`, `…Log`, `…NotifyIsDone`, `…ReceiveImage`, `login.json.php`, `categories.json.php`, `videos.json.php`.
  - Not bypassed: `aVideoEncoderChunk.json.php` and `aVideoEncoderAlert.json.php`. Those accept only same-origin requests or an AVideo user agent.
- Auto rate limit: 300 requests per 60 s per IP per endpoint.
