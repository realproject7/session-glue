"""Optional git drift detection for ``glue status`` / ``glue validate`` (issue #39).

Opt-in only: these helpers are invoked exclusively behind the CLI ``--git`` flag.
``subprocess`` is imported lazily inside :func:`_run_git`, so importing this
module — and every default (no ``--git``) status/validate invocation — performs
no subprocess work at all. Git errors never propagate: a missing ``git``, a
non-repository directory, or any command failure degrades to a single
informative line rather than an exception.

Standard library only: no third-party deps, no network, no background polling.
"""

from __future__ import annotations

from pathlib import Path

# Printed (once) when git cannot answer: not installed, not a repo, or errored.
GIT_UNAVAILABLE = "--git: git unavailable or not a repository"

# Recorded values that mean "nothing to compare against".
_MISSING = frozenset({"", "unknown", "(unknown)", "none"})


def _run_git(repo_root: Path, args: list[str]) -> str | None:
    """Run ``git -C <repo_root> <args>``; return trimmed stdout, or None on any failure.

    ``subprocess`` is imported here (not at module top) so the default,
    non-``--git`` code paths never import or invoke it. Never raises.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def check_git_drift(
    repo_root: Path,
    recorded_branch: object,
    recorded_commit: object,
) -> list[str]:
    """Return advisory git-drift messages for a handoff (never raises).

    - git unavailable / not a repo / any error -> a single degradation line.
    - a recorded branch or commit that is missing/``unknown`` -> an informative
      skip line for that field.
    - actual branch/commit differs from recorded -> one ``drift:`` warning naming
      recorded vs actual (short hashes compared on the recorded hash's length).
    - everything matches -> ``[]``.

    These are warnings only: callers must not let them change an exit code.
    """
    actual_branch = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    # Fetch the FULL 40-char SHA, then compare on the recorded hash's length.
    # Using ``--short`` here would false-positive when the handoff recorded a full
    # SHA (a 7-char actual value never prefix-matches a 40-char recorded one),
    # while the full SHA prefix-matches both a short and a full recorded value.
    actual_commit = _run_git(repo_root, ["rev-parse", "HEAD"])
    if actual_branch is None or actual_commit is None:
        return [GIT_UNAVAILABLE]

    recorded_b = "" if recorded_branch is None else str(recorded_branch).strip()
    recorded_c = "" if recorded_commit is None else str(recorded_commit).strip()

    messages: list[str] = []
    branch_drift = False
    commit_drift = False

    if recorded_b.lower() in _MISSING:
        messages.append(
            "--git: recorded current_branch is missing/unknown — skipping branch check"
        )
    elif recorded_b != actual_branch:
        branch_drift = True

    if recorded_c.lower() in _MISSING:
        messages.append(
            "--git: recorded head_commit is missing/unknown — skipping commit check"
        )
    # Compare on the recorded hash's length, e.g. recorded 7-char prefix vs the
    # first 7 chars of the actual short hash.
    elif actual_commit[: len(recorded_c)].lower() != recorded_c.lower():
        commit_drift = True

    if branch_drift or commit_drift:
        # Show the actual commit at the length the handoff recorded (a short
        # prefix stays short) so the message reads naturally either way.
        shown_commit = actual_commit[: len(recorded_c)] if recorded_c else actual_commit[:7]
        messages.append(
            f"drift: handoff recorded {recorded_b or '(unknown)'}@"
            f"{recorded_c or '(unknown)'} but repo is at {actual_branch}@{shown_commit}"
        )
    return messages
