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
# next_todo_items entries must be scalars (issue #40)
# --------------------------------------------------------------------------- #


def _with_todos(todos):
    fields = {name: "x" for name in REQUIRED_FIELDS}
    fields["next_todo_items"] = todos
    return Handoff.from_frontmatter(fields)


def test_next_todo_items_rejects_mapping_entry():
    errors = _with_todos(["A productive task", {"task": "do x"}]).validate()
    assert any("next_todo_items[1] must be a scalar" in e for e in errors)
    assert any("not dict" in e for e in errors)


def test_next_todo_items_rejects_list_entry():
    errors = _with_todos(["A productive task", ["nested", "list"]]).validate()
    assert any("next_todo_items[1] must be a scalar" in e for e in errors)
    assert any("not list" in e for e in errors)


def test_next_todo_items_accepts_scalar_entries():
    # str and int entries must not trip the scalar-only check.
    errors = _with_todos(["A productive task", 42]).validate()
    assert not any("must be a scalar" in e for e in errors)


# --------------------------------------------------------------------------- #
# Issue #33 regression: bare-substring false positives vs real mechanics.
# The lint must switch from bare substrings ("paste", "new session", "resume
# prompt") to word-boundary mechanic verb+object phrases so ordinary work items
# whose vocabulary includes those words are no longer hard-blocked.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "item",
    [
        "Implement the new session naming scheme in writer.py",
        "Add paste support to the editor component",
        "Fix the resume prompt generator bug in schema.py",
    ],
)
def test_issue33_productive_items_not_flagged(item):
    # These previously false-positived on bare substrings; they must pass now.
    assert lint_first_next_action(item) is None


@pytest.mark.parametrize(
    "item",
    [
        "Paste the prompt into a new session",
        "Start a new agent session and paste RESUME_PROMPT.txt exactly",
        "Read LATEST.md and inspect the handoff",
    ],
)
def test_issue33_real_mechanics_still_flagged(item):
    # Genuine resume mechanics must still be caught by default (no override).
    assert lint_first_next_action(item) is not None


# --------------------------------------------------------------------------- #
# Quality fields — primary_goal, search_tags, validation (issue #43)
# --------------------------------------------------------------------------- #


def _valid_frontmatter() -> dict:
    frontmatter, _ = parse_frontmatter(_read("valid.md"))
    return frontmatter


def test_valid_fixture_carries_new_quality_fields():
    handoff = Handoff.from_text(_read("valid.md"))
    assert handoff.primary_goal == "Ship the chart polling lifecycle with clean teardown"
    assert handoff.search_tags == ["charts", "polling", "react"]
    assert handoff.validation[0] == {
        "command": "npm test",
        "result": "passed",
        "notes": "Unit suite green",
    }
    assert handoff.validate() == []


def test_missing_primary_goal_fails_validation():
    frontmatter = _valid_frontmatter()
    del frontmatter["primary_goal"]
    errors = Handoff.from_frontmatter(frontmatter).validate()
    assert any("primary_goal" in e for e in errors)


def test_empty_search_tags_fails_validation():
    frontmatter = _valid_frontmatter()
    frontmatter["search_tags"] = []
    errors = Handoff.from_frontmatter(frontmatter).validate()
    assert any("search_tags" in e for e in errors)


def test_missing_validation_fails_validation():
    frontmatter = _valid_frontmatter()
    del frontmatter["validation"]
    errors = Handoff.from_frontmatter(frontmatter).validate()
    assert "missing required field: validation" in errors


def test_non_mapping_validation_entry_fails_with_clear_error():
    frontmatter = _valid_frontmatter()
    frontmatter["validation"] = ["ran the tests"]  # scalar, not a mapping
    errors = Handoff.from_frontmatter(frontmatter).validate()
    assert any("validation[0] must be a command/result/notes mapping" in e for e in errors)


def test_validation_result_must_be_a_known_value():
    frontmatter = _valid_frontmatter()
    frontmatter["validation"] = [{"command": "npm test", "result": "green", "notes": "x"}]
    errors = Handoff.from_frontmatter(frontmatter).validate()
    assert any("validation[0].result must be one of passed/failed/not_run" in e for e in errors)


def test_validation_not_run_result_is_allowed():
    frontmatter = _valid_frontmatter()
    frontmatter["validation"] = [{"command": "npm run typecheck", "result": "not_run"}]
    assert Handoff.from_frontmatter(frontmatter).validate() == []


def test_validation_entry_requires_a_command():
    frontmatter = _valid_frontmatter()
    frontmatter["validation"] = [{"result": "passed", "notes": "x"}]
    errors = Handoff.from_frontmatter(frontmatter).validate()
    assert any("validation[0].command is required" in e for e in errors)


def test_validation_notes_is_optional():
    # Per the clarified contract: command + result are required, notes is optional
    # commentary — an entry with no notes still validates.
    frontmatter = _valid_frontmatter()
    frontmatter["validation"] = [{"command": "npm test", "result": "passed"}]
    assert Handoff.from_frontmatter(frontmatter).validate() == []


def test_active_context_files_accepts_scalars_and_mappings():
    # Backward compatibility: bare-scalar paths still validate…
    frontmatter = _valid_frontmatter()
    frontmatter["active_context_files"] = ["src/foo.py", "src/bar.py"]
    assert Handoff.from_frontmatter(frontmatter).validate() == []
    # …and so do path/reason mappings (the preferred form the fixture uses).
    frontmatter = _valid_frontmatter()
    frontmatter["active_context_files"] = [{"path": "src/foo.py", "reason": "target"}]
    assert Handoff.from_frontmatter(frontmatter).validate() == []


# --------------------------------------------------------------------------- #
# Optional decisions field (issue #44)
# --------------------------------------------------------------------------- #


