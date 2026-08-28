"""Tests for the Personal Vault core (issue #78).

Grouped by the acceptance criteria they discharge. The byte-level assertions are
the point of most of them: canonical archives, the state digest and the
acknowledgement digest all feed equality comparisons, so "equivalent" is not a
useful standard anywhere in this module.
"""

from __future__ import annotations

import pytest

from session_glue import schema, validator, vault, writer

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

#: A body carrying every section `validator` requires, so these tests exercise a
#: history the shipped validator accepts rather than a stub it would reject.
BODY = "\n".join(
    f"# {section}\n\nDid the thing.\n"
    for section in (
        "Resume Prompt",
        "What We Did",
        "Current State",
        "Decisions Made",
        "Failed Attempts / Dead Ends",
        "Next-Agent Instructions",
        "Commands And Validation",
        "Risks And Constraints",
    )
)


def _frontmatter(repo_root: str, project_root: str | None = None, **overrides: object) -> dict:
    data = {
        "session_id": "2026-08-28-1200-alpha",
        "session_date": "2026-08-28",
        "generated_at": "2026-08-28T12:00:00+00:00",
        "schema_version": 1,
        "project_root": project_root if project_root is not None else repo_root,
        "repo_root": repo_root,
        "current_branch": "main",
        "head_commit": "abc1234",
        "agent": "codex",
        "status": "in_progress",
        "primary_goal": "Ship the vault core",
        "active_context_files": ["session_glue/vault.py"],
        "completed_tasks": ["Wrote the canonical transform"],
        "next_todo_items": ["Wire the folder transport"],
        "known_issues": ["None"],
        "search_tags": ["vault", "sync"],
        "validation": [{"command": "pytest -q", "result": "passed", "notes": ""}],
    }
    data.update(overrides)
    return data


def _write_history(repo_root, *, project_root=None, extra_field=None, session_id=None, body=BODY):
    """Create a real one-session history via the shipped writer."""
    frontmatter = _frontmatter(str(repo_root), project_root)
    if session_id:
        frontmatter["session_id"] = session_id
    if extra_field:
        frontmatter.update(extra_field)
    handoff = schema.Handoff.from_frontmatter(frontmatter, body)
    return writer.create_handoff(
        repo_root=repo_root, frontmatter=frontmatter, body=body, handoff=handoff
    )


@pytest.fixture()
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    _write_history(root)
    return root


# --------------------------------------------------------------------------- #
# AC2 — identity validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["a", "myproj", "a-b_c.d", "com0", "console", "a" * 64])
def test_valid_project_ids_accepted(value):
    assert vault.validate_project_id(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "A1", "-x", ".hidden", "my proj", "a" * 65, "myproj.", "a-", "..", "con", "con.log",
     "nul.md", "com1", "lpt9", "AUX"],
)
def test_invalid_project_ids_rejected(value):
    with pytest.raises(vault.VaultError):
        vault.validate_project_id(value)


# --------------------------------------------------------------------------- #
# AC1 / AC11 — canonical bytes and digests
# --------------------------------------------------------------------------- #


def test_equal_roots_render_as_bare_token(checkout):
    text = (checkout / ".agent-history" / "LATEST.md").read_text(encoding="utf-8")
    canonical = vault.canonicalize_document(text)
    frontmatter, _ = schema.parse_frontmatter(canonical)
    assert frontmatter["repo_root"] == vault.VAULT_ROOT_TOKEN
    assert frontmatter["project_root"] == vault.VAULT_ROOT_TOKEN


def test_contained_offset_is_preserved_and_reversed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root, project_root=str(root / "packages" / "api"))
    text = (root / ".agent-history" / "LATEST.md").read_text(encoding="utf-8")

    canonical = vault.canonicalize_document(text)
    frontmatter, _ = schema.parse_frontmatter(canonical)
    assert frontmatter["project_root"] == f"{vault.VAULT_ROOT_TOKEN}/packages/api"

    other = tmp_path / "elsewhere"
    materialized = vault.materialize_document(canonical, other)
    frontmatter, _ = schema.parse_frontmatter(materialized)
    assert frontmatter["repo_root"] == str(other)
    assert frontmatter["project_root"] == str(other / "packages" / "api")


