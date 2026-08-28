# Personal Vault post-merge audit

Audit ticket: #82

Audit target: `origin/main` at `8b571c8adb29f54eaf04247cd316296688bbdd0d`

Date: 2026-08-28
Scope: the merged Personal Vault delivery (#78, #79, #80, #81), plus all
production, packaging, agent-surface, and legacy-command paths that can affect
its safety boundary.

## Release status

**Blocked.** This audit confirmed four P0 findings (#87, #88, #89, #91) and
three P1 findings (#90, #92, #93). Creating those tickets is not clearance:
no release or publishing decision is authorized until the P0 fixes merge and a
follow-up audit rechecks their exact tips.

## Method and verification record

Every production file listed below was read in full. Tests were used only as
corroboration, never as a substitute for production-path coverage.

| Check | Result | Evidence |
| --- | --- | --- |
| `python3 -m compileall -q session_glue` | PASS | Current audit branch, no syntax errors. |
| `python3 -m pytest -q` | Not runnable locally | The local Python 3.14 environment has no `pytest`; no dependency was installed for the audit. |
| PR #83 CI | PASS | 12/12 completed-success checks on the merged tip. |
| PR #84 CI | PASS | 12/12 completed-success checks on the merged tip. |
| PR #85 CI | PASS | 12/12 completed-success checks on the merged tip. |
| PR #86 CI | PASS | 12/12 completed-success checks on the merged tip. |
| Package/config inspection | PASS | `pyproject.toml` remains stdlib-only at runtime; assets are explicitly packaged. |
| Local-only boundary inspection | PASS, with existing test corroboration | Folder transport tests replace subprocess and socket creation with failures; `gitcheck` is only behind explicit `--git`. |

## Files read

Production Python: `session_glue/__init__.py`, `__main__.py`, `cli.py`,
`gitcheck.py`, `installer.py`, `leakscan.py`, `reader.py`, `schema.py`,
`skills.py`, `validator.py`, `vault.py`, `vaultgit.py`, and `writer.py`, plus
`session_glue/assets/**`.

Agent/package/docs: `codex-skills/session-glue/**`, bundled Codex and Claude
skill assets, `pyproject.toml`, `README.md`, `CHANGELOG.md`, `SECURITY.md`,
`CONTRIBUTING.md`, `LICENSE`, `.gitattributes`, CI and PR configuration, and
`docs/agent-surfaces.md`.

Corroborating tests read: `tests/test_vault.py`, `tests/test_sync_cli.py`,
`tests/test_sync_git.py`, `tests/test_docs.py`, `tests/test_skills.py`, and
package/skill tests.

## Invariant evidence

| Scoped invariant | Audit result and evidence |
| --- | --- |
| Canonical archive/state bytes and SHA-256 determinism | Pass by source inspection: `vault.py` canonicalization is a targeted raw transform and state rendering orders fields before hashing; byte assertions exist in `test_vault.py`. |
| Contained-root import/export | **Fail — #88.** Source and destination reads/writes do not consistently reject symlinked ancestors or source symlinks. |
| Conflict candidates, active-set exclusion, and candidate privacy gate | Candidate handling is present, but **fail — #91** because resolve omits merged `DECISIONS.md` from its privacy gate. |
| Local replacement rollback file-set identity | Pass for the staged `LocalWrite` replacement path; separate unsafe sync-state write is **#88**. |
| Availability/preflight and content → state → marker | Missing state/referenced content is rejected and ordering exists; **fail — #93** for replacing an already-referenced folder artifact without failure-safe publication. |
| Conservative bootstrap and one-sided lifecycle | Pass by source inspection of namespace and lifecycle merge rules; no issue filed. |
| Consecutive no-op closure | Existing folder/Git no-op tests corroborate the digest comparison path; no separate finding. |
| One-project-ID-per-checkout mismatch/no-clobber | Folder mode rejects before publication; **fail — #87** because Git fetch/fast-forward happens before the core mismatch check. |
| `migrate-roots` raw rewrite and fault rollback | Pass by source inspection of targeted root replacement and staged local write rollback. |
| Git deferred digest and clone restoration after failed push | Deferred digest and post-fast-forward rollback are present; **fail — #87** because reset does not remove new untracked artifacts from a first-sync core failure. |
| Default no-network / no global config / explicit-only sync | Pass. Git is reached only through explicit Git-vault commands, no `gh`/provider API/token handling was found, and no global Git config mutation occurs. |
| Documentation/implementation drift | **Fail — #90.** The visible legacy dry-run installer block no longer satisfies the current handoff schema. |
| Other containment surface | **Fail — #92.** Skill installation can mutate through a symlinked scope ancestor before containment is checked. |

## Vault-write and Git-commit privacy enumeration

The following production routes can write under a vault root or create a Git
commit. The audit traced the privacy gate rather than relying on test names.

| Route | Privacy result |
| --- | --- |
| Folder/Git `push` → `vault.export_project()` → `_publish()` | Gates changed canonical archives and merged decisions before publication. |
| Folder/Git `resolve` → `vault.resolve_project()` → `_publish()` | **Fail — #91.** Gates active archives and conflict candidates, but adds merged decisions after the gate. |
| Git `sync()` → `stage_commit_push()` | Stages only the project namespace; its content inherits the core gate result. The resolve gap therefore reaches a Git commit too. |
| `migrate-roots` | Local-only; it does not write a vault or create a commit. |

Existing tests corroborate ordinary-local safety: `tests/test_sync_cli.py` makes
subprocess and socket creation fail for every folder-transport test, and Git
tests use temporary local bare remotes with a failing `gh` shim. This is not a
live provider test and no provider account, remote URL, or credential was used.

## Confirmed findings and follow-up routing

| Severity | Finding | Follow-up |
| --- | --- | --- |
| P0 | Git clone rollback leaves newly-created untracked artifacts after a first-sync core write failure; mismatch rejection occurs after Git mutation. | #87 |
| P0 | Personal Vault source reads and local sync-state writes can cross symlinked boundaries. | #88 |
| P0 | Pull silently overwrites divergent local archive/lifecycle state. | #89 |
| P1 | Legacy `glue install --dry-run` guidance produces an obsolete handoff contract. | #90 |
| P0 | Resolve can publish/commit privacy-matched `DECISIONS.md` without acknowledgement. | #91 |
| P1 | Skill installation/removal can mutate through a symlinked scope ancestor. | #92 |
| P1 | Folder publication can leave old authoritative metadata pointing at a truncated replacement artifact. | #93 |

Each finding was independently re-read against `origin/main` before ticketing.
No duplicate open issue covered these defects. Rejected false positives include
the intentional raw-root canonicalization, the post-fast-forward Git rollback
target, and ordinary local commands merely importing modules that may use Git
on an explicitly requested path.

## Pre-feature multi-session exercise

The merged test suite includes folder and Git second-checkout round trips with a
local-only archive (`test_sync_cli.py` and `test_sync_git.py`), and their PR CI
was green. The mandatory complete pre-feature multi-session exercise cannot be
accepted as a clean audit result while pull has the P0 no-clobber defect. #89
therefore owns a full pre-feature multi-session push → second-checkout pull →
resume exercise, including any `migrate-roots` recovery evidence. No local
history or remote was mutated by this audit.

## Upgrade residue and rejected findings

No code path was found that automatically migrates old `.agent-history/` state
into a vault; this preserves the opt-in boundary. Partial marker/state content
is generally rejected as unavailable rather than rebuilt. The audit did not use
real operator state, credentials, or a cloud/provider account, so no claim is
made about a specific device upgrade beyond these source-level findings.

## Next step

Run ticket review for #87–#93 before any implementation batch. Do not release,
publish, or treat this report as release approval.
