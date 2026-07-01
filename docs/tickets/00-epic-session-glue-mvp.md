# EPIC: Session Glue MVP

## Summary

Build Session Glue v1: a lightweight, repo-local session continuity protocol and Python CLI for coding agents.

Session Glue lets an operator end a bloated agent session, generate a compact handoff, and resume in a fresh agent session without carrying the full chat history forward.

## Canonical Reference

- Proposal: `docs/PROPOSAL-session-glue.md`

## Product Boundary

V1 includes:

- repo-local `.agent-history/`
- markdown handoff files with YAML frontmatter
- `LATEST.md`
- archived session files under `.agent-history/sessions/`
- `INDEX.yaml`
- `RESUME_PROMPT.txt`
- Python CLI with `glue` and `session-glue` executables
- dry-run global instruction installers
- Codex skill wrapper after the CLI is usable
- Codex and Claude dogfood validation

V1 excludes:

- daemon
- MCP dependency
- embeddings
- vector database
- file watcher
- product UI
- automatic OS clipboard access
- cloud sync

## Initial Ticket Sequence

1. Package scaffold and project metadata
2. Handoff schema and fixture library
3. `glue create` core file writer
4. `glue validate` and next-action lint
5. `glue status` and `glue resume-prompt`
6. Global installer dry-run blocks
7. Codex skill wrapper
8. Dogfood and cross-agent validation
9. Release packaging and PyPI gate

## Routing

- VPS QuadWork: pure Python CLI implementation, schema, fixtures, deterministic tests, installer dry-run logic.
- lead-po direct: repo founding, local global-install verification, Codex skill packaging, Codex/Claude dogfood, release gates.
- operator gate: PyPI token/account usage, public release, and non-dry-run global installer behavior.

## Definition Of Done

- CLI can create, validate, summarize, and print resume prompts from repo-local handoffs.
- `glue validate` catches the original dogfood anti-pattern where `next_todo_items[0]` is a resume mechanic.
- `INDEX.yaml.first_next_action` mirrors `LATEST.md` frontmatter `next_todo_items[0]`.
- Fresh Codex and Claude sessions can resume from `RESUME_PROMPT.txt`.
- Normal resume path does not read large reference docs unless explicitly instructed.
- Package can be built and installed locally.
- PyPI release remains gated by operator approval.
