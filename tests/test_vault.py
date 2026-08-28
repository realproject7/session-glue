"""Tests for the Personal Vault core (issue #78).

Grouped by the acceptance criteria they discharge. The byte-level assertions are
the point of most of them: canonical archives, the state digest and the
acknowledgement digest all feed equality comparisons, so "equivalent" is not a
useful standard anywhere in this module.
"""

from __future__ import annotations

import pathlib
import shutil

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


# --------------------------------------------------------------------------- #
# Issue #88 — containment sweep across every vault source and target
# --------------------------------------------------------------------------- #


def _outside(tmp_path, name, text="secret from outside\n"):
    """A file the operator never meant this tool to touch."""
    external = tmp_path / "outside" / name
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text(text, encoding="utf-8")
    return external


@pytest.fixture()
def synced(tmp_path):
    """A checkout and a folder vault that have already agreed once."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root)
    vault.export_project(root, vault_root, "alpha")
    return root, vault_root


def test_push_refuses_a_symlinked_local_history_ancestor(tmp_path):
    """AC1: the ancestor, not the leaf — each archive file is a real file."""
    external = tmp_path / "elsewhere"
    (external / "sessions").mkdir(parents=True)
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root)
    real_history = root / ".agent-history"
    stolen = tmp_path / "stolen-history"
    real_history.rename(stolen)
    real_history.symlink_to(stolen, target_is_directory=True)

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.export_project(root, vault_root, "alpha")
    assert not (vault_root / vault.PROJECTS_DIRNAME / "alpha").exists()


@pytest.mark.parametrize(
    "relative", ["", "sessions", "state"], ids=["namespace", "sessions", "state"]
)
def test_pull_refuses_a_symlinked_vault_source(tmp_path, synced, relative):
    """AC2 + AC6, pull half: foreign content must not reach the local history.

    Asserted as *behaviour*, not as "an exception was raised". Without the guard
    some of these still raise — a symlink to an empty directory surfaces as
    "absent or empty", which is a VaultError too — so a bare `pytest.raises`
    would pass for a reason that has nothing to do with containment. The
    external side is therefore populated with real, well-formed vault content:
    without the guard the import *succeeds* and materializes it.

    `conflicts/` is deliberately absent — `import_project` never calls
    `read_manifest`, so pull does not read it. It is covered on resolve below,
    where it is actually read.
    """
    root, vault_root = synced
    namespace = vault_root / vault.PROJECTS_DIRNAME / "alpha"

    # A complete foreign vault namespace, so nothing fails for lack of content.
    foreign_repo = tmp_path / "foreign-repo"
    foreign_repo.mkdir()
    _write_history(foreign_repo, session_id="2026-09-09-0900-not-yours")
    foreign_vault = tmp_path / "foreign-vault"
    foreign_vault.mkdir()
    vault.export_project(foreign_repo, foreign_vault, "alpha")
    foreign_namespace = foreign_vault / vault.PROJECTS_DIRNAME / "alpha"

    target = namespace / relative if relative else namespace
    source = foreign_namespace / relative if relative else foreign_namespace
    import shutil

    if target.exists():
        shutil.rmtree(target)
    target.symlink_to(source, target_is_directory=True)

    other = tmp_path / "second"
    other.mkdir()
    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.import_project(other, vault_root, "alpha")

    # The point of the ticket: the external target was never read into place.
    landed = other / ".agent-history" / "sessions"
    assert not landed.exists() or not any(landed.glob("*not-yours*"))


def test_sync_state_read_refuses_a_symlinked_ancestor_before_deciding_identity(
    tmp_path, synced
):
    """AC3: the read that feeds require_project_id and the bootstrap qualifier.

    A foreign VAULT-SYNC.yaml reachable through a symlinked `.agent-history`
    would let the one-project-ID guard decide identity from someone else's
    digest — the identity check reading through the hole it exists to close.
    """
    root, vault_root = synced
    foreign = tmp_path / "outside" / ".agent-history"
    foreign.mkdir(parents=True)
    (foreign / "VAULT-SYNC.yaml").write_text(
        "project_id: someone-else\nlast_remote_state_sha256: " + "0" * 64 + "\n",
        encoding="utf-8",
    )

    import shutil

    shutil.rmtree(root / ".agent-history")
    (root / ".agent-history").symlink_to(foreign, target_is_directory=True)

    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.read_sync_state(root)
    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.require_project_id(root, "alpha")


def test_local_index_read_refuses_a_symlinked_ancestor(tmp_path, synced):
    """AC3: INDEX.yaml feeds lifecycle merge and head selection."""
    root, _ = synced
    foreign = tmp_path / "outside" / ".agent-history"
    foreign.mkdir(parents=True)
    (foreign / "INDEX.yaml").write_text(
        "schema_version: 1\nlatest_session: not-yours\nsessions: []\n", encoding="utf-8"
    )

    import shutil

    shutil.rmtree(root / ".agent-history")
    (root / ".agent-history").symlink_to(foreign, target_is_directory=True)

    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.read_state_local(root)


def test_sync_state_write_refuses_a_symlinked_ancestor_and_leaves_it_untouched(
    tmp_path
):
    """AC4: the only *mutating* site in the enumeration."""
    root = tmp_path / "repo"
    root.mkdir()
    foreign = tmp_path / "outside" / ".agent-history"
    foreign.mkdir(parents=True)
    sentinel = foreign / "VAULT-SYNC.yaml"
    sentinel.write_text("project_id: untouched\n", encoding="utf-8")
    (root / ".agent-history").symlink_to(foreign, target_is_directory=True)

    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.write_sync_state(root, "alpha", "0" * 64)
    assert sentinel.read_text(encoding="utf-8") == "project_id: untouched\n"


def test_decisions_read_refuses_rather_than_silently_reading_empty(tmp_path, synced):
    """`_read_text` swallows OSError, so an unguarded redirect reads as "none".

    Every other read raises; this one would merge silently, which is why the
    guard has to run before the try rather than inside it.
    """
    root, vault_root = synced
    namespace = vault_root / vault.PROJECTS_DIRNAME / "alpha"
    external = _outside(tmp_path, "DECISIONS.md", "- someone else's decision\n")
    (namespace / vault.DECISIONS_FILENAME).symlink_to(external)

    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.export_project(root, vault_root, "alpha")


def test_pull_refuses_a_symlinked_local_history_root(tmp_path, synced):
    """The gap the AC5 sweep surfaced: `.agent-history` was created before it was checked.

    `import_project` ran `history_dir.mkdir(parents=True, exist_ok=True)` and
    only reached a containment guard later, inside `LocalWrite.commit`. A
    symlinked `.agent-history` pointing at an existing directory makes that
    `mkdir` a silent no-op rather than an error, so the redirected root survived
    until the first write.

    Nothing leaked either way — `commit` refuses before any byte lands, which is
    why this test passes without the guard too. It is here to pin the ordering,
    and it is the behavioural half of a finding the sweep makes structurally.
    """
    root, vault_root = synced
    external = tmp_path / "elsewhere"
    external.mkdir()
    history = root / writer.AGENT_HISTORY_DIRNAME
    shutil.rmtree(history)
    history.symlink_to(external)

    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.import_project(root, vault_root, "alpha")

    assert list(external.iterdir()) == []


#: Filesystem verbs that read or write content or structure. Existence probes
#: (`exists`, `is_file`, `is_dir`, `is_symlink`) are excluded deliberately: they
#: leak no content and including them would drown the signal.
_FS_VERBS = frozenset({
    "read_text", "write_text", "read_bytes", "write_bytes",
    "iterdir", "glob", "rglob", "walk",
    "mkdir", "rmdir", "unlink", "rename", "replace", "touch", "symlink_to",
    "open", "hardlink_to", "chmod", "copy", "copy2", "copytree", "move",
})

#: Calls that establish containment for the path handed to them. Each takes the
#: path it proves as one of its arguments, which is what lets the sweep match a
#: guard to a *target* rather than merely to a function body.
#:
#: `writer.reject_symlink` is **not** here, and its absence is the point.
#: It tests one path for being a symlink and says nothing about the path's
#: ancestors -- which is exactly the leaf-only shape #88 exists to remove: a
#: symlinked `sessions/` leaves `target.is_symlink()` false while the access
#: still lands outside the tree. Accepting it as proof would let the sweep
#: certify the defect it was built to catch. `vault.py` calls it only through
#: `guard_contained_path`, which walks root → every ancestor → leaf, so nothing
#: in the module depends on it counting.
#:
#: `assert_within` *is* here on its own merit: it compares `path.resolve()`
#: against the resolved root, and resolution follows symlinks, so a redirected
#: ancestor lands outside the root and is refused.
_GUARD_CALLS = frozenset({
    "guard_contained_path", "_prepare_target", "_write_recorded",
    "_read_text", "assert_within",
})

#: Filesystem calls that are unguarded *by design*, keyed by the exact operation
#: -- `(function, verb, target expression)` -- and carrying **how many** such
#: calls the reason covers.
#:
#: The count is the point. Keying by function alone waives a whole body; keying
#: by `function.verb` still waives *every* `unlink` in that method, so a future
#: unrelated `target.unlink()` would inherit a justification written for the
#: rollback. An exemption is a claim about specific calls, so it says how many
#: it is willing to defend: the (n+1)th is an offender, a different target is an
#: offender, and an entry covering more calls than exist is reported stale.
#:
#: Line numbers are deliberately *not* part of the key. They would make every
#: edit above a call look like a new exemption, and the resulting churn teaches
#: reviewers to re-stamp the allowlist without reading it.
#:
#: All four entries are the same pattern: a path recovered from a list that only
#: ever received targets already proven contained. The sweep does not trace
#: values through containers, so it cannot see that -- a limit, stated here
#: rather than papered over.
_UNGUARDED_BY_DESIGN = {
    ("Creations.restore", "write_bytes", "target"): (
        1,
        "rollback path (#93): restores the bytes of a target `_write_recorded` "
        "proved contained via `_prepare_target` before it displaced them",
    ),
    ("Creations.undo", "unlink", "target"): (
        1, "removes only files recorded during a guarded write"
    ),
    ("Creations.undo", "rmdir", "directory"): (
        1, "removes only directories recorded during a guarded write"
    ),
    ("LocalWrite.commit", "unlink", "target"): (
        1,
        "rollback path: every target in `applied` went through `_prepare_target` "
        "in the try body before it was appended",
    ),
    ("LocalWrite.commit", "write_bytes", "target"): (
        1,
        "rollback path: restores the bytes of a target `_prepare_target` already "
        "proved contained on the way in",
    ),
}


#: Receivers that are modules rather than paths. `os.replace(a, b)` is an
#: attribute call whose receiver is `os`, so without this the sweep would take
#: the module name as the path operand -- flagging the call, but for a reason
#: that has nothing to do with either path it touches.
_MODULE_RECEIVERS = frozenset({"os", "os.path", "shutil", "pathlib"})

#: Verbs with a *second* path operand. Both ends land in the filesystem and the
#: destination is the one that decides where bytes come to rest, so a guard on
#: the source alone proves nothing about where the write went.
_TWO_PATH_VERBS = frozenset({"replace", "rename", "copy", "copy2", "copytree", "move"})

# A verb missing from `_FS_VERBS` is never scanned at all, whatever this set
# says about how to read its operands. `copy2` sat here and not there, so the
# operand model knew how to read a call the sweep never asked about. Asserted
# rather than left for the next reader to notice.
assert not _TWO_PATH_VERBS - _FS_VERBS, sorted(_TWO_PATH_VERBS - _FS_VERBS)

#: Link creation, which this module may not do at all. Containment alone is the
#: wrong test for it: guarding the receiver is *correct* and *complete* -- the
#: link node is created inside the tree, and the argument is what it points at,
#: which is outside by design. Requiring a guard on the pointee would forbid
#: symlinks rather than contain them, and for the wrong reason.
#:
#: But "contained" is not the property that matters here. #88 exists to refuse
#: symlinks that leave the vault, so a helper that *creates* one is planting
#: exactly what every other guard in this module refuses to follow. Nothing in
#: `vault.py` creates a link today, so these are refused outright and a future
#: helper that needs one has to argue for it in `_UNGUARDED_BY_DESIGN` rather
#: than inherit a pass from guarding the one operand that was never in doubt.
_LINK_VERBS = frozenset({"symlink_to", "hardlink_to"})


def _path_operands(source, call):
    """Every path expression a filesystem call acts on.

    `p.write_text(...)` acts on `p`; a bare `open(p)` acts on its first argument.
    A two-path verb acts on both ends: `staged.replace(target)` and
    `os.replace(staged, target)` each have to prove `target`, which is the
    operand that decides where the bytes land.

    Trailing `.parent` hops are stripped because a guard on `p` proves every
    ancestor of `p` too -- that is exactly `guard_contained_path`'s contract --
    so `p.parent.mkdir()` is covered by a guard naming `p`.
    """
    import ast

    func = call.func
    verb = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    receiver_is_path = (
        isinstance(func, ast.Attribute)
        and _normalize(ast.get_source_segment(source, func.value)) not in _MODULE_RECEIVERS
    )

    if receiver_is_path:
        nodes = [func.value]
        if verb in _TWO_PATH_VERBS and call.args:
            nodes.append(call.args[0])
    else:
        # Bare `open(p)`, or module-qualified `os.replace(src, dst)` where the
        # receiver is a module and the operands are all in the argument list.
        nodes = list(call.args[: 2 if verb in _TWO_PATH_VERBS else 1])
    if verb in _LINK_VERBS:
        nodes = nodes[:1]

    operands = []
    for node in nodes:
        while isinstance(node, ast.Attribute) and node.attr == "parent":
            node = node.value
        operands.append(_normalize(ast.get_source_segment(source, node)))
    return operands


def _normalize(text):
    """Collapse `Path(x)` to `x` so the two spellings of one path compare equal."""
    if text is None:
        return None
    text = " ".join(text.split())
    while text.startswith("Path(") and text.endswith(")"):
        inner = text[len("Path("):-1]
        if inner.count("(") != inner.count(")"):
            break
        text = inner.strip()
    return text


def unguarded_fs_targets(source):
    """Every filesystem target in *source* not proven contained before it is touched.

    Closed by default, and the check is **dominance**, not line order: a guard
    counts for a filesystem call only if it is certain to have run first. Guards
    are carried *into* nested blocks but never back *out* of them, so a guard
    inside an `if`, an `except`, or a loop body -- any of which may not execute
    -- does not clear a call that follows the block. A guard and its call in the
    same loop body is fine, which is the shape `read_local_archives` uses.

    Presence of some guard elsewhere in the body proves nothing: the guard must
    name *that* target. Returns `(offenders, allowlisted_but_guarded)`.
    """
    import ast

    #: Fields whose contents are conditional or repeated, so guards inside them
    #: cannot be carried out to the statements that follow.
    _BLOCK_FIELDS = ("body", "orelse", "finalbody", "handlers")

    tree = ast.parse(source)
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def qualname(node):
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                return f"{parent.name}.{node.name}"
            parent = parents.get(parent)
        return node.name

    def calls_in(node):
        """Calls in *node*, in evaluation order, not descending into nested blocks."""
        found = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                found.append(child)
        return sorted(found, key=lambda c: (c.lineno, c.col_offset))

    def scan(node, proven, report):
        """Walk one statement list, threading the set of paths proven so far."""
        for stmt in node:
            # A nested def is its own scope with its own callers: it is analysed
            # separately, and must not inherit proof from where it was written.
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            blocks, own = [], []
            for field, value in ast.iter_fields(stmt):
                if field in _BLOCK_FIELDS and isinstance(value, list):
                    blocks.append(value)
                elif isinstance(value, list):
                    own.extend(v for v in value if isinstance(v, ast.AST))
                elif isinstance(value, ast.AST):
                    own.append(value)

            for expr in sorted(own, key=lambda n: (getattr(n, "lineno", 0),
                                                   getattr(n, "col_offset", 0))):
                for call in calls_in(expr):
                    report(call, proven)

            for block in blocks:
                # A copy: what a branch proves stays in the branch.
                scan(block, set(proven), report)

    import collections

    offenders, seen = [], collections.Counter()
    for node in ast.walk(tree):
        # Methods are walked exactly like module functions: every raw byte-level
        # operation in vault.py lives on a class, so a sweep that missed them
        # would miss the calls that matter most.
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = qualname(node)
        found = []

        def report(call, proven, _found=found):
            func = call.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in _FS_VERBS:
                for operand in _path_operands(source, call):
                    ok = called not in _LINK_VERBS and operand in proven
                    why = "creates a link" if called in _LINK_VERBS else "is unguarded"
                    _found.append((call.lineno, called, operand, ok, why))
            # Added after the call is checked, so a guard cannot clear the very
            # call it is an argument to -- and so a guard placed after the write
            # it protects does not count.
            if called in _GUARD_CALLS:
                for arg in call.args:
                    proven.add(_normalize(ast.get_source_segment(source, arg)))

        scan(node.body, set(), report)

        for lineno, verb, target, ok, why in sorted(found):
            if ok:
                continue
            key = (name, verb, target)
            allowed = _UNGUARDED_BY_DESIGN.get(key, (0, ""))[0]
            seen[key] += 1
            if seen[key] <= allowed:
                continue
            extra = (
                f" -- the allowlist covers {allowed}, this is #{seen[key]}"
                if allowed
                else ""
            )
            offenders.append(
                f"{name} {why}: {target or '?'} via .{verb}() at line {lineno}{extra}"
            )

    stale = sorted(
        f"{name}.{verb}({target}) covers {allowed}, found {seen[(name, verb, target)]}"
        for (name, verb, target), (allowed, _) in _UNGUARDED_BY_DESIGN.items()
        if seen[(name, verb, target)] < allowed
    )
    return offenders, stale


def test_every_vault_helper_reaching_the_filesystem_guards_containment():
    """AC5: closed by default -- a new unguarded filesystem target fails this test.

    Walks the module AST rather than matching substrings, so it sees class
    methods as well as module functions, cannot be fooled by a name that merely
    contains a verb, and does not let one guarded path in a body excuse an
    unguarded second one.

    **What it does not prove**, stated because a sweep that overstates itself is
    worse than none:

    * It matches guards to targets *syntactically*. A guard whose containment
      root is the wrong root still satisfies it; only the behavioural symlink
      tests above catch that.
    * It does not trace values through containers. A path recovered from a list
      that only ever held guarded paths reads as unproven -- which is why the
      two rollback paths need `_UNGUARDED_BY_DESIGN` entries rather than being
      recognised automatically.
    * `_FS_VERBS` is a closed list of names. A filesystem call through a verb
      nobody has thought of -- a new stdlib helper, an aliased method -- is
      invisible until the name is added here. `os.symlink`/`os.link` are omitted
      deliberately rather than overlooked: they place the new link at argument
      *one*, inverting pathlib's order, and guessing that wrong would flag the
      pointee and clear the link. Nothing in this module uses them; adding one
      means teaching `_path_operands` the inversion first.
    * It reasons per function body, so a path laundered through an unguarded
      helper that this sweep clears for other reasons is not traced across the
      call boundary.
    """
    import inspect

    offenders, stale = unguarded_fs_targets(inspect.getsource(vault))
    assert offenders == [], "unguarded filesystem access in vault.py: " + "; ".join(offenders)
    assert stale == [], f"allowlist entries cover calls that no longer exist: {stale}"
    assert all(
        reason.strip() for _, reason in _UNGUARDED_BY_DESIGN.values()
    ), "every allowlist entry needs a stated reason"


#: Each case is source the sweep *must* flag, paired with why it would have
#: slipped through the substring version this replaced. These are the sweep's
#: own regression tests: without them "the sweep is closed by default" is a
#: claim about a test, asserted nowhere.
_MUST_BE_FLAGGED = {
    "a new unguarded helper": """
