# PROPOSAL: Session Glue

> **Date:** 2026-06-30  
> **Status:** Draft  
> **Type:** Product proposal + lightweight agent-memory protocol  
> **One-line summary:** A zero-daemon, repo-local session-continuity protocol that cuts a bloated coding-agent session and glues it onto a clean new session.

---

## 1. Executive Summary

Session Glue is a lightweight memory protocol for long AI coding sessions.

The metaphor is deliberately simple:

> cut the current session at a clean boundary, then glue the useful context onto the next session.

The product does not try to become a universal memory system, RAG layer, MCP server, graph database, or agent OS. Its only job is to solve one recurring problem:

> Long agent sessions become expensive, slow, and forgetful; the operator needs a simple way to freeze the useful context, restart the session, and continue without losing the work state.

The proposed solution is intentionally small:

- the user runs a command such as `/glue`, `/freeze`, or "glue this session"
- the active agent writes a compact handoff document into the repository
- the handoff document includes structured YAML frontmatter, a narrative summary, active files, decisions, failed attempts, validation status, and a copy-paste resume prompt
- an index file makes prior handoffs searchable with `rg`, file names, tags, and basic YAML parsing
- the previous agent prints and stores a copy-paste resume prompt so the operator can start a fresh session without composing any instruction manually

This gives the operator most of the practical value of agent memory without installing infrastructure.

The first version should be a protocol plus a lightweight Python CLI and a Codex skill, with portable rule blocks for Claude Code, Cursor, Gemini CLI, and any other file-writing coding agent.

---

## 2. Product Thesis

Most agent-memory products optimize for continuous long-term memory.

Session Glue should optimize for a narrower workflow:

> Preserve the working set of one coding session at the moment the operator wants to reset context.

This distinction matters. A coding handoff does not need to remember everything about the user forever. It needs to tell the next agent:

- what the current goal is
- what changed
- which files matter
- what has already been tried
- what is still broken
- which commands were run
- what the next action should be

The product should feel closer to a disciplined engineering handoff than an autonomous memory layer.

### 2.1 Core Hook

Strong product sentence:

> Reset the chat, not the work.

Alternative:

> A one-command handoff file for overloaded coding-agent sessions.

More precise:

> Session Glue turns a bloated agent session into a small, indexed markdown briefing that the next clean session can resume from.

---

## 3. Problem

Terminal and IDE-based agents are increasingly used for multi-hour software work. The workflow is powerful but has predictable failure modes:

1. **Context bloat**
   - old messages, logs, diffs, searches, and dead paths remain in context
   - future turns spend more tokens re-reading irrelevant history

2. **Rising cost and latency**
   - every new turn carries more context
   - the operator pays for material that no longer matters

3. **Memory drift**
   - the agent starts forgetting earlier constraints or inventing stale conclusions
   - repeated corrections become necessary

4. **Bad restarts**
   - clearing the session loses useful work state
   - the next session often wastes time scanning the repo again

5. **Heavy existing solutions**
   - many memory projects introduce MCP servers, daemons, databases, embeddings, graphs, ontologies, or custom SDKs
   - these may be valuable for full memory systems, but they are overkill for a simple session reset

The missing product is a small manual tool that lets the operator say:

> Summarize exactly where we are, write it to disk, and tell the next agent how to continue.

---

## 4. Benchmark Findings

The closest existing products are not the large memory frameworks. They are handoff-oriented skills and markdown protocols.

### 4.1 Closest Product Candidates

| Project | What To Benchmark | Gap vs Session Glue |
|---|---|---|
| `thepushkarp/handoff` | Command UX such as `/handoff:create` and `/handoff:resume`; explicit resume flow; single handoff document; optional lifecycle hooks | Claude Code oriented; less focused on portable repo-local indexing across agents |
| `taige221/session-handoff-skill` | No-runtime skill philosophy; concise handoff artifact; next-session starter prompt | Mostly a handoff-writing skill; file persistence and indexing are not the central product |
| `REMvisual/claude-handoff` | Evidence-first session mining; decisions, failed attempts, blockers, command results, and chain tracking | More sophisticated and Claude-specific; heavier than the desired MVP |
| `daystar7777/agent-work-mem` | Markdown-first shared working memory; `INDEX` concept; archives; agent-readable protocol | Broader continuous work-memory system; more day-to-day operating model than a one-command freeze |

### 4.2 Larger Memory Systems

| Project | Useful Idea | Why Not Copy The Architecture |
|---|---|---|
| `akitaonrails/ai-memory` | Rewrite noisy session history into a coherent narrative; prepend prior context into a new session | Lifecycle automation and shared wiki behavior can become heavier than the manual-first use case |
| `agentscope-ai/ReMe` | "Memory as file" direction; markdown/frontmatter/index mindset | Retrieval, watcher, and consolidation features are beyond the first wedge |
| `matrixorigin/Memoria` | Snapshot, branch, rollback, and merge metaphors for memory | Git-like memory operations are promising later, but not needed for the first product |
| Mem0, Letta, Zep, Basic Memory | Durable agent memory, temporal knowledge, graph/retrieval concepts | These solve broader memory architecture problems; Session Glue should avoid becoming a platform in v1 |

### 4.3 Borrowed Logic

Session Glue should borrow the following patterns:

1. **From handoff command tools**
   - provide explicit `freeze`, `resume`, and `status` modes
   - include a copy-paste prompt for the next session

2. **From no-runtime handoff skills**
   - allow the entire workflow to work with only agent instructions and file writes
   - do not require a daemon, MCP server, database, or background process

