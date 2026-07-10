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

# Required frontmatter fields, in canonical order.
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
    "primary_goal",
    "active_context_files",
    "completed_tasks",
    "next_todo_items",
    "known_issues",
    "search_tags",
    "validation",
)

# Required fields whose value must be a YAML block sequence (a list).
_LIST_FIELDS: frozenset[str] = frozenset(
    {
        "active_context_files",
        "completed_tasks",
        "next_todo_items",
        "known_issues",
        "search_tags",
        "validation",
    }
)

# Allowed values for a ``validation`` entry's ``result`` field. ``not_run`` is a
# first-class value: it records a check that was defined but deliberately not
# executed this session, rather than silently omitting the check.
VALIDATION_RESULTS: frozenset[str] = frozenset({"passed", "failed", "not_run"})

# Canonical narrative section headings the handoff body must contain, in order.
# Validation checks for their presence at line start only (exact ``# `` level and
# text) — it never inspects or scores the prose beneath them. A body missing any
# of these is rejected; an empty body names all eight.
REQUIRED_BODY_SECTIONS: tuple[str, ...] = (
    "# Resume Prompt",
    "# What We Did",
    "# Current State",
    "# Decisions Made",
    "# Failed Attempts / Dead Ends",
    "# Next-Agent Instructions",
    "# Commands And Validation",
    "# Risks And Constraints",
)

# List-valued fields that are allowed to be present-but-empty. ``next_todo_items``
# is deliberately excluded: it must contain at least a first productive action.
_LIST_FIELDS_ALLOW_EMPTY: frozenset[str] = frozenset(
    {"active_context_files", "completed_tasks", "known_issues"}
)

# Case-insensitive mechanic verb+object phrases that signal a resume mechanic
# rather than a productive work item. Guardrail only — not a semantic judge.
#
# Each phrase is matched with word boundaries and whitespace-insensitive gaps
# (see ``_MECHANIC_PATTERNS``), NOT as a bare substring. Bare tokens like
# "paste", "new session", or "resume prompt" are deliberately avoided: they
# false-positive on ordinary work items ("Add paste support…", "Implement the
# new session naming scheme…", "Fix the resume prompt generator bug…"). Only a
# concrete verb+object phrase ("paste the prompt", "start a new session",
# "read latest.md") should trip the lint.
RESUME_MECHANIC_PHRASES: tuple[str, ...] = (
    "paste the prompt",
    "paste the resume prompt",
    "paste resume prompt",
    "paste resume_prompt",
    "start a new session",
    "start a new agent session",
    "read latest.md",
    "read the handoff",
    "read the latest handoff",
    "inspect the handoff",
    "inspect handoff",
    "inspect latest.md",
    "verify that resume",
    "verify resume",
    "check whether the new agent",
)

# Precompiled word-boundary matchers for each phrase. Spaces in a phrase match
# any run of whitespace, and ``\b`` anchors prevent partial-word hits (so
# "paste the prompt" never matches inside "pasted" and "read latest.md" needs
# the whole token). Text is lowercased before matching, so patterns are too.
_MECHANIC_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = tuple(
    (
        phrase,
        re.compile(r"\b" + r"\s+".join(re.escape(word) for word in phrase.split()) + r"\b"),
    )
    for phrase in RESUME_MECHANIC_PHRASES
)


class HandoffParseError(ValueError):
    """Raised when a handoff document cannot be parsed."""


# --------------------------------------------------------------------------- #
# Constrained YAML subset parser/serializer
# --------------------------------------------------------------------------- #

# A block-sequence item that begins a mapping, e.g. ``- path: src/foo.py``.
_MAPPING_ITEM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:\s")
# An all-integer scalar (used only for ``schema_version`` coercion).
_INT_RE = re.compile(r"-?\d+$")
# A YAML block-scalar indicator standing alone as a value (``|``, ``>``, ``>-``,
# ``|-`` ...): the shape of a multi-line value, which this subset rejects.
_BLOCK_SCALAR_RE = re.compile(r"[|>][-+]?\d*$")


