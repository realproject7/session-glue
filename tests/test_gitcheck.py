"""Tests for the opt-in git drift check (issue #39).

Drift is advisory: it is a warning for both ``status`` and ``validate`` and must
never flip an exit code. The default (no ``--git``) code path must run no
subprocess at all — asserted by monkeypatching ``subprocess.run`` to blow up.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from session_glue import gitcheck
from session_glue.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"
VALID = (FIXTURES / "valid.md").read_text(encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")


def _actual(repo: Path) -> tuple[str, str]:
    branch = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    short = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    return branch, short


def _set_field(text: str, key: str, value: str) -> str:
    return re.sub(rf"(?m)^{key}: .*$", f"{key}: {value}", text)


def _create(repo: Path, text: str = VALID) -> int:
    src = repo / "in.md"
    src.write_text(text, encoding="utf-8")
    return main(["create", "--input", str(src), "--repo-root", str(repo)])


# --------------------------------------------------------------------------- #
# Unit: check_git_drift
# --------------------------------------------------------------------------- #


def test_drift_when_recorded_differs_from_repo(tmp_path):
    _init_repo(tmp_path)
    messages = gitcheck.check_git_drift(tmp_path, "feature-x", "deadbee")
    assert any(m.startswith("drift:") for m in messages)


def test_no_drift_when_recorded_matches_repo(tmp_path):
    _init_repo(tmp_path)
    branch, short = _actual(tmp_path)
    assert gitcheck.check_git_drift(tmp_path, branch, short) == []


def test_non_git_directory_degrades_gracefully(tmp_path):
    # tmp_path is not a git repository -> single informative line, no exception.
    assert gitcheck.check_git_drift(tmp_path, "main", "abc1234") == [gitcheck.GIT_UNAVAILABLE]


def test_unknown_recorded_values_are_skipped_not_drift(tmp_path):
    _init_repo(tmp_path)
    messages = gitcheck.check_git_drift(tmp_path, "unknown", "unknown")
    assert any("skipping branch check" in m for m in messages)
    assert any("skipping commit check" in m for m in messages)
    assert not any(m.startswith("drift:") for m in messages)


def test_short_hash_compared_on_recorded_length(tmp_path):
    _init_repo(tmp_path)
    branch, short = _actual(tmp_path)
    # A correct 4-char prefix of the real hash must NOT be reported as drift.
    assert gitcheck.check_git_drift(tmp_path, branch, short[:4]) == []


# --------------------------------------------------------------------------- #
# CLI: status --git / validate --git (advisory, warning-only)
# --------------------------------------------------------------------------- #


def test_status_git_reports_drift(tmp_path, capsys):
    _init_repo(tmp_path)
    _create(tmp_path)  # records main@abc1234, which won't match the real HEAD
    capsys.readouterr()
    rc = main(["status", "--repo-root", str(tmp_path), "--git"])
    assert rc == 0  # drift never changes the exit code
    assert "drift:" in capsys.readouterr().out


def test_validate_git_reports_drift_without_failing(tmp_path, capsys):
    _init_repo(tmp_path)
    _create(tmp_path)
    capsys.readouterr()
    rc = main(["validate", "--repo-root", str(tmp_path), "--git"])
    assert rc == 0  # a valid history with drift still validates OK
    assert "drift:" in capsys.readouterr().err


def test_validate_git_still_fails_on_real_problem(tmp_path, capsys):
    _init_repo(tmp_path)
    _create(tmp_path)
    (tmp_path / ".agent-history" / "RESUME_PROMPT.txt").unlink()
    capsys.readouterr()
    rc = main(["validate", "--repo-root", str(tmp_path), "--git"])
    assert rc == 1  # the real problem still fails validation
    err = capsys.readouterr().err
    assert "drift:" in err  # drift still surfaced
    assert "RESUME_PROMPT.txt" in err


def test_status_git_no_drift_when_recorded_matches(tmp_path, capsys):
    _init_repo(tmp_path)
    branch, short = _actual(tmp_path)
    text = _set_field(_set_field(VALID, "current_branch", branch), "head_commit", short)
    _create(tmp_path, text)
    capsys.readouterr()
    main(["status", "--repo-root", str(tmp_path), "--git"])
    assert "drift:" not in capsys.readouterr().out


def test_status_git_non_git_dir_degrades(tmp_path, capsys):
    _create(tmp_path)  # tmp_path is NOT a git repo
    capsys.readouterr()
    rc = main(["status", "--repo-root", str(tmp_path), "--git"])
    assert rc == 0
    assert "git unavailable or not a repository" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# CRITICAL invariant: default (no --git) paths run no subprocess.
# --------------------------------------------------------------------------- #


def test_default_status_and_validate_never_call_subprocess(tmp_path, monkeypatch):
    _create(tmp_path)  # no git repo needed

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called without --git")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert main(["status", "--repo-root", str(tmp_path)]) == 0
    assert main(["validate", "--repo-root", str(tmp_path)]) == 0


def test_resume_prompt_and_create_never_call_subprocess(tmp_path, monkeypatch):
    src = tmp_path / "in.md"
    src.write_text(VALID, encoding="utf-8")

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called on default paths")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert main(["create", "--input", str(src), "--repo-root", str(tmp_path)]) == 0
    assert main(["resume-prompt", "--repo-root", str(tmp_path)]) == 0