def test_out_of_repo_project_root_refuses_export(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root, project_root=str(tmp_path / "outside"))
    text = (root / ".agent-history" / "LATEST.md").read_text(encoding="utf-8")
    with pytest.raises(vault.VaultError, match="outside repo_root"):
        vault.canonicalize_document(text)


def test_unknown_frontmatter_field_survives_canonical_round_trip(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root, extra_field={"reviewer_note": "keep me"})
    text = (root / ".agent-history" / "LATEST.md").read_text(encoding="utf-8")

    canonical = vault.canonicalize_document(text)
    assert "reviewer_note: keep me" in canonical
    round_tripped = vault.canonicalize_document(vault.materialize_document(canonical, root))
    assert round_tripped == canonical


def test_canonicalization_touches_only_the_two_root_lines(checkout):
    text = (checkout / ".agent-history" / "LATEST.md").read_text(encoding="utf-8")
    canonical = vault.canonicalize_document(text)
    differing = [
        (before, after)
        for before, after in zip(text.split("\n"), canonical.split("\n"), strict=True)
        if before != after
    ]
    assert len(differing) == 2
    assert {after.split(":")[0] for _, after in differing} == {"repo_root", "project_root"}


def test_materialize_rejects_relative_escape(checkout):
    text = (checkout / ".agent-history" / "LATEST.md").read_text(encoding="utf-8")
    canonical = vault.canonicalize_document(text)
    escaped = canonical.replace(
        f"project_root: {vault.VAULT_ROOT_TOKEN}",
        f"project_root: {vault.VAULT_ROOT_TOKEN}/../escape",
    )
    with pytest.raises(vault.VaultError, match="escapes the repo root"):
        vault.materialize_document(escaped, checkout)


# --------------------------------------------------------------------------- #
# AC11 — deterministic vault YAML
# --------------------------------------------------------------------------- #


def test_state_renders_with_pinned_order_and_terminal_newline():
    state = {
        "acknowledgements": [{"path": "b", "sha256": "2", "label": "z"}],
        "head_session_id": "s1",
        "lifecycle": [{"session_id": "s2", "status": "DONE"}],
    }
    rendered = vault.render_vault_state(state)
    assert rendered.endswith("\n")
    assert rendered.splitlines()[0] == "head_session_id: s1"
    assert rendered.index("lifecycle:") < rendered.index("acknowledgements:")


def test_state_digest_is_order_independent():
    """Equal logical state must hash equally however it was constructed."""
    one = {
        "head_session_id": "s",
        "lifecycle": [{"session_id": "b", "status": "DONE"}, {"session_id": "a", "status": "BLOCKED"}],
        "acknowledgements": [],
    }
    two = {
        "acknowledgements": [],
        "lifecycle": [{"session_id": "a", "status": "BLOCKED"}, {"session_id": "b", "status": "DONE"}],
        "head_session_id": "s",
    }
    assert vault.state_digest(one) == vault.state_digest(two)


def test_state_with_list_entries_round_trips_byte_identically():
    state = {
        "head_session_id": "s1",
        "lifecycle": [{"session_id": "s1", "status": "DONE"}],
        "acknowledgements": [{"path": "sessions/x.md", "sha256": "ff", "label": "JWT (eyJ)"}],
    }
    rendered = vault.render_vault_state(state)
    assert vault.render_vault_state(schema.parse_mapping(rendered)) == rendered


def test_manifest_round_trip_is_byte_identical():
    records = [
        {"session_id": "s2", "kind": "archive", "side": "vault", "path": "p2", "sha256": "b"},
        {"session_id": "s1", "kind": "archive", "side": "local", "path": "p1", "sha256": "a"},
    ]
    rendered = vault.render_manifest(records)
    parsed = schema.parse_mapping(rendered)
    assert vault.render_manifest(parsed["conflicts"]) == rendered


def test_manifest_records_merge_by_exact_record_union():
    record = {"session_id": "s", "kind": "archive", "side": "local", "path": "p", "sha256": "a"}
    merged = vault.merge_manifest_records([record], [dict(record), {**record, "sha256": "b"}])
    assert len(merged) == 2


# --------------------------------------------------------------------------- #
# AC5 — decisions merge
# --------------------------------------------------------------------------- #


def test_decisions_merge_has_one_header_and_canonical_order():
    left = writer.DECISIONS_HEADER + "- [2026-08-02][s2] second\n"
    right = writer.DECISIONS_HEADER + "- [2026-08-01][s1] first\n"
    merged = vault.merge_decisions(left, right)
    assert merged.count("# Decisions") == 1
    assert merged.index("[s1] first") < merged.index("[s2] second")