def _parse_scalar(token: str) -> Any:
    """Parse a single scalar value (quoted string, ``[]`` literal, or bare string).

    Double-quoted strings are unescaped so they round-trip with
    :func:`_dump_scalar`, which escapes ``\\`` and ``"``. A ``#`` is literal
    content everywhere — inside both quoted strings and bare scalars (issue
    references like ``#207`` are common handoff vocabulary); inline comments are
    NOT supported, only whole-line comments. The literal ``[]`` is the only
    flow-style form accepted and parses
    to an empty list (``[a, b]`` is deliberately unsupported and stays a string,
    which then fails the list-field check loudly). Integers are NOT coerced here:
    all-digit values keep their literal string so identifiers like a numeric
    ``head_commit`` are not silently turned into ints (``schema_version`` is the
    one field coerced, in :func:`parse_mapping`).
    """
    token = token.strip()
    if len(token) >= 2 and token[0] in "\"'" and token[-1] == token[0]:
        inner = token[1:-1]
        if token[0] == '"':
            # Reverse _dump_scalar's escaping in a single left-to-right pass:
            # ``\\`` -> ``\`` and ``\"`` -> ``"``.
            inner = re.sub(r"\\(.)", lambda m: m.group(1), inner)
        return inner
    if token == "[]":
        return []
    return token


def _coerce_schema_version(value: Any) -> Any:
    """Coerce an all-digit ``schema_version`` value to ``int``; leave others as-is."""
    if isinstance(value, str) and _INT_RE.match(value):
        return int(value)
    return value


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
            # A value spilling onto an indented continuation line: this subset
            # keeps every value on one line, so explain that instead of the old
            # cryptic "unexpected indentation" message.
            raise HandoffParseError(
                "multi-line YAML values are not supported — keep each value on "
                f"one line (unexpected indentation at: {raw!r})"
            )
        if ":" not in raw:
            raise HandoffParseError(f"expected 'key: value', got: {raw!r}")

        key, _, rest = raw.partition(":")
        key = key.strip()
        if key in data:
            raise HandoffParseError(f"duplicate top-level key: {key!r}")
        rest = rest.strip()
        if rest and _BLOCK_SCALAR_RE.match(rest):
            # ``key: |`` / ``key: >-`` etc. introduce a multi-line block scalar.
            raise HandoffParseError(
                "multi-line YAML values are not supported — keep each value on one line"
            )
        if rest:
            value = _parse_scalar(rest)
            if key == "schema_version":
                value = _coerce_schema_version(value)
            data[key] = value
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
    primary_goal: str | None = None
    active_context_files: list[Any] = field(default_factory=list)
    completed_tasks: list[Any] = field(default_factory=list)
    next_todo_items: list[Any] = field(default_factory=list)
    known_issues: list[Any] = field(default_factory=list)
    search_tags: list[Any] = field(default_factory=list)
    validation: list[Any] = field(default_factory=list)
    # Optional: durable decisions made this session (scalars). Absence is fine —
    # not a required field. Appended to the append-only DECISIONS.md log.
    decisions: list[Any] = field(default_factory=list)
    # Optional: the prior session_id this handoff replaces (a scalar). Absence is
    # fine; when present it must be a non-empty scalar. Mirrored into each
    # INDEX.yaml session entry (empty string when absent) so session chains stay
    # visible from the index alone.
    supersedes: str | None = None
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
                    continue
                if name not in _LIST_FIELDS_ALLOW_EMPTY and len(value) == 0:
                    errors.append(f"required field is empty: {name}")
                # No individual list entry may be an empty/blank string. This is
                # the second half of the #72 fix: even if a value were somehow
                # emptied, an empty entry now fails loudly per index instead of
                # passing validation silently.
                for idx, item in enumerate(value):
                    if isinstance(item, str) and not item.strip():
                        errors.append(f"{name}[{idx}] must not be empty")
                continue
            if value is None or (isinstance(value, str) and len(value) == 0):
                errors.append(f"required field is empty: {name}")

        # Every next_todo_items entry must be a scalar (string or number). A
        # mapping/list entry would otherwise render its Python repr — e.g.
        # "{'task': 'do x'}" — into RESUME_PROMPT.txt and INDEX.first_next_action.
        if isinstance(self.next_todo_items, list):
            for idx, item in enumerate(self.next_todo_items):
                if not isinstance(item, (str, int)):
                    errors.append(
                        f"next_todo_items[{idx}] must be a scalar (string or number), "
                        f"not {type(item).__name__}"
                    )

        # Every validation entry must be a command/result/notes mapping so the
        # quality record is machine-checkable and never renders a Python repr.
        # ``result`` must be one of passed/failed/not_run.
        if isinstance(self.validation, list):
            for idx, item in enumerate(self.validation):
                if not isinstance(item, dict):
                    errors.append(
                        f"validation[{idx}] must be a command/result/notes mapping, "
                        f"not {type(item).__name__}"
                    )
                    continue
                command = item.get("command")
                if not isinstance(command, (str, int)) or (
                    isinstance(command, str) and not command.strip()
                ):
                    errors.append(
                        f"validation[{idx}].command is required and must be a non-empty scalar"
                    )
                result = item.get("result")
                if result not in VALIDATION_RESULTS:
                    errors.append(
                        f"validation[{idx}].result must be one of "
                        f"passed/failed/not_run, got {result!r}"
                    )
                # ``notes`` is optional commentary — command + result are the
                # machine-checkable record; forcing notes on every entry only
                # produces boilerplate filler.

        # ``decisions`` is optional: absence is fine. When present it must be a
        # list of scalars (one durable decision per entry) so each line appends
        # cleanly to DECISIONS.md without rendering a Python repr.
        if "decisions" in self.present_fields:
            if not isinstance(self.decisions, list):
                errors.append("optional field must be a list: decisions")
            else:
                for idx, item in enumerate(self.decisions):
                    if not isinstance(item, (str, int)):
                        errors.append(
                            f"decisions[{idx}] must be a scalar (string or number), "
                            f"not {type(item).__name__}"
                        )

        # ``supersedes`` is optional: absence is fine. When present it names the
        # prior session this handoff replaces and is mirrored verbatim into
        # INDEX.yaml, so it must be a single non-empty scalar (an empty or
        # non-scalar link would give the index a meaningless lineage value).
        if "supersedes" in self.present_fields:
            value = self.supersedes
            if not isinstance(value, (str, int)) or (
                isinstance(value, str) and not value.strip()
            ):
                errors.append("supersedes must be a non-empty scalar")

        if "next_todo_items" in self.present_fields:
            lint = lint_first_next_action(self.first_next_action)
            if lint:
                errors.append(lint)

        # The narrative body must carry the canonical section skeleton so a
        # resumed agent finds a predictable structure. Headings only — the prose
        # beneath them is never inspected or scored. Every missing heading is
        # reported in a single error (an empty body names all eight) rather than
        # one error per heading. Match at line start with the exact ``# `` level.
        body_headings = {line.rstrip() for line in self.body.splitlines()}
        missing_sections = [h for h in REQUIRED_BODY_SECTIONS if h not in body_headings]
        if missing_sections:
            errors.append(
                "missing required body section(s): " + ", ".join(missing_sections)
            )
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
    for phrase, pattern in _MECHANIC_PATTERNS:
        if pattern.search(text):
            return (
                f"next_todo_items[0] looks like a resume mechanic "
                f"(matched {phrase!r}); it must be the first productive work item"
            )
    return None