3. **From evidence-first handoff generators**
   - record decisions, failed attempts, blockers, validation results, and changed files
   - prevent the next agent from repeating bad paths

4. **From markdown memory protocols**
   - store memory in human-readable files
   - keep a lightweight index for search
   - make the repo itself the storage boundary

5. **From larger memory systems**
   - treat snapshots and supersession as future upgrades
   - keep the MVP small enough that users actually adopt it

---

## 5. Product Positioning

Session Glue should be positioned as:

> Manual-first session memory for coding agents.

It should not be positioned as:

- general AI memory
- universal personal memory
- RAG infrastructure
- agent operating system
- knowledge graph
- autonomous recall layer

The strongest wedge is the operator who works with Claude Code, Codex, Cursor, Gemini CLI, or similar coding agents and often reaches the point where the chat needs to be reset before the task is finished.

---

## 6. Goals

Session Glue should:

- let an agent freeze a long session into a small local file set
- make a new session easy to resume with minimal repo scanning
- preserve useful work state without preserving noisy conversation history
- support Codex first, but remain agent-agnostic
- use plain markdown and YAML
- be searchable with `rg`, filenames, and tags
- avoid external services and hidden state
- be safe to commit or ignore depending on project policy
- degrade gracefully when git is unavailable

### 6.1 Token Economics

Session Glue saves context tokens when it replaces a long, noisy chat history with a compact handoff.

It can increase token usage if used too frequently, because each resume requires the next agent to read the handoff, check drift, inspect active files, and re-orient before doing productive work.

Recommended use:

- after meaningful multi-step work
- before clearing or compacting a long session
- before handing work to another agent
- before switching models or agent tools

Avoid using it:

- every few turns
- as a full transcript archive
- when the next action is obvious and the session is still small
- when no meaningful project state has changed

---

## 7. Non-Goals

V1 should not include:

- MCP server
- vector database
- embeddings
- ontology
- background daemon
- file watcher
- cloud sync
- automatic full transcript ingestion
- browser extension
- semantic search
- multi-user collaboration
- autonomous memory mutation during every turn
- custom IDE UI

These can be explored later only if the manual protocol proves useful.

---

## 8. Core Workflow

### 8.1 Glue

The operator says:

```text
/glue
```

Natural language aliases such as "glue this session", "freeze this session", or "write the Session Glue handoff" should also work.

The agent immediately switches from implementation mode to Session Glue handoff mode.

The agent:

1. inspects the current goal and conversation state
2. checks lightweight repo state when available:
   - current directory
   - git branch
   - HEAD commit
   - changed files
   - recent commands/tests mentioned in the session
3. writes a session handoff file
4. updates `.agent-history/LATEST.md`
5. updates `.agent-history/INDEX.yaml`
6. writes `.agent-history/RESUME_PROMPT.txt`
7. prints the resume prompt in a copyable fenced code block

### 8.2 Reset

The operator clears, compacts, or restarts the agent session.

No background process is required.

### 8.3 Resume

The operator should not have to remember or write the resume instruction.

At the end of the freeze flow, the previous agent must generate a ready-to-copy prompt in two places:

- print it in the final assistant message inside a fenced code block
- write it to `.agent-history/RESUME_PROMPT.txt`

The operator starts a new session by pasting the generated prompt:

```text
Continue the previous coding session.

Project root: /path/to/example-app
First, read: .agent-history/LATEST.md
Then follow the Resume Prompt and continue from the first next_todo_items entry.

Before editing, run git status --short and report any drift from the handoff.
Do not scan the whole repository unless the handoff is stale or insufficient.
```

The generated prompt should include the absolute project path when available, the latest session ID, and the first next action.

The new agent reads the handoff first, inspects only the listed active files unless needed, and continues from the next action.

### 8.4 Search Old Handoffs

When a previous handoff may matter:

```bash
rg "polling|chart|empty-state" .agent-history
```

or:

```bash
rg "search_tags:|primary_goal:|known_issues:" .agent-history
```

The system should work even without a dedicated search command.

---

## 9. Proposed File Structure

```text
.agent-history/
├── LATEST.md
├── RESUME_PROMPT.txt
├── INDEX.yaml
├── sessions/
│   ├── 2026-06-30-1530-chart-polling.md
│   └── 2026-06-30-1715-database-migration-review.md
└── templates/
    └── handoff-template.md            # optional
```

### 9.1 `LATEST.md`

The current resume target.

This should either be:

- a copy of the latest session file, or
- a small file that links to the latest session file

For v1, prefer copying the latest session content into `LATEST.md`. It is simplest for agents and humans.

### 9.2 `sessions/*.md`

Immutable archived handoff files.

Each file should use a stable name:

```text
YYYY-MM-DD-HHMM-short-slug.md
```

The slug should come from the task, not the project name alone.

### 9.3 `INDEX.yaml`

A lightweight index optimized for humans, agents, and scripts.

It should contain only compact metadata, not the full narrative.

### 9.4 `RESUME_PROMPT.txt`

A plain text prompt that the operator can paste directly into a new agent session.

This file should be overwritten on every freeze. It should be short enough to paste comfortably, but explicit enough that the new agent can connect to the correct project and handoff file.

Example:

```text
Continue the previous coding session.

Project root: /path/to/example-app
First, read: .agent-history/LATEST.md
Then follow the Resume Prompt and continue from the first next_todo_items entry.

Before editing, run git status --short and report any drift from the handoff.
Do not scan the whole repository unless the handoff is stale or insufficient.
```

---

## 10. Handoff File Format

