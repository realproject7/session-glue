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

Session Glue cuts one long conversation into two clean ones — and carries the **work** across the gap while letting the **chat** die.

```text
┌──────────────────────────────────────────────────┐
│ SESSION 1                                        │
│ long, costly, the agent is losing the plot       │
└──────────────────────────────────────────────────┘
                          │
                          │  you: "freeze this session"
                          ▼
┌──────────────────────────────────────────────────┐
│ the agent writes a structured handoff into       │
│ .agent-history/  ->  goal, active files,         │
│ what's done, what's next, how it's verified      │
└──────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────┐
│ two small files remain on disk:                  │
│    LATEST.md          the briefing               │
│    RESUME_PROMPT.txt   paste-ready prompt        │
│ the chat history is discarded -- no daemon,      │
│ nothing left running                             │
└──────────────────────────────────────────────────┘
                          │
                          │  reset the session,
                          │  then paste the resume prompt
                          ▼
┌──────────────────────────────────────────────────┐
│ SESSION 2                                        │
│ fresh, clean context                             │
└──────────────────────────────────────────────────┘
                          │
                          │  reads ONE small file -- no repo re-scan
                          ▼
┌──────────────────────────────────────────────────┐
│ continues the real work,                         │
│ exactly where session 1 left off                 │
└──────────────────────────────────────────────────┘
```

The expensive, drifting part — the raw chat history — is thrown away. What survives is the handoff: goal, constraints, what's done, what's next, and how to verify it, written as a few small files in your repo. A fresh session reads one of them and is instantly oriented, with no repo re-scan and no transcript to replay.

### What that looks like on a real task

In one project (call it **Project A**), an agent had spent a long, sprawling session coordinating a staging deployment: several PRs merged, an audit run, and one stubborn blocker — a server that still needed redeploying before a feature would work. The session also carried hard-won operational context that lived **only** in the chat:

> the local checkout is dirty and must not be touched · deploy from `origin/main` in a clean throwaway worktree · the server is a file snapshot, not a git repo · preserve its env file.

One "freeze this session" captured all of it. Then a **brand-new** agent — with none of that history — pasted the resume prompt, read a single file, and:

- picked up the blocker as its first action,
- deployed from a clean worktree **without touching the user's dirty local work** — because the handoff said so,
- ran a full browser + websocket smoke test, and
- reported back to the team,

without re-deriving a single piece of that context. The naive alternative — "paste a summary into a new chat and hope" — loses exactly the non-obvious constraints that separate a safe deploy from a broken one. That gap is what Session Glue closes.

## Getting started

Session Glue is deliberately a plain command-line tool — **not** a daemon, an MCP server, or a background service. Nothing runs in the background, nothing listens on a port, nothing needs keeping patched. Setup is two one-time commands; after that you just talk to your agent.

**1 · Install the CLI** (once per machine). It's a [pipx](https://pipx.pypa.io/) tool with **zero runtime dependencies** — pipx gives it an isolated environment and puts `glue` on your `PATH`:

```bash
pipx install session-glue        # or: uv tool install session-glue
```

<details>
<summary>No pipx yet, or on macOS / Homebrew Python?</summary>

Get pipx with `brew install pipx` (macOS) or `python3 -m pip install --user pipx`, then run `pipx ensurepath` and reopen your terminal.

A plain `pip install` on Homebrew or system Python fails with `externally-managed-environment` — that's [PEP 668](https://peps.python.org/pep-0668/) protecting your system Python, not a problem with the package. Use `pipx` (recommended), or a virtualenv (`python3 -m venv .venv && source .venv/bin/activate && pip install session-glue`).
</details>

**2 · Teach your agents the protocol** (once per machine). Rather than editing your global agent config, Session Glue ships as a **skill** — a small, self-contained folder your agent auto-discovers. Installing it never touches `CLAUDE.md`, `AGENTS.md`, or any global file:

```bash
glue skill install claude --scope user    # -> ~/.claude/skills/session-glue/
glue skill install codex  --scope user    # -> ~/.agents/skills/session-glue/
```

`--scope user` installs to your home directory and works in **every** project — do it once, anywhere. (Want to commit the skill and share it with a team? Use `--scope repo` to install it under the current repo instead.)

