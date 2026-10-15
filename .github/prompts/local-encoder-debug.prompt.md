---
name: "Local Encoder Debug"
description: "Debug a Local Encoder problem using logs, the real code path on both sides (Local Encoder and the AVideo receiver), and a minimal safe fix. Use for a failed download, encode, upload, login, a wrong result on the AVideo site, a UI/CLI error, or any unexpected behavior."
argument-hint: "Describe the issue, error message, log excerpt, AVideo site/version, and what the user did"
agent: agent
---

# Local Encoder Debug Session

Debug the following issue in Local Encoder: **{{ISSUE_DESCRIPTION}}**

## Step 1: Gather Context (Do Not Assume)

1. **Entry point**: web UI action (`/api/import`, `/api/import-file`, `/api/test-connection`,
   `/api/categories`), CLI command (`local-encoder import|serve|logs`), or the frozen executable?
2. **Pipeline stage**: download (yt-dlp) → probe → encode (FFmpeg) → thumbnails → login →
   register (`aVideoEncoder.json` first request) → chunk upload (`aVideoEncoderChunk.json`) →
   finalize (`aVideoEncoder.json` with `chunkFile`) → images → notify done. Find the last stage
   that succeeded.
3. **Logs**: `local-encoder logs` (file `~/.local/share/local-encoder/local-encoder.log`), the SSE
   `log`/`error` events shown in the UI, FFmpeg stderr, and — when the server side is involved —
   the AVideo site's log. Ask the user for the log excerpt if you cannot read it.
4. **The AVideo site**: URL, AVideo version if known, which plugins/settings matter (VideoHLS,
   `allowedExtension`, upload limits, bot blocker, HTTPS/self-signed). One Local Encoder talks to
   many different sites; a bug may exist only on one configuration.
5. Read the relevant source before suggesting anything — both `local_encoder/` and, for protocol
   issues, the Streamer receiver in `D:\git\htdocs\AVideo\objects\aVideoEncoder*.php` and the PHP
   Encoder implementation in `D:\git\htdocs\AVideo\.compose\encoder\` (how the official Encoder
   does the same step).

## Step 2: Compare With the Official Encoder

For any upload/protocol/encoding issue, check what the PHP Encoder sends or runs for the same step
(fields, endpoint, method, FFmpeg arguments, order of calls). A difference from the official
Encoder is the first suspect. See `docs/encoder-parity.md`.

## Step 3: Identify the Root Cause

Check these common causes before concluding:
- The site answered HTML instead of JSON (login redirect, `Bot Found [...]` user-agent blocker,
  PHP warning before the JSON, Cloudflare page).
- TLS: self-signed certificate with `ssl_verify` on, or redirect http↔https changing the method.
- Wrong/missing field compared with the official Encoder (`format`, `resolution`,
  `video_id_hash`, `chunkFile`, `encodedPass`, `return_vars`).
- Site restrictions: extension not in `allowedExtension`, resolution not allowed, upload/post size
  limit, user without upload permission, HLS plugin not enabled.
- FFmpeg/FFprobe: binary not found (`_frozen.py` resolution), unsupported input, missing codec,
  zero duration, timeout.
- yt-dlp: extractor broken (needs update), login/cookies required, geo-block.
- Windows-specific: path with spaces/non-ASCII, file locked by another process, antivirus.
- State: in-memory job lost after restart, two jobs writing the same file name.

Form **one falsifiable hypothesis** and name the cheapest check that could disprove it.

## Step 4: Minimal Safe Fix

- Smallest change that fixes the root cause, in the style of the surrounding module.
- Must keep working with other AVideo sites/versions; never weaken a Streamer-side check to make
  the client work.
- Turn the failure into a plain-language message for the user if it can happen again
  (see `local-encoder-user-experience.instructions.md`).
- If the real fix belongs in AVideo (`D:\git\htdocs\AVideo\`), say so, follow that repository's
  instructions for the PHP change, and still make the Local Encoder handle older sites gracefully.

## Step 5: Verification

- Exact reproduction steps before the fix, and exact verification steps after.
- A regression test in `tests/` that fails before the fix.
- `pytest`, `ruff check .`, `ruff format --check .`, `mypy local_encoder` results.
- For protocol/encoding issues: an end-to-end run against https://vlu.me/ (see
  `local-encoder-e2e-test.prompt.md`) or an explicit "manual verification still required".

## Constraints

- Do not swallow exceptions; do not show tracebacks to the user; never log credentials.
- Do not refactor unrelated code or rename public functions without checking every caller (CLI and
  server share the pipeline).