Each handoff file should use YAML frontmatter followed by a structured narrative.

```markdown
---
memory_schema_version: 1
session_id: 2026-06-30-1530-chart-polling
created_at: 2026-06-30T15:30:00+09:00
agent: codex
project: example-app
repo_root: /path/to/example-app
branch: main
head_commit: abc1234
status: in_progress
primary_goal: "Add real-time polling to the chart view"
active_context_files:
  - path: src/components/ChartView.tsx
    reason: "Main implementation target"
  - path: scripts/review-database-migration.sql
    reason: "Open IDE context; may be related to database work"
completed_tasks:
  - "Implemented static chart layout"
next_todo_items:
  - "Add polling lifecycle with cleanup"
  - "Handle empty data without Y-axis scaling bug"
known_issues:
  - "Y-axis scaling breaks when data is empty"
validation:
  - command: "npm test"
    result: "not_run"
    notes: "No test run before freeze"
search_tags:
  - frontend
  - chart
  - polling
---

# Resume Prompt

Read this file first. Complete the resume mechanics, then continue from `next_todo_items[0]`. Start by inspecting only the files in `active_context_files` unless git status shows newer changes.

# Detailed Session Briefing

## What We Did

Summarize meaningful completed work.

## Current State

State what is true now, which files are canonical, whether the repo is dirty, and what the next agent should assume before doing work.

## Decisions Made

Record decisions that the next agent should not reopen without reason.

## Failed Attempts / Dead Ends

Record paths already tried and why they failed.

## Next-Agent Instructions

Give precise instructions for the next session.

## Commands And Validation

List commands run, outputs that matter, and missing validation.

## Risks And Constraints

Mention secrets, production risks, migration risk, uncommitted user changes, or anything that requires care.
```

### 10.1 Required Frontmatter Fields

| Field | Required | Purpose |
|---|---:|---|
| `memory_schema_version` | yes | Allows future format changes |
| `session_id` | yes | Stable file/session identifier |
| `created_at` | yes | Timestamp with timezone |
| `agent` | yes | Agent that wrote the handoff |
| `project` | yes | Project name or repo folder |
| `repo_root` | yes | Absolute path when known |
| `branch` | no | Git branch when available |
| `head_commit` | no | Git HEAD when available |
| `status` | yes | `complete`, `in_progress`, `blocked`, `needs_review`, or `unknown` |
| `primary_goal` | yes | Current work objective |
| `active_context_files` | yes | Files the next agent should inspect first |
| `completed_tasks` | yes | Done work |
| `next_todo_items` | yes | Ordered productive next actions after resume; `next_todo_items[0]` must be the first real work item, not a resume mechanic |
| `known_issues` | yes | Bugs, blockers, uncertainty |
| `validation` | yes | Commands run or explicitly not run |
| `search_tags` | yes | Short tags for `rg` and index filtering |

### 10.2 `next_todo_items` Rule

`next_todo_items[0]` should always be the first productive action after the new agent has read the handoff.

Do not use it for resume mechanics such as:

- "paste the prompt"
- "start a new session"
- "read `LATEST.md`"
- "inspect the handoff"

Those steps belong in `RESUME_PROMPT.txt` and the `# Resume Prompt` section. `next_todo_items` should describe the actual work to do after orientation.

Valid example:

```yaml
next_todo_items:
  - "Reconcile the manual resume experiment note with the latest validation results."
  - "Update INDEX.yaml schema examples to match emitted artifacts."
```

Invalid example:

```yaml
next_todo_items:
  - "Start a new session and paste RESUME_PROMPT.txt."
  - "Read LATEST.md."
```

The CLI should include a simple heuristic lint for obvious resume mechanics. In v1, reject or warn when `next_todo_items[0]` contains case-insensitive phrases such as:

```text
paste
start a new session
new session
read latest
resume prompt
inspect the handoff
```

This lint is only a guardrail for obvious mistakes. It is not a semantic judge of whether a task is genuinely productive; the writing agent remains responsible for the handoff quality.

---

## 11. Index Format

`INDEX.yaml` should be append-friendly and easy to parse.

```yaml
schema_version: 1
latest: 2026-06-30-1530-chart-polling
sessions:
  - session_id: 2026-06-30-1530-chart-polling
    file: sessions/2026-06-30-1530-chart-polling.md
    created_at: 2026-06-30T15:30:00+09:00
    agent: codex
    project: example-app
    repo_root: /path/to/example-app
    branch: main
    head_commit: abc1234
    status: in_progress
    primary_goal: "Add real-time polling to the chart view"
    first_next_action: "Add polling lifecycle with cleanup"
    active_context_files:
      - src/components/ChartView.tsx
    search_tags:
      - frontend
      - chart
      - polling
```

The index should never become the source of truth. It is a lookup surface. The full handoff file remains canonical.

Include compact fields that help `glue status` and search work without reading the full handoff:

- `repo_root`
- `head_commit`
- `first_next_action`

Do not include the full `next_todo_items` list in `INDEX.yaml`. That creates narrative drift and makes the index compete with the handoff file. `first_next_action` should mirror `next_todo_items[0]`.

---

## 12. Agent Behavior Rules

The skill/rules block should instruct agents to do the following.

### 12.1 Glue Mode

When the user asks to glue, freeze, hand off, checkpoint, compact, or prepare a new session:

1. stop the current task
2. do not continue implementing unless the user explicitly asks
3. write or update `.agent-history`
4. prioritize accuracy over completeness
5. mark unknowns as unknown
6. include validation gaps
7. include a clean resume prompt
8. tell the user they can restart the session

