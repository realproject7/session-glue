# Ticket 8: Dogfood and cross-agent validation

## Route

lead-po direct with optional sub-po review.

## Summary

Validate that Session Glue works across real Codex and Claude sessions without relying on the previous chat context.

## Scope

- Create a medium-length real handoff with the CLI.
- Resume in a fresh Codex session using only `RESUME_PROMPT.txt`.
- Resume in a fresh Claude Code session using only `RESUME_PROMPT.txt`.
- Record findings in docs.
- Fix proposal or tickets if the dogfood exposes protocol issues.

## Validation Questions

- Did the new agent read the handoff first?
- Did it avoid reading large reference docs unless explicitly instructed?
- Did it identify the next productive action?
- Did `next_todo_items[0]` avoid resume mechanics?
- Did `INDEX.yaml.first_next_action` mirror the handoff?
- Did token usage stay lower than carrying a long chat forward?

## Acceptance Criteria

- Dogfood report committed under `docs/`.
- At least one Codex resume and one Claude resume are tested.
- Failures are converted into issues or proposal updates.
- `glue validate` catches any reproduced schema anti-pattern.

## Non-Goals

- Do not claim universal agent support from two tests.
- Do not add per-agent prompt files unless a concrete need is proven.
- Do not add clipboard access.
