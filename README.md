# Session Glue

Session Glue is a lightweight session-continuity protocol and CLI for coding agents.

Its goal is simple: when an agent session gets too long, create a compact local handoff that lets the next session resume without dragging the full chat history forward.

## Status

Pre-MVP founding repository.

The canonical product proposal lives in [`docs/PROPOSAL-session-glue.md`](docs/PROPOSAL-session-glue.md).

## Product Boundary

Session Glue v1 is intentionally small:

- repo-local `.agent-history/` handoffs
- markdown handoff files with YAML frontmatter
- `LATEST.md`, archived session files, `INDEX.yaml`, and `RESUME_PROMPT.txt`
- lightweight Python CLI
- no daemon
- no MCP dependency
- no embeddings
- no vector database
- no file watcher
- no product UI

## Planned CLI

Primary executable:

```bash
glue
```

Fallback executable:

```bash
session-glue
```

Planned commands:

```bash
glue create
glue validate
glue status
glue resume-prompt
glue install codex --dry-run
glue install claude --dry-run
glue install cursor --dry-run
glue install gemini --dry-run
```

### `glue create`

`glue create` archives an agent-composed handoff into the repository-local
`.agent-history/` directory. The agent writes the handoff document (YAML
frontmatter plus a narrative body — see the fixtures under
`tests/fixtures/handoffs/`); the CLI persists it:

```bash
glue create --input handoff.md          # or pipe via stdin: glue create < handoff.md
glue create --input handoff.md --repo-root /path/to/project
```

It creates or updates:

- `.agent-history/sessions/<session>.md` — the archived session
- `.agent-history/LATEST.md` — a copy of the newest handoff
- `.agent-history/RESUME_PROMPT.txt` — the copy-paste resume prompt
- `.agent-history/INDEX.yaml` — compact metadata and a session list

The handoff is validated first: a missing required field or a resume-mechanic
`next_todo_items[0]` is rejected before anything is written. `glue create` never
accesses the network or the OS clipboard.

### `glue validate`

`glue validate` checks that an existing `.agent-history/` is internally
consistent:

```bash
glue validate                              # validate ./.agent-history/
glue validate --repo-root /path/to/project
glue validate --sessions                   # also validate archived session files
```

It verifies that `LATEST.md` has valid frontmatter, that its `next_todo_items[0]`
is a productive action (not a resume mechanic such as "paste the prompt" or
"read `LATEST.md`"), that `RESUME_PROMPT.txt` exists, and that
`INDEX.yaml.first_next_action` matches `LATEST.md`'s `next_todo_items[0]`. It
exits non-zero and prints each problem when validation fails. Like the rest of
the CLI, it never touches the network or an LLM.

### `glue status` and `glue resume-prompt`

Two compact, read-only commands for orienting a new session:

```bash
glue status           # latest session metadata + a cheap validation summary
glue resume-prompt    # print .agent-history/RESUME_PROMPT.txt exactly
```

`glue status` reads `INDEX.yaml` and prints the latest session id, latest file,
current branch, head commit, and first next action, plus a one-line validation
summary. It deliberately does **not** print the full session narrative, so it
orients you without recreating context bloat, and it handles a missing
`.agent-history/` gracefully. `glue resume-prompt` prints the exact contents of
`RESUME_PROMPT.txt`. Both are strictly read-only.

### `glue install <agent> --dry-run`

`glue install` shows the managed instruction block Session Glue would add to a
coding agent's global instruction file, so agents know how to respond to
`/glue`, `/freeze`, `/handoff`, and `/checkpoint`:

```bash
glue install codex --dry-run
glue install claude --dry-run
glue install cursor --dry-run
glue install gemini --dry-run
glue install all --dry-run
```

It prints the target path and the proposed block (delimited by stable
`<!-- BEGIN/END SESSION GLUE (managed) -->` markers so a future updater can
replace it idempotently). **Only `--dry-run` is supported** — it never modifies
your home directory, and real installation is intentionally not implemented
(operator-gated). Running `glue install <agent>` without `--dry-run` exits with
an error.

## Development

Implementation should follow the founding tickets in the proposal. Do not add daemons, background sync, retrieval services, or UI surfaces to the MVP unless the proposal is explicitly updated first.

Session Glue targets Python 3.10+ and has **no required runtime dependencies** — the CLI is built on the standard library so it can be installed and trusted immediately.

### Local install

Create and activate a virtual environment, then install the package in editable mode with the development extras:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

### Verify the CLI

```bash
glue --help
glue --version
session-glue --help              # fallback executable
python -m session_glue --help    # module invocation
```

### Run the tests

```bash
pytest
```

### Lint (optional)

```bash
ruff check .
```

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening issues or pull requests. All public content must avoid credentials, private logs, `.env` contents, and personal local paths.

For vulnerability reports, see [`SECURITY.md`](SECURITY.md).
