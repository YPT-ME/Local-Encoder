---
description: Draft a reply to a Local Encoder GitHub issue for a (usually non-technical) user (reply in English, like AVideo).
argument-hint: Paste the issue text or give the issue number/URL
allowed-tools: Bash(gh issue view:*), Bash(gh issue list:*)
---

Read `.github/prompts/local-encoder-github-issue-answer.prompt.md` in full with the Read tool before doing anything else —
it is the canonical spec for this workflow and this command only routes to it.

Wherever that prompt says `{{ISSUE_URL_OR_TEXT}}`, use:

$ARGUMENTS

Investigate in the code before answering; do not post anything without the user's approval.
