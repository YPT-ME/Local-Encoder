---
description: Debug a Local Encoder problem (failed download, encode, upload, login, UI, CLI) using logs and the real code path, then apply a minimal fix.
argument-hint: Describe the issue, error message, log excerpt, or AVideo site involved
allowed-tools: Bash(git log:*), Bash(git diff:*), Bash(git show:*)
---

Read `.github/prompts/local-encoder-debug.prompt.md` in full with the Read tool before doing anything else —
it is the canonical spec for this workflow and this command only routes to it.

Wherever that prompt says `{{ISSUE_DESCRIPTION}}`, use:

$ARGUMENTS

Gather the real context first (do not assume): read `local-encoder logs`, trace the code path that
actually decides the behavior on both sides (Local Encoder and the AVideo receiver), and form one
falsifiable hypothesis before editing.
