"""Core file writer for ``glue create``.

This module persists a handoff (its parsed frontmatter plus narrative body) into
a repository-local ``.agent-history/`` directory:

- ``.agent-history/sessions/<session>.md`` — an archived, timestamped copy
- ``.agent-history/LATEST.md`` — a copy of the newest handoff
- ``.agent-history/RESUME_PROMPT.txt`` — the copy-paste resume prompt
- ``.agent-history/INDEX.yaml`` — compact metadata + a session list

It is intentionally small and deterministic: no network access, no OS clipboard,
no subprocess, and no writes outside ``<repo_root>/.agent-history/``. Everything
it needs comes from the handoff the agent composed.
"""

from __future__ import annotations

import re
from pathlib import Path

from .schema import (
    Handoff,
    build_index_entry,
    build_resume_prompt,
    dump_mapping,
    parse_mapping,
)

AGENT_HISTORY_DIRNAME = ".agent-history"
SESSIONS_DIRNAME = "sessions"
LATEST_FILENAME = "LATEST.md"
RESUME_PROMPT_FILENAME = "RESUME_PROMPT.txt"
INDEX_FILENAME = "INDEX.yaml"

_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class HandoffWriteError(Exception):
    """Raised when a handoff cannot be written safely (e.g. a symlink escape)."""


def _reject_symlink(path: Path) -> None:
    """Refuse to follow a symlink at ``path``.

    A pre-existing symlink at ``.agent-history``, ``sessions/``, or one of the
    output files could redirect writes outside ``repo_root``. Issue #4 forbids
    mutating files outside the current repo, so we reject rather than follow.
    """
    if path.is_symlink():
        raise HandoffWriteError(f"refusing to write through a symlink: {path}")


def _assert_within(path: Path, root_resolved: Path) -> None:
    """Assert ``path`` resolves to a location inside ``root_resolved``."""
    resolved = path.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise HandoffWriteError(f"refusing to write outside the repo root: {path}")


def slugify_session_name(session_id: str | None) -> str:
    """Turn a ``session_id`` into a safe single-path-segment archive base name.

    Strips directory separators and other unsafe characters so the archive is
    always written inside ``.agent-history/sessions/`` (no path traversal).
    """
    name = _UNSAFE_NAME_RE.sub("-", (session_id or "").strip())
    name = name.strip("-. ")
    return name or "session"


def render_document(frontmatter: dict, body: str) -> str:
    """Render a handoff markdown document from its frontmatter and body."""
    front = dump_mapping(frontmatter)
    body_text = body.rstrip("\n")
    if body_text:
        return f"---\n{front}\n---\n\n{body_text}\n"
    return f"---\n{front}\n---\n"


def _session_entry(handoff: Handoff, archive_file: str) -> dict:
    """Build the compact ``INDEX.yaml`` session entry for a handoff.

    Reuses :func:`schema.build_index_entry` but pins ``file`` to the *actual*
    archive path so the index and the archived file never disagree.
    """
    entry = build_index_entry(handoff)
    entry["file"] = archive_file
    return entry


def build_index(existing: dict | None, handoff: Handoff, archive_file: str) -> dict:
    """Build the updated ``INDEX.yaml`` mapping after archiving ``handoff``.

    The just-archived session becomes ``latest_*``; its entry replaces any prior
    entry with the same ``session_id`` and is appended to the session list. The
    full ``next_todo_items`` list is deliberately not duplicated here — only
    ``first_next_action`` (via :func:`_session_entry`).
    """
    sessions: list = []
    if existing and isinstance(existing.get("sessions"), list):
        sessions = [
            s
            for s in existing["sessions"]
            if not (isinstance(s, dict) and s.get("session_id") == handoff.session_id)
        ]
    sessions.append(_session_entry(handoff, archive_file))

    return {
        "schema_version": handoff.schema_version if handoff.schema_version is not None else 1,
        "latest_session": handoff.session_id,
        "latest_file": archive_file,
        "repo_root": handoff.repo_root,
        "current_branch": handoff.current_branch,
        "head_commit": handoff.head_commit,
        "first_next_action": handoff.first_next_action,
        "sessions": sessions,
    }


def create_handoff(
    repo_root: Path,
    frontmatter: dict,
    body: str,
    handoff: Handoff,
    archive_name: str | None = None,
) -> dict[str, Path]:
    """Write the handoff into ``<repo_root>/.agent-history/`` and update pointers.

    Returns a mapping of ``{"archive"|"latest"|"resume_prompt"|"index": Path}``.
    Creates ``.agent-history/`` (and ``sessions/``) if missing.
    """
    name = slugify_session_name(archive_name or handoff.session_id)
    archive_file = f"{SESSIONS_DIRNAME}/{name}.md"

    root = Path(repo_root)
    root_resolved = root.resolve()
    history_dir = root / AGENT_HISTORY_DIRNAME
    sessions_dir = history_dir / SESSIONS_DIRNAME

    archive_path = sessions_dir / f"{name}.md"
    latest_path = history_dir / LATEST_FILENAME
    resume_path = history_dir / RESUME_PROMPT_FILENAME
    index_path = history_dir / INDEX_FILENAME

    # Safety checks BEFORE creating directories or writing anything, so a
    # rejected write leaves no partial state.
    _reject_symlink(history_dir)
    _reject_symlink(sessions_dir)
    for path in (archive_path, latest_path, resume_path, index_path):
        _reject_symlink(path)

    sessions_dir.mkdir(parents=True, exist_ok=True)

    # After creating the dirs, confirm they resolve inside repo_root (catches a
    # symlinked ancestor directory).
    _assert_within(history_dir, root_resolved)
    _assert_within(sessions_dir, root_resolved)

    document = render_document(frontmatter, body)

    archive_path.write_text(document, encoding="utf-8")
    latest_path.write_text(document, encoding="utf-8")
    resume_path.write_text(build_resume_prompt(handoff), encoding="utf-8")

    existing_index: dict | None = None
    if index_path.exists():
        try:
            existing_index = parse_mapping(index_path.read_text(encoding="utf-8"))
        except Exception:
            # A corrupt/unreadable index is rebuilt from scratch rather than
            # aborting the write; the newest session is authoritative.
            existing_index = None
    index = build_index(existing_index, handoff, archive_file)
    index_path.write_text(dump_mapping(index) + "\n", encoding="utf-8")

    return {
        "archive": archive_path,
        "latest": latest_path,
        "resume_prompt": resume_path,
        "index": index_path,
    }