### 12.2 Resume Mode

When the user asks to resume from `.agent-history/LATEST.md`:

1. read `LATEST.md`
2. inspect `INDEX.yaml` only if older handoffs might matter or a cheap status summary is needed
3. inspect the active context files lazily, starting only with files needed for the first productive action
4. run `git status --short` before editing
5. continue from `next_todo_items[0]`, which must be the first productive work item after resume mechanics are complete
6. avoid broad repo scanning unless the handoff is stale or insufficient
7. treat large docs, proposal files, archived sessions, and design documents as opt-in references, not part of the default resume budget

### 12.3 Staleness Handling

If the handoff is stale:

- compare `head_commit` with current `git rev-parse HEAD`
- compare active files with current `git status`
- mention drift before continuing
- update the next handoff with the drift found

---

## 13. Lightweight CLI

V1 should include a lightweight CLI.

The protocol should still be understandable without the CLI, but the CLI should become the default implementation path because it removes repetitive file/index mechanics from the agent.

Recommended package and command:

```text
Product name: Session Glue
PyPI package: session-glue
Primary command: glue
Fallback command: session-glue
```

PyPI spot checks on 2026-06-30 showed `session-glue` and `sessionglue` were not found, while `glue`, `handoff`, and `handoff-agent` already exist. This makes `session-glue` the best package-name candidate. The package should expose a simple `glue` console command, with `session-glue` as a fallback executable if `glue` conflicts with an existing command on a user's machine.

Responsibilities:

- create `.agent-history`
- generate `session_id`
- read git branch and HEAD
- list changed files
- create a draft markdown file from stdin or template
- copy latest content to `LATEST.md`
- write a copy-paste prompt to `RESUME_PROMPT.txt`
- update `INDEX.yaml`
- validate required frontmatter fields
- reject or warn on obvious `next_todo_items[0]` resume mechanics
- assert `INDEX.yaml` `first_next_action` mirrors `next_todo_items[0]`

The CLI should not summarize the session. The agent must do that because the agent has the conversation context.

### 13.1 CLI Shape

```bash
glue create \
  --agent codex \
  --project example-app \
  --status in_progress \
  --goal "Add real-time polling to the chart view" \
  --input /tmp/handoff-body.md
```

Resume prompt helpers:

```bash
glue resume-prompt
```

Search helpers:

```bash
glue status
glue search "polling chart"
```

For v1, the CLI can also be bundled inside a Codex skill, but the durable distribution target should be PyPI so any agent environment can install the same tool.

### 13.2 CLI Subcommands

| Command | Purpose |
|---|---|
| `glue create` | Create a session file, lint `next_todo_items[0]`, update `LATEST.md`, update `INDEX.yaml`, and write `RESUME_PROMPT.txt` |
| `glue resume-prompt` | Print the current resume prompt for manual copy/paste |
| `glue status` | Show latest session metadata and validation gaps |
| `glue search <query>` | Run a simple local search over `.agent-history` |
| `glue validate` | Validate frontmatter, `next_todo_items[0]` lint, and index consistency |
| `glue install <agent>` | Install or print global Session Glue instructions for a specific agent |
| `glue doctor` | Check CLI availability, current repo state, and likely agent-rule installation status |

### 13.3 Technology Stack

Use Python for the CLI.

Recommended stack:

- Python 3.10+
- `argparse` for commands in v1
- `pathlib`, `datetime`, `subprocess`, `shutil`, and `textwrap` from the standard library
- `tomllib` only if project metadata is read from `pyproject.toml`
- no required runtime dependencies in v1
- `pyproject.toml` with `hatchling` or `setuptools` for packaging
- `console_scripts` entry points for `glue` and fallback `session-glue`
- `pytest` for tests as a development dependency

Avoid Typer, Rich, Textual, SQLite, embeddings, or any daemon dependency in v1. They are useful in larger CLIs, but they weaken the "install and trust immediately" story.

Do not implement OS clipboard access in v1. On macOS and some Linux desktops, clipboard access can trigger permissions, security prompts, or environment-specific failures. The intended "copyable" UX is the standard copy button that many agent UIs show for fenced code blocks, plus a plain `RESUME_PROMPT.txt` file as a durable fallback.

### 13.4 Distribution

The recommended distribution plan:

1. publish the package to PyPI as `session-glue`
2. support installation through:

```bash
pipx install session-glue
uv tool install session-glue
pip install session-glue
```

3. keep the Codex skill as a thin wrapper around the same protocol
4. keep the portable rules block for agents that cannot install the CLI

The PyPI package should contain:

```text
session_glue/
├── __init__.py
├── cli.py
├── git.py
├── index.py
├── prompt.py
├── schema.py
├── install.py
├── doctor.py
└── templates/
    └── handoff.md
```

The CLI should be repo-local by default. It should never require login, cloud sync, or a remote API.

---

## 14. Global Install Model

Session Glue should be globally installable on a machine, while keeping session artifacts local to each repository.

The recommended model has three layers:

```text
1. Global CLI
   pipx install session-glue
   -> makes `glue` available in every project

2. Global agent instructions
   Codex, Claude Code, Cursor, Gemini CLI, etc.
   -> teaches each agent when and how to call Session Glue

3. Project-local artifacts
   .agent-history/
   -> keeps each repo's session state inside that repo
```

This is the best balance between convenience and containment. The user should not need to reinstall Session Glue per project, but session memory should not be mixed into one global bucket like `~/.session-glue/history`.

### 14.1 Agent Install Commands

The CLI should support:

