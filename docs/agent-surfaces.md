# Agent skill/rules surfaces — research

Research feeding a future decision on whether Session Glue should add first-class
`glue skill` install support for agents beyond Codex and Claude. This document is
research only; it implements nothing.

## Requirement

Session Glue installs into **dedicated per-repo or per-user skill/rules folders**
and never mutates broad or global instruction files (for example `AGENTS.md`,
`CLAUDE.md`, or a hierarchical context file). An agent is a real installer
candidate only when it exposes such a dedicated folder. Surfaces that are only a
shared instruction file are print-only or defer territory.

Recommendation vocabulary, one per agent:

- **support next** — a dedicated per-repo and/or per-user skill/rules folder
  exists; a real installer is worth building.
- **print-only** — no dedicated folder we can safely own; the only surface is a
  shared instruction file, so `glue` should at most print guidance for the user
  to paste, never write it.
- **defer** — a dedicated folder may exist but the artifact shape or mapping is
  unresolved; revisit after a design decision.

All findings were checked against current official documentation on
**2026-07-09**.

## Summary

| Agent | Dedicated per-repo folder? | Repo-scope path | User-scope path | Format | Recommendation |
|-------|----------------------------|-----------------|-----------------|--------|----------------|
| Cursor | Yes — project *rules* folder | `<repo_root>/.cursor/rules/` | none (app settings only) | `.mdc` with frontmatter | support next\* |
| Gemini CLI | No dedicated skill/rules folder for context | — (context is `GEMINI.md`) | — (`~/.gemini/GEMINI.md`) | Markdown instruction file | defer |
| OpenCode | Yes — `SKILL.md` skill folder | `<repo_root>/.opencode/skills/<name>/` | `$HOME/.config/opencode/skills/<name>/` | `SKILL.md` + YAML frontmatter | support next |

\* Cursor is a support-next target for **repo scope only**, and requires a
Cursor-specific `.mdc` rule artifact rather than the current `SKILL.md` bundle —
see the Cursor section.

## Cursor

**Dedicated per-repo folder: yes (rules folder).** Cursor project rules live in a
version-controlled directory that is scoped to the codebase and supports nested
subfolders, so a dedicated `session-glue` area is possible without touching any
shared instruction file.

- **Repo scope:** `<repo_root>/.cursor/rules/` — holds `.mdc` rule files and may
  be organized into subdirectories (for example
  `.cursor/rules/session-glue/…mdc`).
- **User scope:** no filesystem folder. User (global) rules are defined inside the
  application under **Customize → Rules**, not on disk, so they are not
  installable by copying files.

**Format caveat.** Cursor's rules system reads `.mdc` files with frontmatter
(`description`, `globs`, `alwaysApply`) and **ignores a plain `.md` file** placed
in `.cursor/rules/`. Session Glue's current bundle ships a `SKILL.md` plus a
`references/protocol.md`, which Cursor will not load as a rule. Real support
therefore requires authoring a Cursor-specific `.mdc` rule artifact (which can
reference or embed the protocol), not copying the existing skill folder.

- Citations (checked 2026-07-09):
  - Cursor — Rules: <https://cursor.com/docs/rules>

**Recommendation: support next** (repo scope). A dedicated per-repo rules folder
exists and is safe to own; the work is to add a `.mdc` rule artifact for Cursor.
User scope is not folder-installable and is print-only at most.

## Gemini CLI

**Dedicated per-repo skill/rules folder: no.** Gemini CLI sources persistent
instructions from **context files named `GEMINI.md`**, loaded hierarchically and
concatenated into every prompt:

- **User scope:** `$HOME/.gemini/GEMINI.md` (defaults for all projects).
- **Repo scope:** `<repo_root>/GEMINI.md` (and subdirectory `GEMINI.md` files).

These are broad, shared instruction files — exactly the kind Session Glue must not
mutate — so they are not an install target.

Gemini CLI does expose a dedicated **custom-commands** folder, but it is for
TOML-defined slash commands, not skills or persistent rules:

- **Repo scope:** `<repo_root>/.gemini/commands/` (e.g. `session-glue.toml`).
- **User scope:** `$HOME/.gemini/commands/` (project command wins on name clash).
- **Format:** `.toml` with a required `prompt` field and optional `description`;
  subdirectories namespace the command (`git/commit.toml` → `/git:commit`).

This folder is safe and dedicated, but a custom command is a one-shot slash
command, not a session-resume skill/rule. Mapping Session Glue onto a command
(whose `prompt` would point at the `glue` CLI) is a separate design decision.

- Citations (checked 2026-07-09):
  - Gemini CLI — Provide context with GEMINI.md files:
    <https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html>
  - Gemini CLI — Custom commands:
    <https://google-gemini.github.io/gemini-cli/docs/cli/custom-commands.html>

**Recommendation: defer.** There is no dedicated per-repo skill/rules folder for
persistent context (the only such surface is the `GEMINI.md` global instruction
file, which is off-limits). The `.gemini/commands/` folder is safe but fits a
slash-command shape, not a skill; committing to it needs its own decision. Interim
safe fallback is print-only — `glue` can print a `GEMINI.md` snippet or a
`.gemini/commands/session-glue.toml` for the user to add by hand — but a real
installer should defer.

## OpenCode

**Dedicated per-repo and per-user folder: yes (`SKILL.md` skill folder),** using
the same `SKILL.md`-per-folder format Session Glue already ships. Each skill is
one folder named for the skill, containing a `SKILL.md` that starts with YAML
frontmatter.

OpenCode discovers skills from multiple roots, including two that Session Glue
already populates for Claude and Codex:

- **Repo scope:**
  - `<repo_root>/.opencode/skills/<name>/SKILL.md` (OpenCode-native)
  - `<repo_root>/.claude/skills/<name>/SKILL.md` (also read)
  - `<repo_root>/.agents/skills/<name>/SKILL.md` (also read)
- **User scope:**
  - `$HOME/.config/opencode/skills/<name>/SKILL.md` (OpenCode-native)
  - `$HOME/.claude/skills/<name>/SKILL.md` (also read)
  - `$HOME/.agents/skills/<name>/SKILL.md` (also read)

Because OpenCode also reads `.claude/skills/` and `.agents/skills/`, the Claude
and Codex skill folders Session Glue installs today are **already discovered by
OpenCode with no additional work**. A first-class `opencode` agent that targets
`.opencode/skills/session-glue/` would be a data-style addition mirroring Codex
and Claude.

**Frontmatter note.** OpenCode recognizes only these `SKILL.md` frontmatter
fields: `name` (required), `description` (required), `license`, `compatibility`,
and `metadata` (a string-to-string map); the skill `name` must match its
containing directory (`^[a-z0-9]+(-[a-z0-9]+)*$`). Any future OpenCode-native
install should confirm the bundled frontmatter stays within these fields.

- Citations (checked 2026-07-09):
  - OpenCode — Agent Skills: <https://opencode.ai/docs/skills/>
  - OpenCode — Rules: <https://opencode.ai/docs/rules/>

**Recommendation: support next.** Strongest candidate: a dedicated `SKILL.md`
folder at both repo and user scope, in the format Session Glue already produces,
and existing installs are already picked up via the `.claude`/`.agents` roots.
