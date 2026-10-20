from pathlib import Path

from session_glue import schema


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
# Standing decisions (issues #140 and #146)
# --------------------------------------------------------------------------- #

RULING_FORM = "`[standing] YYYY-MM-DD operator: \"<the operator's exact words>\"`"
HOLD_FORM = "`[hold] <what>; reason: <why>; until: <end condition>`"
LABELS = (schema.RULINGS_LABEL, schema.HOLDS_LABEL, schema.UNVERIFIED_LABEL)


def test_skill_records_rulings_with_provenance_and_holds_with_an_end():
    # Glue: a ruling quotes the operator with a date; an agent's own hold carries
    # a reason and an end condition; a one-off decision carries its PR or issue.
    assert "DECISIONS.md" in SKILL
    assert "`decisions:` frontmatter list" in FLAT_SKILL
    assert RULING_FORM in FLAT_SKILL
    assert "Quote only what the operator said" in FLAT_SKILL
    assert "Never record your own inference or paraphrase as `[standing]`" in FLAT_SKILL
    assert "never add a condition or restriction to a quoted ruling" in FLAT_SKILL
    assert HOLD_FORM in FLAT_SKILL
    assert "`[retracts <id>]`" in FLAT_SKILL
    assert "Retract an operator ruling only on the operator's words" in FLAT_SKILL
    assert "Give a one-off decision its PR or issue number" in FLAT_SKILL


def test_skill_reads_rulings_by_label_and_keeps_the_bounded_fallback():
    for label in LABELS:
        assert f"`{label}`" in FLAT_SKILL, label
    assert "CLI 0.4.1 printed every `[standing]` line, quoted or not" in FLAT_SKILL
    assert (
        "read the last 20 lines of `DECISIONS.md` plus every line containing `[standing]`, "
        "`[hold]` or `[retracts` yourself"
    ) in FLAT_SKILL
    assert "Operator rulings stand as quoted until the operator changes them" in FLAT_SKILL
    assert "do not append conditions or restrictions to them" in FLAT_SKILL
    assert "state to verify, not operator authority" in FLAT_SKILL
    assert "A hold expires when its end condition is met" in FLAT_SKILL
    assert "Confirm an unverified note with the operator" in FLAT_SKILL
    assert "A resume must not narrow what the operator granted" in FLAT_SKILL
    assert "it cannot take away what the operator granted" in FLAT_SKILL


def test_skill_drops_the_one_way_ratchet():
    """#146: restrictions carried over every resume while permissions never did."""
    for ratchet in (
        "a resume prompt does not clear them",
        "A handoff grants no new permission",
        "a standing operator ruling stays in force until the operator changes it",
        "preserved authorization and holds",
        "An unresolved hold blocks",
    ):
        assert ratchet not in FLAT_SKILL, ratchet
    assert "Respect holds and" not in FLAT_PROTOCOL
    assert "Respect operator gates and holds whose reason still applies" in FLAT_PROTOCOL
    assert "it cannot narrow what the operator granted" in FLAT_PROTOCOL


def test_protocol_defines_markers_retraction_and_bounded_read():
    # glue create appends one DECISIONS.md line per entry; the protocol spells
    # out the three markers, the id, the CLI output and the manual read.
    assert "DECISIONS.md" in PROTOCOL
    assert RULING_FORM in FLAT_PROTOCOL
    assert "nothing after the closing quote" in FLAT_PROTOCOL
    assert "Any other line containing `[standing]` is an unverified note" in FLAT_PROTOCOL
    assert HOLD_FORM in FLAT_PROTOCOL
    assert "it ends when its end condition is met" in FLAT_PROTOCOL
    assert "first 8 hex digits of the SHA-256 of the line" in FLAT_PROTOCOL
    assert "the file keeps both lines" in FLAT_PROTOCOL
    assert "Give a one-off decision its PR or issue number" in FLAT_PROTOCOL
    assert "Neither changes the exit code" in FLAT_PROTOCOL
    for label in LABELS:
        assert f"`{label}`" in FLAT_PROTOCOL, label
    assert "(+N older lines in DECISIONS.md)" in FLAT_PROTOCOL
    assert (
        "its last 20 lines plus every line containing `[standing]`, `[hold]` or `[retracts`"
    ) in FLAT_PROTOCOL
    assert "do not read it whole by default" in FLAT_PROTOCOL
    assert (
        "keep quoted operator rulings separate from agent-recorded holds and one-off decisions"
    ) in FLAT_PROTOCOL


def test_protocol_prompt_template_carries_the_three_blocks_in_order():
    # The fallback writer must produce the same prompt shape as glue create.
    template = PROTOCOL.split("## RESUME_PROMPT.txt", 1)[1].split("\n## ", 1)[0]
    positions = [template.index(label) for label in LABELS]
    assert template.index("<next_todo_items[0]>") < positions[0]
    assert positions == sorted(positions)
    assert positions[-1] < template.index("Before editing")
    assert "Omit a block and its blank line when it has no live line" in _flat(template)


def test_prompt_template_matches_the_generated_prompt():
    """The documented block labels and order are the ones glue create writes."""
    decisions = "\n".join(
        [
            '- [2026-07-01][s] [standing] 2026-07-01 operator: "no review unless asked"',
            "- [2026-07-01][s] [hold] Deploys; reason: CI red; until: CI is green",
            "- [2026-07-01][s] [standing] legacy note",
        ]
    )
    handoff = schema.Handoff.from_frontmatter({"next_todo_items": ["Do the work"]})
    prompt = schema.build_resume_prompt(handoff, decisions)
    template = PROTOCOL.split("## RESUME_PROMPT.txt", 1)[1].split("\n## ", 1)[0]
    for label in LABELS:
        assert f"\n{label}\n" in prompt and f"\n{label}\n" in template
