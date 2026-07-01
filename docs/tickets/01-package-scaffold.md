# Ticket 1: Package scaffold and project metadata

## Route

VPS QuadWork.

## Summary

Create the minimal Python package scaffold for Session Glue without implementing the full CLI behavior yet.

## Scope

- Add `pyproject.toml`.
- Add package module `session_glue`.
- Add console scripts:
  - `glue`
  - `session-glue`
- Add a small CLI entrypoint that supports `--version` and help output.
- Add test framework setup.
- Add README development instructions for local install and tests.

## Technical Direction

Prefer a small, conventional Python package:

- Python 3.10+
- `click` or `typer` for CLI routing
- `pytest` for tests
- `ruff` for lint/format if used
- no daemon
- no MCP package
- no background services

Keep the scaffold boring and easy to publish to PyPI later.

## Acceptance Criteria

- `python -m pip install -e .` works.
- `glue --help` works.
- `session-glue --help` works.
- `glue --version` works.
- `pytest` runs successfully.
- README documents the local development commands.
- No handoff-writing behavior is implemented in this ticket beyond CLI placeholders.

## Non-Goals

- Do not implement `.agent-history/` writing here.
- Do not implement installer logic here.
- Do not add daemon, MCP, database, watcher, UI, or cloud sync.
