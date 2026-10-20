"""Standing decisions in ``glue status`` and the resume prompt (issues #140, #146).

Each test builds a real ``.agent-history/`` with ``glue create`` (or the shipped
writer) under pytest's ``tmp_path``: no real home, no network.

Since #146 a marked ``DECISIONS.md`` line is shown by provenance:

- ``[standing] YYYY-MM-DD operator: "<quote>"`` under ``Standing operator rulings:``
- ``[hold] <what>; reason: <why>; until: <end>`` under ``Agent-recorded holds``
- any other ``[standing]`` line under ``Unverified standing notes``
- ``[retracts <id>]`` removes the line with that id from both outputs

These tests pin which lines appear under which label, in what order, under what
cap, with which id, and that nothing extra appears when there are none.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from session_glue import cli, reader, schema, validator, vault, writer
from session_glue.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"
VALID = (FIXTURES / "valid.md").read_text(encoding="utf-8")
SESSION_ID = "2026-06-30-1530-chart-polling"
SUCCESSOR_ID = "2026-07-01-0900-successor"
FIRST_ACTION = "Add polling lifecycle with cleanup"
RULINGS = schema.RULINGS_LABEL
HOLDS = schema.HOLDS_LABEL
UNVERIFIED = schema.UNVERIFIED_LABEL
LABELS = (RULINGS, HOLDS, UNVERIFIED)
BEFORE_EDITING = "Before editing, run git status --short"

RULING = '[standing] 2026-06-29 operator: "No independent review unless asked"'
HOLD = "[hold] Image generation; reason: cuts under review; until: the operator reviews the cuts"
LEGACY = "[standing] No new image generation is authorized"


class _FixedDate(date):
    """``date.today()`` pinned to 2026-07-10, so ages in ``glue status`` are exact."""

    @classmethod
    def today(cls) -> date:  # type: ignore[override]
        return cls(2026, 7, 10)


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    monkeypatch.setattr(cli, "date", _FixedDate)


def _line(decision: str, session_id: str = SESSION_ID) -> str:
    """The DECISIONS.md line ``glue create`` writes for ``decision``."""
    date_part = "2026-07-01" if session_id == SUCCESSOR_ID else "2026-06-30"
    return f"- [{date_part}][{session_id}] {decision}"


def _ref(decision: str, session_id: str = SESSION_ID) -> str:
    return schema.decision_ref(_line(decision, session_id))


def _shown(decision: str, session_id: str = SESSION_ID) -> str:
    """How the resume prompt shows the line: id, then the line without ``- ``."""
    return f"{_ref(decision, session_id)} {_line(decision, session_id)[2:]}"


def _handoff(
    decisions: list[str] | None = None, *, session_id: str = SESSION_ID, extra: str = ""
) -> str:
    text = VALID.replace(SESSION_ID, session_id)
    if session_id == SUCCESSOR_ID:
        text = text.replace("session_date: 2026-06-30", "session_date: 2026-07-01")
    block = extra
    if decisions:
        block += "decisions:\n" + "".join(f"  - {schema.dump_scalar(d)}\n" for d in decisions)
    return text.replace("status: in_progress\n", "status: in_progress\n" + block, 1)


def _create(repo: Path, text: str, capsys=None) -> str:
    """Run ``glue create``; return its stderr when ``capsys`` is given."""
    src = repo / "in.md"
    src.write_text(text, encoding="utf-8")
    if capsys is not None:
        capsys.readouterr()
    assert main(["create", "--input", str(src), "--repo-root", str(repo)]) == 0
    return capsys.readouterr().err if capsys is not None else ""


def _run(capsys, *argv: str) -> str:
    capsys.readouterr()
    assert main(list(argv)) == 0
    return capsys.readouterr().out


def _status_block(status_out: str, label: str) -> list[str]:
    """The indented lines under ``label`` in ``glue status`` output."""
    lines = status_out.splitlines()
    if label not in lines:
        return []
    block = []
    for line in lines[lines.index(label) + 1 :]:
        if not line.startswith("  "):
            break
        block.append(line[2:])
    return block


def _prompt_block(prompt: str, label: str) -> list[str]:
    """The lines between a prompt label and the blank line that ends its block."""
    if label + "\n" not in prompt:
        return []
    after = prompt.split(label + "\n", 1)[1]
    return after.split("\n\n", 1)[0].splitlines()


def _prompt(tmp_path: Path, capsys) -> str:
    return _run(capsys, "resume-prompt", "--repo-root", str(tmp_path))


def _status(tmp_path: Path, capsys) -> str:
    return _run(capsys, "status", "--repo-root", str(tmp_path))


def _ruling(n: int) -> str:
    return f'[standing] 2026-06-29 operator: "rule {n:02d}"'


RULINGS_25 = [_ruling(n) for n in range(1, 26)]


# --------------------------------------------------------------------------- #
# glue status
# --------------------------------------------------------------------------- #


def test_status_prints_labeled_blocks_after_lineage_with_id_and_age(tmp_path, capsys):
    _create(tmp_path, _handoff([RULING, "Chose polling for #12", LEGACY]))
    _create(
        tmp_path,
        _handoff([HOLD], session_id=SUCCESSOR_ID, extra=f"supersedes: {SESSION_ID}\n"),
    )
    out = _status(tmp_path, capsys)
    lines = out.splitlines()

    # Directly after the lineage line, in the order rulings, holds, unverified,
    # before the validation summary.
    lineage = next(i for i, line in enumerate(lines) if line.startswith("lineage: "))
    assert lines[lineage + 1] == RULINGS
    assert [line for line in lines if line in LABELS] == list(LABELS)
    assert lines.index("validation: OK") > lines.index(UNVERIFIED)

    # Each line: id, age (pinned today 2026-07-10), the line without "- ".
    # A ruling ages from its own date; the others from their session date.
    assert _status_block(out, RULINGS) == [
        f"{_ref(RULING)} (11 days old) {_line(RULING)[2:]}"
    ]
    assert _status_block(out, HOLDS) == [
        f"{_ref(HOLD, SUCCESSOR_ID)} (9 days old) {_line(HOLD, SUCCESSOR_ID)[2:]}"
    ]
    assert _status_block(out, UNVERIFIED) == [
        f"{_ref(LEGACY)} (10 days old) {_line(LEGACY)[2:]}"
    ]
    # A one-off decision is counted but never shown.
    assert "decisions: 4" in out
    assert "Chose polling" not in out


def test_status_prints_nothing_extra_without_decisions_file(tmp_path, capsys):
    _create(tmp_path, VALID)
    assert not (tmp_path / ".agent-history" / "DECISIONS.md").exists()
    out = _status(tmp_path, capsys)
    assert not any(label in out for label in LABELS)
    assert out.splitlines()[-1] == "validation: OK"


def test_status_prints_nothing_extra_without_marked_lines(tmp_path, capsys):
    _create(tmp_path, _handoff(["Chose polling for #12", "Deferred rescale to #13"]))
    assert (tmp_path / ".agent-history" / "DECISIONS.md").is_file()
    out = _status(tmp_path, capsys)
    assert not any(label in out for label in LABELS)
    assert "decisions: 2" in out


def test_status_caps_each_block_at_the_newest_20_and_counts_the_rest(tmp_path, capsys):
    _create(tmp_path, _handoff(RULINGS_25))
    block = _status_block(_status(tmp_path, capsys), RULINGS)

    assert block[0] == "(+5 older lines in DECISIONS.md)"
    assert block[1:] == [
        f"{_ref(rule)} (11 days old) {_line(rule)[2:]}" for rule in RULINGS_25[5:]
    ]
    assert len(block[1:]) == schema.STANDING_LIMIT


def test_status_does_not_follow_a_symlinked_decisions_file(tmp_path, capsys):
    _create(tmp_path, VALID)
    outside = tmp_path / "outside.md"
    outside.write_text("- [2026-06-30][x] [standing] secret from outside\n", encoding="utf-8")
    try:
        (tmp_path / ".agent-history" / "DECISIONS.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available in this environment")
    assert reader.decisions_text(tmp_path) == ""
    assert "secret from outside" not in _status(tmp_path, capsys)


# --------------------------------------------------------------------------- #
# Provenance: only a quoted, dated operator line is an operator ruling (#146)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "decision",
    [
        LEGACY,
        "[standing] Tool X is excluded",
        # Agent text after the operator's quote: an added condition.
        '[standing] 2026-06-29 operator: "start autonomous work" no new image generation',
        # No date, a date that is not a real date, an empty quote.
        '[standing] operator: "No independent review unless asked"',
        '[standing] 2026-13-45 operator: "No independent review unless asked"',
        '[standing] 2026-06-29 operator: ""',
        # A paraphrase: not the operator's own words in quotes.
        "[standing] 2026-06-29 operator said no independent review",
        # The marker anywhere but the start of the decision.
        'Agreed with the operator [standing] 2026-06-29 operator: "no review"',
    ],
)
def test_unquoted_standing_lines_never_show_as_operator_rulings(tmp_path, capsys, decision):
    _create(tmp_path, _handoff([decision]))
    prompt = _prompt(tmp_path, capsys)
    out = _status(tmp_path, capsys)

    assert RULINGS not in prompt and RULINGS not in out
    assert _prompt_block(prompt, UNVERIFIED) == [_shown(decision)]
    assert [line.split(") ", 1)[1] for line in _status_block(out, UNVERIFIED)] == [
        _line(decision)[2:]
    ]


def test_legacy_decisions_file_keeps_working_as_unverified_notes(tmp_path, capsys):
    """A 0.4.1 log, appended by hand, still validates and shows as unverified."""
    _create(tmp_path, VALID)
    decisions = tmp_path / ".agent-history" / "DECISIONS.md"
    legacy = [
        "- [2026-06-01][old] [standing] No independent review unless asked",
        "- [2026-06-02][old] Chose polling for #12",
        "- [2026-06-03][old] [standing] No new image generation is authorized",
    ]
    decisions.write_text(writer.DECISIONS_HEADER + "\n".join(legacy) + "\n", encoding="utf-8")

    out = _status(tmp_path, capsys)
    assert RULINGS not in out
    assert [line.split(") ", 1)[1] for line in _status_block(out, UNVERIFIED)] == [
        legacy[0][2:],
        legacy[2][2:],
    ]
    # The legacy lines do not make glue validate fail; it only warns.
    capsys.readouterr()
    assert main(["validate", "--repo-root", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "glue validate: OK" in captured.out
    assert "2 [standing] line(s) lack the operator's quoted words" in captured.err


def test_a_quoted_ruling_may_contain_markers_inside_the_quote(tmp_path, capsys):
    ruling = '[standing] 2026-06-29 operator: "put a [hold] on deploys until Friday"'
    _create(tmp_path, _handoff([ruling]))
    prompt = _prompt(tmp_path, capsys)
    assert _prompt_block(prompt, RULINGS) == [_shown(ruling)]
    assert HOLDS not in prompt


# --------------------------------------------------------------------------- #
# glue resume-prompt and RESUME_PROMPT.txt
# --------------------------------------------------------------------------- #


def test_resume_prompt_carries_labeled_blocks_after_the_first_action(tmp_path, capsys):
    _create(tmp_path, _handoff([RULING, "Chose polling for #12", HOLD, LEGACY]))
    prompt = _prompt(tmp_path, capsys)

    assert (
        prompt.index(FIRST_ACTION)
        < prompt.index(RULINGS)
        < prompt.index(HOLDS)
        < prompt.index(UNVERIFIED)
        < prompt.index(BEFORE_EDITING)
    )
    assert f"{FIRST_ACTION}\n\n{RULINGS}\n" in prompt
    # No age in the prompt: it is written once and read later.
    assert _prompt_block(prompt, RULINGS) == [_shown(RULING)]
    assert _prompt_block(prompt, HOLDS) == [_shown(HOLD)]
    assert _prompt_block(prompt, UNVERIFIED) == [_shown(LEGACY)]
    assert "Chose polling" not in prompt
    # The command prints the generated file exactly, and the file still validates.
    assert prompt == (tmp_path / ".agent-history" / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    assert validator.validate_history(tmp_path) == []


@pytest.mark.parametrize("decisions", [None, ["Chose polling for #12"]])
def test_resume_prompt_is_unchanged_without_marked_lines(tmp_path, capsys, decisions):
    _create(tmp_path, _handoff(decisions))
    prompt = _prompt(tmp_path, capsys)
    assert not any(label in prompt for label in LABELS)
    # Byte-identical to the prompt generated before #140.
    assert prompt == schema.build_resume_prompt(schema.Handoff.from_text(VALID))


def test_resume_prompt_caps_like_status(tmp_path, capsys):
    _create(tmp_path, _handoff(RULINGS_25))
    block = _prompt_block(_prompt(tmp_path, capsys), RULINGS)
    assert block[0] == "(+5 older lines in DECISIONS.md)"
    assert block[1:] == [_shown(rule) for rule in RULINGS_25[5:]]


def test_later_handoff_without_decisions_still_carries_earlier_lines(tmp_path, capsys):
    _create(tmp_path, _handoff([RULING, HOLD]))
    _create(tmp_path, _handoff(session_id=SUCCESSOR_ID))
    prompt = _prompt(tmp_path, capsys)
    assert _prompt_block(prompt, RULINGS) == [_shown(RULING)]
    assert _prompt_block(prompt, HOLDS) == [_shown(HOLD)]


def test_create_accepts_bare_and_quoted_scalars(tmp_path, capsys):
    # Bare and quoted YAML scalars, marked and not: no schema change.
    extra = (
        "decisions:\n"
        "  - [standing] Bare prefixed note\n"
        f"  - {schema.dump_scalar(RULING)}\n"
        '  - "Quoted one-off for #12"\n'
    )
    _create(tmp_path, _handoff(extra=extra))
    decisions = (tmp_path / ".agent-history" / "DECISIONS.md").read_text(encoding="utf-8")
    assert _line("[standing] Bare prefixed note") in decisions
    assert _line(RULING) in decisions
    assert _line("Quoted one-off for #12") in decisions
    prompt = _prompt(tmp_path, capsys)
    assert _prompt_block(prompt, RULINGS) == [_shown(RULING)]
    assert _prompt_block(prompt, UNVERIFIED) == [_shown("[standing] Bare prefixed note")]


# --------------------------------------------------------------------------- #
# Retraction (#146)
# --------------------------------------------------------------------------- #


def test_retraction_removes_the_line_from_status_and_prompt_but_not_the_file(tmp_path, capsys):
    _create(tmp_path, _handoff([RULING, HOLD, LEGACY]))
    retraction = f"[retracts {_ref(HOLD)}, {_ref(LEGACY)}] the cuts were reviewed"
    err = _create(tmp_path, _handoff([retraction], session_id=SUCCESSOR_ID), capsys)
    assert "WARNING: decisions" not in err

    prompt = _prompt(tmp_path, capsys)
    out = _status(tmp_path, capsys)
    for text in (prompt, out):
        assert RULINGS in text
        assert HOLDS not in text and UNVERIFIED not in text
        assert "Image generation" not in text and "No new image generation" not in text
        assert "the cuts were reviewed" not in text  # a retraction is never displayed
    assert _prompt_block(prompt, RULINGS) == [_shown(RULING)]

    # Append-only: the retracted lines and the retraction stay in the history.
    decisions = (tmp_path / ".agent-history" / "DECISIONS.md").read_text(encoding="utf-8")
    for decision in (HOLD, LEGACY):
        assert _line(decision) in decisions
    assert _line(retraction, SUCCESSOR_ID) in decisions
    assert "decisions: 4" in out


def test_retraction_applies_wherever_it_sits_in_the_log():
    """The vault merge sorts by session date, so a retraction may come first."""
    target = "- [2026-07-02][later] [hold] Deploys; reason: audit; until: the audit passes"
    log = f"- [2026-07-01][early] [retracts {schema.decision_ref(target)}]\n{target}\n"
    assert schema.standing_blocks(log) == []
    assert schema.standing_view(log).unknown_retractions == ()


def test_a_hand_appended_retraction_line_works(tmp_path, capsys):
    _create(tmp_path, _handoff([RULING]))
    decisions = tmp_path / ".agent-history" / "DECISIONS.md"
    with decisions.open("a", encoding="utf-8") as fh:
        fh.write(f"[retracts {_ref(RULING).upper()}]\n")
    assert RULINGS not in _status(tmp_path, capsys)


def test_retracting_an_operator_ruling_and_recording_a_new_one(tmp_path, capsys):
    """Supersession: the operator changes a ruling; the old one is retracted."""
    _create(tmp_path, _handoff([RULING]))
    new = '[standing] 2026-07-01 operator: "Run an independent review on payment changes"'
    _create(tmp_path, _handoff([f"[retracts {_ref(RULING)}]", new], session_id=SUCCESSOR_ID))
    assert _prompt_block(_prompt(tmp_path, capsys), RULINGS) == [_shown(new, SUCCESSOR_ID)]


# --------------------------------------------------------------------------- #
# Advisory warnings from glue create and glue validate (#146)
# --------------------------------------------------------------------------- #


def test_create_warns_about_unquoted_standing_but_still_writes(tmp_path, capsys):
    err = _create(tmp_path, _handoff(["Chose polling for #12", LEGACY]), capsys)
    assert "glue create: WARNING: decisions[1]: [standing] needs the operator's own words" in err
    assert "decisions[0]" not in err
    assert "shown as an unverified note" in err
    decisions = (tmp_path / ".agent-history" / "DECISIONS.md").read_text(encoding="utf-8")
    assert _line(LEGACY) in decisions


def test_create_warns_about_a_hold_without_reason_or_end(tmp_path, capsys):
    err = _create(tmp_path, _handoff(["[hold] Deploys paused"]), capsys)
    assert "decisions[0]: [hold] needs a reason and an end condition" in err
    assert _prompt_block(_prompt(tmp_path, capsys), HOLDS) == [_shown("[hold] Deploys paused")]


def test_create_warns_about_an_unknown_or_malformed_retraction(tmp_path, capsys):
    err = _create(
        tmp_path, _handoff(["[retracts 0000aaaa]", "[retracts the image hold]"]), capsys
    )
    assert "decisions[0]: [retracts 0000aaaa] names no standing line, hold or note" in err
    assert "decisions[1]: a retraction must name 8-character ids" in err


def test_create_is_quiet_for_well_formed_lines(tmp_path, capsys):
    _create(tmp_path, _handoff([RULING, HOLD]))
    err = _create(
        tmp_path,
        _handoff([f"[retracts {_ref(HOLD)}]", "Chose polling for #12"], session_id=SUCCESSOR_ID),
        capsys,
    )
    assert "WARNING: decisions" not in err


def test_validate_is_quiet_for_a_clean_log(tmp_path, capsys):
    _create(tmp_path, _handoff([RULING, HOLD]))
    capsys.readouterr()
    assert main(["validate", "--repo-root", str(tmp_path)]) == 0
    assert "WARNING" not in capsys.readouterr().err


def test_log_warnings_count_only_live_lines():
    legacy = "- [2026-06-01][old] [standing] Tool X is excluded"
    open_hold = "- [2026-06-01][old] [hold] Deploys paused"
    retract_legacy = f"- [2026-06-02][new] [retracts {schema.decision_ref(legacy)}]"
    log = "\n".join([legacy, open_hold, retract_legacy, "- [2026-06-02][new] [retracts 0000aaaa]"])
    assert schema.log_warnings(log) == [
        "DECISIONS.md: 1 [hold] line(s) lack a reason or an end condition "
        f"({schema.HOLD_FORMAT})",
        "DECISIONS.md: [retracts 0000aaaa] names no standing line, hold or note",
    ]


# --------------------------------------------------------------------------- #
# Shared rendering and the vault's rebuilt prompt
# --------------------------------------------------------------------------- #


def test_render_block_cap_boundaries():
    entries = [
        schema.classify_decision(f'- [d][s] [standing] 2026-06-29 operator: "r{n}"')
        for n in range(21)
    ]
    shown = [schema.display_decision(entry) for entry in entries]
    assert schema.render_block([]) == []
    assert schema.render_block(entries[:20]) == shown[:20]
    assert schema.render_block(entries) == ["(+1 older lines in DECISIONS.md)", *shown[1:]]
    assert schema.standing_blocks("# Decisions\n\nheader\n- [d][s] plain\n") == []


def test_decision_ref_is_stable_and_ignores_surrounding_whitespace():
    line = _line(RULING)
    assert schema.decision_ref(line) == schema.decision_ref(f"  {line}\r")
    assert len(schema.decision_ref(line)) == 8
    assert schema.decision_ref(line) != schema.decision_ref(_line(RULING, SUCCESSOR_ID))


def _vault_frontmatter(repo_root: Path, session_id: str, decisions: list[str]) -> dict:
    return {
        "session_id": session_id,
        "session_date": "2026-08-28",
        "generated_at": "2026-08-28T12:00:00+00:00",
        "schema_version": 1,
        "project_root": str(repo_root),
        "repo_root": str(repo_root),
        "current_branch": "main",
        "head_commit": "abc1234",
        "agent": "codex",
        "status": "in_progress",
        "primary_goal": "Carry standing rulings across devices",
        "active_context_files": ["session_glue/vault.py"],
        "completed_tasks": ["Recorded the rulings"],
        "next_todo_items": ["Resume on the other device"],
        "known_issues": ["None"],
        "search_tags": ["vault"],
        "validation": [{"command": "pytest -q", "result": "passed", "notes": ""}],
        "decisions": decisions,
    }


_VAULT_BODY = "\n".join(f"{section}\n\n- Recorded.\n" for section in schema.REQUIRED_BODY_SECTIONS)


def test_vault_import_rebuilds_the_prompt_with_labeled_blocks(tmp_path):
    """Pull rebuilds RESUME_PROMPT.txt; it must match what ``glue create`` wrote."""
    source = tmp_path / "laptop"
    source.mkdir()
    frontmatter = _vault_frontmatter(source, "2026-08-28-1200-alpha", [RULING, HOLD, LEGACY])
    handoff = schema.Handoff.from_frontmatter(frontmatter, _VAULT_BODY)
    writer.create_handoff(
        repo_root=source, frontmatter=frontmatter, body=_VAULT_BODY, handoff=handoff
    )
    created = (source / ".agent-history" / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    line = f"- [2026-08-28][2026-08-28-1200-alpha] {RULING}"
    assert f"{schema.decision_ref(line)} {line[2:]}" in created

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(source, vault_root, "alpha")
    other = tmp_path / "desktop"
    other.mkdir()
    vault.import_project(other, vault_root, "alpha")

    rebuilt = (other / ".agent-history" / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    # Same ids on the other device: the merge keeps every line byte-for-byte.
    assert _prompt_block(rebuilt, RULINGS) == [f"{schema.decision_ref(line)} {line[2:]}"]
    assert _prompt_block(rebuilt, HOLDS) and _prompt_block(rebuilt, UNVERIFIED)
    # Same prompt as the laptop's, apart from the device-local project root.
    assert rebuilt == created.replace(str(source), str(other))
    assert validator.validate_history(other, check_sessions=True) == []


def test_rebuild_derived_without_decisions_keeps_the_plain_prompt(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    frontmatter = _vault_frontmatter(root, "2026-08-28-1200-alpha", [])
    del frontmatter["decisions"]
    handoff = schema.Handoff.from_frontmatter(frontmatter, _VAULT_BODY)
    writer.create_handoff(
        repo_root=root, frontmatter=frontmatter, body=_VAULT_BODY, handoff=handoff
    )
    archives = vault.read_local_archives(root)
    derived = vault.rebuild_derived(archives, "2026-08-28-1200-alpha", [])
    assert not any(label in derived["RESUME_PROMPT.txt"] for label in LABELS)
    assert derived["RESUME_PROMPT.txt"] == (
        root / ".agent-history" / "RESUME_PROMPT.txt"
    ).read_text(encoding="utf-8")
