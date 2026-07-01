# Ticket 7: Codex skill wrapper

## Route

lead-po direct first, with optional review.

## Summary

Create a Codex skill wrapper that makes Session Glue easy to trigger from Codex sessions.

## Scope

- Add a local Codex skill definition after the CLI exists.
- Trigger on Session Glue language and slash-command equivalents.
- Prefer calling the installed CLI.
- Fall back to direct file-writing rules only when the CLI is unavailable.

## Required Behavior

The skill should support:

- `/glue`
- `/freeze`
- `/handoff`
- `/checkpoint`
- "세션 붙여줘"
- "세션 얼려줘"
- "create a Session Glue handoff"

After generating a handoff, the agent should print the exact resume prompt in a fenced code block. This is the intended copyable UX. Do not request OS clipboard access.

## Acceptance Criteria

- Skill instructions are small and clear.
- Skill references the CLI command path when installed.
- Skill fallback preserves the same schema and file layout.
- Manual local Codex test can trigger the workflow.

## Non-Goals

- Do not publish a plugin in this ticket.
- Do not implement a UI.
- Do not add MCP dependency.
