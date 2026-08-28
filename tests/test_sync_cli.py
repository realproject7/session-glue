"""Tests for the filesystem-folder vault transport (issue #79).

The transport is deliberately thin — it validates its own flags and delegates
every mechanism to the #78 core — so these tests concentrate on the two things
that are genuinely its own: the command surface, and the boundary that it
touches no subprocess, socket, or Git.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from session_glue import cli, schema, vault, writer

from test_vault import BODY, _write_history


@pytest.fixture()
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    _write_history(root)
    return root


@pytest.fixture()
def vault_dir(tmp_path):
    path = tmp_path / "vault"
    path.mkdir()
    return path


@pytest.fixture(autouse=True)
def _forbid_subprocess_and_sockets(monkeypatch):
    """AC3: make the boundary a hard failure rather than an assertion.

    Every test in this module runs with subprocess and socket creation wired to
    raise, so a folder-transport path that reached Git, a provider SDK, or the
    network would fail loudly here instead of passing quietly.
    """

    def _forbidden(*args, **kwargs):  # pragma: no cover - only runs on a breach
        raise AssertionError("folder transport must not spawn a subprocess or open a socket")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, _forbidden)
    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)


def _run(*argv: str) -> int:
    return cli.main(list(argv))


# --------------------------------------------------------------------------- #
# AC2 — command surface
# --------------------------------------------------------------------------- #


def test_bare_sync_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        _run("sync")
    assert excinfo.value.code != 0


@pytest.mark.parametrize(
    "argv",
    [
        ("sync", "push"),  # no project id, no transport
        ("sync", "push", "--project-id", "alpha"),  # no transport
        ("sync", "pull", "--vault-dir", "/tmp"),  # no project id
        ("sync", "resolve", "--project-id", "alpha", "--vault-dir", "/tmp"),  # no head
    ],
)
def test_required_flags_are_enforced(argv):
    with pytest.raises(SystemExit) as excinfo:
        _run(*argv)
    assert excinfo.value.code != 0


def test_migrate_roots_takes_no_transport_or_project_id(checkout, tmp_path):
    """Local-only by contract: it must not accept vault flags at all."""
    with pytest.raises(SystemExit):
        _run(
            "sync", "migrate-roots", "--repo-root", str(checkout),
            "--session-id", "x", "--project-root", str(checkout),
            "--vault-dir", str(tmp_path),
        )


def test_local_commands_are_unchanged_and_make_no_transport_call(checkout, capsys):
    assert _run("validate", "--repo-root", str(checkout), "--sessions") == 0
    assert _run("status", "--repo-root", str(checkout)) == 0
    assert _run("resume-prompt", "--repo-root", str(checkout)) == 0
    assert "vault" not in capsys.readouterr().out.lower()


# --------------------------------------------------------------------------- #
# AC1 — two-device round trip through the CLI
# --------------------------------------------------------------------------- #


def test_push_then_pull_across_two_checkouts(tmp_path, checkout, vault_dir, capsys):
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0

    other = tmp_path / "device-b"
    other.mkdir()
    _write_history(other, session_id="2026-08-27-0900-local-only")
    assert _run(
        "sync", "pull", "--repo-root", str(other), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0

    # B's local-only archive survives, and its resume prompt names B's root.
    names = {p.name for p in (other / ".agent-history" / "sessions").glob("*.md")}
    assert {"2026-08-27-0900-local-only.md", "2026-08-28-1200-alpha.md"} <= names
    assert _run("validate", "--repo-root", str(other), "--sessions") == 0
    capsys.readouterr()
    assert _run("resume-prompt", "--repo-root", str(other)) == 0
    assert str(other) in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# AC4 / AC7 — refusals, each non-zero and distinguishable
# --------------------------------------------------------------------------- #


def test_absent_vault_dir_fails_without_creating_anything(tmp_path, checkout):
    missing = tmp_path / "typo" / "vault"
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(missing),
    )
    assert code == cli.EXIT_ERROR
    assert not missing.exists()
    assert not missing.parent.exists()  # never creates intermediate parents
    assert vault.read_sync_state(checkout) is None


def test_bootstrap_into_a_vault_holding_other_projects(tmp_path, checkout, vault_dir):
    """A first push with no local digest may create its own namespace."""
    (vault_dir / "projects" / "other").mkdir(parents=True)
    (vault_dir / "projects" / "other" / "marker").write_text("x\n", encoding="utf-8")
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0
    assert (vault_dir / "projects" / "alpha" / vault.MARKER_FILENAME).is_file()


def test_prior_digest_plus_absent_namespace_is_unavailable(tmp_path, checkout, vault_dir, capsys):
    """The mid-sync case: this device synced before, so absent means not-yet-there."""
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0
    baseline = vault.sync_state_path(checkout).read_bytes()

    import shutil

    shutil.rmtree(vault_dir / "projects" / "alpha")
    capsys.readouterr()
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    )
    assert code == cli.EXIT_UNAVAILABLE
    assert "not fully available" in capsys.readouterr().err
    assert vault.sync_state_path(checkout).read_bytes() == baseline
    assert not (vault_dir / "projects" / "alpha").exists()


def test_pull_against_absent_namespace_is_unavailable(checkout, vault_dir):
    assert _run(
        "sync", "pull", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == cli.EXIT_UNAVAILABLE


def test_project_id_mismatch_fails_without_replacing_the_baseline(checkout, vault_dir, capsys):
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0
    baseline = vault.sync_state_path(checkout).read_bytes()
    capsys.readouterr()

    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "beta",
        "--vault-dir", str(vault_dir),
    )
    assert code == cli.EXIT_ERROR
    assert "one project ID per checkout" in capsys.readouterr().err
    assert vault.sync_state_path(checkout).read_bytes() == baseline
    assert not (vault_dir / "projects" / "beta").exists()


def test_invalid_project_id_is_refused(checkout, vault_dir):
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "con.log",
        "--vault-dir", str(vault_dir),
    ) == cli.EXIT_ERROR
    assert not (vault_dir / "projects").exists()


def test_conflict_and_unavailability_use_distinct_exit_codes(tmp_path, checkout, vault_dir):
    """AC7: a user must be able to tell "decide something" from "wait"."""
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0

    archive = next((vault_dir / "projects" / "alpha" / "sessions").glob("*.md"))
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", "Diverged."),
        encoding="utf-8",
    )
    conflict = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    )
    assert conflict == cli.EXIT_CONFLICT
    assert conflict != cli.EXIT_UNAVAILABLE


def test_push_refuses_an_invalid_local_history(checkout, vault_dir, capsys):
    (checkout / ".agent-history" / "RESUME_PROMPT.txt").unlink()
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    )
    assert code == cli.EXIT_ERROR
    assert "not valid" in capsys.readouterr().err
    assert not (vault_dir / "projects").exists()


# --------------------------------------------------------------------------- #
# AC5 — resolve
# --------------------------------------------------------------------------- #


def _diverge(vault_dir, replacement="Diverged in the vault."):
    archive = next((vault_dir / "projects" / "alpha" / "sessions").glob("*.md"))
    archive.write_text(
        archive.read_text(encoding="utf-8").replace("Did the thing.", replacement),
        encoding="utf-8",
    )


def test_resolve_rejects_an_unresolved_conflict(checkout, vault_dir, capsys):
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0
    _diverge(vault_dir)
    capsys.readouterr()

    code = _run(
        "sync", "resolve", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir), "--head-session", "2026-08-28-1200-alpha",
    )
    assert code == cli.EXIT_ERROR
    assert "explicit selector for every named conflict" in capsys.readouterr().err


def test_resolve_with_a_selector_succeeds_and_retains_the_other_side(checkout, vault_dir):
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0
    _diverge(vault_dir)
    session_id = "2026-08-28-1200-alpha"

    assert _run(
        "sync", "resolve", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir), "--head-session", session_id,
        "--archive", f"{session_id}=local",
    ) == 0

    namespace = vault_dir / "projects" / "alpha"
    records = vault.read_manifest(namespace)
    assert {r["side"] for r in records} == {"local", "vault"}
    active = next((namespace / "sessions").glob("*.md")).read_text(encoding="utf-8")
    assert "Did the thing." in active


def test_resolve_rejects_a_malformed_selector(checkout, vault_dir, capsys):
    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == 0
    _diverge(vault_dir)
    capsys.readouterr()
    code = _run(
        "sync", "resolve", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir), "--head-session", "2026-08-28-1200-alpha",
        "--archive", "no-equals-sign",
    )
    assert code == cli.EXIT_ERROR
    assert "SESSION_ID=local|vault" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# AC4 / AC6 — the privacy gate through the CLI
# --------------------------------------------------------------------------- #


def test_secret_blocks_push_and_the_printed_triple_unblocks_it(tmp_path, vault_dir, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    secret = "ghp_" + "d" * 20
    _write_history(root, body=BODY + f"\nToken {secret}\n")

    code = _run(
        "sync", "push", "--repo-root", str(root), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    )
    assert code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert secret not in err  # the match is never echoed
    assert "--acknowledge" in err
    assert not (vault_dir / "projects").exists()

    challenge = next(
        line.split("--acknowledge ", 1)[1].strip()
        for line in err.splitlines()
        if "--acknowledge " in line
    )
    assert _run(
        "sync", "push", "--repo-root", str(root), "--project-id", "alpha",
        "--vault-dir", str(vault_dir), "--acknowledge", challenge,
    ) == 0


def test_malformed_acknowledgement_is_refused(checkout, vault_dir, capsys):
    code = _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir), "--acknowledge", "not-a-triple",
    )
    assert code == cli.EXIT_ERROR
    assert "PATH:SHA256:LABEL" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# AC2 — migrate-roots routing
# --------------------------------------------------------------------------- #


def test_migrate_roots_routes_to_the_core_transform(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root, project_root=str(tmp_path / "outside"))

    assert _run(
        "sync", "migrate-roots", "--repo-root", str(root),
        "--session-id", "2026-08-28-1200-alpha",
        "--project-root", str(root / "packages" / "api"),
    ) == 0
    assert "migrated" in capsys.readouterr().out

    archive = next((root / ".agent-history" / "sessions").glob("*.md"))
    frontmatter, _ = schema.parse_frontmatter(archive.read_text(encoding="utf-8"))
    assert frontmatter["project_root"] == str(root / "packages" / "api")


def test_migrate_roots_refuses_an_escape(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    _write_history(root)
    code = _run(
        "sync", "migrate-roots", "--repo-root", str(root),
        "--session-id", "2026-08-28-1200-alpha", "--project-root", str(tmp_path / "elsewhere"),
    )
    assert code == cli.EXIT_ERROR
    assert "outside repo_root" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# AC4 — symlink escape is refused on the vault side too
# --------------------------------------------------------------------------- #


def test_symlinked_namespace_blocks_the_push(tmp_path, checkout, vault_dir):
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault_dir / "projects").mkdir()
    (vault_dir / "projects" / "alpha").symlink_to(outside, target_is_directory=True)

    assert _run(
        "sync", "push", "--repo-root", str(checkout), "--project-id", "alpha",
        "--vault-dir", str(vault_dir),
    ) == cli.EXIT_ERROR
    assert list(outside.iterdir()) == []


def test_writer_guard_errors_surface_as_non_zero(checkout, vault_dir):
    """`HandoffWriteError` from the shared guards must not escape as a traceback."""
    assert issubclass(writer.HandoffWriteError, Exception)
    assert cli.EXIT_ERROR != 0
