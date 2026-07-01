# Ticket 2: Handoff schema and fixture library

## Route

VPS QuadWork.

## Summary

Define the handoff schema helpers and test fixtures that later CLI commands will use.

## Scope

- Add structured representation for handoff frontmatter.
- Add parser/serializer helpers for markdown files with YAML frontmatter.
- Add fixture handoffs for valid and invalid cases.
- Add fixture tests for required fields.
- Add fixture tests for `INDEX.yaml.first_next_action` mirroring `next_todo_items[0]`.
- Add fixture tests for `RESUME_PROMPT.txt` generation.

## Required Handoff Fields

- `session_id`
- `session_date`
- `generated_at`
- `schema_version`
- `project_root`
- `repo_root`
- `current_branch`
- `head_commit`
- `agent`
- `status`
- `active_context_files`
- `completed_tasks`
- `next_todo_items`
- `known_issues`

## Critical Rule

`next_todo_items[0]` must be the first productive work item after the new session has completed resume mechanics.

It must not be a resume mechanic such as:

- start a new session
- paste the prompt
- read `LATEST.md`
- inspect the handoff
- verify that resume worked

## Acceptance Criteria

- Valid fixture parses cleanly.
- Invalid missing-field fixture fails validation.
- Invalid `next_todo_items[0]` fixture fails or reports the expected lint.
- Fixture `INDEX.yaml.first_next_action` equals fixture handoff `next_todo_items[0]`.
- Generated resume prompt points at `LATEST.md` and says to continue from `next_todo_items[0]`.
- Tests are deterministic and do not require network or user home access.

## Non-Goals

- Do not write real `.agent-history/` files in this ticket.
- Do not implement full CLI commands in this ticket.
- Do not add retrieval, embeddings, database, watcher, or UI.
