"""Handoff schema helpers for Session Glue.

This module defines the structured representation of a handoff document's YAML
frontmatter, plus helpers that later CLI commands (``glue create``,
``glue validate``, ``glue resume-prompt``) will build on:

- a constrained, dependency-free parser/serializer for markdown files with YAML
  frontmatter (a small YAML subset — no PyYAML requirement, so behavior is
  deterministic across environments)
- required-field validation
- a heuristic lint that rejects obvious resume-mechanic ``next_todo_items[0]``
- an ``INDEX.yaml`` entry builder whose ``first_next_action`` mirrors
  ``next_todo_items[0]``
- a ``RESUME_PROMPT.txt`` generator

No ``.agent-history/`` files are written here and no full CLI command is
implemented; this is the schema/fixture foundation only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Any

# Required frontmatter fields, in canonical order (see the founding ticket
# "Handoff schema and fixture library").
REQUIRED_FIELDS: tuple[str, ...] = (
    "session_id",
    "session_date",
    "generated_at",
    "schema_version",
    "project_root",
    "repo_root",
    "current_branch",
    "head_commit",
    "agent",
    "status",
    "active_context_files",
    "completed_tasks",
    "next_todo_items",
    "known_issues",
)

# Required fields whose value must be a YAML block sequence (a list).
_LIST_FIELDS: frozenset[str] = frozenset(
    {"active_context_files", "completed_tasks", "next_todo_items", "known_issues"}
)

# List-valued fields that are allowed to be present-but-empty. ``next_todo_items``
# is deliberately excluded: it must contain at least a first productive action.
_LIST_FIELDS_ALLOW_EMPTY: frozenset[str] = frozenset(
    {"active_context_files", "completed_tasks", "known_issues"}
)

# Case-insensitive phrases that signal a resume mechanic rather than a
# productive work item. Guardrail only — not a semantic judge (see proposal
# §10.2 and the ticket "Critical Rule").
RESUME_MECHANIC_PHRASES: tuple[str, ...] = (
    "paste",
    "start a new session",
    "new session",
    "read latest",
    "read latest.md",
    "resume prompt",
    "inspect the handoff",
    "inspect handoff",
    "inspect latest",
    "verify that resume",
    "verify resume",
    "check whether the new agent",
)


class HandoffParseError(ValueError):
    """Raised when a handoff document cannot be parsed."""


# --------------------------------------------------------------------------- #
# Constrained YAML subset parser/serializer
# --------------------------------------------------------------------------- #

# A block-sequence item that begins a mapping, e.g. ``- path: src/foo.py``.
_MAPPING_ITEM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:\s")
# A top-level ``key: ...`` line.
_INT_RE = re.compile(r"-?\d+$")


def _parse_scalar(token: str) -> Any:
    """Parse a single scalar value (quoted string, integer, or bare string).

    Double-quoted strings are unescaped so they round-trip with
    :func:`_dump_scalar`, which escapes ``\\`` and ``"``. Single-quoted strings
    are taken literally (the serializer only ever emits double quotes).
    """
    token = token.strip()
    if len(token) >= 2 and token[0] in "\"'" and token[-1] == token[0]:
        inner = token[1:-1]
        if token[0] == '"':
            # Reverse _dump_scalar's escaping in a single left-to-right pass:
            # ``\\`` -> ``\`` and ``\"`` -> ``"``.
            inner = re.sub(r"\\(.)", lambda m: m.group(1), inner)
        return inner
    if _INT_RE.match(token):
        return int(token)
    return token


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_sequence(block: list[str]) -> list[Any]:
    """Parse an indented block into a list of scalars and/or mappings."""
    items: list[Any] = []
    i, n = 0, len(block)
    while i < n:
        line = block[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        stripped = line.strip()
        if not stripped.startswith("-"):
            raise HandoffParseError(f"expected a list item, got: {line!r}")

        dash_indent = _indent(line)
        after = stripped[1:].strip()

        if _MAPPING_ITEM_RE.match(after):
            # Mapping item: first key on the dash line, remaining keys on more
            # deeply indented continuation lines.
            mapping: dict[str, Any] = {}
            key, _, value = after.partition(":")
            mapping[key.strip()] = _parse_scalar(value)
            i += 1
            while i < n:
                cont = block[i]
                if not cont.strip() or cont.strip().startswith("#"):
                    i += 1
                    continue
                if cont.strip().startswith("-") or _indent(cont) <= dash_indent:
                    break
                ck, _, cv = cont.strip().partition(":")
                mapping[ck.strip()] = _parse_scalar(cv)
                i += 1
            items.append(mapping)
        else:
            items.append(_parse_scalar(after))
            i += 1
    return items


def parse_mapping(text: str) -> dict[str, Any]:
    """Parse a constrained YAML mapping (top-level ``key: value`` block).

    Supports scalar values, block sequences of scalars, and block sequences of
    single-level mappings. This is intentionally minimal — enough for handoff
    frontmatter and ``INDEX.yaml``, not a general YAML implementation.
    """
    lines = text.splitlines()
    data: dict[str, Any] = {}
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        if not raw.strip() or raw.strip().startswith("#"):
            i += 1
            continue
        if raw[0] in " \t":
            raise HandoffParseError(f"unexpected indentation at top level: {raw!r}")
        if ":" not in raw:
            raise HandoffParseError(f"expected 'key: value', got: {raw!r}")

        key, _, rest = raw.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            data[key] = _parse_scalar(rest)
            i += 1
            continue

        # Empty value: gather the following indented (or blank) lines as a block.
        block: list[str] = []
        i += 1
        while i < n and (not lines[i].strip() or lines[i][:1] in " \t"):
            block.append(lines[i])
            i += 1
        data[key] = _parse_sequence(block)
    return data


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown document into (frontmatter mapping, body).

    The document must begin with a ``---`` delimiter line, contain the YAML
    frontmatter, and a closing ``---`` line. Everything after the closing
    delimiter is returned as the body.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise HandoffParseError("handoff must begin with a '---' frontmatter delimiter")

    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        raise HandoffParseError("unterminated frontmatter (missing closing '---')")

    frontmatter = parse_mapping("\n".join(lines[1:end]))
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return frontmatter, body


def _dump_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    needs_quotes = (
        text == ""
        or text != text.strip()
        or any(ch in text for ch in ":#")
        or text[0] in "\"'-"
    )
    if needs_quotes:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def dump_mapping(data: dict[str, Any]) -> str:
    """Serialize a mapping back into the constrained YAML subset."""
    out: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            out.append(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    first = True
                    for k, v in item.items():
                        prefix = "  - " if first else "    "
                        out.append(f"{prefix}{k}: {_dump_scalar(v)}")
                        first = False
                else:
                    out.append(f"  - {_dump_scalar(item)}")
        else:
            out.append(f"{key}: {_dump_scalar(value)}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Structured handoff representation
# --------------------------------------------------------------------------- #


@dataclass
class Handoff:
    """Structured view of a handoff document's frontmatter (plus body).

    Fields default to ``None`` / empty so that malformed handoffs can still be
    constructed and then reported by :meth:`validate` rather than raising on
    construction. Use :meth:`from_text` / :meth:`from_frontmatter` to build one.
    """

    session_id: str | None = None
    session_date: str | None = None
    generated_at: str | None = None
    schema_version: int | None = None
    project_root: str | None = None
    repo_root: str | None = None
    current_branch: str | None = None
    head_commit: str | None = None
    agent: str | None = None
    status: str | None = None
    active_context_files: list[Any] = field(default_factory=list)
    completed_tasks: list[Any] = field(default_factory=list)
    next_todo_items: list[Any] = field(default_factory=list)
    known_issues: list[Any] = field(default_factory=list)
    body: str = ""
    # Keys actually present in the source frontmatter (drives presence checks).
    present_fields: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_frontmatter(cls, data: dict[str, Any], body: str = "") -> "Handoff":
        known = {f.name for f in fields(cls)} - {"body", "present_fields"}
        kwargs: dict[str, Any] = {}
        for name in known:
            if name in data:
                kwargs[name] = data[name]
        return cls(body=body, present_fields=frozenset(data), **kwargs)

    @classmethod
    def from_text(cls, text: str) -> "Handoff":
        data, body = parse_frontmatter(text)
        return cls.from_frontmatter(data, body)

    @property
    def first_next_action(self) -> Any:
        """The first productive action: ``next_todo_items[0]`` (or ``None``).

        Guards against a scalar ``next_todo_items`` (e.g. a bare string), which
        would otherwise yield its first *character* instead of ``None``.
        """
        items = self.next_todo_items
        if isinstance(items, list) and items:
            return items[0]
        return None

    def validate(self) -> list[str]:
        """Return a list of validation errors; empty means the handoff is valid."""
        errors: list[str] = []
        for name in REQUIRED_FIELDS:
            if name not in self.present_fields:
                errors.append(f"missing required field: {name}")
                continue
            value = getattr(self, name)
            if name in _LIST_FIELDS:
                # Must be a block sequence, not a scalar. A scalar here would let
                # ``next_todo_items[0]`` silently degrade to a single character.
                if not isinstance(value, list):
                    errors.append(f"required field must be a list: {name}")
                elif name not in _LIST_FIELDS_ALLOW_EMPTY and len(value) == 0:
                    errors.append(f"required field is empty: {name}")
                continue
            if value is None or (isinstance(value, str) and len(value) == 0):
                errors.append(f"required field is empty: {name}")

        if "next_todo_items" in self.present_fields:
            lint = lint_first_next_action(self.first_next_action)
            if lint:
                errors.append(lint)
        return errors

    def is_valid(self) -> bool:
        return not self.validate()


def lint_first_next_action(item: Any) -> str | None:
    """Return an error string if ``item`` looks like a resume mechanic, else None."""
    if item is None:
        return "next_todo_items[0] is missing"
    # Strip markdown code backticks so phrases match regardless of how the
    # action is typeset, e.g. "Inspect `LATEST.md`" -> "inspect latest.md".
    text = str(item).lower().replace("`", "")
    for phrase in RESUME_MECHANIC_PHRASES:
        if phrase in text:
            return (
                f"next_todo_items[0] looks like a resume mechanic "
                f"(matched {phrase!r}); it must be the first productive work item"
            )
    return None


# --------------------------------------------------------------------------- #
# Derived artifacts: INDEX.yaml entry and RESUME_PROMPT.txt
# --------------------------------------------------------------------------- #


def build_index_entry(handoff: Handoff) -> dict[str, Any]:
    """Build a compact ``INDEX.yaml`` session entry for a handoff.

    ``first_next_action`` mirrors ``next_todo_items[0]``; the full
    ``next_todo_items`` list is intentionally omitted so the index does not
    compete with the canonical handoff file.
    """
    return {
        "session_id": handoff.session_id,
        "file": f"sessions/{handoff.session_id}.md",
        "session_date": handoff.session_date,
        "generated_at": handoff.generated_at,
        "agent": handoff.agent,
        "project_root": handoff.project_root,
        "repo_root": handoff.repo_root,
        "current_branch": handoff.current_branch,
        "head_commit": handoff.head_commit,
        "status": handoff.status,
        "first_next_action": handoff.first_next_action,
    }


def build_resume_prompt(handoff: Handoff) -> str:
    """Generate the ``RESUME_PROMPT.txt`` body for a handoff.

    The prompt points the next session at ``.agent-history/LATEST.md`` and tells
    it to continue from the first ``next_todo_items`` entry.
    """
    project_root = handoff.project_root or "(unknown)"
    first_action = handoff.first_next_action or "(no next action recorded)"
    return (
        "Continue the previous coding session.\n"
        "\n"
        f"Project root: {project_root}\n"
        "First, read: .agent-history/LATEST.md\n"
        "Then follow the Resume Prompt and continue from the first "
        "next_todo_items entry.\n"
        "\n"
        "First productive next action (next_todo_items[0]):\n"
        f"{first_action}\n"
        "\n"
        "Before editing, run git status --short and report any drift from the "
        "handoff.\n"
        "Do not scan the whole repository unless the handoff is stale or "
        "insufficient.\n"
    )
