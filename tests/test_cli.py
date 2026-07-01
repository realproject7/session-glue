"""Tests for the Session Glue CLI scaffold.

These tests are deterministic and require no network access, git repository,
or user home access.
"""

from __future__ import annotations

import pytest

from session_glue import __version__
from session_glue.cli import _PLACEHOLDER_COMMANDS, build_parser, main


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


@pytest.mark.parametrize("command", [name for name, _ in _PLACEHOLDER_COMMANDS])
def test_placeholder_commands_are_registered_and_exit_zero(command, capsys):
    code = main([command])
    assert code == 0
    out = capsys.readouterr().out
    assert "not implemented yet" in out


def test_parser_prog_name():
    parser = build_parser()
    assert parser.prog == "glue"
