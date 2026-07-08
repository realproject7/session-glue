"""Tests for the ``glue skill`` command family (issue #29).

All tests operate under pytest's ``tmp_path`` (and a monkeypatched ``HOME`` for
user scope) — they never touch the real user home, the network, or files outside
the documented ``.agents/skills/session-glue/`` target.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import session_glue.assets as assets
from session_glue import skills
from session_glue.cli import main

MANAGED = ("SKILL.md", "agents/openai.yaml", "references/protocol.md")


def _target(root: Path) -> Path:
    return root / ".agents" / "skills" / "session-glue"


def _bundle_bytes(agent: str, rel: str) -> bytes:
    node = assets.skill_dir(agent)
    for part in rel.split("/"):
        node = node.joinpath(part)
    return node.read_bytes()


def _install(root: Path, *extra: str) -> int:
    return main(["skill", "install", "codex", "--repo-root", str(root), *extra])


# --------------------------------------------------------------------------- #
# Module API
# --------------------------------------------------------------------------- #


def test_managed_files_are_derived_from_bundle():
    assert skills.managed_files("codex") == list(MANAGED)


def test_managed_files_rejects_unsupported_agent():
    # claude is bundled but not yet CLI-supported until #28 adds it to the tuple.
    assert "claude" not in skills.SUPPORTED_AGENTS
    with pytest.raises(skills.SkillInstallError):
        skills.managed_files("claude")


def test_skill_targets_use_scope_roots(tmp_path):
    assert skills.skill_target("repo", tmp_path) == _target(tmp_path)
    assert skills.skill_target("user", home=tmp_path) == _target(tmp_path)


# --------------------------------------------------------------------------- #
# list / show
# --------------------------------------------------------------------------- #


def test_skill_list_shows_supported_agents_and_bundle_state(capsys):
    assert main(["skill", "list"]) == 0
    out = capsys.readouterr().out
    assert "codex: bundled skill present" in out


def test_skill_show_prints_targets_and_bundled_skill_md(tmp_path, capsys):
    assert main(["skill", "show", "codex", "--repo-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"repo target: {_target(tmp_path)}" in out
    assert "user target:" in out
    # The full bundled SKILL.md is echoed. Compare via the same read_text path the
    # CLI uses (not raw bytes) so a CRLF checkout on Windows still matches.
    assert skills.bundled_skill_md("codex") in out


# --------------------------------------------------------------------------- #
# install
# --------------------------------------------------------------------------- #


def test_install_repo_scope_writes_managed_files_byte_faithfully(tmp_path):
    assert _install(tmp_path) == 0
    dest = _target(tmp_path)
    for rel in MANAGED:
        assert (dest / rel).is_file()
        assert (dest / rel).read_bytes() == _bundle_bytes("codex", rel)


def test_install_writes_only_under_the_target(tmp_path):
    assert _install(tmp_path) == 0
    # No AGENTS.md, no stray files: only .agents/ appears at the repo root.
    assert sorted(p.name for p in tmp_path.iterdir()) == [".agents"]


def test_install_user_scope_uses_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows fallback
    assert main(["skill", "install", "codex", "--scope", "user"]) == 0
    for rel in MANAGED:
        assert (_target(home) / rel).is_file()


def test_install_dry_run_reports_exact_writes_and_touches_nothing(tmp_path, capsys):
    assert _install(tmp_path, "--dry-run") == 0
    assert not (tmp_path / ".agents").exists()
    out = capsys.readouterr().out
    assert "dry-run" in out
    for rel in MANAGED:
        assert f"would write {_target(tmp_path) / rel}" in out


def test_install_refuses_existing_target_without_replace(tmp_path, capsys):
    assert _install(tmp_path) == 0
    capsys.readouterr()
    assert _install(tmp_path) == 1
    assert "already exists" in capsys.readouterr().err


def test_install_replace_overwrites_managed_files(tmp_path):
    assert _install(tmp_path) == 0
    dest = _target(tmp_path)
    (dest / "SKILL.md").write_text("stale content", encoding="utf-8")
    assert _install(tmp_path, "--replace") == 0
    assert (dest / "SKILL.md").read_bytes() == _bundle_bytes("codex", "SKILL.md")


def test_install_replace_refuses_when_unmanaged_files_present(tmp_path, capsys):
    assert _install(tmp_path) == 0
    dest = _target(tmp_path)
    (dest / "EXTRA.txt").write_text("hand-edited", encoding="utf-8")
    capsys.readouterr()
    assert _install(tmp_path, "--replace") == 1
    err = capsys.readouterr().err
    assert "unmanaged files" in err
    assert "EXTRA.txt" in err
    # The unmanaged file is left untouched.
    assert (dest / "EXTRA.txt").read_text(encoding="utf-8") == "hand-edited"


def test_install_rejects_unsupported_agent_arg():
    with pytest.raises(SystemExit) as exc_info:
        main(["skill", "install", "claude", "--scope", "repo"])
    assert exc_info.value.code == 2


# --------------------------------------------------------------------------- #
# uninstall
# --------------------------------------------------------------------------- #


def test_uninstall_removes_managed_files_and_empty_folder(tmp_path):
    assert _install(tmp_path) == 0
    assert main(["skill", "uninstall", "codex", "--repo-root", str(tmp_path)]) == 0
    assert not _target(tmp_path).exists()
    # The empty scaffolding above it is cleaned up too.
    assert not (_target(tmp_path)).exists()


def test_uninstall_dry_run_reports_exact_removals_and_touches_nothing(tmp_path, capsys):
    assert _install(tmp_path) == 0
    dest = _target(tmp_path)
    capsys.readouterr()
    assert main(["skill", "uninstall", "codex", "--repo-root", str(tmp_path), "--dry-run"]) == 0
    for rel in MANAGED:
        assert (dest / rel).is_file()  # nothing removed
    out = capsys.readouterr().out
    for rel in MANAGED:
        assert f"would remove {dest / rel}" in out


def test_uninstall_refuses_when_unmanaged_files_present(tmp_path, capsys):
    assert _install(tmp_path) == 0
    dest = _target(tmp_path)
    (dest / "EXTRA.txt").write_text("keep me", encoding="utf-8")
    capsys.readouterr()
    assert main(["skill", "uninstall", "codex", "--repo-root", str(tmp_path)]) == 1
    assert "unmanaged files" in capsys.readouterr().err
    # Nothing was removed — managed and unmanaged files both remain.
    assert (dest / "SKILL.md").is_file()
    assert (dest / "EXTRA.txt").is_file()


def test_uninstall_not_installed_is_a_clear_noop(tmp_path, capsys):
    assert main(["skill", "uninstall", "codex", "--repo-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "no skill installed" in out
    assert "nothing to remove" in out


# --------------------------------------------------------------------------- #
# Symlink safety (destination guard, matching writer.py's pattern)
# --------------------------------------------------------------------------- #


def _symlinked_target(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    parent = repo / ".agents" / "skills"
    parent.mkdir(parents=True)
    (parent / "session-glue").symlink_to(outside, target_is_directory=True)
    return repo, outside


def test_install_rejects_symlinked_destination(tmp_path, capsys):
    repo, outside = _symlinked_target(tmp_path)
    assert _install(repo) == 1
    assert "symlink" in capsys.readouterr().err
    # Nothing was written through the symlink into the outside directory.
    assert list(outside.iterdir()) == []


def test_uninstall_rejects_symlinked_destination(tmp_path, capsys):
    repo, outside = _symlinked_target(tmp_path)
    assert main(["skill", "uninstall", "codex", "--repo-root", str(repo)]) == 1
    assert "symlink" in capsys.readouterr().err
    assert list(outside.iterdir()) == []


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #


def test_skill_requires_a_subcommand():
    with pytest.raises(SystemExit) as exc_info:
        main(["skill"])
    assert exc_info.value.code == 2
