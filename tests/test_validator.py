"""Tests for ``glue validate`` and the next-action lint.

Each test builds a real ``.agent-history/`` with ``glue create`` under
pytest's ``tmp_path`` (no real home, no network), then validates it — mutating
copies to exercise the invalid cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_glue.cli import main
from session_glue.schema import Handoff, lint_first_next_action

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"
VALID = (FIXTURES / "valid.md").read_text(encoding="utf-8")
MISSING_FIELD = (FIXTURES / "invalid_missing_field.md").read_text(encoding="utf-8")
# Derive expected values from the fixture so they never drift from valid.md.
_FIXTURE = Handoff.from_text(VALID)
FIRST_ACTION = _FIXTURE.next_todo_items[0]
SESSION_ID = _FIXTURE.session_id


def _build_history(repo: Path) -> Path:
    src = repo / "in.md"
    src.write_text(VALID, encoding="utf-8")
    assert main(["create", "--input", str(src), "--repo-root", str(repo)]) == 0
    return repo / ".agent-history"


def _validate(repo: Path, *extra: str) -> int:
    return main(["validate", "--repo-root", str(repo), *extra])


def _drop_lines(text: str, prefix: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith(prefix)) + "\n"


# --------------------------------------------------------------------------- #
# Valid
# --------------------------------------------------------------------------- #


def test_validate_ok_for_valid_history(tmp_path, capsys):
    _build_history(tmp_path)
    assert _validate(tmp_path) == 0
    assert "OK" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Invalid cases (each acceptance criterion)
# --------------------------------------------------------------------------- #


def test_validate_catches_missing_required_field(tmp_path, capsys):
    hist = _build_history(tmp_path)
    # invalid_missing_field.md drops head_commit but keeps the same first action,
    # so only the missing-field problem is reported (no index mismatch).
    (hist / "LATEST.md").write_text(MISSING_FIELD, encoding="utf-8")
    assert _validate(tmp_path) == 1
    assert "head_commit" in capsys.readouterr().err


def test_validate_catches_index_mismatch(tmp_path, capsys):
    hist = _build_history(tmp_path)
    index = hist / "INDEX.yaml"
    index.write_text(
        index.read_text(encoding="utf-8").replace(FIRST_ACTION, "Do the next productive thing"),
        encoding="utf-8",
    )
    assert _validate(tmp_path) == 1
    assert "does not match" in capsys.readouterr().err


def test_validate_catches_resume_mechanic_first_action(tmp_path, capsys):
    hist = _build_history(tmp_path)
    mechanic = "Paste the prompt into the new chat"
    # Rewrite LATEST.md AND INDEX.yaml so the ONLY problem is the lint, not a
    # first_next_action mismatch.
    (hist / "LATEST.md").write_text(VALID.replace(FIRST_ACTION, mechanic), encoding="utf-8")
    index = hist / "INDEX.yaml"
    index.write_text(
        index.read_text(encoding="utf-8").replace(FIRST_ACTION, mechanic), encoding="utf-8"
    )
    assert _validate(tmp_path) == 1
    assert "resume mechanic" in capsys.readouterr().err


def test_validate_reports_missing_resume_prompt(tmp_path, capsys):
    hist = _build_history(tmp_path)
    (hist / "RESUME_PROMPT.txt").unlink()
    assert _validate(tmp_path) == 1
    assert "RESUME_PROMPT.txt" in capsys.readouterr().err


def test_validate_reports_missing_history(tmp_path, capsys):
    assert _validate(tmp_path) == 1
    assert ".agent-history" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Archived session validation is opt-in (--sessions)
# --------------------------------------------------------------------------- #


def test_sessions_flag_validates_archived_files(tmp_path, capsys):
    hist = _build_history(tmp_path)
    archive = hist / "sessions" / f"{SESSION_ID}.md"
    archive.write_text(_drop_lines(archive.read_text(encoding="utf-8"), "head_commit:"), "utf-8")

    # Without --sessions the corrupt archive is ignored (LATEST/INDEX still fine).
    assert _validate(tmp_path) == 0
    # With --sessions it is caught.
    assert _validate(tmp_path, "--sessions") == 1
    err = capsys.readouterr().err
    assert f"sessions/{SESSION_ID}.md" in err
    assert "head_commit" in err


# --------------------------------------------------------------------------- #
# Next-action lint phrase coverage (issue #5 critical lint)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "item",
    [
        "Start a new session",
        "Paste the prompt",
        "Read LATEST.md",
        "Read `LATEST.md`",  # markdown-backtick form
        "Inspect the handoff",
        "Inspect handoff",
        "Inspect LATEST.md",
        "Inspect `LATEST.md`",  # markdown-backtick form (issue #5 explicit case)
        "Verify resume worked",
        "Check whether the new agent resumed correctly",
    ],
)
def test_lint_flags_resume_mechanics(item):
    assert lint_first_next_action(item) is not None


@pytest.mark.parametrize(
    "item",
    [
        "Add polling lifecycle with cleanup",
        "Fix the Y-axis scaling bug when data is empty",
        "Reconcile the manual resume experiment note with the latest validation results",
    ],
)
def test_lint_allows_productive_actions(item):
    assert lint_first_next_action(item) is None
