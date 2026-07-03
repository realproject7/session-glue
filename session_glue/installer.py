"""Dry-run installer blocks for ``glue install <agent> --dry-run``.

This module only *describes* what Session Glue would add to a coding agent's
global instruction file — it renders the managed instruction block and the
target path. It never mutates user-home files, accesses the network or OS
clipboard, or performs a real install. Non-dry-run installation is intentionally
not implemented here (operator-gated).

The managed block is delimited by stable begin/end markers so a future updater
can replace it idempotently, and so existing installs can be detected.
"""

from __future__ import annotations

from dataclasses import dataclass

# Stable managed-block markers. These are part of the on-disk contract: keep
# them byte-for-byte stable so idempotent updates and detection keep working.
BEGIN_MARKER = "<!-- BEGIN SESSION GLUE (managed) -->"
END_MARKER = "<!-- END SESSION GLUE (managed) -->"

# Agent-agnostic body of the managed block. Tells any file-writing coding agent
# how to respond to the glue triggers while preserving the v1 constraints.
_BLOCK_BODY = """\
## Session Glue

When the user runs `/glue`, `/freeze`, `/handoff`, or `/checkpoint`, or asks in
natural language to glue / freeze / checkpoint / hand off the current session:

1. Compose a handoff document: YAML frontmatter (session_id, session_date,
   generated_at, schema_version, project_root, repo_root, current_branch,
   head_commit, agent, status, active_context_files, completed_tasks,
   next_todo_items, known_issues) plus a narrative body covering what changed,
   what is still broken, and what to do next. `next_todo_items[0]` MUST be the
   first productive work item, never a resume mechanic (do not write "read
   LATEST.md", "paste the prompt", "start a new session", etc.).
2. Run `glue create` to write the handoff into the repository-local
   `.agent-history/` directory (LATEST.md, RESUME_PROMPT.txt, INDEX.yaml, and
   sessions/<id>.md). Optionally run `glue validate` to check it.
3. Print the contents of `.agent-history/RESUME_PROMPT.txt` in a fenced code
   block so the operator can copy it into a fresh session.

Constraints:
- Write only the repository-local `.agent-history/` directory.
- Do not access the OS clipboard.
- Do not run a daemon, watcher, or any external/network service."""


@dataclass(frozen=True)
class AgentTarget:
    """Where a given agent's global instruction block lives (display only)."""

    name: str
    target: str
    note: str = ""


# Target instruction files per agent. Paths are shown in ``~`` form and are
# never opened or written during dry-run.
AGENT_TARGETS: dict[str, AgentTarget] = {
    "codex": AgentTarget("codex", "~/.codex/AGENTS.md"),
    "claude": AgentTarget(
        "claude",
        "~/.claude/skills/session-glue/",
        note="repo-scoped .claude/skills/session-glue/ is the recommended default; "
        "user scope is explicit and reversible",
    ),
    "cursor": AgentTarget(
        "cursor",
        "~/.cursor/rules/session-glue.md",
        note="or paste the block into Cursor Settings -> Rules for AI",
    ),
    "gemini": AgentTarget("gemini", "~/.gemini/GEMINI.md"),
}

# Order used when installing "all".
AGENT_ORDER: tuple[str, ...] = ("codex", "claude", "cursor", "gemini")


def managed_block() -> str:
    """Return the full managed instruction block, including begin/end markers."""
    return f"{BEGIN_MARKER}\n{_BLOCK_BODY}\n{END_MARKER}"


def has_managed_block(text: str) -> bool:
    """Return True if ``text`` already contains a Session Glue managed block."""
    return BEGIN_MARKER in text and END_MARKER in text


def resolve_agents(agent: str) -> list[AgentTarget]:
    """Resolve an agent name (or ``all``) to a list of targets.

    Raises ``KeyError`` for an unknown agent name.
    """
    if agent == "all":
        return [AGENT_TARGETS[name] for name in AGENT_ORDER]
    return [AGENT_TARGETS[agent]]
