# Changelog

All notable changes to Session Glue are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are built and published from CI going forward.

## [Unreleased]

### Added

- `glue validate` and `glue status` accept an optional `--git` flag that warns when the recorded head commit or branch has drifted from the working repository.
- `glue create` warns when a handoff appears to contain secret-like values or personal absolute paths.
- `glue validate` now runs stronger cross-file consistency checks between `LATEST.md`, `INDEX.yaml`, and archived sessions.
- `glue create` accepts a `--allow-flagged-todo` flag to override the resume-mechanic guard when a flagged first todo is intentional.
- `glue status` now reports the handoff lifecycle `status` and a `sessions:` count, and `glue create` prints a hint when it is reading from an interactive terminal.

### Changed

- Handoff parsing is more forgiving of common YAML-subset friction in agent-written frontmatter.
- `next_todo_items` entries must be single scalar values; mappings or lists are now rejected with a clear validation error.

### Fixed

- Corrected a lint false-positive that rejected valid flagged-todo handoffs.
- Added a slug-collision guard so distinct sessions no longer overwrite one another's archived files.

## [0.1.0] - 2026-07-01

### Added

- Initial public release on PyPI: the Session Glue continuity protocol and `glue` CLI (`create`, `validate`, `status`, `resume-prompt`, and `install --dry-run`).
