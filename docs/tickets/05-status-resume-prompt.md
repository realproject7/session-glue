# Ticket 5: `glue status` and `glue resume-prompt`

## Route

VPS QuadWork.

## Summary

Add compact read-only commands for checking Session Glue state and printing the canonical resume prompt.

## Scope

- Add `glue status`.
- Add `glue resume-prompt`.
- Read `.agent-history/INDEX.yaml` and `.agent-history/RESUME_PROMPT.txt`.
- Keep output compact by default.

## Behavior

`glue status` should show:

- whether `.agent-history/` exists
- latest session id
- latest file
- current branch from index
- head commit from index
- first next action
- validation summary if cheap

`glue resume-prompt` should print the exact contents of `.agent-history/RESUME_PROMPT.txt`.

## Token-Economics Requirement

Do not make `glue status` read and print the full narrative by default. It should orient the operator without recreating context bloat.

## Acceptance Criteria

- `glue status` works in a temp repo with valid artifacts.
- `glue status` handles missing `.agent-history/` gracefully.
- `glue resume-prompt` prints exactly the prompt file content.
- Commands are read-only.
- Tests cover present and missing artifact cases.

## Non-Goals

- Do not implement search over old handoffs here.
- Do not add clipboard access.
- Do not add global installers.
- Do not add watcher, daemon, MCP, database, or UI.