def _future_helper(path):
    return path.read_text()
""",
    # The hole that made the previous sweep a checklist: it asked only whether
    # *a* guard appeared somewhere in the body.
    "a second target left unguarded beside a guarded one": """
def _mixed(root, wanted, other):
    guard_contained_path(root, wanted)
    first = wanted.read_text()
    return first + other.read_text()
""",
    # `inspect.isfunction` over module vars never saw these.
    "an unguarded class method": """
class Writer:
    def commit(self, target):
        target.write_bytes(b"x")
""",
    # #93 stages replacement writes with `os.replace`; the old verb list would
    # not have matched it.
    "a replacement write": """
def _swap(staged, target):
    os.replace(staged, target)
""",
    # A guard on the source proves nothing about where the bytes come to rest.
    # The pathlib spelling is the dangerous one: the destination is an argument
    # while the *receiver* is the guarded source, so a receiver-only sweep reads
    # the call as fully guarded.
    "a replacement whose destination is unguarded (pathlib form)": """
def _swap(root, staged, target):
    guard_contained_path(root, staged)
    staged.replace(target)
""",
    "a replacement whose destination is unguarded (os form)": """
def _swap(root, staged, target):
    guard_contained_path(root, staged)
    os.replace(staged, target)
""",
    "a rename whose destination is unguarded": """