**3 · Just talk to your agent.** In any session, say **"freeze this session"** (or `/session-glue`, `/handoff`, `/checkpoint`, "세션 얼려줘"). The agent writes the handoff, `glue create` stores and validates it, and you get a copy-paste resume prompt — paste it into a fresh session to continue.

And your repo stays clean the whole time: on the first freeze, Session Glue quietly registers `.agent-history/` in your personal `.git/info/exclude` — never the shared `.gitignore`, never a tracked file — so `git status` stays spotless with zero effort on your part. That restraint is the whole design philosophy; see [Built to be trusted](#built-to-be-trusted) for everything it deliberately refuses to do.

## Anatomy & design

Session Glue draws one firm line: **the agent supplies judgment, the CLI supplies determinism.**

| The agent decides | The CLI guarantees |
|---|---|
| what context matters, what's done, what's next, which files are active | deterministic writes, indexing, and validation |
| how to summarize the session it actually lived through | that a malformed or lossy handoff is **refused**, never silently saved |

The agent — the only party that has the conversation — writes the summary. The CLI never calls an LLM and never guesses; it stores, indexes, validates, and fails loudly.

### The artifacts

A freeze produces a small, purpose-built file set under a repo-local `.agent-history/`:

```text
.agent-history/
├── LATEST.md            # the resume target — the ONE file a new session reads first
├── RESUME_PROMPT.txt    # the exact prompt you paste to start the next session
├── INDEX.yaml           # compact, grep-able metadata per session — a lookup surface, never the source of truth
├── DECISIONS.md         # append-only: durable decisions, one line each, kept across sessions
└── sessions/            # immutable archive — every handoff, kept forever
```

### A schema that forces a good handoff

A handoff is not free-form prose. Each one is validated before it is written, and the required fields are chosen so that a **bad** handoff cannot be saved silently:

- a one-line **goal**, and **active files each with a `reason`** — so the next agent opens the right two files, not the whole repo;
- **completed work**, **known issues**, and a **validation record** (commands run, and what passed / failed / was not run);
- **search tags**, so the session is findable from `INDEX.yaml` months later;
- a **productive first next-action** — a guard rejects a useless `next_todo_items[0]` like "read the handoff"; it must be real work;
- the **eight canonical narrative sections** (what happened · decided · failed · next · risks); and
- **no empty or truncated entries** — every list item is checked.

Two optional fields extend the model without taxing the common case: `decisions:` appends to `DECISIONS.md`, and `supersedes:` links a handoff to the one it replaces, so a chain stays traversable from `glue status`. Complete examples live in `tests/fixtures/handoffs/`; the full contract is in the bundled skill's `references/protocol.md`.

### What the structure buys you

- **Cheap, sharp resumes** — one small file read plus a `git status`, not a repo re-scan or a 100k-token transcript carried turn after turn. Because the fresh context holds only what matters, the agent also *reasons* better.
- **Cross-agent portability** — plain markdown + YAML; the same `.agent-history/` has been driven end-to-end by fresh Claude Code **and** Codex sessions, each resuming with zero broad scanning.
- **Decisions that don't decay** — `DECISIONS.md` keeps them verbatim across dozens of sessions instead of re-litigating them.
- **Drift you can see** — handoffs record the branch and commit they were written at; `glue status --git` / `glue validate --git` warn when the repo has moved on.

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

**Zero repo footprint by default.** Session Glue never adds anything to version control on its own: skill installs with `--scope user` put no files in your project at all, and `.agent-history/` is plain untracked files — committing handoffs is a per-project choice you make deliberately. To keep `git status` clean without touching any team-visible file, `glue create` registers `.agent-history/` in your personal, never-committed `.git/info/exclude` on first freeze (printing `registered .agent-history/ in .git/info/exclude (personal ignore — not committed)`). It never edits `.gitignore` or any tracked file, and it does nothing if `.agent-history/` is already ignored or there is no `.git/` directory. Intend to commit your handoffs instead? Pass `--no-exclude` to skip registration:

```bash
glue create --no-exclude    # write handoffs but leave git-ignore state untouched
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