# --------------------------------------------------------------------------- #
# Derived artifacts: INDEX.yaml entry and RESUME_PROMPT.txt
# --------------------------------------------------------------------------- #


def join_search_tags(tags: Any) -> str:
    """Mirror ``search_tags`` into a single greppable ``INDEX.yaml`` scalar.

    The constrained INDEX serializer only supports scalar values inside a session
    entry (a block sequence of single-level mappings), so tags are mirrored as a
    comma-joined string rather than a nested list — enough for "which session dealt
    with <topic>?" to be answerable from ``INDEX.yaml`` alone, without a parser
    change.
    """
    if not isinstance(tags, list):
        return ""
    return ", ".join(str(tag) for tag in tags)


def build_index_entry(handoff: Handoff) -> dict[str, Any]:
    """Build a compact ``INDEX.yaml`` session entry for a handoff.

    ``first_next_action`` mirrors ``next_todo_items[0]``; ``search_tags`` is
    mirrored as a comma-joined scalar (see :func:`join_search_tags`); optional
    ``supersedes`` is mirrored as a scalar, using an empty string when absent to
    preserve the scalar-only index constraint. The full ``next_todo_items`` list
    is intentionally omitted so the index does not compete with the canonical
    handoff file.
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
        "primary_goal": handoff.primary_goal,
        "search_tags": join_search_tags(handoff.search_tags),
        "supersedes": handoff.supersedes if handoff.supersedes is not None else "",
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
        "Prompt artifact: .agent-history/RESUME_PROMPT.txt\n"
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