def _swap(root, staged, target):
    guard_contained_path(root, staged)
    staged.rename(target)
""",
    "a move whose destination is unguarded": """
def _swap(root, staged, target):
    guard_contained_path(root, staged)
    shutil.move(staged, target)
""",
    # `copy2` was in `_TWO_PATH_VERBS` but not `_FS_VERBS`, so it was never
    # scanned at all -- the operand model knew how to read it and the sweep
    # never asked.
    "a copy2 with neither end guarded": """
def _clone(src, dst):
    shutil.copy2(src, dst)
""",
    "a copy2 whose destination is unguarded": """
def _clone(root, src, dst):
    guard_contained_path(root, src)
    shutil.copy2(src, dst)
""",
    # A leaf-only check is not containment. Accepting `reject_symlink` as proof
    # would let the sweep certify the exact shape #88 exists to remove: this
    # passes while a symlinked *ancestor* still redirects the read.
    "a leaf-only reject_symlink standing in for containment": """
def _leaf_only(path):
    writer.reject_symlink(path)
    return path.read_text()
""",
    # An exemption is a claim about specific calls, not a licence for the verb.
    # These use the real allowlisted qualnames, so they are the exemption's own
    # boundary rather than a lookalike.
    "a second unguarded unlink beside an allowlisted one": """
class LocalWrite:
    def commit(self, target):
        target.unlink()
        target.unlink()
""",
    "an unguarded unlink on a different target in an allowlisted method": """
class LocalWrite:
    def commit(self, target, other):
        target.unlink()
        other.unlink()
""",
    "an unguarded verb the allowlisted method does not have an exemption for": """
class LocalWrite:
    def commit(self, target):
        target.unlink()
        target.write_text("x")
""",
    # Guarding the receiver is correct for containment and still not enough:
    # `vault.py` has no business creating the thing its every other guard
    # refuses to follow.
    "a symlink created at a fully guarded path": """
def _plant(root, link, external):
    guard_contained_path(root, link)
    link.symlink_to(external)
""",
    "a directory removal": """
def _prune(directory):
    directory.rmdir()
""",
    # Checking after touching is this repo's recurring shape, so the sweep is
    # ordered rather than set-based.
    "a guard placed after the write it protects": """
def _late(root, target):
    target.write_text("x")
    guard_contained_path(root, target)
""",
    # Line order is not dominance. A guard that only *might* have run does not
    # clear a call that always runs, so guards never escape their block.
    "a guard inside an if branch": """
def _maybe(root, target, flag):
    if flag:
        guard_contained_path(root, target)
    target.write_text("x")
""",
    "a guard inside an except handler": """
def _maybe(root, target):
    try:
        pass
    except OSError:
        guard_contained_path(root, target)
    target.write_text("x")
""",
    "a guard inside a loop body, with the write after the loop": """
def _maybe(root, target, items):
    for _ in items:
        guard_contained_path(root, target)
    target.write_text("x")
""",
    "a guard in the if branch, write in the else branch": """
def _maybe(root, target, flag):
    if flag:
        guard_contained_path(root, target)
    else:
        target.write_text("x")
""",
}

#: Source the sweep must *not* flag. A check that fires on everything closes
#: nothing, and two of these encode contracts the real module depends on.
_MUST_BE_CLEAN = {
    "a guarded read": """
def _fine(root, target):
    guard_contained_path(root, target)
    return target.read_text()
""",
    # `guard_contained_path` proves the whole ancestry, so a guard on the leaf
    # covers its parent -- which is how `_prepare_target` and `write_sync_state`
    # are written.
    "a parent derived from a guarded target": """
