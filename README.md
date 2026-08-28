# Session Glue

[![CI](https://github.com/realproject7/session-glue/actions/workflows/ci.yml/badge.svg)](https://github.com/realproject7/session-glue/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/session-glue)](https://pypi.org/project/session-glue/)
[![Python](https://img.shields.io/pypi/pyversions/session-glue)](https://pypi.org/project/session-glue/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Reset the chat, not the work.**

Session Glue is a session-continuity protocol and CLI for coding agents (Claude Code, Codex, Cursor, and friends). When an agent session gets long, expensive, and forgetful, Session Glue freezes the useful context into a compact, repo-local briefing — and a fresh session picks up exactly where the old one left off, without dragging the whole chat history along.

No daemon. No server. No database. No network by default. Just markdown files in your repo — plus an opt-in [Personal Vault](#personal-vault--the-same-work-on-your-other-machine) when you explicitly ask to carry them to another machine.

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
┌────────────────────────────────────────────────────┐
│ SESSION 1  —  long, costly, losing the plot        │
└────────────────────────────────────────────────────┘
                           │
                           │  you say "freeze this session"
                           ▼
┌────────────────────────────────────────────────────┐
│ a small handoff is saved to .agent-history/        │
│ (goal, files, done, next, how to verify);          │
│ the chat is discarded -- no daemon, no server      │
└────────────────────────────────────────────────────┘
                           │
                           │  open a fresh session,
                           │  paste the resume prompt
                           ▼
┌────────────────────────────────────────────────────┐
│ SESSION 2  —  reads one file, continues the        │
│ work exactly where session 1 left off              │
└────────────────────────────────────────────────────┘
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

## Personal Vault — the same work on your other machine

Everything above is local by default and stays that way. If you also want a handoff you
froze on your laptop to be waiting on your desktop, Session Glue offers an **opt-in
Personal Vault**: one command, run by you, naming exactly where the vault is.

It is deliberately unambitious. There is no daemon, no background sync, no provider
integration, and no account. A vault is either **a folder** (which your own cloud-sync
client happens to keep in step) or **a private Git repository you already cloned**. Every
normal Session Glue command keeps working exactly as before, with no vault flags.

```bash
glue sync push --repo-root . --project-id my-app --vault-dir ~/vaults/session-glue
glue sync pull --repo-root . --project-id my-app --vault-dir ~/vaults/session-glue
```

The `--project-id` is the logical identity of this project across your devices. It is
**never inferred** — you name it every time, and the same ID on both machines is what
links them.

### Two devices, folder vault

Device A has a history; the vault side is empty. The first **push** bootstraps it:

```bash
# Device A — publish
glue sync push --repo-root . --project-id my-app --vault-dir ~/vaults/session-glue
# → vault state 4f2c…

# Device B — adopt
glue sync pull --repo-root . --project-id my-app --vault-dir ~/vaults/session-glue
# → .agent-history/ now carries Device A's sessions; resume as usual
```

Bootstrapping is a property of `push` alone, and only when the vault side is genuinely
empty **and** this checkout has never synced this project before. (`pull` has nothing to
import from an empty vault, so it reports that as unavailable.) Once a checkout has a
stored baseline, an absent vault is treated as unavailability rather than a fresh start —
so a half-materialized cloud folder can never be mistaken for "nothing here yet" and
silently overwritten.

### Two devices, Git vault

Identical commands, one different flag. The clone must already exist, be on a branch, and
have an upstream configured — Session Glue does not create, clone, or authenticate
anything:

```bash
git clone git@github.com:you/your-private-vault.git ~/vaults/session-glue-git   # you do this, once

glue sync push --repo-root . --project-id my-app --vault-git-dir ~/vaults/session-glue-git
glue sync pull --repo-root . --project-id my-app --vault-git-dir ~/vaults/session-glue-git
```

Each vault-mutating operation fetches, fast-forwards, and produces **exactly one commit**,
which is then pushed to the branch's own upstream. The local record of "what the vault
holds" advances only after that push succeeds — a commit that never left your machine is
not a sync that happened.

### When both sides moved

If both devices changed the same session since they last agreed, the sync stops and tells
you so. **Nothing is discarded and nothing is auto-merged.** You resolve by naming every
choice explicitly:

```bash
glue sync resolve --repo-root . --project-id my-app --vault-dir ~/vaults/session-glue \
  --head-session 2026-08-20-0930-refactor-parser \
  --archive 2026-08-19-1400-add-index=local \
  --lifecycle 2026-08-19-1400-add-index=vault
```

**Both** sides are retained under the vault's `conflicts/archives/<session-id>/`, each
under its own content digest, alongside a `conflicts/manifest.yaml` recording them — not
just the one you rejected. A resolution is therefore always recoverable, and a wrong call
is never terminal.

A session that exists only on this device is never a conflict at all: local-only archives
are preserved through push and pull rather than being treated as something the vault
"deleted".

### When the vault isn't all there yet

Cloud-sync folders materialize lazily. If Session Glue sees a vault that is present but
incomplete, it refuses with `vault not fully available` and a distinct exit code, rather
than reading a half-written state:

```console
$ glue sync push --repo-root . --project-id my-app --vault-dir ~/vaults/session-glue
glue sync: vault not fully available: ~/vaults/session-glue/projects/my-app is absent or
empty, but this checkout has synced this project before; wait for the sync client rather
than re-initializing
$ echo $?
4
```

**Wait for your sync client to finish, then run the command again yourself.** Session Glue
never retries, polls, or waits in a loop.

One caveat stated plainly, because it is irreducible rather than a bug: on a device that
has **no stored digest for this project yet**, an empty vault namespace that simply hasn't
materialized is indistinguishable from a genuinely new project. That first sync on a new
device is the one moment the tool cannot tell the two apart, so make sure your sync client
has settled before running it.

### Roots have to be inside the repo

A handoff records `repo_root` and `project_root`. For a handoff to mean anything on another
machine, those absolute paths are rewritten to a `<vault-root>` placeholder on export —
which is only possible when `project_root` **is `repo_root` or a directory inside it**.

An archive whose `project_root` points outside the repository has no device-independent
form, so it is not exportable. The fix is explicit, local, and touches no vault:

```bash
glue sync migrate-roots --repo-root . \
  --session-id 2026-08-19-1400-add-index --project-root .
```

That rewrites only those two scalars in the named archive and rebuilds the derived views.

### Before anything leaves your machine

Push and resolve run a privacy gate over every artifact that is about to be shared. If
something looks secret-shaped, the command **blocks** and prints an acknowledgement
challenge — a path, a SHA-256, and a label. It never echoes the matched text back at you.

```console
$ glue sync push --repo-root . --project-id my-app --vault-dir ~/vaults/session-glue
glue sync: blocked by privacy gate; acknowledge the exact triple to proceed:
  --acknowledge sessions/2026-08-20-0930-refactor-parser.md:7b562c00…a3f1fd:GitHub token (ghp_/gho_)
```

Copy the triple back to proceed. Do so deliberately: it is bound to that exact
`(path, sha256, label)` — acknowledging one finding never acknowledges another, and editing
the file invalidates the acknowledgement. **Acknowledging means you have decided to put that
content on every device attached to this vault.**

### Git failures tell you the category, never the details

Git's own error text routinely contains your remote URL, your username, or `remote:` lines
from the server. Session Glue never forwards it. A Git failure is reported as exactly one
named category:

| Category | What it means |
|---|---|
| `git unavailable` | no usable `git` on `PATH` |
| `not a Git working tree` | the path isn't a repository worktree |
| `detached HEAD` | check out a branch in the clone |
| `missing upstream` | the branch tracks nothing (or tracks a local branch) |
| `uncommitted tracked changes` | commit or stash them in the clone first |
| `authentication failed` | your existing git auth was refused |
| `fetch failed` | the fetch did not complete |
| `cannot fast-forward` | the clone diverged from its upstream; reconcile it yourself |
| `non-fast-forward remote changes` | the remote moved; pull, then retry |
| `push failed` | the push was refused |
| `timed out` | 15s for local git commands, 60s for fetch and push |

Session Glue never merges, rebases, or resets your own work to make a sync succeed. If the
clone needs reconciling, it says so and stops.

### What v1 deliberately does not do

This is the whole list, and it is a design boundary rather than a roadmap:

- **No provider APIs** — no Dropbox, Google Drive, or GitHub API calls. A folder is a
  folder; a Git remote is your `git`.
- **No OAuth, no tokens, no credentials.** Nothing is requested, read, parsed, or stored.
  The Git transport inherits the authentication you already configured.
- **No repository creation** and no automatic cloning. You create and clone the vault.
- **No daemon, no watcher, no automatic sync.** Every sync is a command you type.
- **No encryption.** A private Git repository is *access control*, not confidentiality —
  anyone who can read the repo can read your handoffs.
- **No collaboration.** A vault is for your own devices. There is no multi-user model, no
  locking, and no server-side merge; folder operations are user-serialized, meaning you
  are expected not to run two devices against the same vault at the same instant.
- **One project ID per checkout.** A checkout is linked to one `--project-id`; naming a
  different one fails before any write. There is no relink workflow and no second baseline.

## Built to be trusted

Session Glue is deliberately boring in all the ways that matter for something you run inside your repositories:

| Property | What it means for you |
|---|---|
| **Zero runtime dependencies** | Pure Python standard library. `pip install` pulls in exactly one package: this one. Nothing else enters your supply chain. |
| **No daemon, no watcher** | Nothing runs when you're not running it. Nothing to keep alive, patch, or forget about. |
| **No network unless you ask** | The CLI makes no network calls on its own — no telemetry, no background sync, no phoning home, ever. The single exception is explicit: `glue sync … --vault-git-dir` runs *your* `git` against the remote *your* clone already points at, only when you type that command. A folder vault (`--vault-dir`) makes no network call at all, and every other command is entirely local. |
| **No credentials, ever** | Nothing is requested, read, parsed, or stored — no OAuth, no tokens, no provider APIs, no `gh`. The Git vault transport inherits the authentication you already configured and never inspects it. A private repository is access control, not encryption. |
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

# Personal Vault — opt-in, explicit, never automatic. Exactly one transport flag.
glue sync push  --repo-root PATH --project-id ID (--vault-dir PATH | --vault-git-dir PATH) [--acknowledge PATH:SHA256:LABEL]
glue sync pull  --repo-root PATH --project-id ID (--vault-dir PATH | --vault-git-dir PATH)
glue sync resolve --repo-root PATH --project-id ID (--vault-dir PATH | --vault-git-dir PATH) \
    --head-session ID [--archive SESSION_ID=local|vault] [--lifecycle SESSION_ID=local|vault] \
    [--acknowledge PATH:SHA256:LABEL]
glue sync recover-duplicates --repo-root PATH --project-id ID (--vault-dir PATH | --vault-git-dir PATH) [--apply]
glue sync migrate-roots --repo-root PATH --session-id ID --project-root PATH   # local-only; touches no vault
```

Two local archives claiming one `session_id` make every other vault operation refuse,
because the derived head would otherwise depend on filename order. `glue sync
recover-duplicates` is the way out, and it needs a vault: the authoritative copy comes
from there, so one transport flag is required exactly as for `push` and `pull`.

It **lists and changes nothing by default** — you see every duplicated id and each path
claiming it, and nothing moves until you re-run with `--apply`. With `--apply`, the
conflicting copies are *moved* into a timestamped `.agent-history/quarantine-<stamp>/`,
never deleted, and the authoritative set is then re-materialized from the vault. An
archive whose `session_id` is unique keeps its content untouched. If anything fails after
that move, the quarantined copies are put back and your history returns to its
pre-command bytes — and the emptied quarantine directory is then removed, so a rollback
that put everything back leaves no directory behind. Anything that could **not** go back
is named in the error and stays in the quarantine, which is kept for exactly that reason:
if you see one after a failure, it is holding something, and the error says what.

Normal local commands never take a vault flag. Sync exits `3` for a conflict you must
resolve and `4` for a vault that is not fully available — two different problems, so
retrying the wrong one is not silently possible. That distinction covers what a command
detects **before it changes anything**; `recover-duplicates` also has an after, and once
it has moved archives into the quarantine every failure is reported as exit `1`, carrying
the original cause plus the rollback's own account of what went back and what did not. So
a vault that goes missing mid-recovery exits `1`, not `4`. Exit `1` is the general failure
code and is not specific to that phase — read the message, not the number, to tell a
pre-move refusal from a rolled-back one. `glue sync --help` states the v1 limits, the one-project-ID rule, and the
full list of named Git failure categories.

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
