"""Explicit Git working-tree vault transport (issue #80).

Synchronises the #78 vault layout through an **already-cloned** private
repository, using only the operator's existing `git` authentication. It never
invokes `gh`, creates a repository, touches global Git config, or handles a
token: GitHub access stays wholly inside the user's preconfigured Git
remote/auth environment, and credentials are never requested, read, or parsed.

Two properties carry most of the weight:

- **The vault is the remote, not the clone.** A commit that has not been pushed
  is not a vault change that succeeded, so the local baseline is written only
  after the exact upstream push returns success. Advancing it earlier would
  record a state the other device can never observe.
- **Git's own failure text is never forwarded.** It routinely embeds the remote
  URL, a username, or `remote:` lines. Failures are classified into named
  categories and rendered from this module's own strings, so an error is
  actionable without leaking what produced it.

Standard library only. Every subprocess call uses explicit arguments and a
bounded timeout.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import vault, writer

#: Local, non-network Git work: fast and bounded tightly.
LOCAL_TIMEOUT = 15
#: Network-bearing commands. The advisory `gitcheck` precedent uses 10s, which
#: is right for `rev-parse` and far too short for a real fetch or push.
NETWORK_TIMEOUT = 60


class GitVaultError(vault.VaultError):
    """A Git transport failure, already reduced to a named, redacted category."""


# Named failure categories. The category is what the operator sees; the
# underlying Git text never is.
CATEGORY_UNAVAILABLE = "git unavailable"
CATEGORY_NOT_A_REPOSITORY = "not a Git working tree"
CATEGORY_DETACHED = "detached HEAD"
CATEGORY_MISSING_UPSTREAM = "missing upstream"
CATEGORY_DIRTY = "uncommitted tracked changes"
CATEGORY_AUTH = "authentication failed"
CATEGORY_NON_FAST_FORWARD = "non-fast-forward remote changes"
CATEGORY_FETCH = "fetch failed"
CATEGORY_FAST_FORWARD = "cannot fast-forward"
CATEGORY_PUSH = "push failed"
CATEGORY_TIMEOUT = "timed out"


@dataclass(frozen=True)
class GitResult:
    """Outcome of one Git invocation. ``stderr`` is for *classification only*.

    ``stdout`` is kept **raw**: `git status --porcelain` encodes state in the
    first two columns, so stripping it would shift every path by a character.
    Callers that want a single value use :meth:`value`.
    """

    returncode: int
    stdout: str
    stderr: str

    def value(self) -> str:
        """The output as a single trimmed token (for `rev-parse`-style calls)."""
        return self.stdout.strip()


def _run_git(clone: Path, args: list[str], timeout: int) -> GitResult:
    """Run one Git command with explicit arguments and a bounded timeout.

    ``subprocess`` is imported at module scope here (unlike ``gitcheck``, whose
    lazy import keeps the default local commands subprocess-free) because this
    module is only ever imported by the Git transport path.
    """
    try:
        completed = subprocess.run(  # noqa: PLW1510 - returncode is inspected below
            ["git", "-C", str(clone), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitVaultError(
            f"{CATEGORY_UNAVAILABLE}: git is not installed or not on PATH"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitVaultError(
            f"{CATEGORY_TIMEOUT}: 'git {args[0]}' exceeded {timeout}s"
        ) from exc
    except OSError as exc:
        raise GitVaultError(f"{CATEGORY_UNAVAILABLE}: cannot run git: {exc.strerror}") from exc
    return GitResult(completed.returncode, completed.stdout, completed.stderr)


def _classify_remote_failure(stderr: str, default: str) -> str:
    """Map Git's stderr to one of our categories **without quoting any of it**."""
    lowered = stderr.lower()
    if any(
        marker in lowered
        for marker in ("authentication", "could not read username", "permission denied",
                       "access denied", "invalid credentials", "terminal prompts disabled")
    ):
        return CATEGORY_AUTH
    if "non-fast-forward" in lowered or "fetch first" in lowered or "rejected" in lowered:
        return CATEGORY_NON_FAST_FORWARD
    return default


