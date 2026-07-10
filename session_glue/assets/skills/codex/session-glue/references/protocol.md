# Session Glue Fallback Protocol

Use this only when the `glue` CLI is unavailable. The CLI is canonical.

## File Layout

Write all files under the current repository root:

```text
.agent-history/
  LATEST.md
  RESUME_PROMPT.txt
  INDEX.yaml
  DECISIONS.md
  sessions/
    <session_id>.md
```

Never write outside `.agent-history/`. Refuse to follow symlinks that would
redirect these writes outside the repository.

`DECISIONS.md` is an append-only log of durable decisions. Add an optional `decisions:`
list to the frontmatter (scalars — decisions made this session); `glue create` appends
one line per entry and never rewrites existing lines. On resume, after reading
`LATEST.md`, also read `DECISIONS.md` if present — one line per decision, cheap to scan.

`supersedes` is an optional frontmatter scalar naming the prior `session_id` this handoff
replaces; when a handoff continues or replaces an earlier session, record it (when present
it must be a non-empty scalar). It is mirrored into each `INDEX.yaml` session entry (empty
string when absent), and `glue status` prints one single-hop `lineage:` line for the latest
session when it is set.

`glue close [--repo-root PATH] [--session ID] --status DONE|BLOCKED|ABANDONED` sets a
session's lifecycle status in `INDEX.yaml` only (default: the latest session); archived
`sessions/*.md` files and `LATEST.md` stay immutable. Closing the latest session as `DONE`
clears the top-level `first_next_action`; `BLOCKED` and `ABANDONED` leave it unchanged. An
unknown session id exits non-zero.

## Handoff Markdown

`LATEST.md` and `sessions/<session_id>.md` must contain the same markdown
document. Start with YAML frontmatter using these required fields:

```yaml
session_id: 2026-07-01-1200-short-slug
session_date: 2026-07-01
generated_at: 2026-07-01T12:00:00Z
schema_version: 1
project_root: /path/to/project
repo_root: /path/to/project
current_branch: main
head_commit: abc1234
agent: codex
status: IN_PROGRESS
primary_goal: One-line statement of the session's overall objective.
active_context_files:
  - path: path/to/file.py
    reason: Why this file matters to the next agent.
completed_tasks:
  - Concrete completed work item.
next_todo_items:
  - First productive action after the next agent reads the handoff.
known_issues:
  - Known blocker or risk.
search_tags:
  - topic-tag
  - subsystem-name
validation:
  - command: pytest -q
    result: passed
    notes: Full suite green.
  - command: ruff check .
    result: not_run
    notes: Deferred to the next session.
```

Values must be single-line. A `#` inside a value is literal content — issue references like `#207` are safe unquoted; inline `#` comments after values are NOT supported. Only whole-line comments (a line whose first non-space character is `#`) are treated as comments.

Canonicalization: `glue create` re-serializes this frontmatter when it archives the
handoff. Comments are dropped, quoting is normalized, and only single-line values are
supported. Write the frontmatter accordingly — do not rely on comments or multi-line
values surviving the round-trip.

Required quality fields:

- `primary_goal` — a single-line statement of the session's overall objective.
- `active_context_files` — each entry is preferably a `path:`/`reason:` mapping; the
  `reason` tells the next agent why the file matters, so it need not re-read the whole
  file. A bare path scalar is still accepted for backward compatibility.
- `search_tags` — one or more short topical tags (at least one) so a later session can
  find this handoff from `INDEX.yaml` alone.
- `validation` — one or more mappings recording how the work was checked; each entry
  requires `command:` and `result:`. `notes:` is optional commentary. `result` must be
  one of `passed`, `failed`, or `not_run`; use `not_run` to record a defined-but-skipped
  check rather than omitting it.

The first entry, next_todo_items[0], must be productive work, not resume mechanics. Do not use
phrases such as "paste the prompt", "start a new session", "read LATEST.md",
"inspect the handoff", or "verify the new agent reads the handoff".

Below the frontmatter, include these sections:

- `# Resume Prompt`
- `# What We Did`
- `# Current State`
- `# Decisions Made`
- `# Failed Attempts / Dead Ends`
- `# Next-Agent Instructions`
- `# Commands And Validation`
- `# Risks And Constraints`

All eight headings are REQUIRED and validation enforces them: `glue create` and
`glue validate` reject a handoff whose body is missing any of them, matched at
line start with the exact `# ` heading text. Validation checks heading presence
only — it never inspects or scores the prose beneath them.

## RESUME_PROMPT.txt

Write a short paste-ready prompt:

```text
Continue the previous coding session.

Project root: /path/to/project
First, read: .agent-history/LATEST.md
Prompt artifact: .agent-history/RESUME_PROMPT.txt
Then follow the Resume Prompt and continue from the first next_todo_items entry.

First productive next action (next_todo_items[0]):
<next_todo_items[0]>

Before editing, run git status --short and report any drift from the handoff.
Do not scan the whole repository unless the handoff is stale or insufficient.
```

After writing the files, print the exact prompt in a fenced code block.

## Dogfood Harness Guidance

When testing Session Glue with a fresh agent, keep two roles separate:

- The outer observer starts fresh-agent trials and records behavior.
- The trial subject only resumes from the handoff and reports what it did.

Do not make the trial subject's first productive action "run a fresh agent
trial" or "start another agent". That can create a meta-loop where the resumed
agent launches another resumed agent instead of being the test subject.

## INDEX.yaml

Write compact metadata only. Do not duplicate the narrative:

```yaml
schema_version: 1
latest_session: 2026-07-01-1200-short-slug
latest_file: sessions/2026-07-01-1200-short-slug.md
repo_root: /path/to/project
current_branch: main
head_commit: abc1234
primary_goal: One-line statement of the session's overall objective.
search_tags: topic-tag, subsystem-name
first_next_action: First productive action after the next agent reads the handoff.
sessions:
  - session_id: 2026-07-01-1200-short-slug
    file: sessions/2026-07-01-1200-short-slug.md
    session_date: 2026-07-01
    generated_at: 2026-07-01T12:00:00Z
    agent: codex
    project_root: /path/to/project
    repo_root: /path/to/project
    current_branch: main
    head_commit: abc1234
    status: IN_PROGRESS
    primary_goal: One-line statement of the session's overall objective.
    search_tags: topic-tag, subsystem-name
    supersedes: ""
    first_next_action: First productive action after the next agent reads the handoff.
```
