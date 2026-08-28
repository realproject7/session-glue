"""Tests for ``glue install <agent> --dry-run`` and the managed block.

The installer is dry-run only: these tests confirm it prints the target path
and the managed block, detects an existing block in fixture files, and never
mutates user-home files (a monkeypatched ``HOME`` stays empty).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from session_glue import installer, schema
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
        ("claude", "~/.claude/skills/session-glue/"),
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


def test_legacy_claude_target_is_skills_first_with_recommended_default(capsys):
    # The stale ~/.claude/commands/glue.md target was replaced by the skills-first
    # path, with a note that the repo-scoped folder is the recommended default.
    assert main(["install", "claude", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "~/.claude/skills/session-glue/" in out
    assert "repo-scoped .claude/skills/session-glue/ is the recommended default" in out


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


# --------------------------------------------------------------------------- #
# Issue #90 — the block must advertise a handoff the current schema accepts
# --------------------------------------------------------------------------- #


def _advertised_fields() -> list[str]:
    """The frontmatter fields the *rendered block itself* claims are required.

    Parsed out of the block rather than restated here, so these tests check what
    an operator actually reads. Restating the list would let the block drift
    while the tests stayed green against their own copy.
    """
    listed = re.search(
        r"Every frontmatter field is required: (.+?)\.\n", installer.managed_block(), re.S
    )
    assert listed, "the block no longer states its frontmatter contract"
    return [field.strip() for field in listed.group(1).replace("\n", "").split(",")]


def _advertised_sections() -> list[str]:
    """The headings exactly as the block renders them — deliberately not stripped.

    Stripping would hide the defect this exists to catch: the validator compares
    the whole line (`schema.py:513`, `line.rstrip()` trims trailing space only),
    so a heading the block displays indented is one an operator copies and the
    validator then rejects. Returning the raw line means the validator test below
    exercises what is actually on screen.
    """
    return [
        line
        for line in installer.managed_block().splitlines()
        if line.startswith("# ")
    ]


def test_block_names_every_required_frontmatter_field():
    """AC1/AC2: derived from `schema.REQUIRED_FIELDS`, so a schema change fails here.

    Before #90 the block omitted `primary_goal`, `search_tags` and `validation`
    — it advertised a document the validator rejects.
    """
    assert _advertised_fields() == list(schema.REQUIRED_FIELDS)


def test_block_names_every_required_body_section():
    """AC1/AC2: before #90 the block named *none* of the eight headings."""
    assert _advertised_sections() == list(schema.REQUIRED_BODY_SECTIONS)


def test_a_handoff_built_from_the_blocks_own_claims_passes_the_validator():
    """AC1, end to end: the point is not that the strings match, but that an
    agent following the block produces something `glue validate` accepts.

    Field *names* matching the schema would still leave the guidance wrong if a
    heading were displayed in a form the validator rejects. It was: the block
    first rendered the headings indented five spaces, which `Handoff.validate`
    refuses, while this test stripped them and passed anyway. The headings are
    now used **verbatim**, so the document under test is the one an operator
    copying the block would actually produce.
    """
    values = {
        "session_id": "2026-08-28-1200-alpha",
        "session_date": "2026-08-28",
        "generated_at": "2026-08-28T12:00:00+00:00",
        "schema_version": 1,
        "project_root": "/repo",
        "repo_root": "/repo",
        "current_branch": "main",
        "head_commit": "abc1234",
        "agent": "codex",
        "status": "in_progress",
        "primary_goal": "Ship the thing",
        "active_context_files": ["session_glue/installer.py"],
        "completed_tasks": ["Wrote the block"],
        "next_todo_items": ["Extend the dry-run coverage"],
        "known_issues": ["None known"],
        "search_tags": ["installer"],
        "validation": [{"command": "pytest -q", "result": "passed", "notes": ""}],
    }
    frontmatter = {field: values[field] for field in _advertised_fields()}
    body = "\n\n".join(f"{heading}\n\nprose" for heading in _advertised_sections())

    handoff = schema.Handoff.from_frontmatter(frontmatter, body)

    assert handoff.validate() == []


def test_the_block_does_not_advertise_fields_the_schema_does_not_require():
    """The other direction: guidance that over-states the contract is also drift."""
    assert not set(_advertised_fields()) - set(schema.REQUIRED_FIELDS)


@pytest.mark.parametrize("agent", ("codex", "claude"))
def test_the_rendered_dry_run_output_carries_the_corrected_contract(agent, capsys):
    """AC4: what the operator sees, not just the module constant."""
    assert main(["install", agent, "--dry-run"]) == 0
    out = capsys.readouterr().out
    for field in schema.REQUIRED_FIELDS:
        assert field in out, f"{field} missing from the printed block"
    for heading in schema.REQUIRED_BODY_SECTIONS:
        assert heading in out, f"{heading} missing from the printed block"


def test_cli_and_readme_present_the_legacy_route_as_print_only(capsys):
    """AC3: the route is described as superseded and print-only, in both places.

    Tied to the payload deliberately: the claim "print-only, superseded, and
    still usable" is only honest while the payload conforms, which the tests
    above enforce.
    """
    assert main(["install", "codex", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "glue skill install" in out

    # The same two words in `--help`, so the two surfaces agree.
    with pytest.raises(SystemExit):
        main(["install", "--help"])
    help_text = capsys.readouterr().out
    assert "Superseded" in help_text and "print-only" in help_text

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    legacy = [line for line in readme.splitlines() if "glue install" in line]
    assert legacy, "README no longer mentions the legacy route"
    assert any("print-only" in line and "superseded" in line for line in legacy)
