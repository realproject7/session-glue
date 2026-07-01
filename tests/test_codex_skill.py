from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "codex-skills" / "session-glue"
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
PROTOCOL = (SKILL_DIR / "references" / "protocol.md").read_text(encoding="utf-8")
OPENAI_YAML = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")


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


def test_skill_prefers_cli_and_links_fallback_protocol():
    assert "glue create --repo-root . --input <handoff.md>" in SKILL
    assert "glue validate --repo-root ." in SKILL
    assert "glue status --repo-root ." in SKILL
    assert "references/protocol.md" in SKILL


def test_fallback_protocol_matches_v1_schema_contract():
    for field in (
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
    ):
        assert f"{field}:" in PROTOCOL

    assert "next_todo_items[0], must be productive work" in PROTOCOL
    assert "first_next_action:" in PROTOCOL
    assert "Do not duplicate the narrative" in PROTOCOL
    assert "Prompt artifact: .agent-history/RESUME_PROMPT.txt" in PROTOCOL


def test_fallback_protocol_avoids_dogfood_meta_loop():
    assert "outer observer starts fresh-agent trials" in PROTOCOL
    assert "trial subject only resumes from the handoff" in PROTOCOL
    assert "Do not make the trial subject's first productive action" in PROTOCOL


def test_openai_yaml_mentions_skill_name_in_default_prompt():
    assert 'display_name: "Session Glue"' in OPENAI_YAML
    assert "default_prompt:" in OPENAI_YAML
    assert "$session-glue" in OPENAI_YAML
