"""Tests for the Session Glue CLI scaffold.

These tests are deterministic and require no network access, git repository,
or user home access.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from session_glue import __version__, leakscan
from session_glue.cli import build_parser, main
from session_glue.schema import Handoff

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"
VALID = (FIXTURES / "valid.md").read_text(encoding="utf-8")
FIRST_ACTION = Handoff.from_text(VALID).next_todo_items[0]
# A first todo that trips the resume-mechanic lint by default.
FLAGGED_ACTION = "Paste the prompt into a new session"


def _write_handoff(tmp_path: Path, text: str) -> Path:
    src = tmp_path / "handoff-in.md"
    src.write_text(text, encoding="utf-8")
    return src


def test_version_flag_reports_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert "session-glue" in out


def test_help_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "Session Glue" in out


def test_no_args_prints_help_and_exits_zero(capsys):
    code = main([])
    assert code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


@pytest.mark.parametrize(
    "command", ["create", "validate", "status", "resume-prompt", "close", "install", "skill"]
)
def test_subcommands_are_registered(command, capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([command, "--help"])
    assert exc_info.value.code == 0
    assert command in capsys.readouterr().out


def test_parser_prog_name():
    parser = build_parser()
    assert parser.prog == "glue"


def test_close_requires_status_flag():
    # --status is required; argparse exits 2 before any repo is touched.
    with pytest.raises(SystemExit) as exc_info:
        main(["close", "--repo-root", "."])
    assert exc_info.value.code == 2


def test_close_rejects_invalid_status():
    # Only DONE/BLOCKED/ABANDONED are accepted (argparse choices).
    with pytest.raises(SystemExit) as exc_info:
        main(["close", "--repo-root", ".", "--status", "MAYBE"])
    assert exc_info.value.code == 2


# --------------------------------------------------------------------------- #
# Issue #33: --allow-flagged-todo escape hatch on `glue create`.
# --------------------------------------------------------------------------- #


def test_create_blocks_flagged_first_todo_without_flag(tmp_path, capsys):
    src = _write_handoff(tmp_path, VALID.replace(FIRST_ACTION, FLAGGED_ACTION))
    code = main(["create", "--input", str(src), "--repo-root", str(tmp_path)])
    assert code == 2
    err = capsys.readouterr().err
    assert "resume mechanic" in err
    # The freeze was blocked: no history was written.
    assert not (tmp_path / ".agent-history").exists()


def test_create_allow_flagged_todo_warns_and_proceeds(tmp_path, capsys):
    src = _write_handoff(tmp_path, VALID.replace(FIRST_ACTION, FLAGGED_ACTION))
    code = main(
        [
            "create",
            "--input",
            str(src),
            "--repo-root",
            str(tmp_path),
            "--allow-flagged-todo",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    # Loud stderr warning, not a silent pass.
    assert "WARNING" in captured.err
    assert "resume mechanic" in captured.err
    assert "--allow-flagged-todo" in captured.err
    # And the freeze actually happened.
    hist = tmp_path / ".agent-history"
    assert (hist / "LATEST.md").is_file()
    assert (hist / "RESUME_PROMPT.txt").is_file()


def test_allow_flagged_todo_does_not_bypass_other_errors(tmp_path, capsys):
    # A genuinely malformed handoff (missing required field) must still block
    # even with the escape hatch — the flag only downgrades the mechanic lint.
    broken = VALID.replace(FIRST_ACTION, FLAGGED_ACTION).replace(
        "head_commit:", "not_head_commit:"
    )
    src = _write_handoff(tmp_path, broken)
    code = main(
        [
            "create",
            "--input",
            str(src),
            "--repo-root",
            str(tmp_path),
            "--allow-flagged-todo",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "head_commit" in err
    assert not (tmp_path / ".agent-history").exists()


def test_validate_has_no_allow_flagged_todo_flag(capsys):
    # The override lives ONLY on `create`; `validate` must reject the flag.
    with pytest.raises(SystemExit) as exc_info:
        main(["validate", "--allow-flagged-todo", "--repo-root", "."])
    assert exc_info.value.code != 0
    assert "allow-flagged-todo" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Issue #40: TTY stdin hint + scalar todo enforcement at the CLI.
# --------------------------------------------------------------------------- #


class _TTYStdin(io.StringIO):
    """A stdin stand-in that reports it is an interactive terminal."""

    def isatty(self) -> bool:
        return True


def test_create_hints_when_stdin_is_a_tty(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", _TTYStdin(VALID))
    rc = main(["create", "--repo-root", str(tmp_path)])  # no --input -> stdin
    assert rc == 0
    assert "reading handoff from stdin" in capsys.readouterr().err
    assert (tmp_path / ".agent-history" / "LATEST.md").is_file()


def test_create_does_not_hint_for_piped_stdin(tmp_path, capsys, monkeypatch):
    # io.StringIO.isatty() is False -> piped input; behavior is unchanged (no hint).
    monkeypatch.setattr("sys.stdin", io.StringIO(VALID))
    rc = main(["create", "--repo-root", str(tmp_path)])
    assert rc == 0
    assert "reading handoff from stdin" not in capsys.readouterr().err


def test_create_does_not_hint_when_input_path_given(tmp_path, capsys, monkeypatch):
    # Even at a TTY, an explicit --input path must not print the stdin hint.
    monkeypatch.setattr("sys.stdin", _TTYStdin(""))
    src = _write_handoff(tmp_path, VALID)
    rc = main(["create", "--input", str(src), "--repo-root", str(tmp_path)])
    assert rc == 0
    assert "reading handoff from stdin" not in capsys.readouterr().err


def test_create_rejects_mapping_todo_entry(tmp_path, capsys):
    bad = VALID.replace(
        '  - "Add polling lifecycle with cleanup"',
        "  - task: Add polling lifecycle with cleanup",
    )
    src = _write_handoff(tmp_path, bad)
    rc = main(["create", "--input", str(src), "--repo-root", str(tmp_path)])
    assert rc == 2
    assert "next_todo_items[0] must be a scalar" in capsys.readouterr().err
    assert not (tmp_path / ".agent-history").exists()


# --------------------------------------------------------------------------- #
# Freeze-overuse guard (issue #46)
# --------------------------------------------------------------------------- #

# valid.md's frozen timestamp and session id, for building follow-up freezes.
_BASE_GENERATED_AT = "2026-06-30T15:30:00+09:00"
_BASE_SESSION_ID = "2026-06-30-1530-chart-polling"


def _create_cli(tmp_path: Path, text: str) -> int:
    src = _write_handoff(tmp_path, text)
    return main(["create", "--input", str(src), "--repo-root", str(tmp_path)])


def _refreeze(session_id: str, generated_at: str) -> str:
    """A follow-up handoff derived from VALID with a new id + generated_at."""
    return VALID.replace(_BASE_SESSION_ID, session_id).replace(
        _BASE_GENERATED_AT, generated_at
    )


def test_overuse_warns_but_writes_when_refrozen_within_30min(tmp_path, capsys):
    assert _create_cli(tmp_path, VALID) == 0  # first freeze at 15:30
    capsys.readouterr()  # drop first-freeze output
    second = _refreeze("2026-06-30-1540-second", "2026-06-30T15:40:00+09:00")  # +10 min
    assert _create_cli(tmp_path, second) == 0  # warns but still writes (rc 0)
    err = capsys.readouterr().err
    assert "you glued 10 minutes ago" in err
    assert "bloated" in err
    assert (tmp_path / ".agent-history" / "LATEST.md").is_file()


def test_no_overuse_warning_when_more_than_30min_apart(tmp_path, capsys):
    assert _create_cli(tmp_path, VALID) == 0  # 15:30
    capsys.readouterr()
    later = _refreeze("2026-06-30-1630-second", "2026-06-30T16:30:00+09:00")  # +60 min
    assert _create_cli(tmp_path, later) == 0
    assert "you glued" not in capsys.readouterr().err


def test_no_overuse_warning_when_prior_generated_at_unparseable(tmp_path, capsys):
    assert _create_cli(tmp_path, VALID) == 0
    # Corrupt the prior LATEST.md generated_at so it cannot be parsed as ISO-8601.
    latest = tmp_path / ".agent-history" / "LATEST.md"
    latest.write_text(
        latest.read_text(encoding="utf-8").replace(_BASE_GENERATED_AT, "not-a-timestamp"),
        encoding="utf-8",
    )
    capsys.readouterr()
    second = _refreeze("2026-06-30-1535-second", "2026-06-30T15:35:00+09:00")
    assert _create_cli(tmp_path, second) == 0  # fail-open: no crash, still writes
    assert "you glued" not in capsys.readouterr().err


def test_no_overuse_warning_on_first_ever_freeze(tmp_path, capsys):
    # No prior LATEST.md exists, so the guard has nothing to compare against.
    assert _create_cli(tmp_path, VALID) == 0
    assert "you glued" not in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Zero-pollution default: auto-register .agent-history/ in .git/info/exclude
# (issue #66)
# --------------------------------------------------------------------------- #

_REGISTERED_LINE = (
    "registered .agent-history/ in .git/info/exclude (personal ignore — not committed)"
)
# A default-style git exclude file: comment-only, like a fresh `git init`.
_GIT_EXCLUDE_HEADER = (
    "# git ls-files --others --exclude-from=.git/info/exclude\n"
    "# Lines that start with '#' are comments.\n"
)


def _init_git_repo(repo: Path) -> Path:
    """Create a minimal ``.git/info/exclude`` (no real git) and return its path."""
    info = repo / ".git" / "info"
    info.mkdir(parents=True)
    exclude = info / "exclude"
    exclude.write_text(_GIT_EXCLUDE_HEADER, encoding="utf-8")
    return exclude


def test_create_registers_agent_history_in_git_exclude(tmp_path, capsys):
    exclude = _init_git_repo(tmp_path)
    assert _create_cli(tmp_path, VALID) == 0
    assert _REGISTERED_LINE in capsys.readouterr().out
    assert ".agent-history/" in exclude.read_text(encoding="utf-8").splitlines()
    # .gitignore is never touched — the write is personal-only.
    assert not (tmp_path / ".gitignore").exists()
    # Now recognized as ignored, so leakscan stops warning about it.
    assert leakscan.agent_history_ignored(tmp_path) is True


def test_second_create_does_not_duplicate_exclude_line(tmp_path, capsys):
    exclude = _init_git_repo(tmp_path)
    assert _create_cli(tmp_path, VALID) == 0
    capsys.readouterr()
    assert _create_cli(tmp_path, VALID) == 0
    # Nothing to register the second time — already covered.
    assert _REGISTERED_LINE not in capsys.readouterr().out
    assert exclude.read_text(encoding="utf-8").count(".agent-history/") == 1


def test_create_skips_exclude_when_gitignore_already_covers(tmp_path, capsys):
    exclude = _init_git_repo(tmp_path)
    original = exclude.read_text(encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".agent-history/\n", encoding="utf-8")
    assert _create_cli(tmp_path, VALID) == 0
    assert _REGISTERED_LINE not in capsys.readouterr().out
    assert exclude.read_text(encoding="utf-8") == original  # exclude untouched


def test_create_no_exclude_flag_skips_registration(tmp_path, capsys):
    exclude = _init_git_repo(tmp_path)
    original = exclude.read_text(encoding="utf-8")
    src = _write_handoff(tmp_path, VALID)
    rc = main(["create", "--input", str(src), "--repo-root", str(tmp_path), "--no-exclude"])
    assert rc == 0
    assert _REGISTERED_LINE not in capsys.readouterr().out
    assert exclude.read_text(encoding="utf-8") == original
    assert leakscan.agent_history_ignored(tmp_path) is False


def test_create_non_git_dir_skips_registration_silently(tmp_path, capsys):
    # No .git/ at all: registration is a silent no-op and the write still succeeds.
    assert _create_cli(tmp_path, VALID) == 0
    assert _REGISTERED_LINE not in capsys.readouterr().out
    assert not (tmp_path / ".git").exists()
    assert (tmp_path / ".agent-history" / "LATEST.md").is_file()


def test_create_git_file_not_dir_skips_registration(tmp_path, capsys):
    # A `.git` *file* (worktree/submodule pointer) is out of scope; leave it be.
    gitfile = tmp_path / ".git"
    gitfile.write_text("gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8")
    assert _create_cli(tmp_path, VALID) == 0
    assert _REGISTERED_LINE not in capsys.readouterr().out
    assert gitfile.read_text(encoding="utf-8") == "gitdir: /elsewhere/.git/worktrees/x\n"


def test_create_unwritable_exclude_skips_silently(tmp_path, capsys):
    exclude = _init_git_repo(tmp_path)
    original = exclude.read_text(encoding="utf-8")
    exclude.chmod(0o444)
    # Only meaningful where the OS actually blocks the append (skip e.g. as root).
    try:
        with exclude.open("a", encoding="utf-8"):
            pass
    except OSError:
        pass
    else:
        exclude.chmod(0o644)
        pytest.skip("filesystem does not enforce read-only append here")
    try:
        rc = _create_cli(tmp_path, VALID)
    finally:
        exclude.chmod(0o644)  # restore so tmp cleanup can remove it
    assert rc == 0  # fail-open: an unwritable exclude never changes the exit code
    assert _REGISTERED_LINE not in capsys.readouterr().out
    assert exclude.read_text(encoding="utf-8") == original  # untouched


def test_create_symlinked_exclude_is_not_followed(tmp_path, capsys):
    exclude = _init_git_repo(tmp_path)
    exclude.unlink()
    outside = tmp_path / "outside-exclude"
    outside.write_text("", encoding="utf-8")
    try:
        exclude.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    assert _create_cli(tmp_path, VALID) == 0
    assert _REGISTERED_LINE not in capsys.readouterr().out
    assert outside.read_text(encoding="utf-8") == ""  # symlink target never written
