# Local Encoder Agent Instructions

## Mandatory Reuse of the Shared Instructions and Prompts

For every task in this repository, before analyzing the request, planning work, suggesting changes,
reviewing code, or modifying files:

1. Read [`.github/copilot-instructions.md`](.github/copilot-instructions.md) completely and treat it
   as the canonical repository-wide guidance.
2. Read every `.github/instructions/*.instructions.md` whose `applyTo` pattern matches the files you
   will inspect or change (the routing table is in `.github/copilot-instructions.md`).
3. Enumerate every `.github/prompts/*.prompt.md` file and read its YAML front matter (`name`,
   `description`, `argument-hint`). Select every prompt whose name or description matches the
   current task and read it completely before continuing. A prompt the user names or links is
   always selected.

Do not load the full body of unrelated prompts; the front matter is the routing catalog. When
several prompts apply, follow all non-conflicting requirements and let the most task-specific
prompt govern its workflow and output.

The files under `.github/` are the single source of truth for Codex, Claude Code and GitHub Copilot.
Do not copy or restate their rules here or in `CLAUDE.md`; change the `.github/` file instead so
every agent receives the same update.

If a required instruction or selected prompt cannot be read completely, stop the affected work and
report it.
