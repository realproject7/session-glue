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


# --------------------------------------------------------------------------- #
# Personal Vault documentation (issue #81)
# --------------------------------------------------------------------------- #


def test_protocol_defines_the_contained_root_relationship():
    """#77's export contract depends on this containment, so the protocol states it."""
    assert "`project_root` must be **equal to `repo_root` or a descendant of it**" in PROTOCOL
    assert "<vault-root>" in PROTOCOL
    assert "not exportable" in PROTOCOL
    assert "glue sync migrate-roots" in PROTOCOL


def test_protocol_makes_vault_sync_operator_initiated_only():
    assert "never sync on your own initiative" in PROTOCOL.lower()
    # All three must be supplied by the operator; none may be inferred.
    assert "the command, the vault path, and the project ID" in PROTOCOL
    assert "Do not\ninfer a project ID" in PROTOCOL


def test_protocol_forbids_credentials_creation_and_retry():
    for forbidden in (
        "create a vault folder, a Git repository, or a remote",
        "authenticate, or read, request, parse, or store a credential",
        "retry a failed sync, poll for availability, or wait in a loop",
        "synchronize automatically, on a schedule, or as a side effect",
    ):
        assert forbidden in PROTOCOL, f"protocol no longer forbids: {forbidden!r}"


def test_protocol_states_the_operator_owns_unavailability_conflicts_and_privacy():
    # Unavailability is a wait, not a retry.
    assert "vault not fully available" in PROTOCOL
    assert "wait for their sync client" in PROTOCOL
    # Conflicts retain data and are the operator's decision.
    assert "Nothing is discarded" in PROTOCOL
    assert "both\nsides are retained under the vault's `conflicts/` area" in PROTOCOL
    assert "you must\nnot choose for them" in PROTOCOL
    # A privacy override is deliberate and never the agent's to make.
    assert "never acknowledge on their behalf" in PROTOCOL


def test_skill_documents_explicit_vault_resume():
    assert "The default is local. Never sync on your own initiative." in SKILL
    assert "glue sync pull --repo-root . --project-id <id> --vault-dir <path>" in SKILL
    assert "glue sync pull --repo-root . --project-id <id> --vault-git-dir <path>" in SKILL
    assert "do not retry a failure, poll, or sync automatically" in SKILL
