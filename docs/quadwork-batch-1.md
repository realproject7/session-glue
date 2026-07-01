# Session Glue QuadWork Batch 1

## Active Batch

Dispatch target: QuadWork project `session-glue`, repo `realproject7/session-glue`.

Operator instruction:

```text
@head pick up Session Glue Batch 1. Assign implementation to @dev. Require review from both @re1 and @re2 before merge. Each PR must reference its GitHub issue with Fixes #N.
```

## Batch Goal

Establish the Python package foundation and schema/fixture layer for Session Glue without implementing broad CLI behavior yet.

## Tickets

### #2 Package scaffold and project metadata

GitHub issue: https://github.com/realproject7/session-glue/issues/2

Route: VPS QuadWork.

Build a minimal Python package scaffold:

- `pyproject.toml`
- package module `session_glue`
- console scripts `glue` and `session-glue`
- `--help` and `--version`
- pytest setup
- README development commands

Acceptance:

- `python -m pip install -e .` works
- `glue --help` works
- `session-glue --help` works
- `glue --version` works
- `pytest` passes

Non-goals:

- no `.agent-history/` writing
- no installer logic
- no daemon, MCP, database, watcher, UI, cloud sync

### #3 Handoff schema and fixture library

GitHub issue: https://github.com/realproject7/session-glue/issues/3

Route: VPS QuadWork.

Add schema helpers and deterministic fixtures:

- YAML frontmatter parser/serializer for markdown handoff files
- required field validation
- valid and invalid fixture handoffs
- `INDEX.yaml.first_next_action` mirror checks
- `RESUME_PROMPT.txt` generation tests

Critical rule:

`next_todo_items[0]` must be the first productive work item after resume mechanics. It must not be a resume mechanic like "start a new session", "paste the prompt", "read LATEST.md", "inspect the handoff", or "verify resume".

Acceptance:

- valid fixture parses
- missing-field fixture fails
- invalid resume-mechanic `next_todo_items[0]` fixture fails or reports expected lint
- `INDEX.yaml.first_next_action` equals handoff `next_todo_items[0]`
- generated resume prompt points at `LATEST.md` and says to continue from `next_todo_items[0]`
- tests do not require network or user home access

## Required QuadWork Flow

- `@head` assigns the batch to `@dev`.
- `@dev` opens PRs against `main`.
- `@re1` and `@re2` both review every PR.
- `@head` merges only after both reviews are satisfied.
- Keep scope limited to #2 and #3.

## Implementation Constraints

- Keep v1 super simple.
- Do not add daemon, MCP dependency, embeddings, database, watcher, product UI, OS clipboard access, or cloud sync.
- Do not mutate user home files.
- Prefer small conventional Python packaging over custom infrastructure.
