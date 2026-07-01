"""Tests for ``glue status`` and ``glue resume-prompt`` (read-only commands).

Each test builds a real ``.agent-history/`` with ``glue create`` under pytest's
``tmp_path`` (no real home, no network), then reads it back.
"""

from __future__ import annotations

from pathlib import Path

from session_glue.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"
VALID = (FIXTURES / "valid.md").read_text(encoding="utf-8")
SESSION_ID = "2026-06-30-1530-chart-polling"
FIRST_ACTION = "Add polling lifecycle with cleanup"


def _build_history(repo: Path) -> Path:
    src = repo / "in.md"
    src.write_text(VALID, encoding="utf-8")
    assert main(["create", "--input", str(src), "--repo-root", str(repo)]) == 0
    return repo / ".agent-history"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --------------------------------------------------------------------------- #
# glue status
# --------------------------------------------------------------------------- #


def test_status_reports_compact_fields(tmp_path, capsys):
    _build_history(tmp_path)
    capsys.readouterr()  # drop the setup `glue create` output
    assert main(["status", "--repo-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert ".agent-history: present" in out
    assert SESSION_ID in out
    assert f"sessions/{SESSION_ID}.md" in out
    assert "current branch: main" in out
    assert "head commit: abc1234" in out
    assert FIRST_ACTION in out
    assert "validation: OK" in out


def test_status_does_not_print_full_narrative(tmp_path, capsys):
    _build_history(tmp_path)
    capsys.readouterr()  # drop the setup `glue create` output
    main(["status", "--repo-root", str(tmp_path)])
    out = capsys.readouterr().out
    # Token-economics: the session narrative body must not be reproduced.
    assert "Detailed Session Briefing" not in out


def test_status_handles_missing_history(tmp_path, capsys):
    code = main(["status", "--repo-root", str(tmp_path)])
    assert code == 1
    assert "no .agent-history/" in capsys.readouterr().out


def test_status_summarizes_validation_problems(tmp_path, capsys):
    hist = _build_history(tmp_path)
    (hist / "RESUME_PROMPT.txt").unlink()
    capsys.readouterr()  # drop the setup `glue create` output
    # Present history still reports (exit 0), but flags the validation problem.
    assert main(["status", "--repo-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "problem(s)" in out
    assert "RESUME_PROMPT.txt" in out


# --------------------------------------------------------------------------- #
# glue resume-prompt
# --------------------------------------------------------------------------- #


def test_resume_prompt_prints_exact_file_contents(tmp_path, capsys):
    hist = _build_history(tmp_path)
    expected = (hist / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    capsys.readouterr()  # drop the setup `glue create` output before the exact check
    assert main(["resume-prompt", "--repo-root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == expected


def test_resume_prompt_missing_is_reported(tmp_path, capsys):
    code = main(["resume-prompt", "--repo-root", str(tmp_path)])
    assert code == 1
    assert "RESUME_PROMPT.txt" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Read-only guarantee
# --------------------------------------------------------------------------- #


def test_status_and_resume_prompt_are_read_only(tmp_path):
    hist = _build_history(tmp_path)
    before = _snapshot(hist)
    main(["status", "--repo-root", str(tmp_path)])
    main(["resume-prompt", "--repo-root", str(tmp_path)])
    assert _snapshot(hist) == before
