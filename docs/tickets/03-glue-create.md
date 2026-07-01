# Ticket 3: `glue create` core file writer

## Route

VPS QuadWork.

## Summary

Implement the core file-writing path for `glue create`.

## Scope

`glue create` should create or update:

- `.agent-history/LATEST.md`
- `.agent-history/RESUME_PROMPT.txt`
- `.agent-history/INDEX.yaml`
- `.agent-history/sessions/<timestamp>-<slug>.md`

The command may start from explicit CLI options and/or a template body. Keep v1 simple and deterministic.

## Required Behavior

- Create `.agent-history/` if missing.
- Archive a timestamped session markdown file.
- Update `LATEST.md` to point to the newest handoff content.
- Generate `RESUME_PROMPT.txt`.
- Update `INDEX.yaml` with compact metadata.
- Do not access OS clipboard.
- Do not access network.
- Do not mutate files outside the current repo except through explicit output paths in tests.

## `INDEX.yaml` Requirements

Include:

- `schema_version`
- `latest_session`
- `latest_file`
- `repo_root`
- `current_branch`
- `head_commit`
- `first_next_action`
- compact session list

Do not duplicate the full `next_todo_items` list in `INDEX.yaml`.

## Acceptance Criteria

- Command creates all required files in a temp test repo.
- Archive file and `LATEST.md` are consistent.
- `RESUME_PROMPT.txt` is generated.
- `INDEX.yaml.first_next_action` mirrors `next_todo_items[0]`.
- Re-running the command creates a new archive and updates latest pointers.
- Tests do not touch the real user home.

## Non-Goals

- Do not build AI summarization.
- Do not implement global installers.
- Do not add clipboard support.
- Do not add daemon, watcher, database, MCP, or UI.
