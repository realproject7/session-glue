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


# --------------------------------------------------------------------------- #
# Issue #92 — a symlinked scope *ancestor*, not just the final target
# --------------------------------------------------------------------------- #


def _symlinked_ancestor(root: Path, outside: Path, agent: str) -> Path:
    """Redirect the target's parent directory out of the scope root.

    The distinction from `_symlinked_target` is the whole ticket: that one
    replaces the leaf, which `_reject_symlink` catches. This replaces a
    *directory above* it, which the leaf check cannot see — `target.is_symlink()`
    is false while every path through it lands outside.
    """
    ancestor = root / _SUBPATH[agent].parent
    ancestor.parent.mkdir(parents=True, exist_ok=True)
    ancestor.symlink_to(outside, target_is_directory=True)
    return ancestor


def _plant_managed_files(outside: Path, agent: str) -> dict[str, bytes]:
    """A previous install's worth of files, sitting outside the scope root."""
    installed = outside / _SUBPATH[agent].name
    installed.mkdir()
    written = {}
    for rel in _MANAGED[agent]:
        dest = installed / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_bundle_bytes(agent, rel))
        written[rel] = dest.read_bytes()
    return written


def _tree(path: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(path)): (p.read_bytes() if p.is_file() else None)
        for p in path.rglob("*")
    }


@pytest.mark.parametrize("agent", AGENTS)
def test_install_rejects_a_symlinked_ancestor_before_creating_anything(
    tmp_path, agent, capsys
):
    """AC1: `mkdir(parents=True)` used to run first and create a directory outside.

    Asserted as *the external tree is unchanged*, not as a non-zero exit: the old
    code also exited 1 — the containment check ran, just after the damage — so an
    exit-code assertion alone passes on the broken ordering.
    """
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    _symlinked_ancestor(repo, outside, agent)
    before = _tree(outside)

    assert _install(repo, agent) == 1

    assert _tree(outside) == before
    assert "refusing to write outside" in capsys.readouterr().err


@pytest.mark.parametrize("agent", AGENTS)
def test_install_replace_through_a_symlinked_ancestor_deletes_nothing(
    tmp_path, agent, capsys
):
    """AC1: the sharpest case — `--replace` unlinked the operator's files outside.

    The external directory is populated with exactly the managed set so
    `_unmanaged_extras` does not refuse first; the plan therefore succeeds and
    `apply_install` reaches its removal loop, which is the code under test.
    """
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    _symlinked_ancestor(repo, outside, agent)
    planted = _plant_managed_files(outside, agent)
    before = _tree(outside)

    assert _install(repo, agent, "--replace") == 1

    assert _tree(outside) == before
    installed = outside / _SUBPATH[agent].name
    for rel, data in planted.items():
        assert (installed / rel).read_bytes() == data
    assert "refusing to write outside" in capsys.readouterr().err


@pytest.mark.parametrize("agent", AGENTS)
def test_install_user_scope_rejects_a_symlinked_ancestor(tmp_path, agent, monkeypatch):
    """AC1: home scope, which resolves its root from the environment rather than a flag."""
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _symlinked_ancestor(home, outside, agent)
    before = _tree(outside)

    assert main(["skill", "install", agent, "--scope", "user"]) == 1

    assert _tree(outside) == before


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_rejects_a_symlinked_ancestor_before_removing_anything(
    tmp_path, agent
):
    """AC2: a regression guard for ordering `apply_uninstall` already had right.

    This one passes before the fix as well as after — that is the point. It pins
    the behaviour `apply_install` was changed to match, so a future edit cannot
    quietly reintroduce the divergence in the other direction.
    """
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    _symlinked_ancestor(repo, outside, agent)
    _plant_managed_files(outside, agent)
    before = _tree(outside)

    assert _uninstall(repo, agent) == 1

    assert _tree(outside) == before


@pytest.mark.parametrize("agent", AGENTS)
def test_uninstall_user_scope_rejects_a_symlinked_ancestor(tmp_path, agent, monkeypatch):
    """AC1/AC2: the home-scope half of the same regression guard."""
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _symlinked_ancestor(home, outside, agent)
    _plant_managed_files(outside, agent)
    before = _tree(outside)

    assert main(["skill", "uninstall", agent, "--scope", "user"]) == 1

    assert _tree(outside) == before


# --------------------------------------------------------------------------- #
# Issue #105 — a symlink at a *managed* path is refused during planning
# --------------------------------------------------------------------------- #


def _exact_tree(target: Path) -> dict[str, bytes | None]:
    """Every path under the target and its bytes; `None` for dirs and symlinks.

    Symlinks read as `None` rather than their target's bytes, so the comparison
    cannot be satisfied by following a link the operation was supposed to refuse.
    """
    return {
        p.relative_to(target).as_posix(): (
            p.read_bytes() if p.is_file() and not p.is_symlink() else None
        )
        for p in sorted(target.rglob("*"))
    }


