---
description: Review a Local Encoder pull request or diff for correctness, AVideo compatibility, Encoder parity, security, and lay-user UX.
argument-hint: PR number, branch, or 'current diff'
allowed-tools: Bash(git diff:*), Bash(git log:*), Bash(git show:*), Bash(git status:*), Bash(gh pr view:*), Bash(gh pr diff:*)
---

Read `.github/prompts/local-encoder-pr-review.prompt.md` in full with the Read tool before doing anything else —
it is the canonical spec for this workflow and this command only routes to it.

Wherever that prompt says `{{REVIEW_TARGET}}`, use:

$ARGUMENTS

Do not modify files. Report findings first, ordered by severity.
