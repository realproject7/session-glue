"""Tests for the handoff schema helpers and the fixture library.

All tests are deterministic and require no network or user home access — they
read only the checked-in fixtures under ``tests/fixtures/handoffs``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_glue.schema import (
    REQUIRED_FIELDS,
    Handoff,
    HandoffParseError,
    build_index_entry,
    build_resume_prompt,
    dump_mapping,
    lint_first_next_action,
    parse_frontmatter,
    parse_mapping,
)

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_valid_fixture_parses_cleanly():
    handoff = Handoff.from_text(_read("valid.md"))
    assert handoff.validate() == []
    assert handoff.is_valid()

    assert handoff.session_id == "2026-06-30-1530-chart-polling"
    assert handoff.schema_version == 1  # integers parse as ints
    assert handoff.status == "in_progress"
    # Block sequence of mappings.
    assert handoff.active_context_files[0] == {
        "path": "src/components/ChartView.tsx",
        "reason": "Main implementation target",
    }
    # Block sequence of scalars.
    assert handoff.next_todo_items == [
        "Add polling lifecycle with cleanup",
        "Handle empty data without Y-axis scaling bug",
    ]
    # Body is preserved after the closing delimiter.
    assert "Detailed Session Briefing" in handoff.body


def test_all_required_fields_present_in_valid_fixture():
    frontmatter, _ = parse_frontmatter(_read("valid.md"))
    for name in REQUIRED_FIELDS:
        assert name in frontmatter


def test_parse_frontmatter_requires_delimiters():
    with pytest.raises(HandoffParseError):
        parse_frontmatter("no frontmatter here\n")
    with pytest.raises(HandoffParseError):
        parse_frontmatter("---\nsession_id: x\n")  # unterminated


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_missing_field_fixture_fails_validation():
    handoff = Handoff.from_text(_read("invalid_missing_field.md"))
    errors = handoff.validate()
    assert not handoff.is_valid()
    assert any("head_commit" in e for e in errors)


def test_invalid_next_action_fixture_reports_lint():
    handoff = Handoff.from_text(_read("invalid_next_action.md"))
    errors = handoff.validate()
    assert not handoff.is_valid()
    assert any("resume mechanic" in e for e in errors)


def test_scalar_list_field_fails_validation():
    # A scalar where a block sequence is required must be rejected — otherwise a
    # bare-string next_todo_items would validate and first_next_action would
    # silently become the string's first character.
    handoff = Handoff.from_frontmatter(
        {name: "x" for name in REQUIRED_FIELDS}
    )
    errors = handoff.validate()
    assert not handoff.is_valid()
    assert any("must be a list: next_todo_items" in e for e in errors)
    assert handoff.first_next_action is None


def test_scalar_next_todo_items_first_action_is_none():
    handoff = Handoff.from_frontmatter({"next_todo_items": "Add polling lifecycle"})
    # Not indexing into the string: no silent "A".
    assert handoff.first_next_action is None


@pytest.mark.parametrize(
    "item",
    [
        "Start a new session and paste RESUME_PROMPT.txt",
        "Paste the prompt into the new chat",
        "Read LATEST.md",
        "Inspect the handoff",
        "Verify that resume worked",
    ],
)
def test_lint_flags_resume_mechanics(item):
    assert lint_first_next_action(item) is not None


@pytest.mark.parametrize(
    "item",
    [
        "Add polling lifecycle with cleanup",
        "Reconcile the manual resume experiment note with the latest validation results",
        "Fix the Y-axis scaling bug when data is empty",
    ],
)
def test_lint_allows_productive_actions(item):
    assert lint_first_next_action(item) is None


# --------------------------------------------------------------------------- #
# Derived artifacts
# --------------------------------------------------------------------------- #


def test_index_first_next_action_mirrors_next_todo_items_0():
    handoff = Handoff.from_text(_read("valid.md"))
    entry = build_index_entry(handoff)
    assert entry["first_next_action"] == handoff.next_todo_items[0]
    # And the index does not carry the full next_todo_items list.
    assert "next_todo_items" not in entry


def test_fixture_index_matches_handoff_first_next_action():
    handoff = Handoff.from_text(_read("valid.md"))
    index = parse_mapping(_read("INDEX.yaml"))
    session = index["sessions"][0]
    assert session["first_next_action"] == handoff.next_todo_items[0]
    assert index["latest"] == handoff.session_id


def test_resume_prompt_points_at_latest_and_first_action():
    handoff = Handoff.from_text(_read("valid.md"))
    prompt = build_resume_prompt(handoff)
    assert ".agent-history/LATEST.md" in prompt
    assert "Prompt artifact: .agent-history/RESUME_PROMPT.txt" in prompt
    assert "next_todo_items" in prompt
    assert handoff.next_todo_items[0] in prompt
    assert handoff.project_root in prompt
    assert "First, read: RESUME_PROMPT.txt" not in prompt


# --------------------------------------------------------------------------- #
# Serializer round-trip
# --------------------------------------------------------------------------- #


def test_dump_mapping_round_trips_scalars_and_sequences():
    frontmatter, _ = parse_frontmatter(_read("valid.md"))
    reparsed = parse_mapping(dump_mapping(frontmatter))
    assert reparsed == frontmatter


@pytest.mark.parametrize(
    "value",
    [
        'label: "done"',  # colon forces quoting; embedded quotes must escape
        r"a path with a backslash C:\path\to\project",
        r'both \ and " together',
        "trailing backslash \\",
    ],
)
def test_dump_mapping_round_trips_escaped_scalars(value):
    # Values that _dump_scalar escapes must survive a dump -> parse cycle
    # unchanged (previously _parse_scalar stripped quotes without unescaping).
    data = {"note": value}
    assert parse_mapping(dump_mapping(data)) == data
