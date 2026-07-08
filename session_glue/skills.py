"""Install bundled agent skills into dedicated skill folders (``glue skill``).

This implements the ``glue skill`` command family (issue #29): it copies the
package-bundled skill folder for an agent (Codex today) out of
``session_glue/assets/skills/<agent>/session-glue/`` into an explicit repo- or
user-scope target, and removes it again. It only ever touches the dedicated
``.agents/skills/session-glue/`` folder — never ``AGENTS.md`` or any global
instruction file, and nothing outside the two documented target paths.

Assets are read through :mod:`session_glue.assets` (``importlib.resources``), so
this works from an installed wheel without a source checkout. The set of managed
files is derived from the bundle itself, so adding a new agent (e.g. Claude in
#28) is a data change — appending to :data:`SUPPORTED_AGENTS` — not a redesign.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import assets

# Agents the ``glue skill`` CLI supports. Codex only in #29; #28 adds "claude"
# as a data change once its command coverage lands.
SUPPORTED_AGENTS: tuple[str, ...] = ("codex",)

# Install scopes and the target folder layout, relative to the scope root. Both
# scopes share the layout; only the root differs (repo_root vs $HOME).
SCOPES: tuple[str, ...] = ("repo", "user")
SKILL_SUBPATH = Path(".agents") / "skills" / "session-glue"


class SkillInstallError(Exception):
    """Raised when a skill install/uninstall cannot proceed safely."""


class SkillNotInstalledError(SkillInstallError):
    """Raised when uninstalling a skill folder that is not present."""


@dataclass
class SkillPlan:
    """A planned install/uninstall: the target plus ordered write/remove paths."""

    agent: str
    scope: str
    target: Path
    root: Path
    writes: list[Path] = field(default_factory=list)
    removes: list[Path] = field(default_factory=list)


def _reject_symlink(path: Path) -> None:
    """Refuse to write through a symlink at ``path`` (writer.py's guard pattern)."""
    if path.is_symlink():
        raise SkillInstallError(f"refusing to write through a symlink: {path}")


def _assert_within(path: Path, root: Path) -> None:
    """Assert ``path`` resolves to a location inside ``root`` (catches symlinks)."""
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise SkillInstallError(f"refusing to write outside {root_resolved}: {path}")


def _reject_non_directory(path: Path) -> None:
    """Refuse a target that exists but is not a directory (e.g. a regular file).

    A plain file where the skill folder should be is malformed: ``install
    --replace`` would otherwise crash on ``mkdir`` and ``uninstall`` would
    silently no-op. Call after :func:`_reject_symlink` so symlinks are reported
    as symlinks first. (An installed skill folder is always a directory.)
    """
    if path.exists() and not path.is_dir():
        raise SkillInstallError(f"target exists but is not a directory: {path}")


def _require_supported(agent: str) -> None:
    if agent not in SUPPORTED_AGENTS:
        raise SkillInstallError(
            f"unsupported agent: {agent!r}; expected one of {SUPPORTED_AGENTS}"
        )


def scope_root(scope: str, repo_root: str | Path = ".", home: str | Path | None = None) -> Path:
    """Root directory for ``scope``: the repo root (repo) or home dir (user)."""
    if scope == "repo":
        return Path(repo_root)
    if scope == "user":
        return Path(home) if home is not None else Path.home()
    raise SkillInstallError(f"unknown scope: {scope!r}; expected one of {SCOPES}")


def skill_target(scope: str, repo_root: str | Path = ".", home: str | Path | None = None) -> Path:
    """Absolute target skill folder for ``scope``."""
    return scope_root(scope, repo_root, home) / SKILL_SUBPATH


def bundle_present(agent: str) -> bool:
    """True if a bundled skill folder ships for ``agent``."""
    try:
        return assets.skill_dir(agent).is_dir()
    except ValueError:
        return False


def bundled_skill_md(agent: str) -> str:
    """Return the bundled ``SKILL.md`` text for ``agent``."""
    _require_supported(agent)
    return assets.skill_dir(agent).joinpath("SKILL.md").read_text(encoding="utf-8")


def managed_files(agent: str) -> list[str]:
    """The exact bundle-relative files this CLI manages for ``agent`` (sorted).

    Derived by walking the bundle, so a new agent's file set comes from its
    bundle rather than a hardcoded list.
    """
    _require_supported(agent)

    def walk(node, prefix):
        for child in node.iterdir():
            rel = f"{prefix}{child.name}"
            if child.is_dir():
                yield from walk(child, f"{rel}/")
            else:
                yield rel

    return sorted(walk(assets.skill_dir(agent), ""))


def _unmanaged_extras(target: Path, files: list[str]) -> list[str]:
    """Files/symlinks present under ``target`` that the bundle does not manage."""
    if not target.is_dir():
        return []
    managed = set(files)
    present = (
        p.relative_to(target).as_posix()
        for p in target.rglob("*")
        if p.is_file() or p.is_symlink()
    )
    return sorted(rel for rel in present if rel not in managed)


def plan_install(
    agent: str,
    scope: str,
    repo_root: str | Path = ".",
    home: str | Path | None = None,
    *,
    replace: bool = False,
) -> SkillPlan:
    """Validate and plan an install; raise :class:`SkillInstallError` if unsafe."""
    files = managed_files(agent)  # validates the agent and derives the file set
    root = scope_root(scope, repo_root, home)
    target = root / SKILL_SUBPATH
    plan = SkillPlan(agent=agent, scope=scope, target=target, root=root)

    _reject_symlink(target)
    _reject_non_directory(target)
    if target.exists():
        if not replace:
            raise SkillInstallError(
                f"{target} already exists; pass --replace to overwrite the managed files"
            )
        extras = _unmanaged_extras(target, files)
        if extras:
            raise SkillInstallError(
                f"refusing to --replace {target}: it contains unmanaged files: "
                + ", ".join(extras)
            )
        plan.removes = [
            target / rel
            for rel in files
            if (target / rel).exists() or (target / rel).is_symlink()
        ]
    plan.writes = [target / rel for rel in files]
    return plan


def apply_install(plan: SkillPlan) -> None:
    """Perform a planned install: copy the bundle's managed files into the target."""
    target = plan.target
    _reject_symlink(target)
    for path in plan.removes:
        _reject_symlink(path)
        path.unlink()
    target.mkdir(parents=True, exist_ok=True)
    # After creating the target, confirm it resolves inside the scope root — this
    # catches a symlinked ancestor directory before any file is written.
    _assert_within(target, plan.root)
    src = assets.skill_dir(plan.agent)
    for dest in plan.writes:
        resource = src
        for part in dest.relative_to(target).parts:
            resource = resource.joinpath(part)
        data = resource.read_bytes()
        dest.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink(dest)
        dest.write_bytes(data)


def plan_uninstall(
    agent: str,
    scope: str,
    repo_root: str | Path = ".",
    home: str | Path | None = None,
) -> SkillPlan:
    """Validate and plan an uninstall; raise if not installed or unsafe."""
    files = managed_files(agent)  # validates the agent and derives the file set
    root = scope_root(scope, repo_root, home)
    target = root / SKILL_SUBPATH
    plan = SkillPlan(agent=agent, scope=scope, target=target, root=root)

    if not target.exists() and not target.is_symlink():
        raise SkillNotInstalledError(f"no skill installed at {target}")
    _reject_symlink(target)
    _reject_non_directory(target)
    extras = _unmanaged_extras(target, files)
    if extras:
        raise SkillInstallError(
            f"refusing to uninstall {target}: it contains unmanaged files: "
            + ", ".join(extras)
        )
    plan.removes = [
        target / rel
        for rel in files
        if (target / rel).exists() or (target / rel).is_symlink()
    ]
    return plan


def apply_uninstall(plan: SkillPlan) -> None:
    """Perform a planned uninstall: remove managed files, then empty dirs."""
    _reject_symlink(plan.target)
    # Confirm the target resolves inside the scope root before removing anything —
    # catches a symlinked ancestor that would redirect removals outside the scope.
    _assert_within(plan.target, plan.root)
    for path in plan.removes:
        _reject_symlink(path)
        path.unlink()
    _remove_empty_dirs(plan.target)


def _remove_empty_dirs(target: Path) -> None:
    """Remove empty subdirectories of ``target``, then ``target`` itself if empty."""
    if not target.is_dir():
        return
    # Deepest paths first so a child dir is emptied before its parent is checked.
    for path in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if not any(target.iterdir()):
        target.rmdir()
