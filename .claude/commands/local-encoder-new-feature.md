---
description: Implement a new Local Encoder feature safely: Encoder parity, multi-site AVideo compatibility, lay-user UX, tests.
argument-hint: Describe the feature or behavior you want
---

Read `.github/prompts/local-encoder-new-feature.prompt.md` in full with the Read tool before doing anything else —
it is the canonical spec for this workflow and this command only routes to it.

Wherever that prompt says `{{FEATURE_DESCRIPTION}}`, use:

$ARGUMENTS

Before writing code, check whether the PHP Encoder already has this feature and how it does it,
and confirm the Streamer endpoint/fields in the AVideo source. Keep the change small and in the
style of the surrounding module.
