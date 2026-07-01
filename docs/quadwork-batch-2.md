# Session Glue QuadWork Batch 2

Dispatch target: VPS QuadWork project `session-glue`, repo `realproject7/session-glue`.

## Active Batch

- #4 `glue create` core file writer
- #5 `glue validate` and next-action lint

## Operator Instruction

`@head` should pick up this batch on VPS QuadWork only. Assign implementation to `@dev`. Require both `@re1` and `@re2` review before merge. Each PR must reference its GitHub issue with `Fixes #N`.

## Batch Goal

Implement the first useful CLI behavior on top of the existing scaffold and schema layer:

1. `glue create` writes the repo-local `.agent-history/` artifacts.
2. `glue validate` verifies the artifacts and catches the original dogfood anti-pattern.

## Ticket #4: `glue create` Core File Writer

GitHub issue: https://github.com/realproject7/session-glue/issues/4

Build `glue create` so it creates or updates:

- `.agent-history/LATEST.md`
- `.agent-history/RESUME_PROMPT.txt`
- `.agent-history/INDEX.yaml`
- `.agent-history/sessions/<timestamp>-<slug>.md`

Acceptance:

- command creates all required files in a temp test repo
- archive file and `LATEST.md` are consistent
- `RESUME_PROMPT.txt` is generated
- `INDEX.yaml.first_next_action` mirrors `next_todo_items[0]`
- re-running creates a new archive and updates latest pointers
- tests do not touch the real user home

Constraints:

- no AI summarization
- no global installer behavior
- no OS clipboard access
- no daemon, watcher, database, MCP, telemetry, cloud sync, or UI

## Ticket #5: `glue validate` And Next-Action Lint

GitHub issue: https://github.com/realproject7/session-glue/issues/5

Build `glue validate` so it validates:

- `LATEST.md` frontmatter
- archived session markdown files when requested
- `INDEX.yaml`
- `RESUME_PROMPT.txt` presence when expected
- `next_todo_items[0]` resume-mechanic denylist

Critical lint:

Reject or warn on obvious resume mechanics in `next_todo_items[0]`, including case-insensitive phrases such as:

- start a new session
- paste the prompt
- read latest
- read `LATEST.md`
- inspect handoff
- inspect `LATEST.md`
- verify resume
- check whether the new agent

Acceptance:

- valid fixtures pass
- invalid `next_todo_items[0]` fails or emits a clearly testable warning mode
- missing required frontmatter fields are caught
- mismatch between `INDEX.yaml.first_next_action` and `LATEST.md` `next_todo_items[0]` is caught
- tests cover valid, missing-field, index-mismatch, and resume-mechanic cases

## Required QuadWork Flow

- `@head` assigns work to `@dev`.
- `@dev` opens PRs against current `main`.
- `@re1` and `@re2` both review every PR.
- `@head` merges only after both reviewers are satisfied.
- Keep scope limited to #4 and #5.
- Public content hygiene is binding: no credentials, tokens, private logs, `.env` contents, personal local paths, or sensitive screenshots in PR bodies, reviews, comments, fixtures, or docs.

## Implementation Notes

Prefer small stdlib-first code that matches the current package direction. Tests should use temp directories and fixtures rather than the real user home. Keep generated examples generic, for example `/path/to/project` instead of personal local paths.