def _symlink_a_managed_leaf(target: Path, outside: Path, agent: str) -> Path:
    """Replace a managed *inner* file with a symlink pointing out of the scope.

    Distinct from #92's cases: the ancestor and the final target are both intact,
    and the relative path is in the managed set — so `_unmanaged_extras` does not
    see it as an extra and planning used to admit it.
    """
    victim = outside / "operator-owned.md"
    victim.write_bytes(b"operator data the tool must not touch\n")
    leaf = target / "references" / "protocol.md"
    assert "references/protocol.md" in _MANAGED[agent], "leaf must be a managed path"
    leaf.unlink()
    leaf.symlink_to(victim)
    return victim


@pytest.mark.parametrize("agent", AGENTS)
@pytest.mark.parametrize("operation", ["install-replace", "uninstall"])
def test_a_managed_leaf_symlink_is_refused_before_any_repo_scope_mutation(
    tmp_path, agent, operation, capsys
):
    """AC1/AC2/AC3: repo scope, both agents, both operations, exact tree preserved.

    Before #105 the removal loop deleted the earlier managed files and only then
    reached the symlink — codex lost `SKILL.md` and `agents/openai.yaml`, claude
    lost `SKILL.md`, on both operations. The tree comparison is the assertion
    that catches that; a bare `rc == 1` passes on the broken version, because the
    old code also exited 1 *after* deleting.
    """
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    assert _install(repo, agent) == 0
    target = _target(repo, agent)
    victim = _symlink_a_managed_leaf(target, outside, agent)
    before = _exact_tree(target)

    code = _install(repo, agent, "--replace") if operation == "install-replace" else _uninstall(repo, agent)

    assert code == 1
    assert _exact_tree(target) == before, "the selected scope was mutated before the refusal"
    assert victim.read_bytes() == b"operator data the tool must not touch\n"
    err = capsys.readouterr().err
    assert "references/protocol.md" in err, "the refusal must name the offending path"


@pytest.mark.parametrize("agent", AGENTS)
@pytest.mark.parametrize("operation", ["install-replace", "uninstall"])
def test_a_managed_leaf_symlink_is_refused_before_any_user_scope_mutation(
    tmp_path, agent, operation, monkeypatch, capsys
):
    """The scope half of AC3's matrix.

    User scope resolves its root from the environment rather than a flag, so it
    is a distinct path through `scope_root` — the dimension #105's original AC3
    left unstated and which review required be named.
    """
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert main(["skill", "install", agent, "--scope", "user"]) == 0
    target = _target(home, agent)
    victim = _symlink_a_managed_leaf(target, outside, agent)
    before = _exact_tree(target)

    argv = ["skill", "install", agent, "--scope", "user", "--replace"]
    if operation == "uninstall":
        argv = ["skill", "uninstall", agent, "--scope", "user"]
    code = main(argv)

    assert code == 1
    assert _exact_tree(target) == before
    assert victim.read_bytes() == b"operator data the tool must not touch\n"
    assert "references/protocol.md" in capsys.readouterr().err


@pytest.mark.parametrize("agent", AGENTS)
def test_the_refusal_is_prevention_only_and_leaves_the_symlink_in_place(tmp_path, agent):
    """Scope decision: prevention only, manual remediation.

    The tool must not delete the symlink — removing a file an operator placed is
    the mutation this preflight exists to avoid. So the state persists until they
    clear it, and every route keeps refusing; that is the agreed behaviour, not a
    defect. Once removed by hand, the ordinary flow works again.
    """
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    assert _install(repo, agent) == 0
    target = _target(repo, agent)
    _symlink_a_managed_leaf(target, outside, agent)
    leaf = target / "references" / "protocol.md"

    assert _install(repo, agent, "--replace") == 1
    assert leaf.is_symlink(), "the tool removed a file the operator placed"
    assert _uninstall(repo, agent) == 1
    assert leaf.is_symlink()

    # Manual remediation is the documented way out, and it restores the flow.
    leaf.unlink()
    assert _install(repo, agent, "--replace") == 0
    for rel in _MANAGED[agent]:
        assert (target / rel).is_file() and not (target / rel).is_symlink()


@pytest.mark.parametrize("agent", AGENTS)
def test_a_valid_bundle_is_unaffected_by_the_new_preflight(tmp_path, agent):
    """AC3's other half: the check must not refuse a normal install or uninstall."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _install(repo, agent) == 0
    assert _install(repo, agent, "--replace") == 0
    for rel in _MANAGED[agent]:
        assert (_target(repo, agent) / rel).read_bytes() == _bundle_bytes(agent, rel)
    assert _uninstall(repo, agent) == 0
    assert not _target(repo, agent).exists()