def _fine(root, target):
    guard_contained_path(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
""",
    # `p.relative_to(p)` has no parts, so `guard_contained_path(p, p)` reduces
    # to the root symlink check -- exact, not a special case.
    "a path guarded as its own root": """
def _fine(path):
    guard_contained_path(path, path)
    return any(path.iterdir())
""",
    "an existence probe": """
def _fine(path):
    return path.exists() and path.is_symlink()
""",
    "a replacement with both ends guarded": """
def _fine(root, staged, target):
    guard_contained_path(root, staged)
    guard_contained_path(root, target)
    staged.replace(target)
""",
    # Guards are carried *into* nested blocks -- this is `read_marker`'s shape.
    "a guard at body level with the write inside a try": """
def _fine(root, target):
    guard_contained_path(root, target)
    try:
        return target.read_text()
    except OSError:
        return ""
""",
    # ...and a guard beside its own call inside a loop is fine, which is how
    # `read_local_archives` guards each entry it iterates over.
    "a guard and its read in the same loop body": """
def _fine(root, directory):
    guard_contained_path(root, directory)
    for path in directory.glob("*.md"):
        guard_contained_path(root, path)
        yield path.read_text()
""",
    # Exactly the one call the reason defends, and no more.
    "the single unguarded unlink the allowlist actually covers": """
class LocalWrite:
    def commit(self, target):
        target.unlink()
""",
    "a guard at body level with the write nested two blocks deep": """
def _fine(root, target, flag, items):
    guard_contained_path(root, target)
    if flag:
        for _ in items:
            target.write_text("x")
""",
}


@pytest.mark.parametrize("case", sorted(_MUST_BE_FLAGGED))
def test_the_containment_sweep_flags_what_it_claims_to(case):
    offenders, _ = unguarded_fs_targets(_MUST_BE_FLAGGED[case])
    assert offenders, f"the sweep missed {case}, so it does not close the class"


@pytest.mark.parametrize("case", sorted(_MUST_BE_CLEAN))
def test_the_containment_sweep_accepts_a_properly_guarded_body(case):
    offenders, _ = unguarded_fs_targets(_MUST_BE_CLEAN[case])
    assert offenders == [], f"the sweep wrongly flagged {case}: {offenders}"


def test_resolve_refuses_a_symlinked_conflicts_source(tmp_path, synced):
    """AC2, resolve half: `conflicts/` is read by resolve, not by pull."""
    root, vault_root = synced
    namespace = vault_root / vault.PROJECTS_DIRNAME / "alpha"
    external = tmp_path / "outside" / "conflicts"
    external.mkdir(parents=True)
    (external / "manifest.yaml").write_text(
        "format: session-glue-vault-conflicts-v1\nconflicts: []\n", encoding="utf-8"
    )
    (namespace / vault.CONFLICTS_DIRNAME).symlink_to(external, target_is_directory=True)

    with pytest.raises((vault.VaultError, writer.HandoffWriteError)):
        vault.read_manifest(namespace)


# --------------------------------------------------------------------------- #
# Issue #89 — pull preserves divergent local history instead of overwriting it
# --------------------------------------------------------------------------- #


SESSION = "2026-08-28-1200-alpha"


@pytest.fixture()
def pulled(tmp_path, checkout):
    """Device B, having pulled once, so both sides hold the same session."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    other = tmp_path / "device-b"
    other.mkdir()
    vault.import_project(other, vault_root, "alpha")
    return other, vault_root


def _local_archive(root):
    return next((root / ".agent-history" / vault.SESSIONS_DIRNAME).glob("*.md"))


def _vault_state_path(vault_root):
    return (
        vault_root / vault.PROJECTS_DIRNAME / "alpha"
        / vault.STATE_DIRNAME / vault.STATE_FILENAME
    )


def _set_vault_lifecycle(vault_root, session_id, status):
    """Give the vault a lifecycle status for *session_id*, leaving the rest alone."""
    path = _vault_state_path(vault_root)
    state = schema.parse_mapping(path.read_text(encoding="utf-8"))
    state["lifecycle"] = [{"session_id": session_id, "status": status}]
    path.write_text(vault.render_vault_state(state), encoding="utf-8")


def test_pull_refuses_when_the_same_session_diverged_and_writes_nothing(pulled):
    """AC1/AC3: the data-loss path in #82 — `union.update` silently overwrote.

    Asserted as *bytes preserved*, not merely as "it raised": the whole point of
    #89 is that the local version is still there afterwards, so a `pytest.raises`
    alone would pass even if pull had written first and failed later.
    """
    other, vault_root = pulled
    archive = _local_archive(other)
    mine = archive.read_text(encoding="utf-8").replace("Did the thing.", "My local edit.")
    archive.write_text(mine, encoding="utf-8")
    before = {p: p.read_bytes() for p in (other / ".agent-history").rglob("*") if p.is_file()}

    with pytest.raises(vault.VaultConflict) as excinfo:
        vault.import_project(other, vault_root, "alpha")

    assert archive.read_text(encoding="utf-8") == mine
    assert {p: p.read_bytes() for p in (other / ".agent-history").rglob("*") if p.is_file()} == before
    assert f"--archive {SESSION}=local|vault" in str(excinfo.value)
    assert "--lifecycle" not in str(excinfo.value)


def test_pull_refuses_on_lifecycle_divergence_and_names_the_lifecycle_selector(pulled):
    """AC3: divergence that is not in the archive bytes at all."""
    other, vault_root = pulled
    _set_vault_lifecycle(vault_root, SESSION, "DONE")
    index = other / ".agent-history" / "INDEX.yaml"
    index.write_text(
        index.read_text(encoding="utf-8").replace("status: DONE", "status: BLOCKED"),
        encoding="utf-8",
    )
    before = index.read_bytes()

    with pytest.raises(vault.VaultConflict) as excinfo:
        vault.import_project(other, vault_root, "alpha")

    assert index.read_bytes() == before
    assert f"--lifecycle {SESSION}=local|vault" in str(excinfo.value)
    assert "--archive" not in str(excinfo.value)


def test_pull_names_both_selectors_when_one_session_diverged_both_ways(pulled):
    """AC3: "`--archive`, `--lifecycle`, or both" — the *both* case."""
    other, vault_root = pulled
    archive = _local_archive(other)
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "My local edit."),
        encoding="utf-8",
    )
    _set_vault_lifecycle(vault_root, SESSION, "DONE")
    index = other / ".agent-history" / "INDEX.yaml"
    index.write_text(
        index.read_text(encoding="utf-8").replace("status: DONE", "status: BLOCKED"),
        encoding="utf-8",
    )

    with pytest.raises(vault.VaultConflict) as excinfo:
        vault.import_project(other, vault_root, "alpha")

    message = str(excinfo.value)
    assert f"--archive {SESSION}=local|vault" in message
    assert f"--lifecycle {SESSION}=local|vault" in message
    # One line for the session, carrying both selectors, rather than two entries.
    assert sum(line.strip().startswith(SESSION) for line in message.splitlines()) == 1


def test_pull_refuses_a_path_two_different_sessions_claim(pulled):
    """AC1: not resolvable — no selector can name a path collision.

    Raised as `VaultError`, not `VaultConflict`: pointing the operator at
    `resolve` here would send them to a command with no selector that applies.
    """
    other, vault_root = pulled
    archive = _local_archive(other)
    archive.write_text(
        archive.read_text(encoding="utf-8").replace(
            f"session_id: {SESSION}", "session_id: 2026-08-29-0900-other"
        ),
        encoding="utf-8",
    )
    before = archive.read_bytes()

    with pytest.raises(vault.VaultError) as excinfo:
        vault.import_project(other, vault_root, "alpha")

    assert not isinstance(excinfo.value, vault.VaultConflict)
    assert archive.read_bytes() == before
    message = str(excinfo.value)
    assert f"{vault.SESSIONS_DIRNAME}/{SESSION}.md" in message
    assert "2026-08-29-0900-other" in message and SESSION in message
    assert "resolve" not in message


