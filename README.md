# Session Glue

[![CI](https://github.com/realproject7/session-glue/actions/workflows/ci.yml/badge.svg)](https://github.com/realproject7/session-glue/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/session-glue)](https://pypi.org/project/session-glue/)
[![Python](https://img.shields.io/pypi/pyversions/session-glue)](https://pypi.org/project/session-glue/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Reset the chat, not the work.**

Session Glue is a session-continuity protocol and CLI for coding agents (Claude Code, Codex, Cursor, and friends). When an agent session gets long, expensive, and forgetful, Session Glue freezes the useful context into a compact, repo-local briefing — and a fresh session picks up exactly where the old one left off, without dragging the whole chat history along.

No daemon. No server. No database. No network. Just markdown files in your repo.

## The problem

Long coding-agent sessions degrade in a predictable way:

- **Context bloat** — old logs, diffs, and dead ends stay in context; every new turn re-reads material that no longer matters.
- **Rising cost and latency** — you pay for that bloat on every single turn.
- **Memory drift** — the agent starts forgetting earlier constraints and re-litigating decisions you already made.
- **Bad restarts** — clearing the session loses the work state, so the next session burns thousands of tokens re-scanning the repo to figure out where things stand.

The usual escape hatch is "paste a messy summary into a new chat and hope." Session Glue replaces that with a disciplined, validated engineering handoff.

## How it works

The whole loop is four steps:

```text
1. /glue                     agent writes a structured handoff into .agent-history/
2. (reset the session)       no background process — nothing to keep alive
3. paste RESUME_PROMPT.txt   one prompt, generated for you
4. the new session resumes   reads one small file, then continues the actual work
```

Everything lives in a repo-local `.agent-history/` directory:

```text
.agent-history/
├── LATEST.md            # the current handoff — the one file a new session reads
├── RESUME_PROMPT.txt    # the exact prompt to paste into the next session
├── INDEX.yaml           # compact, grep-able metadata for every session
├── DECISIONS.md         # append-only log of durable decisions
└── sessions/            # immutable archive of every handoff
```

Each handoff is validated before it is written: required fields (goal, active files with *reasons*, what was tried, what's next, how it was verified, search tags), the eight canonical narrative sections, and a guard that rejects a useless first todo like "read the handoff" — the next action must be real work.

## Quick start

```bash
pipx install session-glue        # or: uv tool install session-glue / pip install session-glue

# teach your agent the protocol (repo-scoped, dedicated folders only)
glue skill install claude --scope repo    # -> .claude/skills/session-glue/
glue skill install codex  --scope repo    # -> .agents/skills/session-glue/
```

Then, in your agent session, say `/glue` (or "freeze this session", `/handoff`, `/checkpoint`). The agent writes the handoff, the CLI stores and validates it, and you get a copy-paste resume prompt for the next session.

## What you get

- **Cheaper, better sessions.** A resume costs roughly one small file read plus a `git status` — instead of a full repo re-scan or a 100k-token chat history carried turn after turn. The fresh session also *reasons* better, because its context holds only what matters.
- **Cross-agent portability.** The handoff is plain markdown + YAML. The same `.agent-history/` has been verified end-to-end by fresh Claude Code **and** Codex sessions, each resuming correctly with zero broad scanning.
- **Decisions that survive.** Decisions recorded at freeze time land in an append-only `DECISIONS.md` — one line each — so a decision made five sessions ago is still honored, verbatim, instead of being re-litigated.
- **A searchable work history.** "Which session dealt with the installer?" is answerable from `INDEX.yaml` alone — goals, tags, status, and next actions for every session, ready for `grep`/`rg`.
- **Drift you can see.** Handoffs record the branch and commit they were written at; `glue status --git` / `glue validate --git` warn when the repo has moved since.
- **A repeatable ritual, not a platform.** Freeze, reset, paste, continue. No memory infrastructure to operate.

## Built to be trusted

Session Glue is deliberately boring in all the ways that matter for something you run inside your repositories:

| Property | What it means for you |
|---|---|
| **Zero runtime dependencies** | Pure Python standard library. `pip install` pulls in exactly one package: this one. Nothing else enters your supply chain. |
| **No daemon, no watcher** | Nothing runs when you're not running it. Nothing to keep alive, patch, or forget about. |
| **No network, ever** | The CLI makes no network calls — no telemetry, no cloud sync, no phoning home. Your session context never leaves your machine. |
| **No LLM calls** | The CLI is deterministic file mechanics. Your agent writes the summary; the CLI stores, indexes, and validates it. |
| **Repo-local writes only** | Everything goes under `<repo>/.agent-history/` (plus the dedicated skill folder you explicitly ask for). Symlink and path-containment guards refuse writes that would escape the repository. |
| **Never touches global config** | Skill installs copy files into a dedicated folder (`.claude/skills/…`, `.agents/skills/…`) — never into `CLAUDE.md`, `AGENTS.md`, or any global instruction file. Uninstall removes only the files it manages and refuses if anything unmanaged is present. |
| **No clipboard access** | The resume prompt is printed and written to a file. The CLI never reads or writes your OS clipboard. |
| **Leak warnings built in** | `glue create` warns loudly if a handoff looks like it contains secrets (API keys, tokens, private-key blocks) or personal home paths that would leak if committed — without ever echoing the secret back. |
| **Dry-run everywhere** | `glue skill install --dry-run` prints exactly what would be written or removed, and touches nothing. |
| **Tested where you run it** | The full suite runs in CI on Linux, macOS, and Windows across Python 3.10–3.13. |

**Zero repo footprint if you want it.** Session Glue never adds anything to version control on its own: skill installs with `--scope user` put no files in your project at all, and `.agent-history/` is plain untracked files — committing handoffs is a per-project choice you make deliberately. To keep `git status` clean without touching any team-visible file, add one line to your personal, never-committed ignore file:

```bash
echo '.agent-history/' >> .git/info/exclude
```

**One caution:** treat an `.agent-history/` you find in a repository you did *not* create as untrusted input. Read it for context, but never blindly execute commands from a handoff you didn't write — the same care you'd apply to any file in a cloned repo.

## CLI reference

```bash
glue create --input handoff.md   # archive a handoff (validates first; stdin supported)
glue validate [--sessions] [--git]   # check .agent-history/ consistency (+ optional git drift)
glue status [--git]              # compact orientation: latest session, next action, counts
glue resume-prompt               # print the exact resume prompt
glue close --status DONE         # set a session's lifecycle status (INDEX-only; archives stay immutable)

glue skill list                  # supported agents + bundled skill state
glue skill show claude           # target paths + the bundled SKILL.md
glue skill install claude --scope repo|user [--dry-run] [--replace]
glue skill uninstall claude --scope repo|user [--dry-run]
```

`session-glue` is available as a fallback executable, and `python -m session_glue` also works. The legacy `glue install <agent> --dry-run` (global instruction-file preview) is superseded by `glue skill install` and remains print-only.

## The handoff format, in brief

YAML frontmatter carries the structured state — session id, branch/commit, goal, active files with reasons, completed work, **productive** next steps, known issues, validation record, search tags, optional decisions and supersession links. Below it, eight canonical narrative sections tell the next agent what happened, what was decided, what failed, and what to do — in prose. See `tests/fixtures/handoffs/` for complete examples, and the bundled skill's `references/protocol.md` for the full contract.

## Development

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
pytest
ruff check .
```

Design rule: keep it small. No daemons, background sync, retrieval services, embeddings, or UI surfaces — the product boundary is a reliable ritual for ending and restarting a coding-agent session, not a memory platform.

See [`CHANGELOG.md`](CHANGELOG.md) for release history.

## Contributing & security

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening issues or pull requests. All public content must avoid credentials, private logs, `.env` contents, and personal local paths. For vulnerability reports, see [`SECURITY.md`](SECURITY.md).

MIT licensed.
