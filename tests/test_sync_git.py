"""Tests for the Git working-tree vault transport (issue #80).

Everything here runs against **temporary local bare remotes**. No network remote
is contacted, and `gh` is made to fail if anything reaches for it, so AC2 is
proven by the harness rather than asserted in prose.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from session_glue import cli, vault, vaultgit

from test_vault import _write_history

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True, check=False).returncode != 0,
    reason="git is not available",
)


@pytest.fixture(autouse=True)
def _forbid_gh(monkeypatch, tmp_path):
    """AC2: `gh` must never be invoked — make it fail loudly if it is.

    A shim directory is prepended to PATH containing a `gh` that exits non-zero
    with a distinctive message, so a call would surface as a test failure rather
    than silently succeeding on a machine where `gh` happens to be installed.
    """
    import os

    shim = tmp_path / "shim"
    shim.mkdir()
    gh = shim / "gh"
    gh.write_text("#!/bin/sh\necho 'gh must never be invoked' >&2\nexit 97\n", encoding="utf-8")
    gh.chmod(0o755)
    # Prepend the shim, keeping the real PATH so `git` itself stays reachable.
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")
    # Never let Git prompt for credentials: a hung prompt would masquerade as a
    # timeout and make the auth-classification test meaningless.
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture()
def bare_remote(tmp_path):
    remote = tmp_path / "vault.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    return remote


def _clone(bare_remote: Path, destination: Path) -> Path:
    subprocess.run(
        ["git", "clone", "--quiet", str(bare_remote), str(destination)], check=True
    )
    _git(destination, "config", "user.email", "dev@example.invalid")
    _git(destination, "config", "user.name", "Test Dev")
    # A freshly initialised remote has no branch until the first commit; seed one
    # so the branch exists with an upstream, as a real vault clone would. A clone
    # of an already-populated remote needs no seeding.
    has_commits = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--verify", "HEAD"],
        capture_output=True, check=False,
    ).returncode == 0
    if not has_commits:
        (destination / "README.md").write_text("vault\n", encoding="utf-8")
        _git(destination, "add", "README.md")
        _git(destination, "commit", "--quiet", "-m", "seed")
        _git(destination, "push", "--quiet", "-u", "origin", "HEAD")
    return destination


@pytest.fixture()
def clone(tmp_path, bare_remote):
    return _clone(bare_remote, tmp_path / "clone")


@pytest.fixture()
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    _write_history(root)
    return root


def _run(*argv: str) -> int:
    return cli.main(list(argv))


# --------------------------------------------------------------------------- #
# AC1 — round trip over a local bare remote
# --------------------------------------------------------------------------- #


def test_push_pull_round_trip_with_one_commit_per_operation(tmp_path, checkout, clone,
                                                            bare_remote):
    before = len(_git(clone, "rev-list", "--count", "HEAD").stdout.split())
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    ) == 0

    # Exactly one commit was produced, and it reached the remote.
    log = _git(clone, "log", "--oneline").stdout.strip().splitlines()
    assert len(log) == 2  # seed + ours
    assert "session-glue: sync alpha" in log[0]
    remote_log = subprocess.run(
        ["git", "-C", str(bare_remote), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "session-glue: sync alpha" in remote_log
    assert before == 1

    # Device B clones the same remote and pulls.
    other_clone = _clone(bare_remote, tmp_path / "clone-b")
    other = tmp_path / "device-b"
    other.mkdir()
    _write_history(other, session_id="2026-08-27-0900-local-only")
    assert _run(
        "sync", "pull", "--repo-root", str(other), "--project-id", "alpha",
        "--vault-git-dir", str(other_clone),
    ) == 0

    names = {p.name for p in (other / ".agent-history" / "sessions").glob("*.md")}
    assert {"2026-08-27-0900-local-only.md", "2026-08-28-1200-alpha.md"} <= names
    assert _run("validate", "--repo-root", str(other), "--sessions") == 0


def test_only_project_paths_are_staged(checkout, clone):
    """A pre-existing unrelated change must be neither staged nor disturbed."""
    (clone / "unrelated.md").write_text("someone else's file\n", encoding="utf-8")
    _git(clone, "add", "unrelated.md")
    _git(clone, "commit", "--quiet", "-m", "unrelated")

    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    ) == 0
    changed = _git(clone, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert changed and all(name.startswith("projects/alpha/") for name in changed)


def test_untracked_files_neither_block_nor_stage(checkout, clone):
    (clone / ".DS_Store").write_text("junk\n", encoding="utf-8")
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    ) == 0
    changed = _git(clone, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert ".DS_Store" not in changed
    assert (clone / ".DS_Store").exists()


def test_no_op_repeated_sync_is_clean(checkout, clone):
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    ) == 0
    commits = len(_git(clone, "log", "--oneline").stdout.strip().splitlines())
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    ) == 0
    # Nothing changed, so nothing new was committed.
    assert len(_git(clone, "log", "--oneline").stdout.strip().splitlines()) == commits


# --------------------------------------------------------------------------- #
# AC3 — preflight refusals, each before stage/commit/push
# --------------------------------------------------------------------------- #


def test_detached_head_is_refused(checkout, clone, capsys):
    _git(clone, "checkout", "--quiet", "--detach", "HEAD")
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    )
    assert code == cli.EXIT_ERROR
    assert vaultgit.CATEGORY_DETACHED in capsys.readouterr().err
    assert not (clone / "projects").exists()


def test_missing_upstream_is_refused(tmp_path, checkout, clone, capsys):
    _git(clone, "checkout", "--quiet", "-b", "no-upstream")
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    )
    assert code == cli.EXIT_ERROR
    assert vaultgit.CATEGORY_MISSING_UPSTREAM in capsys.readouterr().err
    assert not (clone / "projects").exists()


def test_tracked_dirtiness_is_refused(checkout, clone, capsys):
    (clone / "README.md").write_text("edited\n", encoding="utf-8")
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    )
    assert code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert vaultgit.CATEGORY_DIRTY in err
    assert "README.md" in err  # names the offending path so it is actionable
    assert not (clone / "projects").exists()


def test_a_plain_directory_is_not_a_working_tree(tmp_path, checkout, capsys):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(plain),
    )
    assert code == cli.EXIT_ERROR
    assert vaultgit.CATEGORY_NOT_A_REPOSITORY in capsys.readouterr().err


def test_absent_clone_path_is_refused(tmp_path, checkout, capsys):
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(tmp_path / "nope"),
    )
    assert code == cli.EXIT_ERROR
    assert "never clones" in capsys.readouterr().err


def test_transports_are_mutually_exclusive(tmp_path, checkout, clone):
    with pytest.raises(SystemExit) as excinfo:
        _run(
            "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
            "--vault-dir", str(tmp_path), "--vault-git-dir", str(clone),
        )
    assert excinfo.value.code != 0


# --------------------------------------------------------------------------- #
# AC4 — failure leaves the clone, the local history and the digest untouched
# --------------------------------------------------------------------------- #


def test_failed_push_restores_the_clone_and_preserves_the_digest(checkout, clone, bare_remote,
                                                                 capsys):
    """The two-phase boundary: a local commit is not a vault change that succeeded.

    The remote refuses via a `pre-receive` hook — how a real push is rejected by
    branch protection. Note that a remote merely moving *ahead* is not a failure
    here: this transport fetches and fast-forwards first, so that case pushes
    cleanly, which is why the rejection has to come from the remote itself.
    """
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    ) == 0
    baseline = vault.sync_state_path(checkout).read_bytes()
    before_head = _git(clone, "rev-parse", "HEAD").stdout.strip()

    hooks = bare_remote / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'refused by policy' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    _write_history(checkout, session_id="2026-08-29-1000-second")
    capsys.readouterr()
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    )
    assert code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert vaultgit.CATEGORY_PUSH in err or vaultgit.CATEGORY_NON_FAST_FORWARD in err

    # The clone is back where it was: our commit is gone, the tree is clean, and
    # the local baseline never advanced past what the remote actually holds.
    assert _git(clone, "rev-parse", "HEAD").stdout.strip() == before_head
    assert _git(clone, "status", "--porcelain", "--untracked-files=no").stdout == ""
    assert vault.sync_state_path(checkout).read_bytes() == baseline


def test_privacy_block_prevents_any_commit(tmp_path, clone, capsys):
    from test_vault import BODY

    root = tmp_path / "repo"
    root.mkdir()
    secret = "ghp_" + "e" * 20
    _write_history(root, body=BODY + f"\nToken {secret}\n")
    before_head = _git(clone, "rev-parse", "HEAD").stdout

    code = _run(
        "sync", "push", "--repo-root", str(root), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    )
    assert code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert secret not in err
    assert _git(clone, "rev-parse", "HEAD").stdout == before_head
    assert vault.read_sync_state(root) is None


# --------------------------------------------------------------------------- #
# AC2 — redaction and subprocess discipline
# --------------------------------------------------------------------------- #


def test_errors_name_a_category_and_never_leak_the_remote_url(tmp_path, checkout, clone,
                                                             capsys):
    """A refused remote must produce our category, never Git's text."""
    secret_path = tmp_path / "private-vault-hunter2.git"  # never created
    _git(clone, "remote", "set-url", "origin", str(secret_path))

    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    )
    assert code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "hunter2" not in err
    assert "private-vault" not in err
    assert str(secret_path) not in err
    assert any(
        category in err
        for category in (
            vaultgit.CATEGORY_AUTH, vaultgit.CATEGORY_FETCH,
            vaultgit.CATEGORY_TIMEOUT, vaultgit.CATEGORY_NON_FAST_FORWARD,
        )
    ), err


