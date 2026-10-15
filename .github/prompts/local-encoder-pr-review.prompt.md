---
name: "Local Encoder PR Review"
description: "Review a Local Encoder pull request or diff. Checks correctness, AVideo protocol compatibility across sites/versions, parity with the PHP Encoder, security, lay-user UX, cross-platform behavior, packaging, tests, and lint/type quality."
argument-hint: "PR number/URL, branch, or paste the diff (defaults to the current diff)"
agent: agent
---

# Local Encoder Pull Request Review

Review target: **{{REVIEW_TARGET}}** (if empty, review the current working-tree/branch diff).

Do not modify files during a review.

## Context to Gather First

- Read the full diff and the code paths it changes (not only the changed lines).
- Identify the layers touched: AVideo client/protocol, FFmpeg/encoding, yt-dlp, pipeline
  (`server.py`/`cli.py`), web UI, config, packaging, tests.
- For protocol or encoding changes, open the matching PHP Encoder code
  (`D:\git\htdocs\AVideo\.compose\encoder\`) and Streamer receiver
  (`D:\git\htdocs\AVideo\objects\aVideoEncoder*.php`) and compare.

## Review Checklist

### 1. Correctness and Reuse
- Does it do what it claims? Edge cases (zero duration, audio-only, vertical, huge files,
  non-ASCII names, network failure mid-upload)?
- Duplicates existing logic (`AVideoClient`, `encoder.py`, `utils.py`) instead of reusing it?
- CLI and web UI pipelines still behave the same?

### 2. AVideo Compatibility
- Request fields/endpoint/method match the official Encoder? Changed fields asserted in tests?
- Works on sites without the related plugin/setting, older AVideo versions, self-signed TLS,
  sites that answer HTML instead of JSON?
- Any assumption of a single "current site" that breaks multi-site use?

### 3. Encoder Parity
- Does it move toward or away from parity (`docs/encoder-parity.md`)? Is the doc updated?

### 4. Security
- Credentials never logged/emitted/stored in URLs; TLS verification not silently disabled;
  subprocess argument lists only; paths confined to the work directory; HLS keys handled as
  secrets; server responses treated as untrusted; local API not more exposed.

### 5. User Experience (non-technical users)
- Safe defaults; plain-language labels and errors; progress visible; no tracebacks to users;
  failed uploads do not discard encoded work.

### 6. Cross-Platform and Packaging
- Windows/macOS/Linux paths and binaries; works in the PyInstaller executable (static files,
  bundled FFmpeg, hidden imports); no new mandatory install step.

### 7. Quality
- `mypy --strict` clean without blanket `Any`/`type: ignore`; ruff clean; no bare
  `except`/silent `except Exception: pass`; functions not ballooning (prefer extracting only when
  logic repeats).

### 8. Tests and Regression Risk
- Tests added/updated, no network or real FFmpeg in unit tests; blast radius described; end-to-end
  verification done or explicitly marked as required.

## Output Format

1. **Summary**: 2-3 sentences on overall quality and risk level (Low / Medium / High)
2. **Blockers**: issues that must be fixed before merging (security holes, broken uploads, data
   loss, breaking changes) — each with a clickable workspace-relative file link and evidence
3. **Warnings**: should be fixed but not merge-blocking
4. **Suggestions**: minor improvements
5. **Verdict**: Approve / Request Changes / Needs Discussion

Report only findings supported by the code; separate confirmed issues from assumptions.