def test_decisions_merge_a_b_a_is_byte_identical():
    left = writer.DECISIONS_HEADER + "- [2026-08-02][s2] beta\n- [2026-08-01][s1] alpha\n"
    right = writer.DECISIONS_HEADER + "- [2026-08-01][s1] alpha\n- [2026-08-03][s3] gamma\n"
    once = vault.merge_decisions(left, right)
    assert vault.merge_decisions(once, right) == once
    assert vault.merge_decisions(right, once) == once


# --------------------------------------------------------------------------- #
# AC6 / AC10 — privacy gate
# --------------------------------------------------------------------------- #


def test_secret_blocks_before_output_and_never_echoes_the_match():
    secret = "ghp_" + "a" * 20
    with pytest.raises(vault.PrivacyBlocked) as excinfo:
        vault.gate_artifacts({"sessions/x.md": f"body {secret}\n"})
    message = str(excinfo.value)
    assert secret not in message
    assert "GitHub token" in message
    assert "sessions/x.md" in message


def test_only_the_exact_triple_unblocks_and_a_second_artifact_stays_blocked():
    secret = "ghp_" + "b" * 20
    first = f"one {secret}\n"
    second = f"two {secret}\n"
    label = "GitHub token (ghp_/gho_)"
    ack = {"path": "sessions/a.md", "sha256": vault.canonical_digest(first), "label": label}

    vault.gate_artifacts({"sessions/a.md": first}, [ack])  # exact triple: allowed

    with pytest.raises(vault.PrivacyBlocked):
        vault.gate_artifacts({"sessions/a.md": first, "sessions/b.md": second}, [ack])

    changed = ack | {"sha256": "0" * 64}
    with pytest.raises(vault.PrivacyBlocked):
        vault.gate_artifacts({"sessions/a.md": first}, [changed])


def test_personal_path_is_gated_without_ignore_suppression(tmp_path):
    """`.agent-history/` being gitignored must not suppress a vault-bound hit."""
    (tmp_path / ".gitignore").write_text(".agent-history/\n", encoding="utf-8")
    with pytest.raises(vault.PrivacyBlocked) as excinfo:
        vault.gate_artifacts({"sessions/x.md": "see /home/alice/secrets/notes\n"})
    assert vault.PERSONAL_PATH_LABEL in str(excinfo.value)
    assert "/home/alice/" not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# AC1 / AC3 / AC7 / AC8 — export and import
# --------------------------------------------------------------------------- #


