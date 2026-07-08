"""Tests for the ``glue skill`` command family (issues #29 and #28).

The behavioral tests are parametrized over both supported agents (``codex`` and
``claude``) so the same safety semantics are proven for each and Codex behavior
is shown unchanged. All tests operate under pytest's ``tmp_path`` (and a
monkeypatched ``HOME`` for user scope) — never the real user home, the network,
or files outside the agent's documented skill folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import session_glue.assets as assets
from session_glue import skills
from session_glue.cli import main

AGENTS = ("codex", "claude")

# Expected per-agent target subpath and top-level repo dir.
_SUBPATH = {
    "codex": Path(".agents") / "skills" / "session-glue",
    "claude": Path(".claude") / "skills" / "session-glue",
}
_TOP_DIR = {"codex": ".agents", "claude": ".claude"}

# Managed bundle-relative files per agent (Claude ships no agents/openai.yaml).
_MANAGED = {
    "codex": ["SKILL.md", "agents/openai.yaml", "references/protocol.md"],
    "claude": ["SKILL.md", "references/protocol.md"],
}


def _target(root: Path, agent: str) -> Path:
    return root / _SUBPATH[agent]


def _bundle_bytes(agent: str, rel: str) -> bytes:
    node = assets.skill_dir(agent)
    for part in rel.split("/"):
        node = node.joinpath(part)
    return node.read_bytes()


def _install(root: Path, agent: str, *extra: str) -> int:
    return main(["skill", "install", agent, "--repo-root", str(root), *extra])


def _uninstall(root: Path, agent: str, *extra: str) -> int:
    return main(["skill", "uninstall", agent, "--repo-root", str(root), *extra])


# --------------------------------------------------------------------------- #
# Module API / per-agent targets
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("agent", AGENTS)
def test_managed_files_are_derived_from_bundle(agent):
    assert skills.managed_files(agent) == _MANAGED[agent]


def test_managed_files_rejects_unsupported_agent():
    assert "gemini" not in skills.SUPPORTED_AGENTS
    with pytest.raises(skills.SkillInstallError):
        skills.managed_files("gemini")


def test_supported_agents_are_the_subpath_keys():
    assert set(skills.SUPPORTED_AGENTS) == set(skills.SKILL_SUBPATHS)
    assert set(skills.SUPPORTED_AGENTS) == {"codex", "claude"}


def test_targets_are_per_agent_and_codex_is_unchanged(tmp_path):
    # Codex keeps its #29 location; Claude uses .claude/... — both scopes.
    assert skills.skill_target("codex", "repo", tmp_path) == (
        tmp_path / ".agents" / "skills" / "session-glue"
    )
    assert skills.skill_target("claude", "repo", tmp_path) == (
        tmp_path / ".claude" / "skills" / "session-glue"
    )
    assert skills.skill_target("codex", "user", home=tmp_path) == (
        tmp_path / ".agents" / "skills" / "session-glue"
    )
    assert skills.skill_target("claude", "user", home=tmp_path) == (
        tmp_path / ".claude" / "skills" / "session-glue"
    )


# --------------------------------------------------------------------------- #
# list / show
# --------------------------------------------------------------------------- #


def test_skill_list_shows_both_agents_and_bundle_state(capsys):
    assert main(["skill", "list"]) == 0
    out = capsys.readouterr().out
    assert "codex: bundled skill present" in out
    assert "claude: bundled skill present" in out


@pytest.mark.parametrize("agent", AGENTS)
def test_skill_show_prints_targets_and_bundled_skill_md(tmp_path, agent, capsys):
    assert main(["skill", "show", agent, "--repo-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"repo target: {_target(tmp_path, agent)}" in out
    assert "user target:" in out
    # The full bundled SKILL.md is echoed. Compare via the same read_text path the
    # CLI uses (not raw bytes) so a CRLF checkout on Windows still matches.
    assert skills.bundled_skill_md(agent) in out


# --------------------------------------------------------------------------- #
# install
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("agent", AGENTS)
def test_install_writes_managed_files_byte_faithfully(tmp_path, agent):
    assert _install(tmp_path, agent) == 0
    dest = _target(tmp_path, agent)
    for rel in _MANAGED[agent]:
        assert (dest / rel).is_file()
        assert (dest / rel).read_bytes() == _bundle_bytes(agent, rel)


@pytest.mark.parametrize("agent", AGENTS)
def test_install_writes_only_under_the_target(tmp_path, agent):
    assert _install(tmp_path, agent) == 0
    # No AGENTS.md/CLAUDE.md, no stray files: only the agent's top dir appears.
    assert sorted(p.name for p in tmp_path.iterdir()) == [_TOP_DIR[agent]]


@pytest.mark.parametrize("agent", AGENTS)
def test_install_user_scope_uses_home(tmp_path, agent, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows fallback
    assert main(["skill", "install", agent, "--scope", "user"]) == 0
    for rel in _MANAGED[agent]:
        assert (_target(home, agent) / rel).is_file()


@pytest.mark.parametrize("agent", AGENTS)
def test_install_dry_run_reports_exact_writes_and_touches_nothing(tmp_path, agent, capsys):
    assert _install(tmp_path, agent, "--dry-run") == 0
    assert not (tmp_path / _TOP_DIR[agent]).exists()
    out = capsys.readouterr().out
    assert "dry-run" in out
    for rel in _MANAGED[agent]:
        assert f"would write {_target(tmp_path, agent) / rel}" in out


@pytest.mark.parametrize("agent", AGENTS)
def test_install_refuses_existing_target_without_replace(tmp_path, agent, capsys):
    assert _install(tmp_path, agent) == 0
    capsys.readouterr()
    assert _install(tmp_path, agent) == 1
    assert "already exists" in capsys.readouterr().err


@pytest.mark.parametrize("agent", AGENTS)
def test_install_replace_overwrites_managed_files(tmp_path, agent):
    assert _install(tmp_path, agent) == 0
    dest = _target(tmp_path, agent)
    (dest / "SKILL.md").write_text("stale content", encoding="utf-8")
    assert _install(tmp_path, agent, "--replace") == 0
    assert (dest / "SKILL.md").read_bytes() == _bundle_bytes(agent, "SKILL.md")


@pytest.mark.parametrize("agent", AGENTS)
def test_install_replace_refuses_when_unmanaged_files_present(tmp_path, agent, capsys):
    assert _install(tmp_path, agent) == 0
    dest = _target(tmp_path, agent)
    (dest / "EXTRA.txt").write_text("hand-edited", encoding="utf-8")
    capsys.readouterr()
    assert _install(tmp_path, agent, "--replace") == 1
    err = capsys.readouterr().err
    assert "unmanaged files" in err
    assert "EXTRA.txt" in err
    assert (dest / "EXTRA.txt").read_text(encoding="utf-8") == "hand-edited"


def test_install_rejects_unsupported_agent_arg():
    with pytest.raises(SystemExit) as exc_info:
        main(["skill", "install", "gemini", "--scope", "repo"])
    assert exc_info.value.code == 2


def test_codex_and_claude_install_into_separate_folders(tmp_path):
    assert _install(tmp_path, "codex") == 0
    assert _install(tmp_path, "claude") == 0
    assert (_target(tmp_path, "codex") / "SKILL.md").is_file()
    assert (_target(tmp_path, "claude") / "SKILL.md").is_file()
    assert _target(tmp_path, "codex") != _target(tmp_path, "claude")


# --------------------------------------------------------------------------- #
# uninstall
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_removes_managed_files_and_empty_folder(tmp_path, agent):
    assert _install(tmp_path, agent) == 0
    assert _uninstall(tmp_path, agent) == 0
    assert not _target(tmp_path, agent).exists()


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_dry_run_reports_exact_removals_and_touches_nothing(tmp_path, agent, capsys):
    assert _install(tmp_path, agent) == 0
    dest = _target(tmp_path, agent)
    capsys.readouterr()
    assert _uninstall(tmp_path, agent, "--dry-run") == 0
    for rel in _MANAGED[agent]:
        assert (dest / rel).is_file()  # nothing removed
    out = capsys.readouterr().out
    for rel in _MANAGED[agent]:
        assert f"would remove {dest / rel}" in out


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_refuses_when_unmanaged_files_present(tmp_path, agent, capsys):
    assert _install(tmp_path, agent) == 0
    dest = _target(tmp_path, agent)
    (dest / "EXTRA.txt").write_text("keep me", encoding="utf-8")
    capsys.readouterr()
    assert _uninstall(tmp_path, agent) == 1
    assert "unmanaged files" in capsys.readouterr().err
    assert (dest / "SKILL.md").is_file()
    assert (dest / "EXTRA.txt").is_file()


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_not_installed_is_a_clear_noop(tmp_path, agent, capsys):
    assert _uninstall(tmp_path, agent) == 0
    out = capsys.readouterr().out
    assert "no skill installed" in out
    assert "nothing to remove" in out


# --------------------------------------------------------------------------- #
# Malformed / unsafe targets (per agent)
# --------------------------------------------------------------------------- #


def _symlinked_target(tmp_path: Path, agent: str) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    target = _target(repo, agent)
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)
    return repo, outside


@pytest.mark.parametrize("agent", AGENTS)
def test_install_rejects_symlinked_destination(tmp_path, agent, capsys):
    repo, outside = _symlinked_target(tmp_path, agent)
    assert _install(repo, agent) == 1
    assert "symlink" in capsys.readouterr().err
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_rejects_symlinked_destination(tmp_path, agent, capsys):
    repo, outside = _symlinked_target(tmp_path, agent)
    assert _uninstall(repo, agent) == 1
    assert "symlink" in capsys.readouterr().err
    assert list(outside.iterdir()) == []


def _file_at_target(tmp_path: Path, agent: str) -> Path:
    target = _target(tmp_path, agent)
    target.parent.mkdir(parents=True)
    target.write_text("not a skill folder", encoding="utf-8")
    return target


@pytest.mark.parametrize("agent", AGENTS)
def test_install_rejects_regular_file_target(tmp_path, agent, capsys):
    _file_at_target(tmp_path, agent)
    assert _install(tmp_path, agent) == 1
    assert "not a directory" in capsys.readouterr().err
    assert _install(tmp_path, agent, "--replace") == 1
    assert "not a directory" in capsys.readouterr().err
    assert _target(tmp_path, agent).read_text(encoding="utf-8") == "not a skill folder"


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_rejects_regular_file_target(tmp_path, agent, capsys):
    target = _file_at_target(tmp_path, agent)
    assert _uninstall(tmp_path, agent) == 1
    assert "not a directory" in capsys.readouterr().err
    assert target.is_file()


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #


def test_skill_requires_a_subcommand():
    with pytest.raises(SystemExit) as exc_info:
        main(["skill"])
    assert exc_info.value.code == 2
