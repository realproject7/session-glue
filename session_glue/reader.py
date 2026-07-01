"""Read-only helpers for ``glue status`` and ``glue resume-prompt``.

These commands orient the operator without recreating context bloat: ``status``
reports compact metadata from ``INDEX.yaml`` plus a cheap validation summary —
it deliberately does **not** read or print the full session narrative — and
``resume-prompt`` returns the exact contents of ``RESUME_PROMPT.txt``. Both are
strictly read-only: no writes, no network, no subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import HandoffParseError, parse_mapping
from .validator import validate_history
from .writer import AGENT_HISTORY_DIRNAME, INDEX_FILENAME, RESUME_PROMPT_FILENAME

# Compact fields surfaced by ``glue status``, in display order, mapped from
# their ``INDEX.yaml`` keys. The full ``next_todo_items`` narrative is never
# included (token-economics requirement).
STATUS_FIELDS: tuple[tuple[str, str], ...] = (
    ("latest session", "latest_session"),
    ("latest file", "latest_file"),
    ("current branch", "current_branch"),
    ("head commit", "head_commit"),
    ("first next action", "first_next_action"),
)


@dataclass
class Status:
    """A compact, read-only snapshot of ``.agent-history/`` state."""

    exists: bool
    history_dir: Path
    index: dict[str, Any] | None = None
    problems: list[str] = field(default_factory=list)


def collect_status(repo_root: Path, run_validation: bool = True) -> Status:
    """Gather compact status for ``<repo_root>/.agent-history/``.

    Reads only ``INDEX.yaml`` (plus a cheap, non-``--sessions`` validation pass
    when ``run_validation`` is true). Never reads archived session narratives.
    """
    history = Path(repo_root) / AGENT_HISTORY_DIRNAME
    if not history.is_dir():
        return Status(exists=False, history_dir=history)

    index: dict[str, Any] | None = None
    index_path = history / INDEX_FILENAME
    if index_path.is_file():
        try:
            index = parse_mapping(index_path.read_text(encoding="utf-8"))
        except HandoffParseError:
            index = None

    problems = validate_history(repo_root) if run_validation else []
    return Status(exists=True, history_dir=history, index=index, problems=problems)


def read_resume_prompt(repo_root: Path) -> str | None:
    """Return the exact contents of ``RESUME_PROMPT.txt``, or None if missing."""
    path = Path(repo_root) / AGENT_HISTORY_DIRNAME / RESUME_PROMPT_FILENAME
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
