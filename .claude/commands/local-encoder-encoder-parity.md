---
description: Port a feature from the PHP AVideo Encoder to Local Encoder, or audit feature parity between them.
argument-hint: Name the Encoder feature to port, or 'audit' for a full parity review
---

Read `.github/prompts/local-encoder-encoder-parity.prompt.md` in full with the Read tool before doing anything else —
it is the canonical spec for this workflow and this command only routes to it.

Wherever that prompt says `{{ENCODER_FEATURE}}`, use:

$ARGUMENTS

Read the PHP implementation in `D:\git\htdocs\AVideo\.compose\encoder\` and the Streamer receiver in
`D:\git\htdocs\AVideo\objects\` before designing anything. Update `docs/encoder-parity.md` in the same task.