def test_every_git_call_has_explicit_args_and_a_bounded_timeout():
    """AC2's subprocess discipline, asserted against the source rather than behaviour."""
    source = Path(vaultgit.__file__).read_text(encoding="utf-8")
    assert "timeout=timeout" in source
    assert source.count("subprocess.run(") == 1  # one funnel, so the rule cannot be bypassed
    assert vaultgit.NETWORK_TIMEOUT == 60
    assert vaultgit.LOCAL_TIMEOUT < vaultgit.NETWORK_TIMEOUT


def test_gh_is_never_invoked(checkout, clone):
    """The shim on PATH exits 97; a green push proves nothing reached for it."""
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    ) == 0
    # The proof is the shim: it exits 97 and would fail any call, so a green
    # push means nothing reached for `gh`.


# --------------------------------------------------------------------------- #
# AC1 / AC5 — resolve over Git
# --------------------------------------------------------------------------- #


def test_resolve_over_git_commits_once_and_retains_the_candidate(checkout, clone, bare_remote):
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone),
    ) == 0

    archive = next((clone / "projects" / "alpha" / "sessions").glob("*.md"))
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "Diverged."),
        encoding="utf-8",
    )
    _git(clone, "add", "--", "projects/alpha")
    _git(clone, "commit", "--quiet", "-m", "diverge in the vault")
    _git(clone, "push", "--quiet")

    commits = len(_git(clone, "log", "--oneline").stdout.strip().splitlines())
    session_id = "2026-08-28-1200-alpha"
    assert _run(
        "sync", "resolve", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-git-dir", str(clone), "--head-session", session_id,
        "--archive", f"{session_id}=local",
    ) == 0

    assert len(_git(clone, "log", "--oneline").stdout.strip().splitlines()) == commits + 1
    records = vault.read_manifest(clone / "projects" / "alpha")
    assert {r["side"] for r in records} == {"local", "vault"}
