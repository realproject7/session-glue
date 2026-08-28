"""Documentation-truth tests for the Personal Vault (issue #81).

These are not style checks. Each one pins a *claim* that the shipped code either
honours or does not, because the failure mode this ticket exists to prevent is
documentation that was true when it was written and quietly stopped being true —
exactly what happened to the README's "No network, ever" row when the Git
transport shipped.

Where a claim can be checked against the implementation rather than against
another piece of prose, it is: the Git failure categories and the exit codes are
read from the modules that define them, so renaming one breaks this file.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from session_glue import cli, vaultgit

REPO_ROOT = Path(__file__).resolve().parents[1]
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
CHANGELOG = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
AGENT_SURFACES = (REPO_ROOT / "docs" / "agent-surfaces.md").read_text(encoding="utf-8")


def _help_for(*argv: str) -> str:
    """Capture argparse help exactly as a user would see it."""
    buffer = io.StringIO()
    with redirect_stdout(buffer), pytest.raises(SystemExit) as excinfo:
        cli.main([*argv, "--help"])
    assert excinfo.value.code == 0
    return buffer.getvalue()


def _flat(text: str) -> str:
    """Collapse whitespace so a hard-wrapped claim still matches as one string."""
    return " ".join(text.split())


SYNC_HELP = _help_for("sync")
FLAT_SYNC_HELP = _flat(SYNC_HELP)
FLAT_README = _flat(README)


# --------------------------------------------------------------------------- #
# AC1 — the examples are real commands, and cover the documented ground
# --------------------------------------------------------------------------- #


def test_readme_documents_both_transports_and_every_sync_subcommand():
    for command in (
        "glue sync push",
        "glue sync pull",
        "glue sync resolve",
        "glue sync migrate-roots",
    ):
        assert command in README, f"README never shows {command!r}"
    assert "--vault-dir" in README and "--vault-git-dir" in README


def test_readme_examples_use_no_credential_and_no_provider_api():
    """A vault example that needed a token would contradict the whole design.

    Scoped to the fenced code blocks: the prose legitimately *names* OAuth and
    provider APIs in order to rule them out, and a blanket scan cannot tell a
    disclaimer from a requirement.
    """
    blocks = re.findall(r"```[a-z]*\n(.*?)```", README, flags=re.DOTALL)
    assert blocks, "no fenced examples found in README"
    examples = "\n".join(blocks).lower()
    for banned in ("--token", "github_token", "api.github.com", "oauth", "gh auth", "gh repo"):
        assert banned not in examples, f"a README example implies {banned!r}"


def test_readme_covers_the_scenarios_the_ticket_requires():
    claims = {
        "bootstrap": "first **push** bootstraps it",
        "conflict": "If both devices changed the same session",
        "retention": "retained under the vault's `conflicts/archives/<session-id>/`",
        "local-only preservation": "local-only archives are preserved",
        "unavailability": "vault not fully available",
        "explicit selectors": "--archive 2026-08-19-1400-add-index=local",
        "migrate-roots": "glue sync migrate-roots --repo-root .",
    }
    missing = [name for name, needle in claims.items() if needle not in FLAT_README]
    assert not missing, f"README no longer covers: {missing}"


def test_changelog_records_the_feature_without_publishing_it():
    unreleased = CHANGELOG.split("## [Unreleased]", 1)[1].split("## [0.3.1]", 1)[0]
    assert "Personal Vault" in unreleased
    assert "_Nothing yet._" not in unreleased
    # Release notes only: this ticket documents, it does not cut a version.
    assert "## [0.4.0]" not in CHANGELOG


# --------------------------------------------------------------------------- #
# AC2 — the trust claims match the implemented defaults
# --------------------------------------------------------------------------- #


def test_readme_no_longer_claims_the_cli_never_touches_the_network():
    """The claim that went stale the moment `--vault-git-dir` shipped.

    The Git transport runs the operator's own git against their own remote. That
    is still opt-in and still credential-free, but it is not "no network, ever",
    and a trust table is the worst place to carry an untrue absolute.
    """
    assert "No network, ever" not in README
    assert "No network unless you ask" in README
    assert "makes no network calls on its own" in README
    # The exception has to be named, not merely hedged around.
    assert "--vault-git-dir` runs *your* `git`" in README


def test_readme_and_help_agree_on_every_v1_limit():
    """Both surfaces must carry the boundary, not just the one a reader happens to hit."""
    boundary = README.split("### What v1 deliberately does not do", 1)[1]
    for needle in (
        "No provider APIs",
        "No OAuth, no tokens, no credentials",
        "No repository creation",
        "No daemon, no watcher, no automatic sync",
        "No encryption",
        "No collaboration",
        "One project ID per checkout",
    ):
        assert needle in boundary, f"README v1 boundary list dropped: {needle!r}"

    for needle in (
        "no credential is ever requested, read, parsed, or stored",
        "never invokes gh, creates a repository, or reads a token",
        "Nothing here runs automatically, on a schedule, or as a side effect",
        "access control, not encryption",
    ):
        assert needle in FLAT_SYNC_HELP, f"sync help dropped: {needle!r}"


def test_private_git_is_documented_as_access_control_not_encryption():
    assert "access control, not encryption" in README or "access control, not confidentiality" in README
    assert "access control, not encryption" in FLAT_SYNC_HELP


def test_folder_operations_are_documented_as_user_serialized_without_a_lock():
    assert "user-serialized" in README
    assert "no locking" in FLAT_README


# --------------------------------------------------------------------------- #
# AC4 — normal local commands take no vault flags
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("command", ["create", "validate", "status", "resume-prompt", "close"])
def test_local_commands_expose_no_vault_flags(command):
    help_text = _help_for(command)
    for flag in ("--vault-dir", "--vault-git-dir", "--project-id"):
        assert flag not in help_text, f"{command} help mentions {flag}"


def test_readme_says_local_commands_need_no_vault_flags():
    assert "Normal local commands never take a vault flag." in README


# --------------------------------------------------------------------------- #
# AC6 — README and help state the limits, the caveat, and the categories
# --------------------------------------------------------------------------- #


def test_one_project_id_per_checkout_is_stated_in_both_surfaces():
    for surface, text in (("README", README), ("sync help", SYNC_HELP)):
        assert "One project ID per checkout" in _flat(text), surface
        assert "relink" in text, f"{surface} omits the no-relink limit"


def test_the_no_stored_digest_caveat_is_stated_in_both_surfaces():
    assert "no stored digest" in README
    assert "no stored digest" in FLAT_SYNC_HELP
    # The operator waits; the tool never retries for them.
    assert "wait for it rather than retrying" in FLAT_SYNC_HELP
    assert "never retries, polls, or waits in a loop" in README


def test_every_git_category_defined_in_code_is_documented():
    """Read the categories from the module, so a rename cannot silently desync."""
    categories = sorted(
        value
        for name, value in vars(vaultgit).items()
        if name.startswith("CATEGORY_") and isinstance(value, str)
    )
    assert categories, "no categories found — did the constants move?"
    for category in categories:
        assert category in FLAT_README, f"README omits Git category {category!r}"
        assert category in FLAT_SYNC_HELP, f"sync help omits Git category {category!r}"


def test_git_error_documentation_promises_no_leakage():
    assert "never forwards it" in README or "never as git's own" in README
    assert "The remote URL, your environment, and handoff content never appear" in FLAT_SYNC_HELP


def test_documented_timeouts_match_the_implementation():
    assert f"{vaultgit.LOCAL_TIMEOUT}s for local git commands" in README
    assert f"{vaultgit.NETWORK_TIMEOUT}s for fetch and push" in README


def test_documented_exit_codes_match_the_implementation():
    assert f"exits `{cli.EXIT_CONFLICT}` for a conflict" in README
    assert f"`{cli.EXIT_UNAVAILABLE}` for a vault that is not fully available" in README


# --------------------------------------------------------------------------- #
# Security invariant — the docs themselves carry nothing private
# --------------------------------------------------------------------------- #


def test_agent_surfaces_records_the_vault_boundary_without_adding_behavior():
    """Every installer target inherits the same rule, so the research doc states it.

    Deliberately a pointer: the canonical text is the bundled protocol, and this
    doc must not become a second place where the boundary is defined and can
    drift.
    """
    boundary = AGENT_SURFACES.split("## Requirement", 1)[0]
    assert "The default is **local**" in boundary
    assert "the command, the vault path, and the project ID" in boundary
    assert "never retries, polls, or\n  synchronizes on its own initiative" in boundary
    assert "references/protocol.md" in boundary
    # A pointer, not a fork of the contract.
    assert "adds no behavior of its own" in boundary
    # The installer research it sits above must survive intact.
    for agent in ("## Cursor", "## Gemini CLI", "## OpenCode"):
        assert agent in AGENT_SURFACES


def test_docs_contain_no_personal_path_or_credential_shaped_text():
    banned = ("/home/", "/Users/", "C:\\Users", "BEGIN RSA", "AKIA", "xoxb-")
    for name, text in (
        ("README.md", README),
        ("CHANGELOG.md", CHANGELOG),
        ("docs/agent-surfaces.md", AGENT_SURFACES),
    ):
        for needle in banned:
            assert needle not in text, f"{name} contains {needle!r}"