```bash
glue install codex
glue install claude
glue install cursor
glue install gemini
glue install all
glue doctor
```

Expected behavior:

| Command | Behavior |
|---|---|
| `glue install codex` | Append or update a Session Glue block in the user's global Codex instructions, for example `~/.codex/AGENTS.md` when that is the active global file |
| `glue install claude` | Install or print a Claude Code global command/rules block, such as `~/.claude/commands/glue.md` or the relevant global memory file |
| `glue install cursor` | Print a Cursor User Rules block and, only when safe, offer a file-based install path for environments that expose one |
| `glue install gemini` | Install or print a Gemini CLI global instruction block |
| `glue install all` | Run all supported installers in conservative mode |
| `glue doctor` | Check whether `glue` is on PATH, whether the current repo has `.agent-history`, and whether likely global agent instructions exist |

Installers should be conservative:

- never overwrite an existing global instruction file
- append a managed block with clear begin/end markers
- do nothing if the block already exists
- print the block when automatic installation is unsafe
- keep project-specific memory in `.agent-history/`, not in global config

### 14.2 Managed Instruction Block

The global instruction block should be short and portable:

```markdown
<!-- SESSION_GLUE:BEGIN -->
## Session Glue Session Continuity

When the user asks to glue, freeze, checkpoint, compact, hand off, or prepare a new session, write a repo-local handoff under `.agent-history/` using the Session Glue protocol.

Prefer the `glue` CLI when available. If it is not available, write the files directly:
- `.agent-history/LATEST.md`
- `.agent-history/RESUME_PROMPT.txt`
- `.agent-history/sessions/YYYY-MM-DD-HHMM-short-slug.md`
- `.agent-history/INDEX.yaml`

After writing the handoff, print the exact contents of `RESUME_PROMPT.txt` in a fenced code block so the operator can paste it into the next session.
<!-- SESSION_GLUE:END -->
```

### 14.3 Opinionated Default

Session Glue should not try to build one global memory store.

Use:

```text
Global install: yes
Global instructions: yes
Global memory storage: no
Project-local .agent-history: yes
```

This keeps the tool available everywhere while preserving the context boundary that matters most: the repository being worked on.

---

## 15. Codex Skill Shape

Recommended skill name:

```text
session-glue
```

Trigger description:

```text
Use when the user asks to glue, freeze, compact, checkpoint, summarize, hand off, or resume a long coding-agent session by writing or reading repo-local .agent-history markdown files.
```

Skill contents:

```text
session-glue/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    └── protocol.md
```

The `SKILL.md` should stay short. It should define:

- freeze triggers
- resume triggers
- required file format
- rules for `LATEST.md`
- rules for `INDEX.yaml`
- validation checklist

The PyPI CLI should handle deterministic file/index mechanics. The Codex skill should call the CLI when it is installed and fall back to direct file writing when it is not.

---

## 16. Portable Rules Block

The protocol should also ship as a copy-paste block for non-Codex agents.

```markdown
## Session Glue Session Protocol

When the user asks to glue, freeze, hand off, checkpoint, compact, or prepare a new session, stop the active task and write a repo-local handoff under `.agent-history/`.

Write:
- `.agent-history/LATEST.md`
- `.agent-history/RESUME_PROMPT.txt`
- `.agent-history/sessions/YYYY-MM-DD-HHMM-short-slug.md`
- `.agent-history/INDEX.yaml`

Each handoff file must include YAML frontmatter with:
`memory_schema_version`, `session_id`, `created_at`, `agent`, `project`, `repo_root`, `branch`, `head_commit`, `status`, `primary_goal`, `active_context_files`, `completed_tasks`, `next_todo_items`, `known_issues`, `validation`, and `search_tags`.

Below the frontmatter, include:
- Resume Prompt
- What We Did
- Current State, including canonical files, repo dirty state, and assumptions for the next agent
- Decisions Made
- Failed Attempts / Dead Ends
- Next-Agent Instructions
- Commands And Validation
- Risks And Constraints

`next_todo_items[0]` must be the first productive work item after resume mechanics are complete. Do not use it for "paste the prompt", "start a new session", or "read LATEST.md".

When resuming, read `.agent-history/LATEST.md` first, inspect active context files before broad repo search, run `git status --short`, and continue from the first productive `next_todo_items` entry.

After freezing, print the exact contents of `.agent-history/RESUME_PROMPT.txt` in a copyable fenced code block so the operator can paste it into the next session without writing a custom instruction.
```

---

## 17. UX Details

### 17.1 Commands

V1 command vocabulary:

| Command | Meaning |
|---|---|
| `/glue` | Primary slash command; write latest handoff and stop |
| `/freeze` | Compatibility alias for users who think in freeze/resume terms |
| `/handoff` | Compatibility alias for users coming from existing handoff tools |
| `/checkpoint` | Compatibility alias for users who think in snapshots |
| `/resume` | Read latest handoff and continue |
| `/glue status` | Summarize current `.agent-history` state |
| `/glue search <query>` | Search old handoffs using `rg` |

The actual implementation does not need slash-command infrastructure. Natural language triggers are enough. Slash-style commands are useful because operators remember them.

For the standalone CLI, prefer:

```bash
glue create
glue resume-prompt
glue status
```

### 17.2 Confirmation Message

After freezing, the agent should print:

```text
Frozen to .agent-history/LATEST.md.
Copy-paste resume prompt written to .agent-history/RESUME_PROMPT.txt.

Paste this into the next session:
```

Then the agent should print a separate fenced block containing the exact generated resume prompt:

