# Ticket 4: `glue validate` and next-action lint

## Route

VPS QuadWork.

## Summary

Implement validation for Session Glue handoff artifacts, with special focus on preventing resume-mechanic todos.

## Scope

- Add `glue validate`.
- Validate `LATEST.md` frontmatter.
- Validate archived session markdown files when requested.
- Validate `INDEX.yaml`.
- Validate `RESUME_PROMPT.txt` exists when expected.
- Add heuristic lint for `next_todo_items[0]`.

## Critical Lint

Reject or warn on obvious resume mechanics in `next_todo_items[0]`, including case-insensitive phrases such as:

- start a new session
- paste the prompt
- read latest
- read `LATEST.md`
- inspect handoff
- inspect `LATEST.md`
- verify resume
- check whether the new agent

The exact phrase list can be conservative. The goal is to catch the dogfood failure without building a semantic classifier.

## Acceptance Criteria

- `glue validate` exits zero for valid fixtures.
- `glue validate` exits non-zero, or emits a clearly testable warning mode, for invalid `next_todo_items[0]`.
- `glue validate` catches missing required frontmatter fields.
- `glue validate` catches mismatch between `INDEX.yaml.first_next_action` and `LATEST.md` `next_todo_items[0]`.
- Tests cover valid, missing-field, index-mismatch, and resume-mechanic cases.

## Non-Goals

- Do not add LLM-based validation.
- Do not add embeddings or retrieval.
- Do not add daemon, watcher, MCP, database, or UI.
