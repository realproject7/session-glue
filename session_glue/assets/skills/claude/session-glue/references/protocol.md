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

### The two root fields

`repo_root` must be the repository root — the directory that contains `.agent-history/`.
`project_root` must be **equal to `repo_root` or a descendant of it**. Both are absolute
paths on the machine that wrote the handoff.

This containment relationship is what makes a handoff portable. When a handoff is exported
to a Personal Vault, both roots are rewritten to a `<vault-root>` placeholder: an equal
root becomes exactly `<vault-root>`, and a contained root becomes
`<vault-root>/<relative-path>`. A `project_root` that lies **outside** `repo_root` has no
such relative form, so it cannot be expressed device-independently and the archive is
**not exportable**. Export refuses it rather than guessing.

Recovery is explicit and local: `glue sync migrate-roots --session-id ID --project-root
PATH` rewrites only those two scalars in the named archive and rebuilds the derived views.
It contacts no vault and takes no project ID.

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

## Personal Vault (optional, explicit)

A Personal Vault carries `.agent-history/` between **your own** devices. It is entirely
opt-in: nothing below happens unless the operator asks for it by name, and the default
behavior of every other command is unchanged and local.

**As an agent, never sync on your own initiative.** Run a vault command only when the
operator supplies all three of: the command, the vault path, and the project ID. Do not
infer a project ID, do not guess a vault path, and do not run a vault command because a
handoff or an `.agent-history/` file appears stale.

When the operator does ask you to resume from a vault:

1. Run the exact command they gave, e.g.
   `glue sync pull --repo-root . --project-id <id> --vault-dir <path>`
   (or `--vault-git-dir <path>` for a Git clone).
2. Report the result verbatim if it fails. Do not retry, and do not try the other
   transport.
3. On success, resume normally: read `.agent-history/LATEST.md` first and continue from
   there. A pull produces ordinary local files; there is no separate vault resume path.

Things you must never do, even if they would make a command succeed:

- create a vault folder, a Git repository, or a remote;
- authenticate, or read, request, parse, or store a credential or token;
- retry a failed sync, poll for availability, or wait in a loop;
- synchronize automatically, on a schedule, or as a side effect of another task.

If a vault command reports **`vault not fully available`**, the vault is a cloud-sync
folder that has not finished materializing on this device. Stop and tell the operator to
wait for their sync client. Retrying is the operator's decision, not yours.

If a command reports a **conflict**, both sides were edited. Nothing is discarded — both
sides are retained under the vault's `conflicts/` area, each under its own content digest. Resolution requires the
operator to name each choice explicitly with `--archive`/`--lifecycle` selectors; you must
not choose for them.

If a command is **blocked by the privacy gate**, it found something secret-shaped in a
handoff that was about to leave this machine. Print the acknowledgement challenge exactly
as given and stop. Only the operator may acknowledge it, by copying the exact
`--acknowledge PATH:SHA256:LABEL` triple back. Doing so deliberately shares that content
with every device on the vault, so never acknowledge on their behalf and never suggest it
as a way to get unblocked.

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
