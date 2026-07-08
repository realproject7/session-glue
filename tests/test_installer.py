"""Tests for ``glue install <agent> --dry-run`` and the managed block.

The installer is dry-run only: these tests confirm it prints the target path
and the managed block, detects an existing block in fixture files, and never
mutates user-home files (a monkeypatched ``HOME`` stays empty).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_glue import installer
from session_glue.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "installer"
WITH_BLOCK = (FIXTURES / "with_block.md").read_text(encoding="utf-8")
WITHOUT_BLOCK = (FIXTURES / "without_block.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Managed block + markers
# --------------------------------------------------------------------------- #


def test_markers_are_stable_constants():
    # These strings are an on-disk contract; guard against accidental drift.
    assert installer.BEGIN_MARKER == "<!-- BEGIN SESSION GLUE (managed) -->"
    assert installer.END_MARKER == "<!-- END SESSION GLUE (managed) -->"


def test_managed_block_is_marker_delimited_and_complete():
    block = installer.managed_block()
    assert block.startswith(installer.BEGIN_MARKER)
    assert block.endswith(installer.END_MARKER)
    # Covers every documented trigger and the v1 constraints.
    for trigger in ("/glue", "/freeze", "/handoff", "/checkpoint"):
        assert trigger in block
    assert "glue create" in block
    assert ".agent-history" in block
    assert "RESUME_PROMPT.txt" in block
    assert "clipboard" in block
    assert "daemon" in block


def test_has_managed_block_detects_fixtures():
    assert installer.has_managed_block(WITH_BLOCK) is True
    assert installer.has_managed_block(WITHOUT_BLOCK) is False


# --------------------------------------------------------------------------- #
# Dry-run CLI
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "agent,target",
    [
        ("codex", "~/.codex/AGENTS.md"),
        ("claude", "~/.claude/commands/glue.md"),
        ("cursor", "~/.cursor/rules/session-glue.md"),
        ("gemini", "~/.gemini/GEMINI.md"),
    ],
)
def test_dry_run_prints_target_and_block(agent, target, capsys):
    assert main(["install", agent, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert target in out
    assert installer.BEGIN_MARKER in out
    assert installer.END_MARKER in out
    assert "/glue" in out


def test_dry_run_all_covers_every_agent(capsys):
    assert main(["install", "all", "--dry-run"]) == 0
    out = capsys.readouterr().out
    for target in installer.AGENT_TARGETS.values():
        assert target.target in out
    # One managed block printed per agent.
    assert out.count(installer.BEGIN_MARKER) == len(installer.AGENT_ORDER)


def test_install_without_dry_run_is_blocked(capsys):
    code = main(["install", "codex"])
    assert code == 2
    assert "--dry-run" in capsys.readouterr().err


def test_legacy_install_mentions_skill_install_successor(capsys):
    # Legacy `glue install` stays dry-run-only but points at its successor.
    assert main(["install", "codex", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "glue skill install" in out


def test_unknown_agent_is_rejected():
    with pytest.raises(SystemExit) as exc_info:
        main(["install", "notanagent", "--dry-run"])
    assert exc_info.value.code == 2


# --------------------------------------------------------------------------- #
# No user-home mutation
# --------------------------------------------------------------------------- #


def test_dry_run_does_not_touch_home(tmp_path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows fallback

    for agent in (*installer.AGENT_ORDER, "all"):
        assert main(["install", agent, "--dry-run"]) == 0

    # Nothing was created or written under the (fake) home directory.
    assert list(fake_home.rglob("*")) == []