def preflight(clone: Path) -> tuple[str, str]:
    """Validate the clone and return ``(branch, upstream_ref)``.

    Refuses, before anything is read or written: a path that is not a real Git
    working tree, a symlinked one, a detached HEAD, a branch with no configured
    upstream, or any *tracked* modification. Untracked files are deliberately
    ignored — staging is exact-path only, so stray files can never ride along,
    and blocking on a `.DS_Store` would be a refusal the operator cannot see the
    cause of in their own `git status`.
    """
    path = Path(clone)
    writer.reject_symlink(path)
    if not path.is_dir():
        raise GitVaultError(f"{CATEGORY_NOT_A_REPOSITORY}: {path} is not a directory")
    # A worktree or submodule checkout has `.git` as a *file*; both are valid.
    git_entry = path / ".git"
    writer.reject_symlink(git_entry)
    if not git_entry.exists():
        raise GitVaultError(f"{CATEGORY_NOT_A_REPOSITORY}: {path} has no .git entry")

    inside = _run_git(path, ["rev-parse", "--is-inside-work-tree"], LOCAL_TIMEOUT)
    if inside.returncode != 0 or inside.value() != "true":
        raise GitVaultError(f"{CATEGORY_NOT_A_REPOSITORY}: {path} is not a Git working tree")

    branch = _run_git(path, ["symbolic-ref", "--quiet", "--short", "HEAD"], LOCAL_TIMEOUT)
    if branch.returncode != 0 or not branch.value():
        raise GitVaultError(
            f"{CATEGORY_DETACHED}: check out a branch in the vault clone before syncing"
        )

    upstream = _run_git(
        path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], LOCAL_TIMEOUT
    )
    if upstream.returncode != 0 or not upstream.value():
        raise GitVaultError(
            f"{CATEGORY_MISSING_UPSTREAM}: branch {branch.value()!r} has no configured upstream; "
            "set one with 'git branch --set-upstream-to' in the vault clone"
        )
    # A branch may track another *local* branch, which has no remote component.
    # Both the fetch and the push split the upstream on "/", so without this
    # clause the operator would be told the fetch failed when in truth there was
    # never a remote to fetch from.
    if "/" not in upstream.value():
        raise GitVaultError(
            f"{CATEGORY_MISSING_UPSTREAM}: branch {branch.value()!r} tracks "
            f"{upstream.value()!r}, which is a local branch, not a remote one; "
            "the vault must live on a remote"
        )

    dirty = _run_git(path, ["status", "--porcelain", "--untracked-files=no"], LOCAL_TIMEOUT)
    if dirty.returncode != 0:
        raise GitVaultError(f"{CATEGORY_NOT_A_REPOSITORY}: cannot read status of {path}")
    if dirty.stdout.strip():
        changed = ", ".join(sorted(line[3:] for line in dirty.stdout.splitlines() if line[3:]))
        raise GitVaultError(
            f"{CATEGORY_DIRTY}: commit or stash them in the vault clone first ({changed})"
        )
    return branch.value(), upstream.value()


def head_commit(clone: Path) -> str:
    result = _run_git(Path(clone), ["rev-parse", "HEAD"], LOCAL_TIMEOUT)
    if result.returncode != 0:
        raise GitVaultError(f"{CATEGORY_NOT_A_REPOSITORY}: cannot resolve HEAD")
    return result.value()


def fetch_and_fast_forward(clone: Path, branch: str, upstream: str) -> None:
    """Bring the checked-out branch up to date, or refuse.

    Explicitly ``fetch`` then ``merge --ff-only`` rather than ``git pull``: pull's
    behaviour depends on the user's ``pull.rebase``/``pull.ff`` settings, and this
    transport must not read or change their Git configuration.
    """
    path = Path(clone)
    remote, _, remote_branch = upstream.partition("/")
    fetched = _run_git(path, ["fetch", "--quiet", remote, remote_branch], NETWORK_TIMEOUT)
    if fetched.returncode != 0:
        raise GitVaultError(
            f"{_classify_remote_failure(fetched.stderr, CATEGORY_FETCH)}: "
            f"could not fetch {branch!r} from its configured upstream"
        )
    merged = _run_git(path, ["merge", "--ff-only", upstream], LOCAL_TIMEOUT)
    if merged.returncode != 0:
        raise GitVaultError(
            f"{CATEGORY_FAST_FORWARD}: {branch!r} has diverged from its upstream; "
            "reconcile the vault clone yourself — this command never merges or resets your work"
        )


def restore(clone: Path, commit: str) -> GitResult:
    """Return the clone to a pre-operation commit and tracked working-tree state.

    Used only to undo *our own* work — a partial write from a failed core
    operation, or our commit after a failed push. The target is always the
    post-fast-forward commit, never a pre-fetch one: commits fetched from the
    upstream are the operator's own work from another device, and resetting the
    branch away from them would be exactly the automatic reset of user-authored
    changes this transport refuses to perform. Untracked files are left alone —
    the core deletes the targets it created — and the preflight has already
    established that the tracked tree was clean.
    """
    return _run_git(Path(clone), ["reset", "--hard", "--quiet", commit], LOCAL_TIMEOUT)


