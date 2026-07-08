"""Tests for the ``glue create`` core file writer.

All tests write only under pytest's ``tmp_path`` — they never touch the real
user home, the network, or the OS clipboard.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from session_glue import writer
from session_glue.cli import main
from session_glue.schema import Handoff, parse_frontmatter, parse_mapping

FIXTURES = Path(__file__).parent / "fixtures" / "handoffs"
VALID = (FIXTURES / "valid.md").read_text(encoding="utf-8")
# Derive expected values from the fixture so they never drift from valid.md.
_FIXTURE = Handoff.from_text(VALID)
FIRST_ACTION = _FIXTURE.next_todo_items[0]
SESSION_ID = _FIXTURE.session_id


def _create(tmp_path: Path, text: str) -> int:
    src = tmp_path / "handoff-in.md"
    src.write_text(text, encoding="utf-8")
    return main(["create", "--input", str(src), "--repo-root", str(tmp_path)])


def _history(tmp_path: Path) -> Path:
    return tmp_path / ".agent-history"


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_create_writes_all_required_files(tmp_path):
    rc = _create(tmp_path, VALID)
    assert rc == 0
    hist = _history(tmp_path)
    assert (hist / "LATEST.md").is_file()
    assert (hist / "RESUME_PROMPT.txt").is_file()
    assert (hist / "INDEX.yaml").is_file()
    assert (hist / "sessions" / f"{SESSION_ID}.md").is_file()


def test_archive_and_latest_are_consistent(tmp_path):
    _create(tmp_path, VALID)
    hist = _history(tmp_path)
    archive = (hist / "sessions" / f"{SESSION_ID}.md").read_text(encoding="utf-8")
    latest = (hist / "LATEST.md").read_text(encoding="utf-8")
    assert archive == latest
    # Archived document is itself a valid, re-parseable handoff.
    reparsed = Handoff.from_text(archive)
    assert reparsed.is_valid()
    assert reparsed.session_id == SESSION_ID


def test_resume_prompt_generated(tmp_path):
    _create(tmp_path, VALID)
    prompt = (_history(tmp_path) / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    assert ".agent-history/LATEST.md" in prompt
    assert FIRST_ACTION in prompt


def test_index_mirrors_first_next_action_and_is_compact(tmp_path):
    _create(tmp_path, VALID)
    index = parse_mapping((_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8"))
    assert index["first_next_action"] == FIRST_ACTION
    assert index["latest_session"] == SESSION_ID
    assert index["latest_file"] == f"sessions/{SESSION_ID}.md"
    for key in ("schema_version", "repo_root", "current_branch", "head_commit"):
        assert key in index
    session = index["sessions"][0]
    assert session["first_next_action"] == FIRST_ACTION
    # The compact list must not duplicate the full next_todo_items.
    assert "next_todo_items" not in session
    # The index pointer and the actual archived file agree.
    assert session["file"] == f"sessions/{SESSION_ID}.md"


def test_index_mirrors_primary_goal_and_search_tags(tmp_path):
    _create(tmp_path, VALID)
    index = parse_mapping((_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8"))
    # Top-level latest block.
    assert index["primary_goal"] == _FIXTURE.primary_goal
    assert index["search_tags"] == "charts, polling, react"
    # Per-session entry mirrors the same quality fields (scalar-joined tags).
    session = index["sessions"][0]
    assert session["primary_goal"] == _FIXTURE.primary_goal
    assert session["search_tags"] == "charts, polling, react"


# --------------------------------------------------------------------------- #
# Re-run behavior
# --------------------------------------------------------------------------- #


def test_rerun_adds_archive_and_updates_latest(tmp_path):
    second_id = "2026-07-01-0900-second-session"
    second = VALID.replace(SESSION_ID, second_id)

    assert _create(tmp_path, VALID) == 0
    assert _create(tmp_path, second) == 0

    hist = _history(tmp_path)
    sessions_dir = hist / "sessions"
    archives = sorted(p.name for p in sessions_dir.glob("*.md"))
    assert archives == [f"{SESSION_ID}.md", f"{second_id}.md"]

    # LATEST + INDEX now point at the second session.
    latest = Handoff.from_text((hist / "LATEST.md").read_text(encoding="utf-8"))
    assert latest.session_id == second_id
    index = parse_mapping((hist / "INDEX.yaml").read_text(encoding="utf-8"))
    assert index["latest_session"] == second_id
    assert index["latest_file"] == f"sessions/{second_id}.md"
    assert [s["session_id"] for s in index["sessions"]] == [SESSION_ID, second_id]


def test_rerun_same_session_replaces_index_entry(tmp_path):
    assert _create(tmp_path, VALID) == 0
    assert _create(tmp_path, VALID) == 0
    index = parse_mapping((_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8"))
    # Same session_id must not accumulate duplicate index entries.
    assert [s["session_id"] for s in index["sessions"]] == [SESSION_ID]


# --------------------------------------------------------------------------- #
# Append-only decisions log (issue #44)
# --------------------------------------------------------------------------- #

_DECISIONS_FRONT = (
    "status: in_progress\n"
    "decisions:\n"
    '  - "Chose polling over websockets for simplicity"\n'
    '  - "Deferred the Y-axis rescale fix"\n'
)
VALID_WITH_DECISIONS = VALID.replace("status: in_progress\n", _DECISIONS_FRONT, 1)


def _decisions_lines(tmp_path: Path) -> list[str]:
    text = (_history(tmp_path) / "DECISIONS.md").read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if ln.startswith("- [")]


def test_no_decisions_creates_no_decisions_file(tmp_path):
    _create(tmp_path, VALID)  # valid.md carries no decisions
    assert not (_history(tmp_path) / "DECISIONS.md").exists()


def test_first_create_writes_decisions_header_and_lines(tmp_path):
    _create(tmp_path, VALID_WITH_DECISIONS)
    text = (_history(tmp_path) / "DECISIONS.md").read_text(encoding="utf-8")
    assert text.startswith("# Decisions\n")
    assert "Append-only log of durable decisions" in text
    lines = _decisions_lines(tmp_path)
    assert lines == [
        f"- [2026-06-30][{SESSION_ID}] Chose polling over websockets for simplicity",
        f"- [2026-06-30][{SESSION_ID}] Deferred the Y-axis rescale fix",
    ]


def test_rerun_same_session_does_not_duplicate_decisions(tmp_path):
    _create(tmp_path, VALID_WITH_DECISIONS)
    _create(tmp_path, VALID_WITH_DECISIONS)
    assert len(_decisions_lines(tmp_path)) == 2  # deduped, not 4


def test_second_session_appends_after_first(tmp_path):
    _create(tmp_path, VALID_WITH_DECISIONS)
    second = VALID_WITH_DECISIONS.replace(SESSION_ID, "2026-07-01-0900-second")
    second = second.replace("Deferred the Y-axis rescale fix", "Adopted the DECISIONS.md log")
    _create(tmp_path, second)
    lines = _decisions_lines(tmp_path)
    # First session's two lines are preserved (append-only), second session adds its own.
    assert len(lines) == 4
    assert lines[0] == f"- [2026-06-30][{SESSION_ID}] Chose polling over websockets for simplicity"
    assert any("2026-07-01-0900-second] Adopted the DECISIONS.md log" in ln for ln in lines)


# --------------------------------------------------------------------------- #
# Archive slug-collision guard (issue #35)
# --------------------------------------------------------------------------- #

# Two distinct session_ids that slugify to the same archive base name.
_COLLIDE_A = "team-alpha"
_COLLIDE_B = "team/alpha"


def test_slug_collision_pair_actually_collides():
    # Guard the guard: if slugify ever changed so these no longer collide, the
    # collision tests below would silently stop testing a collision.
    assert writer.slugify_session_name(_COLLIDE_A) == writer.slugify_session_name(_COLLIDE_B)
    assert _COLLIDE_A != _COLLIDE_B


def test_slug_collision_different_session_id_fails_loud_with_no_partial_state(tmp_path):
    assert _create(tmp_path, VALID.replace(SESSION_ID, _COLLIDE_A)) == 0
    hist = _history(tmp_path)
    slug = writer.slugify_session_name(_COLLIDE_A)
    archive = hist / "sessions" / f"{slug}.md"

    # Snapshot every artifact the first session produced.
    before_archive = archive.read_text(encoding="utf-8")
    before_latest = (hist / "LATEST.md").read_text(encoding="utf-8")
    before_index = (hist / "INDEX.yaml").read_text(encoding="utf-8")
    assert Handoff.from_text(before_archive).session_id == _COLLIDE_A

    # A different session_id that collides on the slug must fail loud (rc 1 via
    # the CLI's HandoffWriteError handler), not clobber the first session.
    rc = _create(tmp_path, VALID.replace(SESSION_ID, _COLLIDE_B))
    assert rc == 1

    # No partial state: archive, LATEST.md, and INDEX.yaml are byte-for-byte
    # unchanged, and there is still exactly one archive file.
    assert archive.read_text(encoding="utf-8") == before_archive
    assert (hist / "LATEST.md").read_text(encoding="utf-8") == before_latest
    assert (hist / "INDEX.yaml").read_text(encoding="utf-8") == before_index
    assert [p.name for p in (hist / "sessions").glob("*.md")] == [f"{slug}.md"]


def test_slug_collision_error_is_raised_by_writer_directly(tmp_path):
    # Direct-writer assertion that the failure is a HandoffWriteError naming both
    # sessions, independent of the CLI exit-code mapping.
    assert _create(tmp_path, VALID.replace(SESSION_ID, _COLLIDE_A)) == 0
    text_b = VALID.replace(SESSION_ID, _COLLIDE_B)
    frontmatter, body = parse_frontmatter(text_b)
    handoff_b = Handoff.from_frontmatter(frontmatter, body)
    with pytest.raises(writer.HandoffWriteError) as exc_info:
        writer.create_handoff(
            repo_root=tmp_path, frontmatter=frontmatter, body=body, handoff=handoff_b
        )
    message = str(exc_info.value)
    assert _COLLIDE_A in message and _COLLIDE_B in message


def test_same_session_id_recreate_still_overwrites(tmp_path):
    # Idempotent re-freeze is preserved: the same session_id may be re-created,
    # overwriting the archive with the newer body.
    assert _create(tmp_path, VALID.replace(SESSION_ID, _COLLIDE_A)) == 0
    updated = VALID.replace(SESSION_ID, _COLLIDE_A).replace(
        "Add polling lifecycle with cleanup", "Add polling lifecycle with cleanup and retries"
    )
    assert _create(tmp_path, updated) == 0
    hist = _history(tmp_path)
    slug = writer.slugify_session_name(_COLLIDE_A)
    archive = (hist / "sessions" / f"{slug}.md").read_text(encoding="utf-8")
    assert "Add polling lifecycle with cleanup and retries" in archive
    index = parse_mapping((hist / "INDEX.yaml").read_text(encoding="utf-8"))
    # No duplicate archive files and no duplicate index entries.
    assert [p.name for p in (hist / "sessions").glob("*.md")] == [f"{slug}.md"]
    assert [s["session_id"] for s in index["sessions"]] == [_COLLIDE_A]


def test_unparseable_existing_archive_is_not_clobbered(tmp_path):
    assert _create(tmp_path, VALID.replace(SESSION_ID, _COLLIDE_A)) == 0
    hist = _history(tmp_path)
    slug = writer.slugify_session_name(_COLLIDE_A)
    archive = hist / "sessions" / f"{slug}.md"

    # Corrupt the on-disk archive so its frontmatter can no longer be parsed.
    garbage = "this file is no longer a valid handoff\n"
    archive.write_text(garbage, encoding="utf-8")

    # Re-creating the SAME session_id must fail loud rather than silently clobber
    # an archive we can't verify.
    rc = _create(tmp_path, VALID.replace(SESSION_ID, _COLLIDE_A))
    assert rc == 1
    assert archive.read_text(encoding="utf-8") == garbage


# --------------------------------------------------------------------------- #
# Validation / rejection
# --------------------------------------------------------------------------- #


def test_missing_field_handoff_is_rejected_and_writes_nothing(tmp_path):
    invalid = (FIXTURES / "invalid_missing_field.md").read_text(encoding="utf-8")
    rc = _create(tmp_path, invalid)
    assert rc == 2
    assert not _history(tmp_path).exists()


def test_resume_mechanic_first_action_is_rejected(tmp_path):
    invalid = (FIXTURES / "invalid_next_action.md").read_text(encoding="utf-8")
    rc = _create(tmp_path, invalid)
    assert rc == 2
    assert not _history(tmp_path).exists()


def test_non_handoff_input_is_rejected(tmp_path):
    rc = _create(tmp_path, "just some text, no frontmatter\n")
    assert rc == 2
    assert not _history(tmp_path).exists()


# --------------------------------------------------------------------------- #
# Safety / determinism
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "etc-passwd"),
        ("a/b/c", "a-b-c"),
        ("....", "session"),
        ("", "session"),
        (None, "session"),
        (SESSION_ID, SESSION_ID),  # an already-safe id slugifies to itself
    ],
)
def test_slugify_prevents_path_traversal(raw, expected):
    assert writer.slugify_session_name(raw) == expected


def test_traversal_session_id_stays_inside_sessions_dir(tmp_path):
    text = VALID.replace(SESSION_ID, "../escape")
    assert _create(tmp_path, text) == 0
    sessions_dir = _history(tmp_path) / "sessions"
    written = list(sessions_dir.glob("*.md"))
    assert len(written) == 1
    # Resolves to a path inside the sessions directory — no escape.
    assert written[0].resolve().parent == sessions_dir.resolve()
    assert not (tmp_path.parent / "escape.md").exists()


def _repo_and_outside(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    return repo, outside


def _create_in(repo: Path, text: str) -> int:
    src = repo / "handoff-in.md"
    src.write_text(text, encoding="utf-8")
    return main(["create", "--input", str(src), "--repo-root", str(repo)])


def test_symlinked_agent_history_dir_is_rejected(tmp_path):
    repo, outside = _repo_and_outside(tmp_path)
    (repo / ".agent-history").symlink_to(outside, target_is_directory=True)
    rc = _create_in(repo, VALID)
    assert rc == 1
    # Nothing was written through the symlink into the outside directory.
    assert list(outside.iterdir()) == []


def test_symlinked_sessions_dir_is_rejected(tmp_path):
    repo, outside = _repo_and_outside(tmp_path)
    (repo / ".agent-history").mkdir()
    (repo / ".agent-history" / "sessions").symlink_to(outside, target_is_directory=True)
    rc = _create_in(repo, VALID)
    assert rc == 1
    assert list(outside.iterdir()) == []


def test_symlinked_output_file_is_rejected(tmp_path):
    repo, outside = _repo_and_outside(tmp_path)
    (repo / ".agent-history").mkdir()
    evil = outside / "stolen.md"
    (repo / ".agent-history" / "LATEST.md").symlink_to(evil)
    rc = _create_in(repo, VALID)
    assert rc == 1
    # The symlink target outside the repo must not have been created/written.
    assert not evil.exists()


def test_symlinked_decisions_file_is_rejected(tmp_path):
    repo, outside = _repo_and_outside(tmp_path)
    (repo / ".agent-history").mkdir()
    evil = outside / "stolen-decisions.md"
    (repo / ".agent-history" / "DECISIONS.md").symlink_to(evil)
    rc = _create_in(repo, VALID_WITH_DECISIONS)
    assert rc == 1
    # The write is rejected before any output, so nothing leaks through the symlink.
    assert not evil.exists()


def test_create_reads_from_stdin(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(VALID))
    rc = main(["create", "--repo-root", str(tmp_path)])
    assert rc == 0
    assert (_history(tmp_path) / "LATEST.md").is_file()


def test_create_does_not_write_outside_agent_history(tmp_path):
    _create(tmp_path, VALID)
    # Only the input file and .agent-history/ exist at the repo root.
    top_level = sorted(p.name for p in tmp_path.iterdir())
    assert top_level == [".agent-history", "handoff-in.md"]


# --------------------------------------------------------------------------- #
# Supersession links + glue close (issue #45)
# --------------------------------------------------------------------------- #


def _with_supersedes(text: str, prior_id: str) -> str:
    """Inject a ``supersedes:`` line into a handoff's frontmatter."""
    return text.replace(
        "status: in_progress\n", f"status: in_progress\nsupersedes: {prior_id}\n", 1
    )


