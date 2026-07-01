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
network, no subprocess, no LLM — the ``next_todo_items[0]`` guard is the
conservative phrase heuristic from :mod:`session_glue.schema`.
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
    """Validate ``INDEX.yaml`` and its consistency with ``LATEST.md``."""
    if not index_path.is_file():
        return [f"missing {INDEX_FILENAME}"]
    try:
        index = parse_mapping(index_path.read_text(encoding="utf-8"))
    except HandoffParseError as exc:
        return [f"{INDEX_FILENAME}: {exc}"]

    problems: list[str] = []
    if latest is not None:
        index_action = index.get("first_next_action")
        latest_action = latest.first_next_action
        if index_action != latest_action:
            problems.append(
                f"{INDEX_FILENAME}.first_next_action ({index_action!r}) does not match "
                f"{LATEST_FILENAME} next_todo_items[0] ({latest_action!r})"
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

    if not (history / RESUME_PROMPT_FILENAME).is_file():
        problems.append(f"missing {RESUME_PROMPT_FILENAME}")

    problems.extend(_validate_index(history / INDEX_FILENAME, latest))

    if check_sessions:
        problems.extend(_validate_sessions(history / SESSIONS_DIRNAME))

    return problems