def stage_commit_push(
    clone: Path, project_id: str, branch: str, upstream: str, message: str
) -> bool:
    """Stage exactly this project's paths, make one commit, and push it.

    Returns ``False`` when there was nothing to commit. Staging is restricted to
    ``projects/<id>/`` — never ``git add -A`` or ``.`` — so a pre-existing
    conflict or an unrelated change in the vault clone is neither staged nor
    disturbed.
    """
    path = Path(clone)
    vault.validate_project_id(project_id)
    project_path = f"{vault.PROJECTS_DIRNAME}/{project_id}"

    added = _run_git(path, ["add", "--", project_path], LOCAL_TIMEOUT)
    if added.returncode != 0:
        raise GitVaultError(f"{CATEGORY_NOT_A_REPOSITORY}: cannot stage {project_path}")

    staged = _run_git(path, ["diff", "--cached", "--name-only"], LOCAL_TIMEOUT)
    if not staged.value():
        return False
    stray = sorted(n for n in staged.value().splitlines() if not n.startswith(project_path + "/"))
    if stray:
        raise GitVaultError(
            f"refusing to commit paths outside {project_path}/: {', '.join(stray)}"
        )

    committed = _run_git(path, ["commit", "--quiet", "-m", message], LOCAL_TIMEOUT)
    if committed.returncode != 0:
        raise GitVaultError(f"{CATEGORY_NOT_A_REPOSITORY}: cannot create the vault commit")

    remote, _, remote_branch = upstream.partition("/")
    pushed = _run_git(
        path, ["push", "--quiet", remote, f"{branch}:{remote_branch}"], NETWORK_TIMEOUT
    )
    if pushed.returncode != 0:
        raise GitVaultError(
            f"{_classify_remote_failure(pushed.stderr, CATEGORY_PUSH)}: "
            f"could not push {branch!r} to its configured upstream"
        )
    return True


def sync(
    repo_root: Path | str,
    clone: Path | str,
    project_id: str,
    operation,
    message: str,
    finalize: list | None = None,
) -> str:
    """Run one vault-mutating operation against a Git clone, end to end.

    Order matters throughout: preflight, fast-forward, then the #78 core work
    (which performs its own validation, privacy gate and content→state→marker
    publication), then exactly one commit, then the push — and only then the
    local baseline.

    ``finalize`` runs only once the push has succeeded, and deliberately outside
    the rollback: it is for work that must not exist if the vault write did not
    land — resolve's local materialization (#89), whose early application would
    leave the losing local bytes in neither place after a failed push. A failure
    there is not a reason to undo a push that already succeeded, and the local
    write rolls itself back, so the unadvanced digest is the only trace.

    ``before`` is the commit the clone sits on once it is current with its
    upstream, and *both* the core work and the commit/push run under the same
    rollback. A failure anywhere in that span returns the clone to ``before``
    and leaves the local digest untouched: the core rolls back its own writes,
    but this is the backstop for the case where it cannot, so a failed sync
    never leaves a dirty clone that the next run's preflight would refuse for a
    reason the operator did not cause.
    """
    # Before the clone is touched at all: a checkout linked to another project
    # must not cause even a fetch, let alone a fast-forward (#87).
    vault.require_project_id(Path(repo_root), project_id)

    clone_path = Path(clone)
    branch, upstream = preflight(clone_path)
    fetch_and_fast_forward(clone_path, branch, upstream)
    before = head_commit(clone_path)

    created = vault.Creations()
    try:
        digest = operation(clone_path, created)
        stage_commit_push(clone_path, project_id, branch, upstream, message)
    except Exception as exc:
        # Two halves, and neither covers the other: the reset restores tracked
        # bytes and discards our commit, and `created.undo()` removes artifacts
        # that never reached a commit — which `git reset --hard` leaves in place
        # precisely because they are untracked.
        restored = restore(clone_path, before)
        created.undo()
        # If the rollback itself fails the operator must hear about it here: the
        # only other signal is the *next* run's preflight refusing a clone they
        # did not dirty.
        if restored.returncode != 0:
            raise GitVaultError(
                f"{exc}; additionally, the vault clone could not be returned to "
                f"{before} — reset it yourself before syncing again"
            ) from exc
        raise
    for step in finalize or ():
        step()
    vault.write_sync_state(Path(repo_root), project_id, digest)
    return digest


def push(repo_root: Path | str, clone: Path | str, project_id: str, **kwargs) -> str:
    def operation(clone_path: Path, created: "vault.Creations") -> str:
        return vault.export_project(
            repo_root, clone_path, project_id, write_local_state=False,
            created=created, **kwargs
        )

    return sync(repo_root, clone, project_id, operation, f"session-glue: sync {project_id}")


def resolve(repo_root: Path | str, clone: Path | str, project_id: str, head_session: str,
            **kwargs) -> str:
    deferred: list = []

    def operation(clone_path: Path, created: "vault.Creations") -> str:
        return vault.resolve_project(
            repo_root, clone_path, project_id, head_session, write_local_state=False,
            created=created, defer_local=deferred, **kwargs
        )

    return sync(
        repo_root, clone, project_id, operation,
        f"session-glue: resolve {project_id}", finalize=deferred,
    )


def pull(repo_root: Path | str, clone: Path | str, project_id: str) -> str:
    """Import from a Git vault: fast-forward the clone, then import locally.

    Read-only with respect to the remote, so it makes no commit and no push, and
    the local baseline is written by the core in the ordinary way.
    """
    vault.require_project_id(Path(repo_root), project_id)
    clone_path = Path(clone)
    branch, upstream = preflight(clone_path)
    fetch_and_fast_forward(clone_path, branch, upstream)
    return vault.import_project(repo_root, clone_path, project_id)
