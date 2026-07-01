# Ticket 9: Release packaging and PyPI gate

## Route

lead-po direct until operator approval is required.

## Summary

Prepare Session Glue for packaging and release, but do not publish to PyPI without operator approval.

## Scope

- Verify build artifacts.
- Verify local installation through `pipx` or `uv tool`.
- Verify command names:
  - `glue`
  - `session-glue`
- Prepare release checklist.
- Document PyPI publish steps.

## Operator Gates

The operator must approve before:

- using PyPI token/account
- publishing any package
- changing repo visibility from private to public
- enabling non-dry-run global installer behavior against real user-home files

## Acceptance Criteria

- `python -m build` works.
- Local wheel install works.
- `pipx install .` or equivalent local install works.
- Release checklist exists.
- PyPI publish command is documented but not run.

## Non-Goals

- Do not publish to PyPI in this ticket without explicit operator approval.
- Do not make the GitHub repo public without explicit operator approval.
- Do not add telemetry or cloud services.