```text
Continue the previous coding session.

Project root: /path/to/example-app
First, read: .agent-history/LATEST.md
Then follow the Resume Prompt and continue from the first next_todo_items entry.

Before editing, run git status --short and report any drift from the handoff.
Do not scan the whole repository unless the handoff is stale or insufficient.
```

The agent should also mention if validation was not run.

---

## 18. Safety And Privacy

The handoff files may contain sensitive implementation details.

V1 should default to repo-local files and let the project decide whether to commit them.

Recommended `.gitignore` options:

```gitignore
# Option A: keep handoffs local
.agent-history/
```

or:

```gitignore
# Option B: commit handoffs but ignore local scratch
.agent-history/tmp/
```

The skill should instruct agents:

- do not include secrets from `.env` files
- do not copy raw API keys, tokens, cookies, or private keys
- mention secret-dependent context abstractly
- flag when a handoff may contain sensitive material
- preserve user changes and uncommitted work warnings

---

## 19. MVP Plan

### Phase 1: Protocol

Deliver:

- canonical handoff markdown schema
- `INDEX.yaml` schema
- valid and invalid `next_todo_items[0]` examples
- documented heuristic lint for obvious resume mechanics
- portable rules block
- example handoff file

Success criteria:

- a new agent can resume from `LATEST.md` without reading the old chat
- the operator can find old handoffs with `rg`

### Phase 2: Lightweight CLI

Deliver:

- `session-glue` Python package
- `glue create`
- `glue resume-prompt`
- `glue status`
- `glue validate`
- PyPI-ready `pyproject.toml`
- tests for session ID generation, index updates, prompt writing, and validation
- tests that `glue create` rejects or warns on resume-mechanic `next_todo_items[0]`
- tests that `INDEX.yaml` `first_next_action` mirrors `next_todo_items[0]`

Success criteria:

- an agent can call the CLI to write consistent `.agent-history` files
- the CLI prints the resume prompt without requiring OS clipboard access
- the CLI cannot silently emit the dogfood anti-pattern where `next_todo_items[0]` is "start a new session"
- the same package can be installed with `pipx`, `uv tool`, or `pip`

### Phase 3: Global Agent Installers

Deliver:

- `glue install codex`
- `glue install claude`
- `glue install cursor`
- `glue install gemini`
- `glue doctor`

Success criteria:

- one global CLI installation can make Session Glue usable across projects
- each agent receives a short global instruction block or a copyable block when automatic installation is unsafe
- `.agent-history/` remains project-local

### Phase 4: Codex Skill

Deliver:

- `session-glue` skill under `$CODEX_HOME/skills`
- fallback direct-write workflow when the CLI is not installed
- validation checklist

Success criteria:

- user can say `/glue` or "freeze this session"
- Codex writes valid `.agent-history` files
- Codex prints a copy-paste prompt that the user can paste into the next session

### Phase 5: Multi-Agent Portability

Deliver:

- Claude Code rule block
- Cursor rule block
- Gemini CLI rule block
- minimal examples for each environment

Success criteria:

- the same `.agent-history` files can be consumed by at least two different coding agents

### Phase 6: Optional Enhancements

Only after repeated usage:

- `glue search` helper
- stale-handling checks
- session supersession fields
- linked handoff chains
- project-level handoff dashboard
- git snapshot integration
- pre-compact hooks for agents that support them

### 19.1 Manual Resume Experiments

On 2026-06-30, Session Glue was tested manually using generated `.agent-history/LATEST.md` and `RESUME_PROMPT.txt` files.

Fresh Codex and Claude sessions were able to:

- read the handoff first
- reconstruct the Session Glue product decisions
- inspect the canonical proposal
- identify relevant drift
- determine the next concrete action without access to the previous chat

This validates the core protocol shape, but also surfaced important dogfood issues:

- `next_todo_items[0]` must describe the next productive action after resume, not the act of starting the resume session itself.
- Large reference documents such as the full proposal should be opt-in during ordinary resume flows; they were appropriate in this experiment only because the task was proposal review.
- Per-agent prompt files such as `RESUME_PROMPT_CLAUDE.txt` add artifact drift and should stay out of v1 unless a concrete need appears.
- `INDEX.yaml` should expose `first_next_action`, not the full `next_todo_items` list.

---

## 20. Build Execution Plan

Session Glue should be built with the normal PO workflow:

1. finalize proposal
2. create repo and EPIC
3. create sub-tickets with acceptance criteria
4. review the tickets before implementation
5. route pure implementation work through QuadWork where it fits
6. keep local/direct PO work for environment-specific installs, final dogfood, and release gates

Do not start by hand-coding the CLI from this proposal. The next real step is founding: create the repository, EPIC, labels, and scoped tickets.

Planning note: this execution plan was reviewed through an Agent Gather PO room with `lead-po` and `sub-po`. The review reinforced three constraints for the build plan:

- keep v1 super simple: no daemon, MCP dependency, embeddings, database, watcher, or UI
- use QuadWork only for headless, fixture-testable implementation work
- keep local PO ownership over global installs, Codex/Claude dogfood, and release gates

### 20.1 Routing Decision

Default routing:

