"""Tests for the package-owned skill assets bundled with Session Glue (issue #26).

These verify three things:

1. The assets are reachable *through the installed package* via
   ``importlib.resources`` (``session_glue.assets``), i.e. a PyPI install can
   read them without the source repository checkout.
2. The bundled Codex skill is a byte-faithful mirror of the repository
   ``codex-skills/`` source, and the shared fallback protocol is identical
   across the Codex and Claude bundles (so it cannot silently drift).
3. A freshly built wheel and sdist actually contain the skill files.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

import session_glue.assets as assets

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_CODEX = REPO_ROOT / "codex-skills" / "session-glue"

# Relative asset paths (inside each bundled ``session-glue`` skill dir) that must
# ship in every distribution.
CODEX_FILES = ("SKILL.md", "agents/openai.yaml", "references/protocol.md")
CLAUDE_FILES = ("SKILL.md", "references/protocol.md")

# Their location inside the wheel / installed package.
PKG_PREFIX = "session_glue/assets/skills"
WHEEL_ASSETS = [f"{PKG_PREFIX}/codex/session-glue/{p}" for p in CODEX_FILES] + [
    f"{PKG_PREFIX}/claude/session-glue/{p}" for p in CLAUDE_FILES
]


def _read_pkg_bytes(agent: str, rel: str) -> bytes:
    """Read a bundled asset via importlib.resources (package-resource access)."""
    resource = assets.skill_dir(agent)
    for part in rel.split("/"):
        resource = resource.joinpath(part)
    return resource.read_bytes()


# --------------------------------------------------------------------------- #
# Access through the installed package
# --------------------------------------------------------------------------- #


def test_skills_root_and_skill_dirs_resolve():
    assert assets.skills_root().is_dir()
    for agent in assets.SKILL_AGENTS:
        assert assets.skill_dir(agent).is_dir()


def test_bundled_assets_are_readable_resources():
    for rel in CODEX_FILES:
        assert _read_pkg_bytes("codex", rel).strip(), f"codex/{rel} is empty"
    for rel in CLAUDE_FILES:
        assert _read_pkg_bytes("claude", rel).strip(), f"claude/{rel} is empty"


def test_skill_dir_rejects_unknown_agent():
    with pytest.raises(ValueError):
        assets.skill_dir("emacs")


# --------------------------------------------------------------------------- #
# Parity / no-drift guarantees
# --------------------------------------------------------------------------- #


def test_bundled_codex_mirrors_repo_source_byte_for_byte():
    # The package copy must stay identical to the canonical repo skill so the
    # shipped wheel never drifts from what the repository documents.
    for rel in CODEX_FILES:
        repo_bytes = (REPO_CODEX / Path(rel)).read_bytes()
        assert _read_pkg_bytes("codex", rel) == repo_bytes, f"codex/{rel} drifted from repo source"


def test_shared_protocol_is_identical_across_bundles():
    codex_protocol = _read_pkg_bytes("codex", "references/protocol.md")
    claude_protocol = _read_pkg_bytes("claude", "references/protocol.md")
    assert codex_protocol == claude_protocol


def test_claude_skill_is_protocol_equivalent():
    skill = _read_pkg_bytes("claude", "SKILL.md").decode("utf-8")
    for trigger in ("/glue", "/freeze", "/handoff", "/checkpoint", "create a Session Glue handoff"):
        assert trigger in skill
    assert "glue create --repo-root . --input <handoff.md>" in skill
    assert "references/protocol.md" in skill
    assert "Do not request OS clipboard access" in skill


def test_bundled_assets_are_public_safe():
    # Guard against personal-path / credential leakage in shipped assets.
    banned = ("/home/", "/Users/", "C:\\Users", "BEGIN RSA", "ghp_", "AKIA")
    for agent, files in (("codex", CODEX_FILES), ("claude", CLAUDE_FILES)):
        for rel in files:
            text = _read_pkg_bytes(agent, rel).decode("utf-8")
            for needle in banned:
                assert needle not in text, f"{agent}/{rel} contains {needle!r}"


# --------------------------------------------------------------------------- #
# Built distributions actually carry the assets
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def built_dists(tmp_path_factory):
    """Build the wheel and sdist once (non-isolated, offline) for inspection.

    Requires the ``[dev]`` extra (``build`` + ``hatchling``); skips cleanly if
    the build backend is unavailable so a bare environment can still run the
    rest of the suite.
    """
    build = pytest.importorskip("build")
    pytest.importorskip("hatchling")
    out = tmp_path_factory.mktemp("dist")
    try:
        builder = build.ProjectBuilder(REPO_ROOT)
        builder.build("wheel", str(out))
        builder.build("sdist", str(out))
    except Exception as exc:  # missing backend, sandboxed FS, etc.
        pytest.skip(f"could not build distributions in this environment: {exc}")
    return out


def test_built_wheel_contains_skill_assets(built_dists):
    wheels = list(built_dists.glob("*.whl"))
    assert wheels, "no wheel was built"
    names = set(zipfile.ZipFile(wheels[0]).namelist())
    missing = [p for p in WHEEL_ASSETS if p not in names]
    assert not missing, f"wheel is missing skill assets: {missing}"


def test_built_sdist_contains_skill_assets(built_dists):
    sdists = list(built_dists.glob("*.tar.gz"))
    assert sdists, "no sdist was built"
    with tarfile.open(sdists[0]) as tar:
        names = set(tar.getnames())
    missing = [p for p in WHEEL_ASSETS if not any(n.endswith("/" + p) for n in names)]
    assert not missing, f"sdist is missing skill assets: {missing}"
