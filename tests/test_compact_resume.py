"""Resume cost stays independent of history; authority stays recoverable (#148)."""

from pathlib import Path

from session_glue import schema, writer
from session_glue.cli import main


VALID = (Path(__file__).parent / "fixtures/handoffs/valid.md").read_text()


def _history(root):
    handoff = schema.Handoff.from_text(VALID)
    frontmatter, body = schema.parse_frontmatter(VALID)
    writer.create_handoff(
        repo_root=root, frontmatter=frontmatter, body=body,
        handoff=handoff,
    )
    return root / ".agent-history"


def _log():
    rule = '[standing] 2026-07-01 operator: "Proceed without a review unless asked"'
    lines = [f"- [2026-07-01][s{i}] {rule}" for i in range(3)]
    lines += [
        f'- [2026-07-01][s] [standing] 2026-07-01 operator: "rule {i}"'
        for i in range(25)
    ]
    lines += [
        f"- [2026-07-01][s] [hold] job {i}; reason: busy; until: idle"
        for i in range(25)
    ]
    lines += [f"- [2026-07-01][s] [standing] legacy note {i}" for i in range(50)]
    return "\n".join(lines) + "\n"


def test_prompt_size_does_not_grow_with_decision_history():
    handoff = schema.Handoff.from_text(VALID)
    empty = schema.build_resume_prompt(handoff)
    populated = schema.build_resume_prompt(handoff, _log())
    assert populated == empty
    assert len(populated.encode()) < 1024
    assert handoff.first_next_action in populated
    assert "glue status --repo-root ." in populated
    assert "lifecycle" in populated and "before acting" in populated


def test_status_keeps_all_authority_and_full_provenance_without_mutation(tmp_path, capsys):
    history = _history(tmp_path)
    (history / "DECISIONS.md").write_text(_log())
    before = {p: p.read_bytes() for p in history.rglob("*") if p.is_file()}
    assert main(["status", "--repo-root", str(tmp_path)]) == 0
    compact = capsys.readouterr().out
    assert compact.count('operator: "Proceed without') == 1
    for line in _log().splitlines()[:3]:
        assert schema.decision_ref(line) in compact
    for i in range(25):
        assert f'operator: "rule {i}"' in compact
        assert f"[hold] job {i};" in compact
    assert "legacy note 0" not in compact
    assert "50 live note(s)" in compact and "--full" in compact
    assert main(["status", "--full", "--repo-root", str(tmp_path)]) == 0
    full = capsys.readouterr().out
    for line in _log().splitlines():
        assert line[2:] in full
    assert before == {p: p.read_bytes() for p in history.rglob("*") if p.is_file()}


def test_retractions_apply_before_display_grouping(tmp_path, capsys):
    history = _history(tmp_path)
    lines = _log().splitlines()[:3]
    lines.append(f"[retracts {schema.decision_ref(lines[0])}]")
    (history / "DECISIONS.md").write_text("\n".join(lines))
    assert main(["status", "--repo-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert schema.decision_ref(lines[0]) not in out
    assert out.count('operator: "Proceed without') == 1
    assert all(schema.decision_ref(line) in out for line in lines[1:3])


def test_different_dates_and_quote_text_are_not_grouped(tmp_path, capsys):
    history = _history(tmp_path)
    lines = [
        '- [d][s] [standing] 2026-07-01 operator: "Go"',
        '- [d][s] [standing] 2026-07-02 operator: "Go"',
        '- [d][s] [standing] 2026-07-01 operator: "Go now"',
    ]
    (history / "DECISIONS.md").write_text("\n".join(lines))
    assert main(["status", "--repo-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert all(line[2:] in out for line in lines)


def test_size_advice_never_blocks_capture_or_validation(tmp_path, capsys):
    src = tmp_path / "input.md"
    src.write_text(VALID + "\n" + "Historical detail. " * 600)
    assert main(["create", "--repo-root", str(tmp_path), "--input", str(src)]) == 0
    assert "size advisory" in capsys.readouterr().err
    history = tmp_path / ".agent-history"
    (history / "RESUME_PROMPT.txt").write_text(
        schema.Handoff.from_text(VALID).first_next_action + "\n" + "x" * 2048
    )
    assert main(["validate", "--repo-root", str(tmp_path)]) == 0
    err = capsys.readouterr().err
    assert "LATEST.md" in err and "RESUME_PROMPT.txt" in err
    assert "size advisory" in err


def test_legacy_embedded_prompt_still_validates_and_prints_exactly(tmp_path, capsys):
    history = _history(tmp_path)
    legacy = (history / "RESUME_PROMPT.txt").read_text() + (
        '\nStanding operator rulings:\nold-id operator: "Existing instructions"\n'
    )
    (history / "RESUME_PROMPT.txt").write_text(legacy)
    assert main(["validate", "--repo-root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["resume-prompt", "--repo-root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == legacy