def test_pull_refuses_an_archive_with_no_usable_session_id(pulled):
    """AC1: the other non-resolvable shape."""
    other, vault_root = pulled
    archive = _local_archive(other)
    archive.write_text(
        archive.read_text(encoding="utf-8").replace(f"session_id: {SESSION}\n", ""),
        encoding="utf-8",
    )
    before = archive.read_bytes()

    with pytest.raises(vault.VaultError) as excinfo:
        vault.import_project(other, vault_root, "alpha")

    assert not isinstance(excinfo.value, vault.VaultConflict)
    assert archive.read_bytes() == before
    assert "no usable session ID" in str(excinfo.value)


def test_pull_still_succeeds_when_the_shared_session_is_unchanged(pulled):
    """The control: a guard that refuses everything would pass every test above."""
    other, vault_root = pulled
    assert vault.import_project(other, vault_root, "alpha")
    assert validator.validate_history(other, check_sessions=True) == []


def test_resolve_accepts_the_vault_version_that_pull_refused_to_take(pulled):
    """AC2/AC4: taking the vault copy is a choice, and only `resolve` can make it."""
    other, vault_root = pulled
    archive = _local_archive(other)
    original = archive.read_text(encoding="utf-8")
    archive.write_text(original.replace("Did the thing.", "My local edit."), encoding="utf-8")

    with pytest.raises(vault.VaultConflict):
        vault.import_project(other, vault_root, "alpha")

    vault.resolve_project(
        other, vault_root, "alpha", SESSION, archive_choices={SESSION: "vault"}
    )

    # AC4: resolve is the flow that persists candidates, and both sides survive.
    records = vault.read_manifest(vault_root / vault.PROJECTS_DIRNAME / "alpha")
    assert {r["side"] for r in records if r["kind"] == "archive"} == {"local", "vault"}

    # The selection is materialized locally, rooted at *this* checkout.
    landed = _local_archive(other).read_text(encoding="utf-8")
    assert "Did the thing." in landed and "My local edit." not in landed
    assert vault.VAULT_ROOT_TOKEN not in landed
    assert validator.validate_history(other, check_sessions=True) == []

    # And the deadlock is gone: the pull that refused now has nothing to refuse.
    assert vault.import_project(other, vault_root, "alpha")


def test_resolving_to_local_keeps_the_local_bytes_and_clears_the_conflict(pulled):
    """The counterpart selection: choosing `local` must also settle the conflict.

    Worth asserting separately even though local already holds these bytes: the
    resolve tail rewrites local history either way, so this is the case where a
    wrong materialization would overwrite the operator's own choice with the
    version they rejected.
    """
    other, vault_root = pulled
    archive = _local_archive(other)
    mine = archive.read_text(encoding="utf-8").replace("Did the thing.", "My local edit.")
    archive.write_text(mine, encoding="utf-8")

    vault.resolve_project(
        other, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
    )

    assert _local_archive(other).read_text(encoding="utf-8") == mine
    assert vault.import_project(other, vault_root, "alpha")
    assert _local_archive(other).read_text(encoding="utf-8") == mine


def test_resolving_lifecycle_to_vault_lands_the_status_locally(pulled):
    """AC4 for the other kind: a lifecycle selection is materialized too."""
    other, vault_root = pulled
    _set_vault_lifecycle(vault_root, SESSION, "DONE")
    index = other / ".agent-history" / "INDEX.yaml"
    index.write_text(
        index.read_text(encoding="utf-8").replace("status: DONE", "status: BLOCKED"),
        encoding="utf-8",
    )

    with pytest.raises(vault.VaultConflict):
        vault.import_project(other, vault_root, "alpha")

    vault.resolve_project(
        other, vault_root, "alpha", SESSION, lifecycle_choices={SESSION: "vault"}
    )

    statuses = {
        e["session_id"]: e["status"] for e in vault.read_state_local(other)["lifecycle"]
    }
    assert statuses[SESSION] == "DONE"
    assert vault.import_project(other, vault_root, "alpha")


def test_a_fault_in_resolves_local_write_leaves_the_same_file_set_and_bytes(
    pulled, monkeypatch
):
    """The rollback half of the amended AC4.

    Resolve's local materialization is a *replacement* of existing archives, so
    a fault partway through is the case that could leave a checkout holding half
    one version and half another. The vault publication has already succeeded at
    this point; what this pins is that the local side is all-or-nothing.
    """
    other, vault_root = pulled
    archive = _local_archive(other)
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "My local edit."),
        encoding="utf-8",
    )
    history = other / ".agent-history"
    before = {p: p.read_bytes() for p in history.rglob("*") if p.is_file()}

    original_commit = vault.LocalWrite.commit
    monkeypatch.setattr(
        vault.LocalWrite, "commit", lambda self, **_: original_commit(self, fault_after=1)
    )
    with pytest.raises(vault.VaultError, match="injected replace-phase fault"):
        vault.resolve_project(
            other, vault_root, "alpha", SESSION, archive_choices={SESSION: "vault"}
        )

    assert {p: p.read_bytes() for p in history.rglob("*") if p.is_file()} == before


def test_a_failed_local_write_leaves_the_sync_digest_unadvanced(pulled, monkeypatch):
    """Local materialization runs *before* `VAULT-SYNC.yaml`, so a failure is un-run."""
    other, vault_root = pulled
    archive = _local_archive(other)
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "My local edit."),
        encoding="utf-8",
    )
    before = vault.read_sync_state(other)

    original_commit = vault.LocalWrite.commit
    monkeypatch.setattr(
        vault.LocalWrite, "commit", lambda self, **_: original_commit(self, fault_after=1)
    )
    with pytest.raises(vault.VaultError, match="injected replace-phase fault"):
        vault.resolve_project(
            other, vault_root, "alpha", SESSION, archive_choices={SESSION: "vault"}
        )

    assert vault.read_sync_state(other) == before


def test_pull_does_not_persist_conflict_candidates(pulled):
    """AC4: detection is pull's job; retention is `resolve`'s."""
    other, vault_root = pulled
    archive = _local_archive(other)
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "My local edit."),
        encoding="utf-8",
    )

    with pytest.raises(vault.VaultConflict):
        vault.import_project(other, vault_root, "alpha")

    assert not (vault_root / vault.PROJECTS_DIRNAME / "alpha" / vault.CONFLICTS_DIRNAME).exists()


def test_a_local_only_lifecycle_entry_survives_a_clean_pull(pulled):
    """The vault's list alone would have dropped this; the merged one keeps it."""
    other, vault_root = pulled
    _write_history(other, session_id="2026-08-27-0900-local-only")
    index = other / ".agent-history" / "INDEX.yaml"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "sessions:", "sessions:\n  - session_id: 2026-08-27-0900-local-only\n    status: DONE"
        ),
        encoding="utf-8",
    )

    vault.import_project(other, vault_root, "alpha")

    assert "2026-08-27-0900-local-only" in index.read_text(encoding="utf-8")
    assert {
        e["session_id"] for e in vault.read_state_local(other)["lifecycle"]
    } >= {"2026-08-27-0900-local-only"}


def test_a_pre_feature_multi_session_history_pushes_pulls_and_resumes(tmp_path):
    """AC7 / closes #82 AC7: the whole point of the feature, end to end.

    "Pre-feature" is the load-bearing word: this checkout is built by the shipped
    writer alone and has never synced, so it has no `VAULT-SYNC.yaml` and no
    vault-shaped anything. It is the history an operator already had before the
    vault existed, and it has to survive the round trip without a migration step.
    """
    source = tmp_path / "laptop"
    source.mkdir()
    sessions = [
        "2026-08-26-0900-first",
        "2026-08-27-1000-second",
        "2026-08-28-1200-alpha",
    ]
    for session_id in sessions:
        _write_history(source, session_id=session_id)
    assert vault.read_sync_state(source) is None  # never synced: genuinely pre-feature
    assert validator.validate_history(source, check_sessions=True) == []

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(source, vault_root, "alpha")

    other = tmp_path / "desktop"
    other.mkdir()
    vault.import_project(other, vault_root, "alpha")

    history = other / ".agent-history"
    assert {p.stem for p in (history / vault.SESSIONS_DIRNAME).glob("*.md")} == set(sessions)
    assert validator.validate_history(other, check_sessions=True) == []

    # Resume: the prompt and LATEST are rooted at *this* device, not the laptop.
    resume = (history / "RESUME_PROMPT.txt").read_text(encoding="utf-8")
    latest = (history / "LATEST.md").read_text(encoding="utf-8")
    assert vault.VAULT_ROOT_TOKEN not in resume and vault.VAULT_ROOT_TOKEN not in latest
    assert str(source) not in resume and str(source) not in latest
    frontmatter, _ = schema.parse_frontmatter(latest)
    assert frontmatter["repo_root"] == str(other)
    assert frontmatter["session_id"] == sessions[-1]

    # Recovery evidence: pulling again is a clean no-op rather than a conflict,
    # which is what makes the migrated history genuinely usable and not a
    # one-shot import.
    assert vault.import_project(other, vault_root, "alpha")
    assert validator.validate_history(other, check_sessions=True) == []