def test_supersedes_mirrored_into_index_entry(tmp_path):
    # First session has no supersedes -> mirrors an empty string.
    assert _create(tmp_path, VALID) == 0
    second_id = "2026-07-01-0900-second-session"
    second = _with_supersedes(VALID.replace(SESSION_ID, second_id), SESSION_ID)
    assert _create(tmp_path, second) == 0

    index = parse_mapping((_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8"))
    entries = {s["session_id"]: s for s in index["sessions"]}
    assert entries[SESSION_ID]["supersedes"] == ""
    assert entries[second_id]["supersedes"] == SESSION_ID


def test_unknown_supersedes_warns_but_still_writes(tmp_path, capsys):
    text = _with_supersedes(VALID, "2020-01-01-0000-does-not-exist")
    rc = _create(tmp_path, text)
    assert rc == 0  # fail-open: an unknown reference never blocks the freeze
    err = capsys.readouterr().err
    assert "supersedes references unknown session id" in err
    assert (_history(tmp_path) / "LATEST.md").is_file()


def test_known_supersedes_does_not_warn(tmp_path, capsys):
    assert _create(tmp_path, VALID) == 0
    capsys.readouterr()
    second = _with_supersedes(VALID.replace(SESSION_ID, "2026-07-01-second"), SESSION_ID)
    assert _create(tmp_path, second) == 0
    assert "unknown session id" not in capsys.readouterr().err


def test_close_updates_status_in_index_only(tmp_path):
    assert _create(tmp_path, VALID) == 0
    hist = _history(tmp_path)
    archive = hist / "sessions" / f"{SESSION_ID}.md"
    before_archive = archive.read_bytes()
    before_latest = (hist / "LATEST.md").read_bytes()

    assert main(["close", "--repo-root", str(tmp_path), "--status", "DONE"]) == 0

    index = parse_mapping((hist / "INDEX.yaml").read_text(encoding="utf-8"))
    entry = index["sessions"][0]
    assert entry["session_id"] == SESSION_ID
    assert entry["status"] == "DONE"
    # Archives are immutable: archive + LATEST.md bytes are untouched.
    assert archive.read_bytes() == before_archive
    assert (hist / "LATEST.md").read_bytes() == before_latest


def test_close_unknown_session_errors(tmp_path, capsys):
    assert _create(tmp_path, VALID) == 0
    rc = main(
        ["close", "--repo-root", str(tmp_path), "--session", "no-such-session", "--status", "DONE"]
    )
    assert rc == 1
    assert "unknown session id" in capsys.readouterr().err


def test_close_defaults_to_latest_session(tmp_path):
    assert _create(tmp_path, VALID) == 0
    second_id = "2026-07-01-0900-second-session"
    assert _create(tmp_path, VALID.replace(SESSION_ID, second_id)) == 0
    assert main(["close", "--repo-root", str(tmp_path), "--status", "BLOCKED"]) == 0

    index = parse_mapping((_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8"))
    entries = {s["session_id"]: s for s in index["sessions"]}
    # Only the latest session's status changed; the earlier one is untouched.
    assert entries[second_id]["status"] == "BLOCKED"
    assert entries[SESSION_ID]["status"] == "in_progress"


def test_close_done_clears_first_next_action(tmp_path):
    assert _create(tmp_path, VALID) == 0
    before = parse_mapping((_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8"))
    assert before["first_next_action"]  # non-empty before close

    assert main(["close", "--repo-root", str(tmp_path), "--status", "DONE"]) == 0
    index = parse_mapping((_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8"))
    assert index["first_next_action"] == ""


def test_close_blocked_keeps_first_next_action(tmp_path):
    assert _create(tmp_path, VALID) == 0
    expected = parse_mapping(
        (_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8")
    )["first_next_action"]
    assert main(["close", "--repo-root", str(tmp_path), "--status", "BLOCKED"]) == 0
    index = parse_mapping((_history(tmp_path) / "INDEX.yaml").read_text(encoding="utf-8"))
    assert index["first_next_action"] == expected


def test_close_no_index_errors(tmp_path, capsys):
    rc = main(["close", "--repo-root", str(tmp_path), "--status", "DONE"])
    assert rc == 1
    assert "no INDEX.yaml" in capsys.readouterr().err


def test_close_symlinked_index_is_rejected(tmp_path):
    repo, outside = _repo_and_outside(tmp_path)
    assert _create_in(repo, VALID) == 0
    index_path = repo / ".agent-history" / "INDEX.yaml"
    stolen = outside / "stolen-index.yaml"
    index_path.unlink()
    index_path.symlink_to(stolen)
    rc = main(["close", "--repo-root", str(repo), "--status", "DONE"])
    assert rc == 1
    # Nothing was written through the symlink into the outside directory.
    assert not stolen.exists()


def test_close_symlinked_history_dir_is_rejected(tmp_path):
    repo, outside = _repo_and_outside(tmp_path)
    (repo / ".agent-history").symlink_to(outside, target_is_directory=True)
    rc = main(["close", "--repo-root", str(repo), "--status", "DONE"])
    assert rc == 1
    assert list(outside.iterdir()) == []
