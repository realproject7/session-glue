# Changelog

All notable changes to Session Glue are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are cut from main: a lightweight tag vX.Y.Z on the landed commit, a GitHub
release whose notes are that version's CHANGELOG section, then the operator uploads the
built sdist and wheel with twine.

## [Unreleased]

### Added

- `[retracts <id>]` in a later `decisions:` entry removes the line with that id from
  `glue status` and the resume prompt. `DECISIONS.md` stays append-only and keeps both
  lines. One bracket may list several ids, and a retraction applies wherever it sits in
  the file, including after a vault merge reorders lines (#146).
- `glue create` and `glue validate` warn about a `[standing]` line without a dated
  operator quote, a `[hold]` without a reason or end condition, and a retraction of an
  unknown id. The warnings never block a freeze or change an exit code, so existing logs
  keep working (#146).

### Changed

- Standing decisions carry provenance (#146). Only a `DECISIONS.md` line of the form
  `[standing] YYYY-MM-DD operator: "<quote>"`, with nothing after the quote, appears under
  `Standing operator rulings:` in `glue status` and the resume prompt. An agent's hold,
  `[hold] <what>; reason: <why>; until: <end condition>`, appears under
  `Agent-recorded holds (verify before relying on them):`. Every other `[standing]` line,
  including the lines 0.4.1 told agents to write, appears under
  `Unverified standing notes (agent-written; confirm with the operator before relying on them):`.
  Each displayed line starts with a stable 8-character id, and `glue status` adds its age.
  The single `standing:` block in `glue status` is replaced by these labeled blocks. Each
  block is capped at the newest 20 lines and led by `(+N older lines in DECISIONS.md)`
  when more exist. A resume prompt with no marked lines stays byte-identical to 0.4.0.
- Codex and Claude skills record an operator ruling only as a dated quote of the
  operator's own words, never add conditions to it, record an agent's hold with its reason
  and end condition, and retract lines that no longer apply. On resume, operator rulings
  stand as quoted until the operator changes them, agent-recorded holds and unverified
  notes are state to verify, and a resume must not narrow what the operator granted. The
  one-way wording that let holds only accumulate is gone (#146).

## [0.4.1] - 2026-10-13

### Added

- `glue status` prints a `standing:` block after the lineage line with every `DECISIONS.md`
  line containing `[standing]`, oldest first and capped at the newest 20, led by a
  `(+N older standing lines in DECISIONS.md)` line when more exist. `glue resume-prompt` and
  the generated `RESUME_PROMPT.txt` carry the same lines under `Standing operator rulings:`
  after the first productive next action, including the prompt that `glue sync pull`,
  `resolve` and `migrate-roots` rebuild. Nothing extra is printed when `DECISIONS.md` is
  absent or has no such line, so those prompts stay byte-identical to 0.4.0. `decisions:`
  entries work with or without the prefix; no schema change (#140).

### Changed

- Codex and Claude skills read standing rulings from `glue status` and the resume prompt
  with CLI 0.4.1 or newer, and keep reading the last 20 lines of `DECISIONS.md` plus every
  `[standing]` line themselves as the fallback for older CLIs. The fallback prompt template
  in `references/protocol.md` gains the same block (#140).

## [0.4.0] - 2026-10-12

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

- Codex and Claude skills carry standing operator rulings across sessions. On glue, a
  standing ruling goes into the `decisions:` list with a `[standing]` prefix so it reaches
  `DECISIONS.md`, and a one-off decision carries its PR or issue number instead. On resume,
  the skills read the last 20 lines of `DECISIONS.md` plus every `[standing]` line, and a
  standing ruling stays in force until the operator changes it. No schema, CLI, validator
  or prompt-generation change (#140, #141).

- Codex and Claude skills preserve compact outcome, role, authority and gate context on resume. They check current index lifecycle and git drift, reconcile applicable instructions and load references only for the current decision. README distinguishes visible context from cached/billed tokens and recommends meaningful continuity checkpoints. No schema, CLI, installer or vault behavior changed.

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

### Fixed

- `glue validate` accepts an empty top-level `first_next_action` in `INDEX.yaml` when the
  `latest_session` entry's status is `DONE`, which is the state `glue close --status DONE`
  produces and documents. `BLOCKED` and `ABANDONED` keep their next action, and an
  `in_progress` session with an empty value is still reported. `glue status` prints
  `first next action: none (session DONE)` for that case instead of `(unknown)` (#142).

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
