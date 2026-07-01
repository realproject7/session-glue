# Ticket 6: Global installer dry-run blocks

## Route

VPS QuadWork for implementation. lead-po performs local verification before any real user-home mutation.

## Summary

Implement dry-run installer commands that show the managed instruction blocks Session Glue would add to coding-agent instruction files.

## Scope

Add dry-run support for:

- `glue install codex --dry-run`
- `glue install claude --dry-run`
- `glue install cursor --dry-run`
- `glue install gemini --dry-run`
- optional `glue install all --dry-run`

## Managed Block

Use explicit begin/end markers so future updates can be idempotent.

The block should tell agents how to respond to:

- `/glue`
- `/freeze`
- `/handoff`
- `/checkpoint`
- natural-language requests to glue/freeze/checkpoint a session

The block should preserve v1 constraints:

- write repo-local `.agent-history/`
- print `RESUME_PROMPT.txt` content in a fenced code block
- no OS clipboard access
- no daemon
- no external service

## Acceptance Criteria

- Dry-run commands print target path and proposed block.
- Dry-run commands do not modify user home files.
- Managed block markers are stable and test-covered.
- Installer logic can detect an existing block in fixture files.
- Non-dry-run behavior is either not implemented or guarded behind an explicit flag and tests; actual local verification is not part of this ticket.

## Non-Goals

- Do not mutate real `~/.codex`, `~/.claude`, Cursor, or Gemini files in tests.
- Do not implement OS clipboard access.
- Do not add MCP, daemon, watcher, database, or UI.
