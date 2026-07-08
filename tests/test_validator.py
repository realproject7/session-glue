"""Tests for ``glue validate`` and the next-action lint.

Each test builds a real ``.agent-history/`` with ``glue create`` under
pytest's ``tmp_path`` (no real home, no network), then validates it — mutating
copies to exercise the invalid cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_glue.cli import main
from session_glue.schema import Handoff, dump_mapping, lint_first_next_action, parse_mapping

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
# Cross-file consistency checks (issue #36)
# --------------------------------------------------------------------------- #


def _rewrite_index(hist: Path, mutate) -> None:
    """Parse INDEX.yaml, apply ``mutate(index)`` in place, and write it back."""
    index_path = hist / "INDEX.yaml"
    index = parse_mapping(index_path.read_text(encoding="utf-8"))
    mutate(index)
    index_path.write_text(dump_mapping(index) + "\n", encoding="utf-8")


def test_validate_catches_latest_session_mismatch(tmp_path, capsys):
    hist = _build_history(tmp_path)
    _rewrite_index(hist, lambda idx: idx.update(latest_session="a-different-session"))
    assert _validate(tmp_path) == 1
    err = capsys.readouterr().err
    assert "latest_session" in err
    assert "does not match" in err


def test_validate_catches_missing_latest_file(tmp_path, capsys):
    hist = _build_history(tmp_path)
    _rewrite_index(hist, lambda idx: idx.update(latest_file="sessions/does-not-exist.md"))
    assert _validate(tmp_path) == 1
    err = capsys.readouterr().err
    assert "latest_file" in err
    assert "does not exist on disk" in err


def test_validate_catches_stale_resume_prompt(tmp_path, capsys):
    hist = _build_history(tmp_path)
    # A prompt that no longer mentions the recorded first_next_action (as if left
    # over from an older generator) must be caught — presence alone is not enough.
    (hist / "RESUME_PROMPT.txt").write_text(
        "Continue the previous coding session.\n(stale prompt, no next action)\n",
        encoding="utf-8",
    )
    assert _validate(tmp_path) == 1
    err = capsys.readouterr().err
    assert "RESUME_PROMPT.txt is stale" in err
    assert FIRST_ACTION in err


def test_validate_catches_dangling_session_entry_file(tmp_path, capsys):
    hist = _build_history(tmp_path)
    # Add an index entry pointing at an archive file that does not exist.
    _rewrite_index(
        hist,
        lambda idx: idx["sessions"].append(
            {"session_id": "ghost", "file": "sessions/ghost-missing.md"}
        ),
    )
    assert _validate(tmp_path) == 1
    err = capsys.readouterr().err
    assert "sessions/ghost-missing.md" in err
    assert "does not exist on disk" in err


def test_validate_reports_malformed_sessions_without_crashing(tmp_path, capsys):
    hist = _build_history(tmp_path)
    # A non-mapping session entry must produce its own problem line, not a crash.
    _rewrite_index(hist, lambda idx: idx["sessions"].append("not-a-mapping"))
    assert _validate(tmp_path) == 1
    assert "is not a mapping" in capsys.readouterr().err


def test_validate_reports_non_list_sessions_without_crashing(tmp_path, capsys):
    hist = _build_history(tmp_path)
    _rewrite_index(hist, lambda idx: idx.update(sessions="oops-a-scalar"))
    assert _validate(tmp_path) == 1
    assert "sessions is not a list" in capsys.readouterr().err


def test_validate_rejects_absolute_latest_file_even_if_it_exists(tmp_path, capsys):
    # Security boundary: an absolute latest_file that points at an existing file
    # outside .agent-history/ must be flagged, not silently pass the exists-check.
    hist = _build_history(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    _rewrite_index(hist, lambda idx: idx.update(latest_file=str(outside)))
    assert _validate(tmp_path) == 1
    err = capsys.readouterr().err
    assert "latest_file" in err
    assert "outside .agent-history/" in err
    assert "does not exist on disk" not in err


def test_validate_rejects_dotdot_escape_in_latest_file(tmp_path, capsys):
    hist = _build_history(tmp_path)
    _rewrite_index(hist, lambda idx: idx.update(latest_file="../../etc/passwd"))
    assert _validate(tmp_path) == 1
    err = capsys.readouterr().err
    assert "latest_file" in err
    assert "outside .agent-history/" in err


def test_validate_rejects_absolute_session_entry_file_even_if_it_exists(tmp_path, capsys):
    hist = _build_history(tmp_path)
    outside = tmp_path / "outside-session.md"
    outside.write_text("x", encoding="utf-8")
    _rewrite_index(
        hist,
        lambda idx: idx["sessions"].append({"session_id": "esc", "file": str(outside)}),
    )
    assert _validate(tmp_path) == 1
    err = capsys.readouterr().err
    assert "outside .agent-history/" in err
    assert "does not exist on disk" not in err


def test_validate_rejects_dotdot_escape_in_session_entry_file(tmp_path, capsys):
    hist = _build_history(tmp_path)
    _rewrite_index(
        hist,
        lambda idx: idx["sessions"].append(
            {"session_id": "esc", "file": "../../../etc/passwd"}
        ),
    )
    assert _validate(tmp_path) == 1
    assert "outside .agent-history/" in capsys.readouterr().err


def test_consistent_history_passes_all_cross_file_checks(tmp_path, capsys):
    # Negative case: an untouched, freshly created history satisfies every new
    # cross-file check with no problems reported.
    _build_history(tmp_path)
    assert _validate(tmp_path) == 0
    assert "OK" in capsys.readouterr().out


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
