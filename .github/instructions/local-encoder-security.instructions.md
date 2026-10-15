---
name: "Local Encoder Security"
description: "Use when writing or reviewing code that handles credentials, HTTP/TLS, the local web server, subprocess/FFmpeg/yt-dlp, files, ZIP/HLS packaging, uploads, logs, or anything security-related."
applyTo: "local_encoder/**"
---

# Local Encoder — Security Rules

Local Encoder runs on the user's own computer, holds their AVideo credentials, executes FFmpeg and
yt-dlp on untrusted media/URLs, and serves a local web UI. It also talks to many AVideo sites,
some of which may be misconfigured or hostile.

## Credentials

- The password is sent only to the AVideo `login` endpoint. After login, use the encrypted `pass`
  returned by the server with `encodedPass=1` (as `AVideoClient` does); never resend the plain
  password on other calls.
- Never log, print, emit over SSE, store in history, or put in an exception message: passwords,
  the encrypted `pass`, `video_id_hash`, cookies, or yt-dlp cookie files.
- Do not put credentials in URL query strings (they end up in logs and browser history); use a
  POST body.
- Web UI: the password lives only in memory and is sent once to `/api/test-connection`; the local
  server keeps the AVideo token in an in-memory session (`server._sessions`) and the browser keeps
  only the session id. Never persist the password in `localStorage`/`sessionStorage`.
- `.env` holds local secrets and is gitignored; never commit it or copy real values into
  `.env.example`, tests, docs or fixtures.

## TLS

- `ssl_verify=True` by default. Turning it off is an explicit user choice (`--ssl-no-verify`,
  *Verify SSL* checkbox) for self-signed test servers; never disable it silently, never as a
  fallback after a TLS error.

## Local Web Server (`server.py`)

- Bind to `127.0.0.1` by default. If binding to another interface is ever supported, it must be
  opt-in with a visible warning, because the API accepts credentials and starts jobs.
- The API changes state (starts downloads/encodes/uploads, accepts uploaded files). Do not add
  permissive CORS. Be aware that any web page the user visits can POST to `localhost`; new
  state-changing endpoints should not be triggerable by a simple cross-site form post (require a
  JSON body / custom header, or a per-session token).
- Implemented in `server._local_requests_only`: every request must have a local `Host`
  (`127.0.0.1`, `localhost`, `::1` – blocks DNS rebinding), and every non-GET request the
  `X-Local-Encoder: 1` header (a cross-site form cannot send it without a CORS preflight, which
  this server never answers). The page's `api()` helper and file uploads send it; keep it on new
  endpoints. GET endpoints must not change state.
- “Report a problem” zips the logs through `server.redact()` (passwords, `_user_hash_` tokens,
  `video_id_hash`); extend the patterns when a new secret could reach the log.
- Uploaded files from the browser: write only inside the job work directory with a generated name
  (`sanitize_filename` + unique id); never use the client-supplied path.

## Subprocesses (FFmpeg, FFprobe)

- Argument lists only, never `shell=True`, never string commands. Titles, file names and URLs are
  data, not command fragments.
- A file name or URL starting with `-` must not be interpretable as an FFmpeg option (use
  `-i` with an explicit path / `Path.resolve()`).
- Input from the internet is untrusted: always set timeouts, and do not enable FFmpeg network
  protocols on local-file inputs beyond what is needed.

## yt-dlp

- Use the Python API (`yt_dlp.YoutubeDL`) with explicit options; do not pass arbitrary
  user-supplied option dictionaries through.
- Accept only `http`/`https` URLs from the UI/CLI for remote import; local files go through the
  file-upload/local-path path.
- Keep `yt-dlp` updatable — site extractors break often; never pin it to an exact old version.

## Files, ZIP and HLS

- Write only under the configured output/work directory; build paths with `Path` and
  `sanitize_filename`; reject results that resolve outside the work directory.
- HLS ZIPs must contain relative paths only (no absolute paths, no `..`). The AES-128 key file is a
  secret: generate it with `secrets`, never log its bytes, and delete the work directory after a
  successful upload unless `keep_files` is set.
- Clean up temporary files on success and on failure (respecting `keep_files`).

## Server Responses

- Every AVideo response is untrusted input: tolerate missing keys, wrong types, HTML instead of
  JSON (bot blockers, login redirects, PHP warnings), and never `eval`/execute anything from it.
- Never follow a server-provided path or URL to write local files.

## Server-Side (AVideo) Security Work

If a task requires changing AVideo or the PHP Encoder (`D:\git\htdocs\AVideo\`), that repository's
canonical security policy applies: read
`D:\git\htdocs\AVideo\.github\prompts\avideo-security-advisory-triage.prompt.md` and
`D:\git\htdocs\AVideo\.github\instructions\avideo-security.instructions.md` before changing PHP code.
Never weaken a Streamer-side check (authentication, `video_id_hash`, `allowedExtension`,
`chunkFile` path validation) to make the Local Encoder work — fix the client instead.