def test_push_then_pull_into_a_second_checkout(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")

    other = tmp_path / "device-b"
    other.mkdir()
    vault.import_project(other, vault_root, "alpha")

    assert validator.validate_history(other, check_sessions=True) == []
    frontmatter, _ = schema.parse_frontmatter(
        (other / ".agent-history" / "LATEST.md").read_text(encoding="utf-8")
    )
    assert frontmatter["repo_root"] == str(other)
    assert vault.VAULT_ROOT_TOKEN not in (other / ".agent-history" / "LATEST.md").read_text(
        encoding="utf-8"
    )


def test_unknown_field_survives_into_both_archive_and_latest(tmp_path):
    source = tmp_path / "a"
    source.mkdir()
    _write_history(source, extra_field={"reviewer_note": "keep me"})
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(source, vault_root, "alpha")

    other = tmp_path / "b"
    other.mkdir()
    vault.import_project(other, vault_root, "alpha")

    history = other / ".agent-history"
    assert "reviewer_note: keep me" in (history / "LATEST.md").read_text(encoding="utf-8")
    archive = next((history / "sessions").glob("*.md"))
    assert "reviewer_note: keep me" in archive.read_text(encoding="utf-8")


def test_local_only_archive_survives_pull(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")

    other = tmp_path / "device-b"
    other.mkdir()
    _write_history(other, session_id="2026-08-27-0900-local-only")
    vault.import_project(other, vault_root, "alpha")

    names = {p.name for p in (other / ".agent-history" / "sessions").glob("*.md")}
    assert "2026-08-27-0900-local-only.md" in names
    assert "2026-08-28-1200-alpha.md" in names


def test_two_consecutive_no_op_syncs_do_not_diverge(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    first = vault.export_project(checkout, vault_root, "alpha")
    second = vault.export_project(checkout, vault_root, "alpha")
    assert first == second
    stored = schema.parse_mapping(
        vault.sync_state_path(checkout).read_text(encoding="utf-8")
    )
    assert stored["last_remote_state_sha256"] == second
    assert stored["project_id"] == "alpha"


def test_project_id_mismatch_fails_before_a_write(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    before = vault.sync_state_path(checkout).read_bytes()

    with pytest.raises(vault.VaultError, match="one project ID per checkout"):
        vault.export_project(checkout, vault_root, "beta")

    assert vault.sync_state_path(checkout).read_bytes() == before
    assert not (vault_root / "projects" / "beta").exists()


def test_marker_less_populated_namespace_is_refused(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    namespace = vault_root / "projects" / "alpha"
    (namespace / "sessions").mkdir(parents=True)
    (namespace / "sessions" / "stray.md").write_text("noise\n", encoding="utf-8")
    with pytest.raises(vault.VaultError, match="marker-less|no vault-project.yaml"):
        vault.export_project(checkout, vault_root, "alpha")


def test_mismatched_marker_is_refused(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    namespace = vault_root / "projects" / "alpha"
    (namespace / vault.MARKER_FILENAME).write_text(
        vault.render_marker("beta"), encoding="utf-8"
    )
    with pytest.raises(vault.VaultError, match="belongs to project"):
        vault.export_project(checkout, vault_root, "alpha")


def test_import_from_absent_namespace_reports_unavailable(tmp_path):
    other = tmp_path / "device-b"
    other.mkdir()
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    with pytest.raises(vault.VaultUnavailable, match="not fully available"):
        vault.import_project(other, vault_root, "alpha")


def test_same_session_byte_divergence_is_a_conflict(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")

    archive = next((vault_root / "projects" / "alpha" / "sessions").glob("*.md"))
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "Did something else."),
        encoding="utf-8",
    )
    with pytest.raises(vault.VaultConflict, match="differ between local and vault"):
        vault.export_project(checkout, vault_root, "alpha")


def test_lifecycle_merge_rules():
    local = [{"session_id": "s1", "status": "DONE"}]
    merged, conflicts = vault.merge_lifecycle(local, [])
    assert merged == local and conflicts == []  # one-sided → adopt

    merged, conflicts = vault.merge_lifecycle(local, list(local))
    assert merged == local and conflicts == []  # equal → no-op

    merged, conflicts = vault.merge_lifecycle(local, [{"session_id": "s1", "status": "BLOCKED"}])
    assert conflicts == ["s1"]  # different → conflict


# --------------------------------------------------------------------------- #
# AC7 / AC12 — rollback and migration
# --------------------------------------------------------------------------- #


def test_replace_phase_fault_restores_the_same_file_set_and_bytes(tmp_path, checkout):
    """A failure after a new archive is created must leave no trace of it."""
    history = checkout / ".agent-history"
    before_files = {p.name for p in history.rglob("*")}
    before_bytes = {p: p.read_bytes() for p in history.rglob("*") if p.is_file()}

    write = vault.LocalWrite(history)
    write.stage("sessions/2026-08-29-0900-new.md", "brand new\n")
    write.stage("LATEST.md", "replaced\n")
    with pytest.raises(vault.VaultError, match="injected replace-phase fault"):
        write.commit(fault_after=1)

    assert {p.name for p in history.rglob("*")} == before_files
    assert {p: p.read_bytes() for p in history.rglob("*") if p.is_file()} == before_bytes


def test_publication_fault_leaves_no_state_or_marker(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    with pytest.raises(vault.VaultError, match="injected publication fault"):
        vault.export_project(checkout, vault_root, "alpha", fault_after=0)
    namespace = vault_root / "projects" / "alpha"
    assert not (namespace / vault.MARKER_FILENAME).exists()
    assert not vault.state_path(namespace).exists()
    assert vault.read_sync_state(checkout) is None


def test_migrate_roots_changes_only_the_two_root_scalars(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root, project_root=str(tmp_path / "outside"))
    archive = next((root / ".agent-history" / "sessions").glob("*.md"))
    before = archive.read_text(encoding="utf-8")

    vault.migrate_roots(root, "2026-08-28-1200-alpha", root / "packages" / "api")

    after = archive.read_text(encoding="utf-8")
    differing = [
        (b, a) for b, a in zip(before.split("\n"), after.split("\n"), strict=True) if b != a
    ]
    # Only root scalars may move; repo_root was already correct here, so exactly
    # one line changes — the assertion is that nothing *else* did.
    assert {a.split(":")[0] for _, a in differing} <= {"repo_root", "project_root"}
    assert differing
    frontmatter, _ = schema.parse_frontmatter(after)
    assert frontmatter["project_root"] == str(root / "packages" / "api")
    assert frontmatter["repo_root"] == str(root)


def test_migration_fault_leaves_the_same_file_set_and_bytes(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root, project_root=str(tmp_path / "outside"))
    history = root / ".agent-history"
    before = {p: p.read_bytes() for p in history.rglob("*") if p.is_file()}

    original_commit = vault.LocalWrite.commit
    monkeypatch.setattr(
        vault.LocalWrite, "commit", lambda self, **_: original_commit(self, fault_after=1)
    )
    with pytest.raises(vault.VaultError, match="injected replace-phase fault"):
        vault.migrate_roots(root, "2026-08-28-1200-alpha", root / "packages" / "api")

    assert {p: p.read_bytes() for p in history.rglob("*") if p.is_file()} == before


def test_migrate_roots_refuses_an_out_of_repo_target(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root)
    with pytest.raises(vault.VaultError, match="outside repo_root"):
        vault.migrate_roots(root, "2026-08-28-1200-alpha", tmp_path / "elsewhere")


# --------------------------------------------------------------------------- #
# AC9 — no regression in the local-only surface
# --------------------------------------------------------------------------- #


def test_existing_local_behaviour_needs_no_vault_import(checkout):
    """The vault module is opt-in: the local surface must not depend on it."""
    assert validator.validate_history(checkout, check_sessions=True) == []
    status = writer.close_session(checkout, None, "DONE")
    assert status == "2026-08-28-1200-alpha"


# --------------------------------------------------------------------------- #
# AC3 / AC4 / AC10 — conflict retention and explicit resolution
# --------------------------------------------------------------------------- #


def _diverge(vault_root, replacement="Did something else."):
    archive = next((vault_root / "projects" / "alpha" / "sessions").glob("*.md"))
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", replacement),
        encoding="utf-8",
    )


def test_populated_both_sides_first_sync_conflicts(tmp_path, checkout):
    """A device with no baseline meeting a populated vault must not silently win."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")

    other = tmp_path / "device-b"
    other.mkdir()
    _write_history(other, session_id="2026-08-27-0900-other")
    with pytest.raises(vault.VaultConflict):
        vault.export_project(other, vault_root, "alpha")


def test_resolve_requires_a_selector_for_every_named_conflict(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    _diverge(vault_root)

    with pytest.raises(vault.VaultError, match="explicit selector for every named conflict"):
        vault.resolve_project(checkout, vault_root, "alpha", "2026-08-28-1200-alpha")


def test_resolve_rejects_an_unknown_side_and_an_absent_head(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    _diverge(vault_root)
    session_id = "2026-08-28-1200-alpha"

    with pytest.raises(vault.VaultError, match="unknown conflict side"):
        vault.resolve_project(
            checkout, vault_root, "alpha", session_id, archive_choices={session_id: "theirs"}
        )
    with pytest.raises(vault.VaultError, match="not present in the resolved active archive union"):
        vault.resolve_project(
            checkout, vault_root, "alpha", "no-such-session",
            archive_choices={session_id: "local"},
        )


def test_resolve_retains_the_nonchosen_candidate_and_records_it(tmp_path, checkout):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    _diverge(vault_root)
    session_id = "2026-08-28-1200-alpha"

    vault.resolve_project(
        checkout, vault_root, "alpha", session_id, archive_choices={session_id: "local"}
    )

    namespace = vault_root / "projects" / "alpha"
    records = vault.read_manifest(namespace)
    assert {r["side"] for r in records} == {"local", "vault"}
    for record in records:
        retained = namespace / record["path"]
        assert retained.is_file()
        assert vault.canonical_digest(retained.read_text(encoding="utf-8")) == record["sha256"]

    # The chosen side is active; the retained candidates are not indexed locally.
    active = next((namespace / "sessions").glob("*.md")).read_text(encoding="utf-8")
    assert "Did the thing." in active
    other = tmp_path / "device-b"
    other.mkdir()
    vault.import_project(other, vault_root, "alpha")
    index = schema.parse_mapping(
        (other / ".agent-history" / "INDEX.yaml").read_text(encoding="utf-8")
    )
    assert all("conflicts/" not in str(entry.get("file")) for entry in index["sessions"])


def test_resolve_gates_a_pattern_matching_local_candidate_before_any_vault_write(
    tmp_path, checkout
):
    """AC10: the selection path is gated, not only the retention path."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    _diverge(vault_root)

    archive = next((checkout / ".agent-history" / "sessions").glob("*.md"))
    archive.write_text(
        archive.read_text(encoding="utf-8").replace(
            "Did the thing.", "token ghp_" + "c" * 20
        ),
        encoding="utf-8",
    )
    session_id = "2026-08-28-1200-alpha"
    before = vault.state_path(vault_root / "projects" / "alpha").read_bytes()

    with pytest.raises(vault.PrivacyBlocked) as excinfo:
        vault.resolve_project(
            checkout, vault_root, "alpha", session_id, archive_choices={session_id: "local"}
        )
    assert "ghp_" + "c" * 20 not in str(excinfo.value)
    assert vault.state_path(vault_root / "projects" / "alpha").read_bytes() == before


# --------------------------------------------------------------------------- #
# Containment: a symlink at any level, on either side, must stop the write
# --------------------------------------------------------------------------- #


def test_symlinked_local_ancestor_blocks_the_write(tmp_path, checkout):
    """Guarding only the leaf is insufficient — an ancestor redirects too."""
    outside = tmp_path / "outside"
    outside.mkdir()
    history = checkout / ".agent-history"
    (history / "sessions").rename(tmp_path / "moved-sessions")
    (history / "sessions").symlink_to(outside, target_is_directory=True)

    write = vault.LocalWrite(history)
    write.stage("sessions/2026-08-29-0900-new.md", "content\n")
    with pytest.raises(writer.HandoffWriteError, match="symlink"):
        write.commit()
    assert list(outside.iterdir()) == []


def test_symlinked_vault_namespace_blocks_publication(tmp_path, checkout):
    outside = tmp_path / "outside"
    outside.mkdir()
    vault_root = tmp_path / "vault"
    (vault_root / "projects").mkdir(parents=True)
    (vault_root / "projects" / "alpha").symlink_to(outside, target_is_directory=True)

    with pytest.raises(writer.HandoffWriteError, match="symlink"):
        vault.export_project(checkout, vault_root, "alpha")
    assert list(outside.iterdir()) == []


def test_marker_present_but_state_missing_is_unavailable(tmp_path, checkout):
    """A torn namespace must not read as an empty one and be overwritten."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")

    namespace = vault_root / "projects" / "alpha"
    state_file = vault.state_path(namespace)
    original = state_file.read_bytes()
    state_file.unlink()

    with pytest.raises(vault.VaultUnavailable, match="not fully available"):
        vault.export_project(checkout, vault_root, "alpha")
    assert not state_file.exists()  # refused before any write

    # The import side refuses the same torn namespace.
    with pytest.raises(vault.VaultUnavailable, match="not fully available"):
        vault.import_project(checkout, vault_root, "alpha")

    # Restoring the state file makes both paths work again.
    state_file.write_bytes(original)
    assert vault.export_project(checkout, vault_root, "alpha")


def test_state_referencing_a_missing_archive_is_unavailable(tmp_path, checkout):
    """A state naming a session with no readable archive is torn, not empty."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")

    namespace = vault_root / "projects" / "alpha"
    archive = next((namespace / "sessions").glob("*.md"))
    archive.unlink()

    with pytest.raises(vault.VaultUnavailable, match="no readable archive"):
        vault.import_project(checkout, vault_root, "alpha")
    with pytest.raises(vault.VaultUnavailable, match="no readable archive"):
        vault.export_project(checkout, vault_root, "alpha")


def test_vault_writes_use_lf_regardless_of_platform(tmp_path, checkout):
    """Identical content must be identical bytes, so Git mode sees no churn."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")

    namespace = vault_root / "projects" / "alpha"
    for path in (
        vault.state_path(namespace),
        namespace / vault.MARKER_FILENAME,
        next((namespace / "sessions").glob("*.md")),
    ):
        assert b"\r\n" not in path.read_bytes(), path
