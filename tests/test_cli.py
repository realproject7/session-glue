"""Tests for the Session Glue CLI scaffold.

These tests are deterministic and require no network access, git repository,
or user home access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_glue import __version__
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


@pytest.mark.parametrize("command", ["create", "validate", "status", "resume-prompt", "install"])
def test_subcommands_are_registered(command, capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([command, "--help"])
    assert exc_info.value.code == 0
    assert command in capsys.readouterr().out


def test_parser_prog_name():
    parser = build_parser()
    assert parser.prog == "glue"


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
