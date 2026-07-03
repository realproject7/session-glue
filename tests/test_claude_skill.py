from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "claude-skills" / "session-glue"
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
PROTOCOL = (SKILL_DIR / "references" / "protocol.md").read_text(encoding="utf-8")

CODEX_PROTOCOL = (
    ROOT / "codex-skills" / "session-glue" / "references" / "protocol.md"
).read_text(encoding="utf-8")


def test_skill_frontmatter_declares_skill_name():
    # Claude Code discovers the skill by the `name` field; it must match the
    # folder name so `/session-glue` resolves.
    assert SKILL.startswith("---\n")
    assert "name: session-glue" in SKILL
    assert "description:" in SKILL


def test_skill_has_required_triggers_and_copyable_prompt_rule():
    for trigger in (
        "/glue",
        "/freeze",
        "/handoff",
        "/checkpoint",
        "세션 붙여줘",
        "세션 얼려줘",
        "create a Session Glue handoff",
    ):
        assert trigger in SKILL

    assert "fenced\n   code block" in SKILL
    assert "Do not request OS clipboard access" in SKILL


def test_skill_documents_claude_invocation_expectation():
    # In Claude Code the skill is invoked as /session-glue or by natural
    # language; /glue is a spoken trigger, not a registered slash command.
    assert "/session-glue" in SKILL


def test_skill_prefers_cli_and_links_fallback_protocol():
    assert "glue create --repo-root . --input <handoff.md>" in SKILL
    assert "glue validate --repo-root ." in SKILL
    assert "glue status --repo-root ." in SKILL
    assert "references/protocol.md" in SKILL


def test_claude_protocol_is_byte_identical_to_codex_protocol():
    # Single canonical fallback protocol shared across agent skills. Keeping the
    # two copies byte-identical prevents cross-agent drift until packaging (#26)
    # can copy one source into every skill folder at build time.
    assert PROTOCOL == CODEX_PROTOCOL
