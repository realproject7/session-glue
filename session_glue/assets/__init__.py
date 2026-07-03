"""Package-owned skill assets bundled with Session Glue.

These files let a PyPI-installed Session Glue provide agent skill templates
(Codex, Claude) and the shared fallback protocol without requiring the source
repository checkout. They ship as package data in both the wheel and the sdist;
see ``tests/test_package_assets.py``.

Layout, per agent, mirrors the repository ``codex-skills/`` skill format so a
future installer can copy a bundle out install-ready::

    session_glue/assets/skills/
        codex/session-glue/SKILL.md
        codex/session-glue/agents/openai.yaml
        codex/session-glue/references/protocol.md
        claude/session-glue/SKILL.md
        claude/session-glue/references/protocol.md
"""

from __future__ import annotations

from importlib.resources import files

#: Agents that ship a bundled skill under ``skills/<agent>/session-glue/``.
SKILL_AGENTS = ("codex", "claude")


def skills_root():
    """Return the bundled ``skills`` directory as an importlib.resources path.

    The result is a ``Traversable``; use ``joinpath`` / ``is_file`` /
    ``read_text`` to reach individual assets so this works whether Session Glue
    is imported from a source checkout or an installed wheel.
    """
    return files(__name__).joinpath("skills")


def skill_dir(agent):
    """Return the bundled ``session-glue`` skill directory for ``agent``."""
    if agent not in SKILL_AGENTS:
        raise ValueError(f"unknown skill agent: {agent!r}; expected one of {SKILL_AGENTS}")
    return skills_root().joinpath(agent, "session-glue")
