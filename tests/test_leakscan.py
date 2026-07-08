"""Tests for advisory leak-scan warnings (issue #38).

Warnings must be loud but fail-open: they never block a ``glue create`` write
and never flip the ``glue validate`` exit code by themselves. All fixtures use
OBVIOUSLY fake tokens (never realistic live credentials).
"""

from __future__ import annotations

from pathlib import Path

from session_glue import leakscan
from session_glue.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"
VALID = (FIXTURES / "valid.md").read_text(encoding="utf-8")

# Obviously fake credentials — shape matches, value is plainly not real.
FAKE_GH_TOKEN = "ghp_" + "x" * 36
FAKE_PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----"
HOME_PATH = "/home/alice/project/notes.py"


def _create(repo: Path, text: str) -> int:
    src = repo / "in.md"
    src.write_text(text, encoding="utf-8")
    return main(["create", "--input", str(src), "--repo-root", str(repo)])


def _with_body(extra: str) -> str:
    """Append content to the handoff body (after the frontmatter)."""
    return VALID + "\n\n" + extra + "\n"


# --------------------------------------------------------------------------- #
# Unit: scanners
# --------------------------------------------------------------------------- #


def test_scan_secrets_detects_and_labels_by_type():
    assert "GitHub token (ghp_/gho_)" in leakscan.scan_secrets(f"token: {FAKE_GH_TOKEN}")
    assert any("private key" in s for s in leakscan.scan_secrets(FAKE_PRIVATE_KEY))
    assert leakscan.scan_secrets("nothing sensitive in this line") == []


def test_scan_secrets_does_not_echo_the_secret():
    # The warning names the type only; it must not contain the raw token.
    labels = leakscan.scan_secrets(f"token: {FAKE_GH_TOKEN}")
    assert all(FAKE_GH_TOKEN not in label for label in labels)


def test_scan_secrets_avoids_obvious_false_positives():
    # 'sk-' inside an ordinary word must not trip the OpenAI key pattern.
    assert leakscan.scan_secrets("this is a task-force sync meeting") == []


def test_find_personal_paths():
    paths = leakscan.find_personal_paths("see /home/bob/x.py and /Users/carol/y.py")
    assert "/home/bob/" in paths
    assert "/Users/carol/" in paths
    assert leakscan.find_personal_paths("/path/to/project only") == []


def test_agent_history_ignored_variants(tmp_path):
    assert leakscan.agent_history_ignored(tmp_path) is False  # no .gitignore at all
    for line in (".agent-history", ".agent-history/", "/.agent-history"):
        (tmp_path / ".gitignore").write_text(f"*.log\n{line}\n", encoding="utf-8")
        assert leakscan.agent_history_ignored(tmp_path) is True, line
    (tmp_path / ".gitignore").write_text("*.log\n# .agent-history commented\n", encoding="utf-8")
    assert leakscan.agent_history_ignored(tmp_path) is False


def test_scan_handoff_gates_personal_path_on_gitignore(tmp_path):
    text = f"context file at {HOME_PATH}"
    # Not gitignored -> personal-path warning present.
    assert any("personal absolute path" in w for w in leakscan.scan_handoff(text, tmp_path))
    # Gitignored -> no personal-path warning (the path is never committed).
    (tmp_path / ".gitignore").write_text(".agent-history/\n", encoding="utf-8")
    assert leakscan.scan_handoff(text, tmp_path) == []


def test_scan_handoff_secrets_warn_regardless_of_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text(".agent-history/\n", encoding="utf-8")
    warnings = leakscan.scan_handoff(f"key {FAKE_GH_TOKEN}", tmp_path)
    assert any("possible secret" in w for w in warnings)


# --------------------------------------------------------------------------- #
# CLI: glue create (warn-but-write, fail-open)
# --------------------------------------------------------------------------- #


def test_create_warns_on_secret_but_still_writes(tmp_path, capsys):
    rc = _create(tmp_path, _with_body(f"Debug leftover token {FAKE_GH_TOKEN}"))
    assert rc == 0  # fail-open: the freeze still succeeds
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "GitHub token" in err
    assert "leak warning(s) — review before committing" in err
    # The handoff was written despite the warning.
    assert (tmp_path / ".agent-history" / "LATEST.md").is_file()


def test_create_warns_on_private_key_block(tmp_path, capsys):
    rc = _create(tmp_path, _with_body(FAKE_PRIVATE_KEY))
    assert rc == 0
    assert "private key block" in capsys.readouterr().err


def test_create_home_path_without_gitignore_warns(tmp_path, capsys):
    rc = _create(tmp_path, _with_body(f"Working file: {HOME_PATH}"))
    assert rc == 0
    err = capsys.readouterr().err
    assert "personal absolute path" in err
    assert "/home/alice/" in err


def test_create_home_path_with_gitignore_no_path_warning(tmp_path, capsys):
    (tmp_path / ".gitignore").write_text(".agent-history/\n", encoding="utf-8")
    rc = _create(tmp_path, _with_body(f"Working file: {HOME_PATH}"))
    assert rc == 0
    assert "personal absolute path" not in capsys.readouterr().err


def test_create_clean_handoff_emits_zero_warnings(tmp_path, capsys):
    rc = _create(tmp_path, VALID)
    assert rc == 0
    err = capsys.readouterr().err
    assert "WARNING" not in err
    assert "leak warning" not in err


# --------------------------------------------------------------------------- #
# CLI: glue validate (warn without flipping the exit code)
# --------------------------------------------------------------------------- #


def test_validate_reports_warning_without_failing(tmp_path, capsys):
    assert _create(tmp_path, _with_body(f"token {FAKE_GH_TOKEN}")) == 0
    capsys.readouterr()  # discard create output
    rc = main(["validate", "--repo-root", str(tmp_path)])
    assert rc == 0  # a leak warning alone does NOT fail validation
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "GitHub token" in err


def test_validate_still_fails_on_real_problem_and_still_warns(tmp_path, capsys):
    assert _create(tmp_path, _with_body(f"token {FAKE_GH_TOKEN}")) == 0
    # Introduce a genuine validation problem alongside the leak.
    (tmp_path / ".agent-history" / "RESUME_PROMPT.txt").unlink()
    capsys.readouterr()
    rc = main(["validate", "--repo-root", str(tmp_path)])
    assert rc == 1  # the real problem still fails validation
    err = capsys.readouterr().err
    assert "WARNING" in err  # warning is still surfaced
    assert "RESUME_PROMPT.txt" in err  # and the real problem is reported