| Workstream | Route | Reason |
|---|---|---|
| Repo scaffold, README, license, issue labels, EPIC | lead-po direct | Founding work is small, cross-project, and establishes the source of truth |
| Pure Python CLI implementation | VPS QuadWork | Headless, fixture-testable, no browser/native dependency |
| CLI unit tests and fixture tests | VPS QuadWork | Deterministic Python tests are a good QuadWork fit |
| Global installer dry-run logic | VPS QuadWork for implementation, lead-po local verification | Code is headless, but actual `~/.codex` / `~/.claude` modification must be verified locally |
| Codex skill packaging | lead-po direct first, then optional review | It touches local Codex skill paths and should be verified on this Mac |
| Claude/Cursor/Gemini rule text | lead-po direct with sub-po review | More policy/protocol than code; preserve wording quality |
| PyPI publish | operator gate | Requires account/token/release decision |
| Dogfood across Codex/Claude | lead-po direct, optionally AG/sub-po review | Requires local agent sessions and human-observed UX |

Do not use Open Design for v1. Session Glue is a CLI/protocol tool with no product UI in the MVP.

Use Agent Gather/sub-po for planning and review only when it materially improves the protocol. Do not keep an AG room open as a default work loop.

### 20.2 Founding Tickets

Create one EPIC and these initial tickets.

| Ticket | Title | Route | Acceptance Criteria |
|---|---|---|---|
| EPIC | Session Glue MVP | lead-po direct | Links all sub-tickets; states product boundary, v1 scope, non-goals, routing, release gate |
| 1 | Package scaffold and project metadata | VPS QuadWork | `pyproject.toml`, package module `session_glue`, console scripts `glue` and `session-glue`, README skeleton, tests run locally |
| 2 | Handoff schema and fixture library | VPS QuadWork | Fixture handoffs cover valid/invalid frontmatter, `next_todo_items[0]` productive rule, `first_next_action`, and `RESUME_PROMPT.txt` generation |
| 3 | `glue create` core file writer | VPS QuadWork | Creates `.agent-history/`, session archive, `LATEST.md`, `RESUME_PROMPT.txt`, `INDEX.yaml`; no network; no OS clipboard |
| 4 | `glue validate` and next-action lint | VPS QuadWork | Fails or warns on denylisted resume mechanics in `next_todo_items[0]`; asserts `INDEX.yaml.first_next_action == next_todo_items[0]` |
| 5 | `glue status` and `glue resume-prompt` | VPS QuadWork | Prints compact status without reading full narrative by default; prints resume prompt exactly |
| 6 | Global installer dry-run blocks | VPS QuadWork plus lead-po local verification | `glue install codex/claude/cursor/gemini --dry-run`; managed begin/end blocks; no overwrite of existing instructions |
| 7 | Codex skill wrapper | lead-po direct | Skill triggers on glue/freeze/checkpoint/handoff; calls CLI when installed; falls back to direct write rules |
| 8 | Dogfood and cross-agent validation | lead-po direct with optional sub-po review | Fresh Codex and Claude sessions resume from generated handoffs; token-heavy paths documented; dogfood artifacts obey schema |
| 9 | Release packaging and PyPI gate | lead-po direct until operator gate | `python -m build` works; install via `pipx`/`uv tool` verified; PyPI publish waits for operator approval/token |

### 20.3 Ticket Review Pass

Before dispatching implementation:

- check every ticket has verified file paths after repo scaffold exists
- check every ticket has explicit scope and non-goals
- check QuadWork tickets are headless and fixture-testable
- check no ticket asks QuadWork to edit local user home files directly
- check no ticket introduces MCP, daemon, embeddings, database, watcher, or UI in v1
- check every acceptance criterion can be verified by tests or a concrete dogfood command

If a ticket is ambiguous, edit the issue body. Do not add scattered clarification comments.

### 20.4 QuadWork Dispatch Plan

Use VPS QuadWork after the EPIC and tickets exist.

Batch 1:

- Ticket 1: package scaffold
- Ticket 2: schema and fixtures

Batch 2:

- Ticket 3: `glue create`
- Ticket 4: `glue validate`

Batch 3:

- Ticket 5: status/resume-prompt
- Ticket 6: installer dry-run blocks

Keep Ticket 7 and Ticket 8 local/direct until the CLI is usable, because they require local Codex/Claude environment checks.

For each QuadWork batch:

- `@head` assigns implementation to `@dev`
- `@dev` opens a PR
- `@re1` and `@re2` both review
- `@head` merges only after both reviews are satisfied
- lead-po performs final local dogfood after merge

### 20.5 Dogfood Gates

Before v1 is considered working:

1. Create a real handoff from a fresh medium-length coding session.
2. Resume it in a new Codex session using only `RESUME_PROMPT.txt`.
3. Resume it in a new Claude Code session using the same canonical prompt.
4. Confirm neither resume path reads large reference docs unless explicitly instructed.
5. Confirm `next_todo_items[0]` is productive.
6. Confirm `INDEX.yaml.first_next_action` mirrors the handoff.
7. Confirm `glue validate` catches the original dogfood anti-pattern.

### 20.6 Operator Gates

The operator must approve:

- final product/repo name before creating or publishing a public repo
- PyPI account/token usage
- global installer behavior that modifies `~/.codex`, `~/.claude`, Cursor rules, or Gemini rules without `--dry-run`
- any decision to commit `.agent-history/` artifacts to a public repository

---

## 21. Implementation Notes

### 21.1 Minimal Python CLI Responsibilities

The CLI should be boring and deterministic:

- no LLM calls
- no network
- no dependency outside Python standard library if possible
- parse frontmatter with simple YAML only if PyYAML is available; otherwise use a constrained writer path
- fail loudly if required fields are missing
- always write `RESUME_PROMPT.txt`
- always print the resume prompt after a successful freeze

### 21.2 Agent Responsibilities

The agent should handle judgment:

- what context matters
- which files are active
- what decisions were made
- which failed attempts matter
- what the next agent should do

