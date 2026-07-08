"""Validation for a repository-local ``.agent-history/`` directory.

Backs ``glue validate``. Checks that the handoff artifacts written by
``glue create`` are internally consistent:

- ``LATEST.md`` has valid frontmatter (required fields + a productive
  ``next_todo_items[0]``, not a resume mechanic)
- ``RESUME_PROMPT.txt`` exists
- ``INDEX.yaml`` parses and its ``first_next_action`` matches ``LATEST.md``'s
  ``next_todo_items[0]``
- optionally, archived session files under ``sessions/`` validate too

It returns a list of human-readable problems; an empty list means valid. No
network and no LLM — the ``next_todo_items[0]`` guard is the conservative phrase
heuristic from :mod:`session_glue.schema`. Validation itself runs no subprocess;
a subprocess (git) runs only for the optional drift check behind the explicit
``glue validate --git`` flag, which is advisory and never changes the result.
"""

from __future__ import annotations

from pathlib import Path

from .schema import Handoff, HandoffParseError, parse_mapping
from .writer import (
    AGENT_HISTORY_DIRNAME,
    INDEX_FILENAME,
    LATEST_FILENAME,
    RESUME_PROMPT_FILENAME,
    SESSIONS_DIRNAME,
)


def _validate_latest(latest_path: Path) -> tuple[list[str], Handoff | None]:
    """Validate ``LATEST.md``; return (problems, parsed handoff or None)."""
    if not latest_path.is_file():
        return ([f"missing {LATEST_FILENAME}"], None)
    try:
        handoff = Handoff.from_text(latest_path.read_text(encoding="utf-8"))
    except HandoffParseError as exc:
        return ([f"{LATEST_FILENAME}: {exc}"], None)
    return ([f"{LATEST_FILENAME}: {err}" for err in handoff.validate()], handoff)


def _validate_index(index_path: Path, latest: Handoff | None) -> list[str]:
    """Validate ``INDEX.yaml`` and its consistency with ``LATEST.md`` and disk.

    Cross-file checks (issue #36): ``first_next_action`` and ``latest_session``
    must agree with ``LATEST.md``; ``latest_file`` and every ``sessions[]`` entry
    file must exist on disk. Index paths are relative to ``.agent-history/`` (the
    directory that holds ``INDEX.yaml``).
    """
    if not index_path.is_file():
        return [f"missing {INDEX_FILENAME}"]
    try:
        index = parse_mapping(index_path.read_text(encoding="utf-8"))
    except HandoffParseError as exc:
        return [f"{INDEX_FILENAME}: {exc}"]

    history = index_path.parent
    problems: list[str] = []

    if latest is not None:
        index_action = index.get("first_next_action")
        latest_action = latest.first_next_action
        if index_action != latest_action:
            problems.append(
                f"{INDEX_FILENAME}.first_next_action ({index_action!r}) does not match "
                f"{LATEST_FILENAME} next_todo_items[0] ({latest_action!r})"
            )
        latest_session = index.get("latest_session")
        if latest_session != latest.session_id:
            problems.append(
                f"{INDEX_FILENAME}.latest_session ({latest_session!r}) does not match "
                f"{LATEST_FILENAME} session_id ({latest.session_id!r})"
            )

    latest_file = index.get("latest_file")
    if isinstance(latest_file, str) and latest_file:
        resolved = _history_relative_path(history, latest_file)
        if resolved is None:
            problems.append(
                f"{INDEX_FILENAME}.latest_file ({latest_file!r}) is outside "
                f"{AGENT_HISTORY_DIRNAME}/"
            )
        elif not resolved.is_file():
            problems.append(
                f"{INDEX_FILENAME}.latest_file ({latest_file!r}) does not exist on disk"
            )

    problems.extend(_validate_index_sessions(index.get("sessions"), history))
    return problems


