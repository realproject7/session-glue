# Session Glue QuadWork Batch 3

Dispatch target: VPS QuadWork project `session-glue`, repo `realproject7/session-glue`.

## Active Batch

- #6 `glue status` and `glue resume-prompt`
- #7 Global installer dry-run blocks

## Operator Instruction

`@head` should pick up this batch on VPS QuadWork only. Assign implementation to `@dev`. Require both `@re1` and `@re2` review before merge. Each PR must reference its GitHub issue with `Fixes #N`.

Repository is public. All PR bodies, reviews, comments, docs, and fixtures must follow `CONTRIBUTING.md` and `.github/pull_request_template.md`.

## Batch Goal

Complete the remaining operator-safe CLI workflows before local PO dogfood:

1. read-only status and resume-prompt commands
2. dry-run-only global installer instruction blocks

## Ticket #6: `glue status` And `glue resume-prompt`

GitHub issue: https://github.com/realproject7/session-glue/issues/6

Implement compact read-only commands:

- `glue status`
- `glue resume-prompt`

Acceptance:

- `glue status` works in a temp repo with valid artifacts
- `glue status` handles missing `.agent-history/` gracefully
- `glue resume-prompt` prints exactly `.agent-history/RESUME_PROMPT.txt`
- commands are read-only
- tests cover present and missing artifact cases

Token-economics constraint:

- `glue status` must not print the full handoff narrative by default
- status output should use compact index/resume metadata where possible

## Ticket #7: Global Installer Dry-Run Blocks

GitHub issue: https://github.com/realproject7/session-glue/issues/7

Implement dry-run support only:

- `glue install codex --dry-run`
- `glue install claude --dry-run`
- `glue install cursor --dry-run`
- `glue install gemini --dry-run`
- optional `glue install all --dry-run`

Hard boundary:

- Do not implement real user-home mutation in this batch.
- Do not write to real `~/.codex`, `~/.claude`, Cursor, Gemini, or any user config path.
- If non-dry-run behavior is scaffolded, it must fail closed with a clear operator-gate message.
- All tests must use fixture paths or temp directories.

Managed block requirements:

- stable begin/end markers
- explain `/glue`, `/freeze`, `/handoff`, `/checkpoint`, and natural-language glue/freeze/checkpoint requests
- write repo-local `.agent-history/`
- print `RESUME_PROMPT.txt` content in a fenced code block
- no OS clipboard access
- no daemon
- no external service

Acceptance:

- dry-run commands print target path and proposed block
- dry-run commands do not modify user home files
- managed block markers are stable and test-covered
- installer logic detects an existing block in fixture files
- public examples use placeholders, not personal local paths

## Required QuadWork Flow

- `@head` assigns work to `@dev`.
- `@dev` opens PRs against current `main`.
- `@re1` and `@re2` both review every PR.
- `@head` merges only after both reviewers are satisfied.
- Keep scope limited to #6 and #7.
- Stop before operator gates: no PyPI publish, no credentials, no real non-dry-run installer behavior.

## Public Hygiene

Before posting public content, check for:

- credentials, tokens, cookies, passwords, private keys, or `.env` contents
- private data or proprietary logs
- personal local paths
- screenshots or transcripts with sensitive information

Use placeholders such as `/path/to/project`, `<TOKEN>`, and `<REDACTED>`.
