# Changelog

All notable changes to Session Glue are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are built and published from CI going forward.

## [Unreleased]

## [0.4.0] - 2026-08-29

### Added

- **Personal Vault — opt-in sync of `.agent-history/` between your own devices.** New
  `glue sync push|pull|resolve` commands take `--repo-root PATH --project-id ID` and
  exactly one transport: `--vault-dir PATH` (a plain folder your own cloud-sync client
  keeps in step) or `--vault-git-dir PATH` (a private Git repository you have already
  cloned). Every sync is a command you type; nothing runs automatically, on a schedule, or
  as a side effect of another command, and normal local commands take no vault flags.
- Handoffs are made device-independent on export: `repo_root` and `project_root` are
  rewritten to a `<vault-root>` placeholder, which requires `project_root` to be the repo
  root or a directory inside it. New local-only `glue sync migrate-roots --session-id ID
  --project-root PATH` repairs an archive whose roots fall outside the repository; it
  contacts no vault and takes no project ID.
- Conflicts are surfaced, never guessed. When both sides changed the same session,
  `glue sync` stops with exit code `3` and `glue sync resolve` requires an explicit
  `--head-session` plus `--archive`/`--lifecycle` selectors for every named conflict. The
  **both** sides are retained under the vault's `conflicts/archives/<session-id>/` rather
  than either being discarded. Sessions that exist on only one device are preserved rather than treated as
  deletions.
- A privacy gate runs before anything leaves the machine. A secret-shaped finding blocks
  the sync and prints an acknowledgement challenge bound to the exact
  `(path, sha256, label)` triple, without ever echoing the matched text. Overriding it is
  deliberate: acknowledging shares that content with every device on the vault.
- Incomplete vaults are refused with exit code `4` (`vault not fully available`) instead of
  being read half-written. Session Glue never retries, polls, or waits — the operator
  re-runs the command once their sync client has settled. Documented caveat: on a device
  with no stored digest for a project, an unmaterialized namespace and a genuinely new
  project are indistinguishable.
- The Git transport fetches and fast-forwards, then produces exactly one commit per
  vault-mutating operation and pushes it to the branch's own upstream. The local record of
  vault state advances only after that push succeeds. Failures are reported as named,
  redacted categories (git unavailable, not a Git working tree, detached HEAD, missing
  upstream, uncommitted tracked changes, authentication failed, fetch failed, cannot
  fast-forward, non-fast-forward remote changes, push failed, timed out) — git's own
  output, your remote URL, your environment, and handoff content never appear in an error.
  Session Glue never merges, rebases, or resets your work to make a sync succeed.
- The bundled Codex and Claude skills teach the explicit-resume rule: an agent runs a vault
  command only when the operator supplies the command, the path, and the project ID, and
  never creates a vault, authenticates, retries, or synchronizes on its own initiative.

### Changed

- README and `glue sync --help` now state the v1 limits directly: no provider APIs (Dropbox,
  Google Drive, GitHub), no OAuth, no token storage, no credential request/read/parse, no
  automatic repository creation, no daemon, no automatic sync, no encryption, and no
  collaboration. A private Git repository is **access control, not confidentiality**, and
  folder operations are user-serialized rather than locked.
- README's trust posture is corrected rather than merely extended. "No network, ever" was
  true before the Git transport and is not any more: the CLI still makes no network call on
  its own, and the one exception — `--vault-git-dir` running your own `git` against your own
  configured remote — is now stated as such. A companion row records that no credential is
  ever requested, read, parsed, or stored.
- One `--project-id` per checkout is enforced before any write, and both README and CLI
  help say so: there is no relink workflow and no second baseline in v1.

## [0.3.1] - 2026-07-10

### Fixed

- Handoff values containing a `#` — most importantly GitHub issue/PR references such as `#207` — are no longer silently truncated. A `#` is now literal content everywhere; inline comments are not supported (only whole-line comments). This was a data-loss regression in 0.2.0–0.3.0: an agent writing `after #207 merge` had it stored as `after`, and a list item like `#214 merged` was emptied entirely. If you have handoffs written with 0.2.0–0.3.0, re-freeze from the original session to recover truncated text.
- `glue validate` now rejects empty-string entries in list fields, so a truncated or blank entry fails loudly per index instead of passing silently.

## [0.3.0] - 2026-07-09

### Added

- Zero-pollution default: the first `glue create` in a git repository registers `.agent-history/` in `.git/info/exclude` — the personal, never-committed ignore file — so `git status` stays clean without modifying any tracked file. Opt out with `--no-exclude` if you intend to commit handoffs. The leak scanner recognizes both `.gitignore` and `.git/info/exclude` coverage.
- `.gitattributes` pins LF line endings for all text files, and a new packaging test guards that bundled skill assets contain no CRLF — a wheel built on Windows now ships byte-identical assets to one built on Linux or macOS.

### Changed

- README rebuilt around the product story, user benefits, and the trust posture (zero dependencies, no daemon/network/clipboard, repo-local writes only), with an accurate description of the repository footprint.

## [0.2.0] - 2026-07-09

### Added
- `glue skill list/show/install/uninstall` for Codex and Claude: install the bundled skill into a dedicated repo- or user-scope folder (`.agents/skills/` / `.claude/skills/`), with dry-run, managed-files-only replace/uninstall, and symlink guards. Global instruction files are never modified.
- Handoffs now require `primary_goal`, `search_tags`, and a `validation` record (`command`/`result`; `notes` optional), and `active_context_files` entries may carry a `reason` — mirrored into `INDEX.yaml` so topical lookup works from the index alone.
- Optional `decisions:` frontmatter appends to an append-only `.agent-history/DECISIONS.md` log, so durable decisions survive across sessions verbatim.
- Optional `supersedes:` session links, a `glue close --status DONE|BLOCKED|ABANDONED` lifecycle command (INDEX-only; archives stay immutable), and a lineage line in `glue status`.
- Handoff bodies must carry the eight canonical narrative sections, and `glue create` warns when the previous freeze was under 30 minutes old.
- `glue validate` and `glue status` accept an optional `--git` flag that warns when the recorded head commit or branch has drifted from the working repository.
- `glue create` warns when a handoff appears to contain secret-like values or personal absolute paths.
- `glue validate` now runs stronger cross-file consistency checks between `LATEST.md`, `INDEX.yaml`, and archived sessions.
- `glue create` accepts a `--allow-flagged-todo` flag to override the resume-mechanic guard when a flagged first todo is intentional.
- `glue status` now reports the handoff lifecycle `status` and a `sessions:` count, and `glue create` prints a hint when it is reading from an interactive terminal.
- The test suite now runs in CI across Linux, macOS, and Windows on Python 3.10 through 3.13.

### Changed

- Handoff parsing is more forgiving of common YAML-subset friction in agent-written frontmatter.
- `next_todo_items` entries must be single scalar values; mappings or lists are now rejected with a clear validation error.

### Fixed

- Corrected lint false positives that rejected ordinary productive work items as resume mechanics.
- Added a slug-collision guard so distinct sessions no longer overwrite one another's archived files.

## [0.1.0] - 2026-07-01

### Added

- Initial public release on PyPI: the Session Glue continuity protocol and `glue` CLI (`create`, `validate`, `status`, `resume-prompt`, and `install --dry-run`).