def test_a_pre_feature_history_needing_root_migration_says_so_before_any_write(tmp_path):
    """AC7's migration evidence: the blocking case names the session and writes nothing."""
    source = tmp_path / "laptop"
    source.mkdir()
    _write_history(source, session_id="2026-08-26-0900-first")
    _write_history(
        source, session_id="2026-08-28-1200-alpha", project_root=str(tmp_path / "outside")
    )
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    with pytest.raises(vault.VaultError) as excinfo:
        vault.export_project(source, vault_root, "alpha")

    # Refused before any vault artifact exists, pointing at the way out, and
    # naming the session that blocks it — #77 requires the blocking session ID,
    # and `migrate-roots` takes exactly that as `--session-id`.
    #
    # Deliberately no assertion that the *other* session is absent. A message
    # that named every blocking session would still satisfy #77, so asserting
    # its absence would make a legitimate future improvement fail this test —
    # the same shape as the `not in` assertion this replaced.
    assert not (vault_root / vault.PROJECTS_DIRNAME).exists()
    assert "migrate-roots" in str(excinfo.value)
    assert "2026-08-28-1200-alpha" in str(excinfo.value)

    # The named migration is the documented way out, and then the round trip works.
    vault.migrate_roots(source, "2026-08-28-1200-alpha", source)
    vault.export_project(source, vault_root, "alpha")
    other = tmp_path / "desktop"
    other.mkdir()
    vault.import_project(other, vault_root, "alpha")
    assert validator.validate_history(other, check_sessions=True) == []


def test_a_local_only_archive_survives_a_resolve_and_stays_indexed(pulled):
    """AC6, resolve half: `rebuild_derived` must see the union, not the selection.

    Its own docstring says rebuilding from the vault's set alone "would silently
    orphan a local-only session, which nothing downstream would detect" — so the
    archive surviving on disk is not enough to prove this. The `INDEX.yaml`
    assertion is the one that would catch a subset rebuild.
    """
    other, vault_root = pulled
    _write_history(other, session_id="2026-08-27-0900-local-only")
    archive = _local_archive(other)
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "My local edit."),
        encoding="utf-8",
    )

    vault.resolve_project(
        other, vault_root, "alpha", SESSION, archive_choices={SESSION: "vault"}
    )

    history = other / ".agent-history"
    assert (history / vault.SESSIONS_DIRNAME / "2026-08-27-0900-local-only.md").is_file()
    index = schema.parse_mapping((history / "INDEX.yaml").read_text(encoding="utf-8"))
    assert "2026-08-27-0900-local-only" in {
        str(entry.get("session_id")) for entry in index["sessions"]
    }
    assert validator.validate_history(other, check_sessions=True) == []


def test_re_running_the_same_selector_completes_after_a_local_write_failure(
    pulled, monkeypatch
):
    """AC4's recovery clause: vault published, local rolled back, same command finishes it.

    This is the cross-store partial failure — the two stores cannot commit
    together — so what makes it safe is that the second run is not a different
    command with different flags.
    """
    other, vault_root = pulled
    archive = _local_archive(other)
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "My local edit."),
        encoding="utf-8",
    )

    original_commit = vault.LocalWrite.commit
    monkeypatch.setattr(
        vault.LocalWrite, "commit", lambda self, **_: original_commit(self, fault_after=1)
    )
    with pytest.raises(vault.VaultError, match="injected replace-phase fault"):
        vault.resolve_project(
            other, vault_root, "alpha", SESSION, archive_choices={SESSION: "vault"}
        )
    monkeypatch.undo()

    # The vault kept the publication; the identical command now completes.
    vault.resolve_project(
        other, vault_root, "alpha", SESSION, archive_choices={SESSION: "vault"}
    )

    landed = _local_archive(other).read_text(encoding="utf-8")
    assert "Did the thing." in landed and "My local edit." not in landed
    assert vault.import_project(other, vault_root, "alpha")
    # Retention stayed idempotent across the two publications.
    records = vault.read_manifest(vault_root / vault.PROJECTS_DIRNAME / "alpha")
    assert len(records) == len({(r["session_id"], r["kind"], r["side"], r["sha256"]) for r in records})


# --------------------------------------------------------------------------- #
# Issue #91 — resolve gates DECISIONS.md before it publishes
# --------------------------------------------------------------------------- #


SECRET = "ghp_" + "d" * 20


@pytest.fixture()
def diverged_vault(tmp_path, checkout):
    """A vault whose shared session diverged, so `resolve` has something to do."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    _diverge(vault_root)
    return checkout, vault_root


def _local_decisions(root, text):
    (root / ".agent-history" / vault.DECISIONS_FILENAME).write_text(text, encoding="utf-8")


def _namespace(vault_root):
    return vault_root / vault.PROJECTS_DIRNAME / "alpha"


def test_resolve_blocks_when_only_decisions_carries_a_finding(diverged_vault):
    """AC2: the #82 hole — the archive conflict is clean, the decision is not.

    The archives here are deliberately free of any match, so the *only* thing
    that can block is `DECISIONS.md`. Before this fix the gate had already run by
    the time decisions were added to `content`, and the secret was published.
    """
    root, vault_root = diverged_vault
    _local_decisions(root, f"# Decisions\n\n- 2026-08-28 {SESSION} 1 use token {SECRET}\n")
    state_before = vault.state_path(_namespace(vault_root)).read_bytes()

    with pytest.raises(vault.PrivacyBlocked) as excinfo:
        vault.resolve_project(
            root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
        )

    # AC4/AC5: nothing published, and the match text never echoed.
    assert vault.state_path(_namespace(vault_root)).read_bytes() == state_before
    assert not (_namespace(vault_root) / vault.DECISIONS_FILENAME).exists()
    assert SECRET not in str(excinfo.value)
    assert vault.DECISIONS_FILENAME in str(excinfo.value)


def test_acknowledging_the_decision_triple_lets_the_resolve_through(diverged_vault):
    """AC3: the block is releasable by the exact triple, not merely a refusal."""
    root, vault_root = diverged_vault
    decisions = f"# Decisions\n\n- 2026-08-28 {SESSION} 1 use token {SECRET}\n"
    _local_decisions(root, decisions)

    with pytest.raises(vault.PrivacyBlocked) as excinfo:
        vault.resolve_project(
            root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
        )
    finding = excinfo.value.findings[0]

    vault.resolve_project(
        root, vault_root, "alpha", SESSION,
        archive_choices={SESSION: "local"},
        acknowledgements=[
            {"path": finding.path, "sha256": finding.sha256, "label": finding.label}
        ],
    )

    published = (_namespace(vault_root) / vault.DECISIONS_FILENAME).read_text(encoding="utf-8")
    assert SECRET in published


def test_unchanged_vault_decisions_are_not_re_gated(tmp_path, checkout):
    """AC3: an acknowledgement binds to a digest, so carrying bytes forward is free.

    The vault already holds this decision under an acknowledgement. A later
    resolve that does not change it must not demand the acknowledgement again —
    re-gating would make every subsequent resolve fail for content this
    operation did not introduce.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _local_decisions(checkout, f"# Decisions\n\n- 2026-08-28 {SESSION} 1 use token {SECRET}\n")

    # Acknowledge from the challenge the tool actually issues: the gated artifact
    # is the *merged* text, whose digest is not the raw file's.
    with pytest.raises(vault.PrivacyBlocked) as excinfo:
        vault.export_project(checkout, vault_root, "alpha")
    finding = excinfo.value.findings[0]
    vault.export_project(
        checkout, vault_root, "alpha",
        acknowledgements=[
            {"path": finding.path, "sha256": finding.sha256, "label": finding.label}
        ],
    )
    published = _namespace(vault_root) / vault.DECISIONS_FILENAME
    assert published.is_file()

    # Make the local copy byte-identical to the vault's, so the merge introduces
    # nothing and the artifact is genuinely carried forward.
    _local_decisions(checkout, published.read_text(encoding="utf-8"))
    _diverge(vault_root)

    # No acknowledgement passed this time.
    vault.resolve_project(
        checkout, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
    )

    assert SECRET in (_namespace(vault_root) / vault.DECISIONS_FILENAME).read_text(
        encoding="utf-8"
    )


