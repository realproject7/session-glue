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
from session_glue import schema

SKILL = assets.skill_dir("claude").joinpath("SKILL.md").read_text(encoding="utf-8")
#: Whitespace-collapsed copy, so a claim matches wherever the line wrap fell.
FLAT_SKILL = " ".join(SKILL.split())


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


def test_claude_skill_documents_explicit_vault_resume():
    """Issue #81: the packaged Claude asset must carry the same rule as Codex.

    The protocol byte-identity guard covers ``references/protocol.md`` only; the
    two ``SKILL.md`` files legitimately differ (the Claude invocation note), so
    this content is asserted separately rather than by comparison.
    """
    assert "The default is local. Never sync on your own initiative." in FLAT_SKILL
    assert "glue sync pull --repo-root . --project-id <id> --vault-dir <path>" in FLAT_SKILL
    assert "glue sync pull --repo-root . --project-id <id> --vault-git-dir <path>" in FLAT_SKILL
    assert "do not authenticate or handle a" in FLAT_SKILL
    assert "vault not fully available" in FLAT_SKILL


def test_claude_skill_carries_and_reads_standing_decisions():
    """Issues #140 and #146: record rulings with provenance, read them by label.

    ``glue create`` appends one ``DECISIONS.md`` line per ``decisions:`` entry.
    Only a dated quote of the operator is an operator ruling; an agent's hold is
    a ``[hold]`` with an end condition; ``[retracts <id>]`` retires a line. The
    skill keeps the bounded manual read as the fallback, in step with
    ``references/protocol.md``, and no longer carries the one-way ratchet.
    """
    protocol = assets.skill_dir("claude").joinpath("references", "protocol.md")
    flat_protocol = " ".join(protocol.read_text(encoding="utf-8").split())

    assert "DECISIONS.md" in SKILL
    assert "`decisions:` frontmatter list" in FLAT_SKILL
    assert "`[standing] YYYY-MM-DD operator: \"<the operator's exact words>\"`" in FLAT_SKILL
    assert "never add a condition or restriction to a quoted ruling" in FLAT_SKILL
    assert "`[hold] <what>; reason: <why>; until: <end condition>`" in FLAT_SKILL
    assert "`[retracts <id>]`" in FLAT_SKILL
    assert "Retract an operator ruling only on the operator's words" in FLAT_SKILL
    assert "Give a one-off decision its PR or issue number" in FLAT_SKILL
    # The labels the skill names are the ones the CLI prints.
    for label in (schema.RULINGS_LABEL, schema.HOLDS_LABEL, schema.UNVERIFIED_LABEL):
        assert f"`{label}`" in FLAT_SKILL, label
    assert (
        "read the last 20 lines of `DECISIONS.md` plus every line containing `[standing]`, "
        "`[hold]` or `[retracts` yourself"
    ) in FLAT_SKILL
    assert "Operator rulings stand as quoted until the operator changes them" in FLAT_SKILL
    assert "A hold expires when its end condition is met" in FLAT_SKILL
    assert "A resume must not narrow what the operator granted" in FLAT_SKILL
    # #146: the one-way ratchet is gone.
    for ratchet in (
        "a resume prompt does not clear them",
        "A handoff grants no new permission",
        "a standing operator ruling stays in force until the operator changes it",
        "preserved authorization and holds",
    ):
        assert ratchet not in FLAT_SKILL, ratchet

    assert "DECISIONS.md" in flat_protocol
    assert "`[standing] YYYY-MM-DD operator: \"<the operator's exact words>\"`" in flat_protocol
    assert "(+N older lines in DECISIONS.md)" in flat_protocol
    assert (
        "its last 20 lines plus every line containing `[standing]`, `[hold]` or `[retracts`"
    ) in flat_protocol
    assert "do not read it whole by default" in flat_protocol