def _history_relative_path(history: Path, value: str) -> Path | None:
    """Resolve an index file value under ``history``, or ``None`` if it escapes it.

    ``INDEX.yaml`` file values must be relative paths that stay inside
    ``.agent-history/``. An absolute path or a ``..`` escape is rejected
    (returns ``None``) so a malformed/hostile index can neither probe files
    outside the repo's ``.agent-history/`` nor silently pass by pointing the
    existence check at an unrelated file that happens to exist.
    """
    if Path(value).is_absolute():
        return None
    candidate = (history / value).resolve()
    hist = history.resolve()
    if candidate == hist or hist in candidate.parents:
        return candidate
    return None


def _validate_index_sessions(sessions: object, history: Path) -> list[str]:
    """Check that every ``sessions[]`` entry's ``file`` points at an existing file.

    Malformed data (a non-list ``sessions``, a non-mapping entry, a bad ``file``
    value, or a ``file`` that escapes ``.agent-history/``) yields its own problem
    line rather than crashing validation.
    """
    if sessions is None:
        return []
    if not isinstance(sessions, list):
        return [f"{INDEX_FILENAME}.sessions is not a list"]

    problems: list[str] = []
    for i, entry in enumerate(sessions):
        if not isinstance(entry, dict):
            problems.append(f"{INDEX_FILENAME}.sessions[{i}] is not a mapping")
            continue
        if "file" not in entry:
            continue
        entry_file = entry.get("file")
        if not isinstance(entry_file, str) or not entry_file:
            problems.append(f"{INDEX_FILENAME}.sessions[{i}].file is malformed ({entry_file!r})")
            continue
        resolved = _history_relative_path(history, entry_file)
        if resolved is None:
            problems.append(
                f"{INDEX_FILENAME}.sessions[{i}].file ({entry_file!r}) is outside "
                f"{AGENT_HISTORY_DIRNAME}/"
            )
        elif not resolved.is_file():
            problems.append(
                f"{INDEX_FILENAME}.sessions[{i}].file ({entry_file!r}) does not exist on disk"
            )
    return problems


def _validate_sessions(sessions_dir: Path) -> list[str]:
    """Validate every archived session markdown file under ``sessions/``."""
    problems: list[str] = []
    if not sessions_dir.is_dir():
        return problems
    for path in sorted(sessions_dir.glob("*.md")):
        rel = f"{SESSIONS_DIRNAME}/{path.name}"
        try:
            handoff = Handoff.from_text(path.read_text(encoding="utf-8"))
        except HandoffParseError as exc:
            problems.append(f"{rel}: {exc}")
            continue
        problems.extend(f"{rel}: {err}" for err in handoff.validate())
    return problems


def validate_history(repo_root: Path, check_sessions: bool = False) -> list[str]:
    """Validate ``<repo_root>/.agent-history/``; return a list of problems.

    An empty list means the handoff artifacts are valid. When ``check_sessions``
    is true, archived session files under ``sessions/`` are validated as well.
    """
    history = Path(repo_root) / AGENT_HISTORY_DIRNAME
    if not history.is_dir():
        return [f"no {AGENT_HISTORY_DIRNAME}/ directory at {history}"]

    problems, latest = _validate_latest(history / LATEST_FILENAME)

    resume_path = history / RESUME_PROMPT_FILENAME
    if not resume_path.is_file():
        problems.append(f"missing {RESUME_PROMPT_FILENAME}")
    elif latest is not None and latest.first_next_action is not None:
        # Freshness, not just presence: a prompt regenerated by an older
        # generator (or left stale after LATEST.md changed) would otherwise
        # validate clean. The first productive action must appear verbatim.
        action = str(latest.first_next_action)
        if action not in resume_path.read_text(encoding="utf-8"):
            problems.append(
                f"{RESUME_PROMPT_FILENAME} is stale: it does not contain "
                f"{LATEST_FILENAME} next_todo_items[0] ({action!r})"
            )

    problems.extend(_validate_index(history / INDEX_FILENAME, latest))

    if check_sessions:
        problems.extend(_validate_sessions(history / SESSIONS_DIRNAME))

    return problems