def test_the_manifest_is_assembled_but_not_treated_as_user_content(diverged_vault):
    """AC1: bookkeeping is exempt by name, not by being appended after the gate."""
    root, vault_root = diverged_vault

    vault.resolve_project(
        root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
    )

    manifest = _namespace(vault_root) / vault.CONFLICTS_DIRNAME / vault.MANIFEST_FILENAME
    assert manifest.is_file()
    assert vault.read_manifest(_namespace(vault_root))


def test_published_content_is_exactly_the_gated_set_plus_two_named_exemptions(
    diverged_vault, monkeypatch
):
    """AC1, observed end to end: what the gate was handed, versus what was published.

    `resolve_project` assembles the final mapping, hands the gate everything in
    it except the named exemptions, and publishes that same mapping unchanged.
    There is no separate check to call and nothing to inject from outside, so
    this observes the two ends instead: `gate_artifacts` is spied to capture its
    input, and the vault directory is read afterwards to see what actually
    landed.

    Only two artifacts may be published without having been gated, and #91 names
    both: the tooling-written manifest, and a decision carried forward
    byte-identical from the vault. Vault-owned bookkeeping — the state file and
    the marker — is subtracted because it is written by `_publish`, not drawn
    from the content mapping at all.
    """
    root, vault_root = diverged_vault
    _local_decisions(root, f"# Decisions\n\n- 2026-08-28 {SESSION} 1 keep this\n")

    gated = {}
    real = vault.gate_artifacts
    monkeypatch.setattr(
        vault,
        "gate_artifacts",
        lambda artifacts, acks=None: gated.update(artifacts) or real(artifacts, acks),
    )

    vault.resolve_project(
        root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
    )

    namespace = _namespace(vault_root)
    published = {
        str(path.relative_to(namespace).as_posix())
        for path in namespace.rglob("*")
        if path.is_file()
    }
    # Vault-owned bookkeeping the operator never wrote.
    published -= {
        f"{vault.STATE_DIRNAME}/{vault.STATE_FILENAME}",
        vault.MARKER_FILENAME,
        f"{vault.CONFLICTS_DIRNAME}/{vault.MANIFEST_FILENAME}",
    }

    assert vault.DECISIONS_FILENAME in gated, "a changed decision must reach the gate"
    ungated = published - set(gated)
    assert ungated == set(), f"published without ever reaching the privacy gate: {ungated}"


# --------------------------------------------------------------------------- #
# Issue #93 — a failed folder publication cannot make truncated bytes authoritative
# --------------------------------------------------------------------------- #


def _vault_snapshot(namespace):
    """Every file under the namespace and its exact bytes."""
    return {
        path.relative_to(namespace).as_posix(): path.read_bytes()
        for path in namespace.rglob("*")
        if path.is_file()
    }


