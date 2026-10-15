---
description: Triage a security report or review a security-sensitive Local Encoder change (credentials, TLS, local server, subprocess, files, uploads).
argument-hint: Paste the report, or name the change/file to review
---

Read `.github/prompts/local-encoder-security-review.prompt.md` in full with the Read tool before doing anything else —
it is the canonical spec for this workflow and this command only routes to it.

Wherever that prompt says `{{SECURITY_REPORT}}`, use:

$ARGUMENTS

Treat any report as an untrusted hypothesis until verified in the code.