def test_decisions_field_is_optional():
    # valid.md carries no decisions and must still validate — absence is fine.
    handoff = Handoff.from_text(_read("valid.md"))
    assert "decisions" not in handoff.present_fields
    assert handoff.validate() == []


def test_scalar_decisions_validate():
    frontmatter = _valid_frontmatter()
    frontmatter["decisions"] = ["Chose polling over websockets", "Deferred rescale", 42]
    assert Handoff.from_frontmatter(frontmatter).validate() == []


def test_non_scalar_decision_entry_fails_with_clear_error():
    frontmatter = _valid_frontmatter()
    frontmatter["decisions"] = [{"why": "nested"}]
    errors = Handoff.from_frontmatter(frontmatter).validate()
    assert any("decisions[0] must be a scalar (string or number)" in e for e in errors)


def test_non_list_decisions_fails():
    frontmatter = _valid_frontmatter()
    frontmatter["decisions"] = "just a string"
    errors = Handoff.from_frontmatter(frontmatter).validate()
    assert any("must be a list: decisions" in e for e in errors)


# --------------------------------------------------------------------------- #
# Derived artifacts
# --------------------------------------------------------------------------- #


def test_index_first_next_action_mirrors_next_todo_items_0():
    handoff = Handoff.from_text(_read("valid.md"))
    entry = build_index_entry(handoff)
    assert entry["first_next_action"] == handoff.next_todo_items[0]
    # And the index does not carry the full next_todo_items list.
    assert "next_todo_items" not in entry


def test_index_entry_mirrors_primary_goal_and_search_tags():
    handoff = Handoff.from_text(_read("valid.md"))
    entry = build_index_entry(handoff)
    assert entry["primary_goal"] == handoff.primary_goal
    # search_tags mirror as a single greppable scalar, not a nested list, because
    # the constrained INDEX serializer only supports scalar values in a session entry.
    assert entry["search_tags"] == "charts, polling, react"
    assert isinstance(entry["search_tags"], str)


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
# YAML-subset friction reductions (issue #37)
# --------------------------------------------------------------------------- #


def test_empty_list_literal_parses_as_empty_list():
    # Behavior 1: `[]` is accepted as an empty list (previously rejected).
    parsed = parse_mapping("active_context_files: []")
    assert parsed == {"active_context_files": []}
    assert isinstance(parsed["active_context_files"], list)


def test_flow_list_with_items_stays_unsupported_and_fails_loudly():
    # Behavior 1: `[a, b]` is NOT flow-parsed; it stays a scalar string, so a
    # list field then fails loudly instead of silently accepting flow YAML.
    parsed = parse_mapping("active_context_files: [a, b]")
    assert parsed["active_context_files"] == "[a, b]"
    handoff = Handoff.from_frontmatter(parsed)
    assert any("must be a list: active_context_files" in e for e in handoff.validate())


@pytest.mark.parametrize(
    "text",
    [
        "notes: |\n  line one\n  line two",  # block literal indicator
        "notes: >-\n  folded text",  # folded block indicator
        "notes: value\n  spilled onto a second line",  # bare continuation
    ],
)
def test_multiline_values_rejected_with_clear_message(text):
    # Behavior 2: multi-line value shapes get a clear single-line message, not
    # the old cryptic "unexpected indentation at top level".
    with pytest.raises(HandoffParseError) as exc_info:
        parse_mapping(text)
    message = str(exc_info.value)
    assert "multi-line" in message.lower()
    assert "one line" in message


def test_inline_comment_after_unquoted_scalar_is_stripped():
    # Behavior 3: `# ...` preceded by whitespace is a comment and dropped.
    assert parse_mapping("head_commit: abc1234 # short sha")["head_commit"] == "abc1234"


def test_hash_inside_quoted_string_stays_literal():
    # Behavior 3: a `#` inside a quoted string is NOT a comment.
    assert parse_mapping('note: "release # 5"')["note"] == "release # 5"


def test_hash_glued_to_text_is_not_a_comment():
    # Behavior 3: a `#` not preceded by whitespace stays part of the value.
    assert parse_mapping("lang: C#sharp")["lang"] == "C#sharp"


def test_duplicate_top_level_key_raises_naming_the_key():
    # Behavior 4: duplicate top-level keys are an error, not last-one-wins.
    with pytest.raises(HandoffParseError) as exc_info:
        parse_mapping("agent: codex\nagent: claude")
    message = str(exc_info.value)
    assert "duplicate" in message.lower()
    assert "agent" in message


def test_only_schema_version_is_coerced_to_int():
    # Behavior 5: schema_version coerces to int; other all-digit fields keep
    # their literal string (no `1234567` -> int, no `007` -> 7).
    parsed = parse_mapping("schema_version: 2\nhead_commit: 1234567\nsession_id: 007")
    assert parsed["schema_version"] == 2
    assert isinstance(parsed["schema_version"], int)
    assert parsed["head_commit"] == "1234567"
    assert parsed["session_id"] == "007"


def test_numeric_hash_round_trips_as_string():
    # Behavior 5 round-trip: a numeric-looking hash stays a string across
    # parse -> dump -> parse.
    data = {"head_commit": "1234567"}
    reparsed = parse_mapping(dump_mapping(data))
    assert reparsed == data
    assert isinstance(reparsed["head_commit"], str)


def test_comment_stripped_value_round_trips_stably():
    # Behavior 3 round-trip: the first parse drops the comment; the cleaned
    # value is then stable across parse -> dump -> parse.
    once = parse_mapping("head_commit: abc1234 # sha")
    assert once == {"head_commit": "abc1234"}
    assert parse_mapping(dump_mapping(once)) == once


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
