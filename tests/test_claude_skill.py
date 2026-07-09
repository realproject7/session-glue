"""Content tests for the bundled Claude skill (issue #28).

These read the Claude skill from the *bundled package asset* — there is no
repository ``claude-skills/`` source, the Claude skill ships only in the package.
They cover the Claude-specific content: the ``name: session-glue`` frontmatter,
the full trigger set including the Korean triggers, the ``/session-glue``
invocation note, CLI-preferred guidance, and the ``references/protocol.md``
fallback link.

The Codex↔Claude ``protocol.md`` byte-identity drift guard already lives in
``test_package_assets.py`` (``test_shared_protocol_is_identical_across_bundles``)
and is intentionally not duplicated here.
"""

from __future__ import annotations

import session_glue.assets as assets

SKILL = assets.skill_dir("claude").joinpath("SKILL.md").read_text(encoding="utf-8")


def test_claude_skill_frontmatter_name_is_session_glue():
    assert SKILL.startswith("---")
    # The name lives in the frontmatter, above the body's first heading.
    frontmatter = SKILL.split("# Session Glue", 1)[0]
    assert "name: session-glue" in frontmatter


def test_claude_skill_has_full_trigger_set_including_korean():
    for trigger in (
        "/glue",
        "/freeze",
        "/handoff",
        "/checkpoint",
        "세션 붙여줘",
        "세션 얼려줘",
        "create a Session Glue handoff",
    ):
        assert trigger in SKILL, f"missing trigger: {trigger!r}"


def test_claude_skill_documents_session_glue_invocation():
    # Claude Code invokes the skill as /session-glue; /glue is only a spoken trigger.
    assert "/session-glue" in SKILL
    assert "not a registered slash command" in SKILL


def test_claude_skill_prefers_cli_and_links_fallback_protocol():
    assert "glue create --repo-root . --input <handoff.md>" in SKILL
    assert "glue validate --repo-root ." in SKILL
    assert "references/protocol.md" in SKILL


def test_claude_skill_keeps_v1_constraints():
    assert "Do not request OS clipboard access" in SKILL
    assert "fenced" in SKILL and "code block" in SKILL
