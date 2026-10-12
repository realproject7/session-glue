from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "codex-skills" / "session-glue"
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
PROTOCOL = (SKILL_DIR / "references" / "protocol.md").read_text(encoding="utf-8")
OPENAI_YAML = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Collapse whitespace so a claim matches wherever the line wrap fell."""
    return " ".join(text.split())


FLAT_PROTOCOL = _flat(PROTOCOL)
FLAT_SKILL = _flat(SKILL)


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
    assert "`project_root` must be **equal to `repo_root` or a descendant of it**" in FLAT_PROTOCOL
    assert "<vault-root>" in PROTOCOL
    assert "not exportable" in PROTOCOL
    assert "glue sync migrate-roots" in PROTOCOL


def test_protocol_makes_vault_sync_operator_initiated_only():
    assert "never sync on your own initiative" in FLAT_PROTOCOL.lower()
    # All three must be supplied by the operator; none may be inferred.
    assert "the command, the vault path, and the project ID" in FLAT_PROTOCOL
    assert "Do not infer a project ID" in FLAT_PROTOCOL


def test_protocol_forbids_credentials_creation_and_retry():
    for forbidden in (
        "create a vault folder, a Git repository, or a remote",
        "authenticate, or read, request, parse, or store a credential",
        "retry a failed sync, poll for availability, or wait in a loop",
        "synchronize automatically, on a schedule, or as a side effect",
    ):
        assert forbidden in FLAT_PROTOCOL, f"protocol no longer forbids: {forbidden!r}"


def test_protocol_states_the_operator_owns_unavailability_conflicts_and_privacy():
    # Unavailability is a wait, not a retry.
    assert "vault not fully available" in PROTOCOL
    assert "wait for their sync client" in FLAT_PROTOCOL
    # Conflicts retain data and are the operator's decision.
    assert "Nothing is discarded" in FLAT_PROTOCOL
    assert "both sides are retained under the vault's `conflicts/` area" in FLAT_PROTOCOL
    assert "you must not choose for them" in FLAT_PROTOCOL
    # A privacy override is deliberate and never the agent's to make.
    assert "never acknowledge on their behalf" in FLAT_PROTOCOL


def test_skill_documents_explicit_vault_resume():
    assert "The default is local. Never sync on your own initiative." in FLAT_SKILL
    assert "glue sync pull --repo-root . --project-id <id> --vault-dir <path>" in FLAT_SKILL
    assert "glue sync pull --repo-root . --project-id <id> --vault-git-dir <path>" in FLAT_SKILL
    assert "do not retry a failure, poll, or sync automatically" in FLAT_SKILL


# --------------------------------------------------------------------------- #
# Standing decisions (issue #140, PR #141)
# --------------------------------------------------------------------------- #


def test_skill_carries_and_reads_standing_decisions():
    # Glue: a standing ruling goes into decisions: with the prefix; a one-off
    # decision carries its PR or issue number instead.
    assert "DECISIONS.md" in SKILL
    assert "[standing]" in SKILL
    assert "`decisions:` frontmatter list with a `[standing]` prefix" in FLAT_SKILL
    assert "give a one-off decision its PR or issue number" in FLAT_SKILL
    # Resume: CLI 0.4.1+ prints them; older CLIs keep the bounded manual read,
    # in step with references/protocol.md.
    assert (
        "With CLI 0.4.1 or newer (`glue --version`), `glue status` and the resume prompt "
        "print the `[standing]` lines of `.agent-history/DECISIONS.md`"
    ) in FLAT_SKILL
    assert (
        "With an older CLI or none, read the last 20 lines of `DECISIONS.md` plus every "
        "line containing `[standing]` yourself"
    ) in FLAT_SKILL
    assert "a standing operator ruling stays in force until the operator changes it" in FLAT_SKILL


def test_protocol_defines_standing_decisions_and_bounded_read():
    # glue create appends one DECISIONS.md line per entry; [standing] is plain
    # text, so the protocol spells out both the CLI output and the manual read.
    assert "DECISIONS.md" in PROTOCOL
    assert "Prefix a standing operator ruling with `[standing]`" in FLAT_PROTOCOL
    assert "give a one-off decision its PR or issue number" in FLAT_PROTOCOL
    assert "With CLI 0.4.1 or newer, `glue status` prints a `standing:` block" in FLAT_PROTOCOL
    assert "the resume prompt a `Standing operator rulings:` block" in FLAT_PROTOCOL
    assert "(+N older standing lines in DECISIONS.md)" in FLAT_PROTOCOL
    assert "its last 20 lines plus every line containing `[standing]`" in FLAT_PROTOCOL
    assert "do not read it whole by default" in FLAT_PROTOCOL
    assert "keep standing operator rulings separate from one-off decisions" in FLAT_PROTOCOL


def test_protocol_prompt_template_carries_the_standing_block():
    # The fallback writer must produce the same prompt shape as glue create.
    template = PROTOCOL.split("## RESUME_PROMPT.txt", 1)[1].split("\n## ", 1)[0]
    assert template.index("<next_todo_items[0]>") < template.index("Standing operator rulings:")
    assert template.index("Standing operator rulings:") < template.index("Before editing")
    assert "Omit the `Standing operator rulings:` block" in _flat(template)
