"""Standing operator rulings in ``glue status`` and the resume prompt (issue #140).

Each test builds a real ``.agent-history/`` with ``glue create`` (or the shipped
writer) under pytest's ``tmp_path``: no real home, no network. ``[standing]`` is
plain text that nothing in the schema parses, so these tests pin only what the
CLI prints and writes: which lines appear, in what order, under what cap, and
that nothing extra appears when there are none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_glue import reader, schema, validator, vault, writer
from session_glue.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"
VALID = (FIXTURES / "valid.md").read_text(encoding="utf-8")
SESSION_ID = "2026-06-30-1530-chart-polling"
SUCCESSOR_ID = "2026-07-01-0900-successor"
FIRST_ACTION = "Add polling lifecycle with cleanup"
HEADING = "Standing operator rulings:"
BEFORE_EDITING = "Before editing, run git status --short"


def _line(decision: str, session_id: str = SESSION_ID) -> str:
    """The DECISIONS.md line ``glue create`` writes for ``decision``."""
    return f"- [2026-06-30][{session_id}] {decision}"


def _handoff(
    decisions: list[str] | None = None, *, session_id: str = SESSION_ID, extra: str = ""
) -> str:
    text = VALID.replace(SESSION_ID, session_id)
    block = extra
    if decisions:
        block += "decisions:\n" + "".join(f'  - "{d}"\n' for d in decisions)
    return text.replace("status: in_progress\n", "status: in_progress\n" + block, 1)


def _create(repo: Path, text: str) -> None:
    src = repo / "in.md"
    src.write_text(text, encoding="utf-8")
    assert main(["create", "--input", str(src), "--repo-root", str(repo)]) == 0


def _run(capsys, *argv: str) -> str:
    capsys.readouterr()
    assert main(list(argv)) == 0
    return capsys.readouterr().out


def _standing_block(status_out: str) -> list[str]:
    """The indented lines under ``standing:`` in ``glue status`` output."""
    lines = status_out.splitlines()
    start = lines.index("standing:") + 1
    block = []
    for line in lines[start:]:
        if not line.startswith("  "):
            break
        block.append(line[2:])
    return block


def _prompt_block(prompt: str) -> list[str]:
    """The lines between the prompt heading and the blank line that ends it."""
    after = prompt.split(HEADING + "\n", 1)[1]
    return after.split("\n\n", 1)[0].splitlines()


RULES_25 = [f"[standing] rule {n:02d}" for n in range(1, 26)]


# --------------------------------------------------------------------------- #
# glue status
# --------------------------------------------------------------------------- #


def test_status_prints_standing_block_after_lineage_oldest_first(tmp_path, capsys):
    _create(
        tmp_path,
        _handoff(["[standing] No independent review unless asked", "Chose polling for #12"]),
    )
    _create(
        tmp_path,
        _handoff(
            ["[standing] Tool X is excluded"],
            session_id=SUCCESSOR_ID,
            extra=f"supersedes: {SESSION_ID}\n",
        ),
    )
    out = _run(capsys, "status", "--repo-root", str(tmp_path))
    lines = out.splitlines()

    # Directly after the lineage line, before the validation summary.
    lineage = next(i for i, line in enumerate(lines) if line.startswith("lineage: "))
    assert lines[lineage + 1] == "standing:"
    assert _standing_block(out) == [
        _line("[standing] No independent review unless asked"),
        _line("[standing] Tool X is excluded", SUCCESSOR_ID),
    ]
    assert lines.index("validation: OK") > lineage + 2
    # A one-off decision is counted but never shown as a standing ruling.
    assert "decisions: 3" in out
    assert "Chose polling" not in out


def test_status_prints_nothing_extra_without_decisions_file(tmp_path, capsys):
    _create(tmp_path, VALID)
    assert not (tmp_path / ".agent-history" / "DECISIONS.md").exists()
    out = _run(capsys, "status", "--repo-root", str(tmp_path))
    assert "standing" not in out
    assert out.splitlines()[-1] == "validation: OK"


def test_status_prints_nothing_extra_without_standing_lines(tmp_path, capsys):
    _create(tmp_path, _handoff(["Chose polling for #12", "Deferred rescale to #13"]))
    assert (tmp_path / ".agent-history" / "DECISIONS.md").is_file()
    out = _run(capsys, "status", "--repo-root", str(tmp_path))
    assert "standing" not in out
    assert "decisions: 2" in out


def test_status_caps_at_the_newest_20_and_counts_the_rest(tmp_path, capsys):
    _create(tmp_path, _handoff(RULES_25))
    block = _standing_block(_run(capsys, "status", "--repo-root", str(tmp_path)))

    assert block[0] == "(+5 older standing lines in DECISIONS.md)"
    assert block[1:] == [_line(rule) for rule in RULES_25[5:]]  # rules 06..25, oldest first
    assert len(block[1:]) == schema.STANDING_LIMIT


def test_status_does_not_follow_a_symlinked_decisions_file(tmp_path, capsys):
    _create(tmp_path, VALID)
    outside = tmp_path / "outside.md"
    outside.write_text("- [2026-06-30][x] [standing] secret from outside\n", encoding="utf-8")
    try:
        (tmp_path / ".agent-history" / "DECISIONS.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available in this environment")
    assert reader.standing_decisions(tmp_path) == []
    assert "secret from outside" not in _run(capsys, "status", "--repo-root", str(tmp_path))


# --------------------------------------------------------------------------- #
# glue resume-prompt and RESUME_PROMPT.txt
# --------------------------------------------------------------------------- #


def test_resume_prompt_carries_standing_after_the_first_action(tmp_path, capsys):
    _create(
        tmp_path,
        _handoff(["[standing] No independent review unless asked", "Chose polling for #12"]),
    )
    prompt = _run(capsys, "resume-prompt", "--repo-root", str(tmp_path))

    assert prompt.index(FIRST_ACTION) < prompt.index(HEADING) < prompt.index(BEFORE_EDITING)
    assert f"{FIRST_ACTION}\n\n{HEADING}\n" in prompt
    assert _prompt_block(prompt) == [_line("[standing] No independent review unless asked")]
    assert "Chose polling" not in prompt
    # The command prints the generated file exactly, and the file still validates.
    assert prompt == (tmp_path / ".agent-history" / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    assert validator.validate_history(tmp_path) == []


@pytest.mark.parametrize("decisions", [None, ["Chose polling for #12"]])
def test_resume_prompt_is_unchanged_without_standing_lines(tmp_path, capsys, decisions):
    _create(tmp_path, _handoff(decisions))
    prompt = _run(capsys, "resume-prompt", "--repo-root", str(tmp_path))
    assert HEADING not in prompt
    # Byte-identical to the prompt generated before #140.
    assert prompt == schema.build_resume_prompt(schema.Handoff.from_text(VALID))


def test_resume_prompt_caps_like_status(tmp_path, capsys):
    _create(tmp_path, _handoff(RULES_25))
    block = _prompt_block(_run(capsys, "resume-prompt", "--repo-root", str(tmp_path)))
    assert block[0] == "(+5 older standing lines in DECISIONS.md)"
    assert block[1:] == [_line(rule) for rule in RULES_25[5:]]


def test_later_handoff_without_decisions_still_carries_earlier_standing(tmp_path, capsys):
    _create(tmp_path, _handoff(["[standing] Tool X is excluded"]))
    _create(tmp_path, _handoff(session_id=SUCCESSOR_ID))
    prompt = _run(capsys, "resume-prompt", "--repo-root", str(tmp_path))
    assert _prompt_block(prompt) == [_line("[standing] Tool X is excluded")]


def test_create_accepts_decisions_with_or_without_the_prefix(tmp_path, capsys):
    # Bare and quoted scalars, prefixed and not: no schema change, all accepted.
    extra = 'decisions:\n  - [standing] Bare prefixed ruling\n  - "Quoted one-off for #12"\n'
    _create(tmp_path, _handoff(extra=extra))
    decisions = (tmp_path / ".agent-history" / "DECISIONS.md").read_text(encoding="utf-8")
    assert _line("[standing] Bare prefixed ruling") in decisions
    assert _line("Quoted one-off for #12") in decisions
    out = _run(capsys, "status", "--repo-root", str(tmp_path))
    assert _standing_block(out) == [_line("[standing] Bare prefixed ruling")]
    assert "validation: OK" in out


# --------------------------------------------------------------------------- #
# Shared rendering and the vault's rebuilt prompt
# --------------------------------------------------------------------------- #


def test_render_standing_cap_boundaries():
    lines = [f"- [d][s] [standing] r{n}" for n in range(21)]
    assert schema.render_standing([]) == []
    assert schema.render_standing(lines[:20]) == lines[:20]
    assert schema.render_standing(lines) == [
        "(+1 older standing lines in DECISIONS.md)",
        *lines[1:],
    ]
    assert schema.standing_lines("# Decisions\n\nheader\n- [d][s] plain\n") == []


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


def test_vault_import_rebuilds_the_prompt_with_standing_lines(tmp_path):
    """Pull rebuilds RESUME_PROMPT.txt; it must match what ``glue create`` wrote."""
    source = tmp_path / "laptop"
    source.mkdir()
    frontmatter = _vault_frontmatter(
        source, "2026-08-28-1200-alpha", ["[standing] Tool X is excluded"]
    )
    handoff = schema.Handoff.from_frontmatter(frontmatter, _VAULT_BODY)
    writer.create_handoff(
        repo_root=source, frontmatter=frontmatter, body=_VAULT_BODY, handoff=handoff
    )
    created = (source / ".agent-history" / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    assert "[standing] Tool X is excluded" in created

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(source, vault_root, "alpha")
    other = tmp_path / "desktop"
    other.mkdir()
    vault.import_project(other, vault_root, "alpha")

    rebuilt = (other / ".agent-history" / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    assert _prompt_block(rebuilt) == [
        "- [2026-08-28][2026-08-28-1200-alpha] [standing] Tool X is excluded"
    ]
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
    assert HEADING not in derived["RESUME_PROMPT.txt"]
    assert derived["RESUME_PROMPT.txt"] == (
        root / ".agent-history" / "RESUME_PROMPT.txt"
    ).read_text(encoding="utf-8")