This keeps the tool small and avoids pretending that a script can understand the session.

### 21.3 Why Markdown Instead Of JSON

Markdown is preferable because:

- humans can read it
- agents can read it naturally
- YAML frontmatter keeps it structured enough
- diffs are clear
- `rg` works well
- no viewer is needed

JSON can be generated later as a derived artifact if needed.

---

## 22. Risks

### 22.1 Bad Summaries

The biggest risk is not storage. It is inaccurate handoff writing.

Mitigation:

- require validation status
- require failed attempts
- require active files with reasons
- instruct agents to mark uncertainty
- prefer concrete file paths and commands over vague prose

### 22.2 Handoff Bloat

The handoff itself can become too long.

Mitigation:

- enforce a compact resume prompt
- keep detailed notes structured
- avoid raw logs unless essential
- summarize command outputs, do not paste full logs by default

### 22.3 Stale Handoffs

The repo may change after the handoff is written.

Mitigation:

- store branch and HEAD commit
- resume agent checks `git status --short`
- resume agent reports drift before editing

### 22.4 Accidental Secret Capture

The agent may summarize sensitive content.

Mitigation:

- explicit no-secrets rule
- default to abstract descriptions of environment variables
- recommend `.agent-history/` in `.gitignore` for private projects

---

## 23. Product Boundary

Session Glue should stay small until the core loop proves itself.

The correct product boundary is:

> A reliable ritual for ending and restarting a coding-agent session.

The incorrect product boundary is:

> A complete memory system for everything the agent has ever learned.

This boundary is the advantage. Users who reject heavy memory systems may still adopt a one-command handoff file.

---

## 24. Naming Options

`Session Glue` is the recommended product name.

It is stronger than a generic "handoff" name because it describes the operator action in plain language:

> cut the useful tail of the current session and glue it onto a clean new session.

`/handoff` is still understandable, but it is already a crowded word in the agent ecosystem. It is also too generic for PyPI and search.

Recommendation:

- use `Session Glue` as the product name
- use `session-glue` as the PyPI package candidate
- expose `glue` as the primary CLI command
- expose `/glue` as the primary slash command
- support `/handoff`, `/freeze`, and `/checkpoint` as compatibility aliases inside agent environments
- avoid publishing a package or executable named only `handoff`

PyPI spot checks on 2026-06-30:

| Name | PyPI Status | Judgment |
|---|---|---|
| `session-glue` | Not found | Best package candidate |
| `sessionglue` | Not found | Good fallback, but less readable |
| `agent-session-glue` | Not found | Clear but longer |
| `glue-session` | Not found | Good fallback, but weaker word order |
| `glue` | Exists | Do not use as PyPI package; acceptable as console command with fallback |
| `handoff` | Exists | Do not use |
| `handoff-agent` | Exists | Do not use |
| `freeze-handoff` | Not found | Older candidate; less brandable |

Best product names:

- Session Glue
- Session Glue Protocol
- Session Glue CLI
- Glue

Recommended:

```text
Session Glue
```

It communicates the link between sessions:

- cut the old session
- glue the useful context onto the new one

Best command names:

| Command | Judgment |
|---|---|
| `/glue` | Best primary slash command; short, memorable, and matches the product metaphor |
| `/freeze` | Good compatibility alias; short and intuitive for the context-reset moment |
| `/checkpoint` | Good alias for users who think in snapshots |
| `/snapshot` | Good concept, but may imply git/file snapshot rather than context handoff |
| `/handoff` | Useful compatibility alias, but too crowded as the primary brand |
| `/compact` | Familiar in some agent contexts, but implies compression more than handoff |
| `/seal` | Distinctive, but less obvious |

Final naming recommendation:

```text
Product: Session Glue
PyPI: session-glue
CLI: glue
Fallback CLI: session-glue
Primary slash command: /glue
Compatibility slash aliases: /freeze, /handoff, /checkpoint
```

---

## 25. Reference Links

Closest handoff and markdown-protocol references:

- `thepushkarp/handoff`: https://github.com/thepushkarp/handoff
- `taige221/session-handoff-skill`: https://github.com/taige221/session-handoff-skill
- `REMvisual/claude-handoff`: https://github.com/REMvisual/claude-handoff
- `daystar7777/agent-work-mem`: https://github.com/daystar7777/agent-work-mem

Larger memory-system references:

- `akitaonrails/ai-memory`: https://github.com/akitaonrails/ai-memory
- `agentscope-ai/ReMe`: https://github.com/agentscope-ai/ReMe
- `matrixorigin/Memoria`: https://github.com/matrixorigin/Memoria
- Mem0: https://github.com/mem0ai/mem0
- Letta: https://github.com/letta-ai/letta
- Zep / Graphiti: https://github.com/getzep/graphiti
- Basic Memory: https://github.com/basicmachines-co/basic-memory

---

## 26. Final Recommendation

Build Session Glue as a protocol plus lightweight CLI first, and agent-specific skills/rules second.

The MVP should not compete with Mem0, Letta, Zep, ReMe, or Memoria. It should compete with the operator's current habit:

> "I will just paste a messy summary into the next chat and hope the agent understands."

The winning user experience is:

1. `/glue`
2. the agent writes `.agent-history` and prints a copy-paste resume prompt in a fenced code block
3. restart session
4. paste the generated prompt

The winning installation model is:

1. `pipx install session-glue`
2. `glue install all`
3. every supported local agent learns the same Session Glue protocol
4. every project keeps its own `.agent-history/`

If that loop feels reliable, the product has a strong wedge.
