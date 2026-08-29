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
    """Named for *every* subcommand, and now enumerating them from the parser.

    This passed for the whole of #128's lifetime while the README omitted
    `glue sync recover-duplicates`. The list was typed by hand, so it asserted
    the four commands someone remembered rather than the ones the CLI ships —
    and a hand-maintained coverage guard goes stale at exactly the moment it
    exists to catch, the addition of a command. Deriving it from the parser is
    what makes the test's own name true.
    """
    shipped: list[str] = []
    for action in cli.build_parser()._actions:
        for name, sub in getattr(action, "_name_parser_map", {}).items():
            if name != "sync":
                continue
            for inner in sub._actions:
                shipped = sorted(getattr(inner, "_name_parser_map", {})) or shipped
    assert shipped, "no `glue sync` subparsers found"
    assert "recover-duplicates" in shipped, "fixture: the parser must register it"
    for name in shipped:
        assert f"glue sync {name}" in README, f"README never shows 'glue sync {name}'"
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


def test_changelog_cuts_0_4_0_below_an_empty_unreleased():
    """The vault notes sit in the dated release, with nothing above it (#134).

    Replaces an assertion that `## [0.4.0]` was *absent* — correct while #81 was
    documenting a feature it deliberately did not release, and a prohibition on
    the deliverable once this ticket cut the version.

    **Each slice ends at the next heading, which is the whole point.** The old
    span ran `[Unreleased]`→`[0.3.1]`, so once `[0.4.0]` appeared between them the
    range swallowed it: `"Personal Vault" in unreleased` stayed green with the
    notes no longer in Unreleased at all, and could not fail for the property its
    name stated. A section test whose slice does not stop at the next heading
    stops discriminating the moment a section is inserted.
    """
    # Before the slices: without it, dropping the heading raises `IndexError`
    # from the split rather than failing with a message, in a test whose whole
    # purpose is to fail for the property its name states (@re2, PR #135).
    assert "## [0.4.0] - 2026-08-29" in CHANGELOG, "the changelog was never cut"

    unreleased = CHANGELOG.split("## [Unreleased]", 1)[1].split("## [0.4.0]", 1)[0]
    release = CHANGELOG.split("## [0.4.0] - 2026-08-29", 1)[1].split("## [0.3.1]", 1)[0]

    assert unreleased.strip() == "", "the Unreleased section must be literally empty"
    assert "_Nothing yet._" not in unreleased, "no placeholder either (#134 defines empty)"
    assert "Personal Vault" in release, "the vault notes belong to the 0.4.0 release"
    assert CHANGELOG.index("## [Unreleased]") < CHANGELOG.index(
        "## [0.4.0] - 2026-08-29"
    ), "[Unreleased] must come above the dated 0.4.0 section"


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
    # The exception has to be named, not merely hedged around. Scoped to the row
    # itself rather than the whole file, so it is the *claim* that is pinned and
    # not the markdown emphasis around it.
    row = next(
        line for line in README.splitlines() if line.startswith("| **No network unless you ask**")
    )
    assert "--vault-git-dir" in row


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


def _readme_section(heading: str) -> str:
    """The text under one README heading, up to the next heading of any level."""
    body = README.split(heading, 1)[1]
    # Stop at the next markdown heading -- two or more hashes. A single "#" also
    # begins a shell comment, and the CLI reference block contains one.
    match = re.search(r"\n#{2,6} ", body)
    return body if match is None else body[: match.start()]


def test_documented_timeouts_match_the_implementation():
    """Bind the numbers to the code; leave the sentence around them free."""
    categories = _readme_section("### Git failures tell you the category")
    assert f"{vaultgit.LOCAL_TIMEOUT}s" in categories
    assert f"{vaultgit.NETWORK_TIMEOUT}s" in categories


def test_documented_exit_codes_match_the_implementation():
    reference = _readme_section("## CLI reference")
    assert f"`{cli.EXIT_CONFLICT}`" in reference, "CLI reference omits the conflict exit code"
    assert f"`{cli.EXIT_UNAVAILABLE}`" in reference, "CLI reference omits the unavailable exit code"


# --------------------------------------------------------------------------- #
# Security invariant — the docs themselves carry nothing private
# --------------------------------------------------------------------------- #


def test_agent_surfaces_records_the_vault_boundary_without_adding_behavior():
    """Every installer target inherits the same rule, so the research doc states it.

    Deliberately a pointer: the canonical text is the bundled protocol, and this
    doc must not become a second place where the boundary is defined and can
    drift.
    """
    boundary = _flat(AGENT_SURFACES.split("## Requirement", 1)[0])
    assert "The default is **local**" in boundary
    assert "the command, the vault path, and the project ID" in boundary
    assert "never retries, polls, or synchronizes on its own initiative" in boundary
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
