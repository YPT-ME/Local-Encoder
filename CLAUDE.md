# CLAUDE.md — Local Encoder

This file is the Claude Code entry point for this repository. The detailed rules are **not**
duplicated here: they live in `.github/` and are shared with GitHub Copilot and Codex, so there is a
single source of truth. Update `.github/`, never a second copy.

@.github/copilot-instructions.md

If the import above did not load for any reason, read `.github/copilot-instructions.md` in full
before analyzing or changing anything.

## Topic Rules — Read Before Touching Matching Files

GitHub Copilot auto-applies these by glob (`applyTo` front matter). Claude Code does not, so **read
the matching file(s) yourself before inspecting or editing code that matches the pattern**:

| Read this file | Before touching files matching |
| --- | --- |
| `.github/instructions/local-encoder-python.instructions.md` | `**/*.py` |
| `.github/instructions/local-encoder-avideo-integration.instructions.md` | `local_encoder/**` (AVideo protocol, Encoder parity, multi-site compatibility) |
| `.github/instructions/local-encoder-security.instructions.md` | `local_encoder/**` |
| `.github/instructions/local-encoder-user-experience.instructions.md` | `local_encoder/static/**`, `local_encoder/cli.py`, `local_encoder/server.py`, `local_encoder/progress.py`, `README.md`, `local-encoder.spec` |
| `.github/instructions/local-encoder-testing.instructions.md` | `tests/**`, and before declaring any change done |

## Workflows

Each `.github/prompts/*.prompt.md` is available as a slash command in `.claude/commands/`. The
command is only a router: it tells you to read the prompt file in full and execute it.

| Command | Purpose |
| --- | --- |
| `/local-encoder-new-feature` | Implement a feature safely (parity-aware, multi-site, lay-user UX) |
| `/local-encoder-encoder-parity` | Port a PHP Encoder feature, or audit parity with the PHP Encoder |
| `/local-encoder-debug` | Debug a failed import/encode/upload or any bug |
| `/local-encoder-e2e-test` | End-to-end test against a real AVideo site (local Docker: https://vlu.me/) |
| `/local-encoder-pr-review` | Review a pull request or diff |
| `/local-encoder-security-review` | Review a security report or security-sensitive change |
| `/local-encoder-github-issue-answer` | Draft a reply to a GitHub issue for an end user |

Two subagents in `.claude/agents/` mirror `.github/agents/`: `local-encoder-code-reviewer`
(read-only review) and `local-encoder-feature-implementer` (implements focused changes).

## Claude-Specific Notes

- Never edit `.claude/` and `.github/` rule files out of sync — change the rule in `.github/` and
  keep `.claude/` files as thin routers.
- Use the project virtualenv: `.venv\Scripts\python -m pytest`, `.venv\Scripts\ruff check .`,
  `.venv\Scripts\mypy local_encoder` (Windows paths; the shell may be PowerShell or Git Bash).
- AVideo source: `D:\git\htdocs\AVideo\` — PHP Encoder: `D:\git\htdocs\AVideo\.compose\encoder\`.
  Never grep the whole AVideo repo: exclude `vendor node_modules .compose .git` and search
  `.compose/encoder` by explicit path (`.compose/videos` and `.compose/db*` are huge).
- When working inside `D:\git\htdocs\AVideo\`, that repository's own `CLAUDE.md` and `.github/`
  rules apply to the files there.

While working, keep the shared documentation current: when you learn something important and
non-obvious about this project (a protocol detail, a pitfall, a command, an AVideo version
difference), record it in the right `.github/` instruction file or in `docs/` during the task.
Verify before writing, do not record assumptions, do not duplicate existing content, and keep the
top-level instructions short — move long details into `docs/`.
