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
