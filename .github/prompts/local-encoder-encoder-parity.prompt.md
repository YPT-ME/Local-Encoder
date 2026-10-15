---
name: "Local Encoder Encoder Parity"
description: "Port a feature from the official AVideo PHP Encoder to Local Encoder, or audit feature parity between them. Reads the PHP implementation and the Streamer receiver first, keeps multi-site compatibility, and updates docs/encoder-parity.md."
argument-hint: "Name the Encoder feature to port (e.g. 'WebM output', 'release date', 'resume upload'), or 'audit' for a full parity review"
agent: agent
---

# Local Encoder — Encoder Parity

Task: **{{ENCODER_FEATURE}}**

Local Encoder must offer at least every uploader-facing feature of the PHP Encoder
(`D:\git\htdocs\AVideo\.compose\encoder\`). The current status is in `docs/encoder-parity.md`.

## Mode A — Port a Feature

### 1. Understand the Original
- Find the feature in the PHP Encoder: UI (`view/index.php`, `view/*.php`,
  `view/jquery-file-upload/js/main.js`), logic (`objects/Encoder.php`, `Format.php`,
  `HLSProcessor.php`, `MP4Processor.php`, `Streamer.php`, `Login.php`, `functions.php`), and DB
  formats (`install/database.sql`).
- Find what the Streamer does with it: `D:\git\htdocs\AVideo\objects\aVideoEncoder*.php` and the
  helpers they call; which plugin/setting enables it (`advancedCustom.json.php`, VideoHLS,
  Scheduler, UserGroups…).
- Write down, with `file:line`: inputs, the FFmpeg commands or HTTP requests, the order of calls,
  error handling, and how the UI hides/shows it based on site flags.

### 2. Design the Local Version
- Same observable result on the site (files, fields, statuses) as the official Encoder.
- Behavior on sites that lack the plugin/setting or run an older AVideo: detect and degrade
  gracefully with a plain-language note.
- UX for non-technical users: automatic by default; expose an option only if the Encoder exposes
  it to uploaders, with a clear label and a safe default.
- Where it goes: HTTP in `avideo_client.py`, FFmpeg in `encoder.py`, orchestration shared by
  `server.py` and `cli.py`, UI in `static/index.html`, CLI flag in `cli.py`.
- If the PHP behavior is buggy or unsafe, do not copy the bug: match the result, document the
  deviation.
- Present the plan before coding when it changes user-visible behavior or the protocol.

### 3. Implement and Validate
- Follow `local-encoder-new-feature.prompt.md` Phases 3–4.
- Unit tests assert the exact request fields / FFmpeg argument list that mirror the PHP Encoder.
- End-to-end test on https://vlu.me/ (`local-encoder-e2e-test.prompt.md`); compare the result
  with the same video sent through the PHP Encoder at https://vlu.me/Encoder/ when practical.
- Update the row in `docs/encoder-parity.md` (status + notes) and `docs/avideo-encoder-protocol.md`
  if you learned something new about the protocol.

## Mode B — Parity Audit

1. Re-inventory the PHP Encoder features from its UI and `Format.php` orders (do not trust the
   existing doc blindly — the Encoder evolves).
2. For each feature, check Local Encoder's code (not its README) and classify:
   ✅ present · 🟡 partial/different · ❌ missing · 🐞 present but broken · ➖ not applicable (explain).
3. Re-verify every entry in "Known Defects".
4. Update `docs/encoder-parity.md` with dates and evidence (`file:line`).
5. Output a prioritized backlog: first defects that break uploads on current AVideo, then features
   most uploaders use (Auto HLS/MP4, thumbnails, metadata, reliability), then the rest.

## Output

- What was ported/audited, with links to the PHP source and the new code.
- Deviations from the PHP Encoder and why.
- Validation results (checks + end-to-end) and anything not verified.
- The updated parity rows.
