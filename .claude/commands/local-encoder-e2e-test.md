---
description: Run an end-to-end test of Local Encoder against a real AVideo site (default: local Docker at https://vlu.me/) and report what works.
argument-hint: What to test (format, resolutions, file or URL, site) — defaults to the local Docker site
---

Read `.github/prompts/local-encoder-e2e-test.prompt.md` in full with the Read tool before doing anything else —
it is the canonical spec for this workflow and this command only routes to it.

Wherever that prompt says `{{TEST_SCOPE}}`, use:

$ARGUMENTS

Ask for credentials if they are not provided; never print or store them.