def _tear_write_at(monkeypatch, matches, keep=lambda text: text[:40]):
    """Fail a publication write partway, leaving `keep(text)` behind.

    Patches `Path.write_text` rather than adding a production seam: the point is
    that the *filesystem* write dies mid-way, which no parameter of ours can
    honestly simulate. `matches` selects which target tears so a test can aim at
    an archive rather than at whichever file happens to be written first.
    """
    real = pathlib.Path.write_text
    fired = []

    def torn(self, data, **kwargs):
        if matches(self):
            fired.append(self.name)
            real(self, keep(data), **kwargs)
            raise OSError("simulated disk-full mid-write")
        return real(self, data, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", torn)
    return fired


def _is_vault_archive(path):
    return path.suffix in (".md", ".partial") and "sessions" in str(path) and "projects" in str(path)


def _body_only(text):
    """Truncate after the frontmatter, keeping it fully parseable — #82's case."""
    return text[: text.index("---", text.index("---") + 3) + 20]


@pytest.fixture()
def diverged(tmp_path, checkout):
    """A vault whose archive differs, so `resolve` must *replace* it."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    _diverge(vault_root)
    return checkout, vault_root, vault_root / "projects" / "alpha"


def test_a_body_only_truncation_during_resolve_never_becomes_authoritative(
    diverged, monkeypatch
):
    """AC1: the exact #82 finding, which the referenced-archive check cannot catch.

    A truncation that keeps the whole frontmatter still parses, so
    `require_referenced_archives` reports the archive as present and the
    surviving state/marker make the partial bytes authoritative — another device
    then pulls them. Verified on the pre-#93 code: the check passed and a pull
    materialized the truncated archive.
    """
    root, vault_root, namespace = diverged
    before = _vault_snapshot(namespace)
    fired = _tear_write_at(monkeypatch, _is_vault_archive, keep=_body_only)

    with pytest.raises(OSError, match="simulated disk-full"):
        vault.resolve_project(
            root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
        )

    assert fired, "the seam never reached an archive write; the test proves nothing"
    assert _vault_snapshot(namespace) == before
    # The guarantee restated the way #82 framed it: not merely "bytes restored",
    # but that nothing authoritative points at partial content.
    vault.require_referenced_archives(namespace, vault.read_state(namespace))


def test_a_mid_write_failure_during_push_leaves_the_vault_exactly_as_it_was(
    tmp_path, checkout, monkeypatch
):
    """AC2/AC4: the same seam on the push path, where state and marker are replaced."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault.export_project(checkout, vault_root, "alpha")
    namespace = vault_root / "projects" / "alpha"
    _write_history(checkout, session_id="2026-08-29-0900-second")
    before = _vault_snapshot(namespace)

    fired = _tear_write_at(monkeypatch, lambda p: "vault-state" in p.name)
    with pytest.raises(OSError, match="simulated disk-full"):
        vault.export_project(checkout, vault_root, "alpha")

    assert fired
    assert _vault_snapshot(namespace) == before
    assert vault.read_sync_state(checkout)  # the baseline never advanced past it


def test_a_partial_set_failure_restores_every_archive_already_replaced(
    diverged, monkeypatch
):
    """AC2: partial-set failure, distinct from a torn single write.

    `fault_after` stops the publication cleanly between targets, so earlier ones
    were fully replaced with new bytes. Restoring them is the half `Creations`
    could not do before #93 — it removed created files and left displaced ones.
    """
    root, vault_root, namespace = diverged
    before = _vault_snapshot(namespace)
    real_publish = vault._publish
    monkeypatch.setattr(
        vault, "_publish", lambda *a, **k: real_publish(*a, **{**k, "fault_after": 1})
    )

    with pytest.raises(vault.VaultError, match="injected publication fault"):
        vault.resolve_project(
            root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
        )

    assert _vault_snapshot(namespace) == before


def test_no_staging_sibling_survives_a_failed_publication(diverged, monkeypatch):
    """AC1 asks for the exact file *set*: a half-written sibling is a new file."""
    root, vault_root, namespace = diverged
    _tear_write_at(monkeypatch, _is_vault_archive, keep=_body_only)

    with pytest.raises(OSError):
        vault.resolve_project(
            root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
        )

    assert list(namespace.rglob("*" + vault.STAGING_SUFFIX)) == []


def test_a_caller_supplied_record_still_owns_its_own_rollback(diverged, monkeypatch):
    """AC3/#87: passing `created` must keep the caller in charge, as Git needs.

    Git sequences `created.undo()` against a `git reset --hard`, so `_publish`
    undoing on its own would double-recover. This pins that the folder-mode
    rollback added by #93 is conditional, not unconditional.
    """
    root, vault_root, namespace = diverged
    record = vault.Creations()
    archive = next((namespace / vault.SESSIONS_DIRNAME).glob("*.md"))
    original = archive.read_bytes()

    _tear_write_at(monkeypatch, _is_vault_archive, keep=_body_only)
    with pytest.raises(OSError):
        vault.resolve_project(
            root, vault_root, "alpha", SESSION,
            archive_choices={SESSION: "local"}, created=record,
        )

    # Not rolled back by `_publish` — but recorded, so the caller can.
    assert record.replaced, "nothing recorded for the caller to restore"
    record.restore()
    assert archive.read_bytes() == original


def _staging_lookalike(namespace):
    """A file an operator (or a killed run) left where staging wants to write."""
    archive = next((namespace / vault.SESSIONS_DIRNAME).glob("*.md"))
    sibling = archive.with_name(archive.name + vault.STAGING_SUFFIX)
    sibling.write_bytes(b"operator's notes, not ours\n")
    return sibling


def test_a_pre_existing_staging_sibling_survives_a_failed_publication(
    diverged, monkeypatch
):
    """AC1: the rollback must not be the thing that changes the file set.

    A fixed `<target>.partial` would be overwritten on the way in and unlinked on
    the way out, and `Creations` records only the target — so the rollback could
    not have put it back. The staging name is unique per write instead.
    """
    root, vault_root, namespace = diverged
    sibling = _staging_lookalike(namespace)
    before = _vault_snapshot(namespace)
    _tear_write_at(monkeypatch, _is_vault_archive, keep=_body_only)

    with pytest.raises(OSError):
        vault.resolve_project(
            root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
        )

    assert sibling.read_bytes() == b"operator's notes, not ours\n"
    assert _vault_snapshot(namespace) == before


def test_a_pre_existing_staging_sibling_survives_a_successful_publication(diverged):
    """The worse half of the same defect: a fixed name consumes it on success.

    `os.replace(staged, target)` would have moved the operator's file onto the
    archive — silent loss on the *happy* path, with no failure for anyone to
    notice. #87's contract is explicit that an operator file inside the namespace
    survives a sync, and that has to hold when the sync works.
    """
    root, vault_root, namespace = diverged
    sibling = _staging_lookalike(namespace)

    vault.resolve_project(
        root, vault_root, "alpha", SESSION, archive_choices={SESSION: "local"}
    )

    assert sibling.read_bytes() == b"operator's notes, not ours\n"
    archive = next((namespace / vault.SESSIONS_DIRNAME).glob("*.md"))
    assert b"operator's notes" not in archive.read_bytes()


def test_staging_siblings_are_unique_per_write(tmp_path):
    """The mechanism behind both tests above, pinned directly."""
    root = tmp_path / "vault"
    target = root / "projects" / "alpha" / vault.SESSIONS_DIRNAME / "s.md"
    target.parent.mkdir(parents=True)

    first = vault._free_staging_sibling(root, target)
    first.write_bytes(b"occupied")
    second = vault._free_staging_sibling(root, target)

    assert first != second
    assert second.name.endswith(vault.STAGING_SUFFIX)
    assert not second.exists()
    # Never collides with the archive glob, so a leftover cannot be read as one.
    assert second not in set((target.parent).glob("*.md"))


# --------------------------------------------------------------------------- #
# Issue #106 — containment resolves BOTH roots, so a symlinked project_root
# cannot masquerade as an in-repo offset
# --------------------------------------------------------------------------- #


def _escaping_project_root(tmp_path):
    """`<repo>/packages/app` that is really a symlink out of the repository."""
    repo = tmp_path / "repo"
    (repo / "packages").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = repo / "packages" / "app"
    escaped.symlink_to(outside, target_is_directory=True)
    return repo, escaped, outside


def _repo_reached_through_a_symlink(tmp_path):
    """A valid repository whose *path* runs through a symlink.

    The shape a symlinked worktree, a symlinked home, or macOS `/tmp` produces.
    This is the case that separates resolving both roots from resolving only the
    child: child-only rejects it, which would refuse a perfectly good setup.
    """
    real = tmp_path / "real"
    (real / "repo" / "packages" / "api").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    return link / "repo", link / "repo" / "packages" / "api"


def test_export_refuses_a_project_root_that_escapes_through_a_symlink(tmp_path):
    """AC2: rejected before publication — the vault must not exist afterwards.

    Lexically `<repo>/packages/app` is inside the repo, so the old check accepted
    it and stored `<vault-root>/packages/app` — an offset claiming an in-repo
    location that materializes somewhere else on another checkout.
    """
    repo, escaped, _ = _escaping_project_root(tmp_path)
    _write_history(repo, project_root=str(escaped))
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    with pytest.raises(vault.VaultError, match="outside repo_root"):
        vault.export_project(repo, vault_root, "alpha")

    assert not (vault_root / vault.PROJECTS_DIRNAME).exists()


def test_migrate_roots_refuses_a_project_root_that_escapes_through_a_symlink(tmp_path):
    """AC2, the other route: rejected before the migration mutates anything."""
    repo, escaped, _ = _escaping_project_root(tmp_path)
    _write_history(repo)
    history = repo / ".agent-history"
    before = {p: p.read_bytes() for p in history.rglob("*") if p.is_file()}

    with pytest.raises(vault.VaultError, match="outside repo_root"):
        vault.migrate_roots(repo, "2026-08-28-1200-alpha", escaped)

    assert {p: p.read_bytes() for p in history.rglob("*") if p.is_file()} == before


def test_export_still_accepts_a_repository_reached_through_a_symlink(tmp_path):
    """AC1/AC3: the case that distinguishes resolve-both from resolve-child-only.

    Resolving only the project root rejects this — the resolved child sits under
    `real/` while the unresolved parent is `link/` — which would refuse every
    operator whose checkout is reached through a symlink.
    """
    repo, nested = _repo_reached_through_a_symlink(tmp_path)
    _write_history(repo, project_root=str(nested))
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    assert vault.export_project(repo, vault_root, "alpha")

    archive = next(
        (vault_root / vault.PROJECTS_DIRNAME / "alpha" / vault.SESSIONS_DIRNAME).glob("*.md")
    ).read_text(encoding="utf-8")
    assert f"project_root: {vault.VAULT_ROOT_TOKEN}/packages/api" in archive


def test_migrate_roots_still_accepts_a_repository_reached_through_a_symlink(tmp_path):
    """AC3's accepted case on the migration route."""
    repo, nested = _repo_reached_through_a_symlink(tmp_path)
    _write_history(repo)

    relative = vault.migrate_roots(repo, "2026-08-28-1200-alpha", nested)

    rewritten = (repo / ".agent-history" / relative).read_text(encoding="utf-8")
    assert f"project_root: {nested}" in rewritten


@pytest.mark.parametrize(
    "layout",
    ["nested", "equal"],
    ids=["normal-nested-in-repo", "project-root-equals-repo-root"],
)
def test_ordinary_project_roots_are_unaffected(tmp_path, layout):
    """AC1's second half: valid paths keep their raw root-scalar rewrite.

    `project_root == repo_root` renders as exactly `<vault-root>` with no offset,
    which is #77's contract and must survive the change to resolved comparison.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    if layout == "nested":
        project = repo / "packages" / "api"
        project.mkdir(parents=True)
        expected = f"{vault.VAULT_ROOT_TOKEN}/packages/api"
    else:
        project = repo
        expected = vault.VAULT_ROOT_TOKEN
    _write_history(repo, project_root=str(project))
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    assert vault.export_project(repo, vault_root, "alpha")

    archive = next(
        (vault_root / vault.PROJECTS_DIRNAME / "alpha" / vault.SESSIONS_DIRNAME).glob("*.md")
    ).read_text(encoding="utf-8")
    assert f"project_root: {expected}" in archive


def test_a_vanished_project_root_is_not_newly_refused(tmp_path):
    """`Path.resolve()` is non-strict, so a stale archive keeps working.

    An archive can name a `project_root` whose directory has since been deleted.
    Resolution must not turn that into a refusal — it resolves what exists and
    appends the rest.
    """
    repo = tmp_path / "repo"
    (repo / "packages").mkdir(parents=True)
    gone = repo / "packages" / "api"          # never created
    _write_history(repo, project_root=str(gone))
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    assert vault.export_project(repo, vault_root, "alpha")


def test_a_dangling_escape_is_still_refused(tmp_path):
    """The escape must stay caught when its symlink target no longer exists."""
    repo, escaped, outside = _escaping_project_root(tmp_path)
    outside.rmdir()                            # the symlink now dangles
    _write_history(repo, project_root=str(escaped))
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    with pytest.raises(vault.VaultError, match="outside repo_root"):
        vault.export_project(repo, vault_root, "alpha")
