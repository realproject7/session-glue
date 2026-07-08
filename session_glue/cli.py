"""Command-line entry point for Session Glue.

This module wires up the ``glue`` (and fallback ``session-glue``) console
scripts. It implements ``glue create``, ``glue validate``, ``glue status``,
``glue resume-prompt``, and ``glue install --dry-run`` (see
:mod:`session_glue.writer`, :mod:`session_glue.validator`,
:mod:`session_glue.reader`, and :mod:`session_glue.installer`). The CLI is built
on :mod:`argparse` from the standard library so the package has no required
runtime dependencies.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__, gitcheck, installer, leakscan, reader, skills, validator, writer
from .schema import (
    Handoff,
    HandoffParseError,
    lint_first_next_action,
    parse_frontmatter,
)


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser for the ``glue`` CLI."""
    parser = argparse.ArgumentParser(
        prog="glue",
        description=(
            "Session Glue — cut a bloated coding-agent session at a clean "
            "boundary and glue the useful context onto a clean new session."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"session-glue {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    create = subparsers.add_parser(
        "create",
        help="Archive a handoff into .agent-history/ and update pointers.",
        description=(
            "Write an agent-composed handoff (frontmatter + body) into "
            ".agent-history/: archive a timestamped session file, refresh "
            "LATEST.md, RESUME_PROMPT.txt, and INDEX.yaml."
        ),
    )
    create.add_argument(
        "--input",
        "-i",
        default="-",
        metavar="PATH",
        help="Handoff markdown file (frontmatter + body). Use '-' for stdin (default).",
    )
    create.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Repository root that holds .agent-history/ (default: current directory).",
    )
    create.add_argument(
        "--allow-flagged-todo",
        action="store_true",
        help=(
            "Proceed even if next_todo_items[0] looks like a resume mechanic: "
            "downgrade that lint failure to a loud stderr warning instead of "
            "blocking the freeze. Other validation errors still block. This "
            "escape hatch exists only on 'create'; 'validate' never gains it."
        ),
    )
    create.set_defaults(func=_cmd_create)

    validate = subparsers.add_parser(
        "validate",
        help="Validate .agent-history/ handoff artifacts.",
        description=(
            "Validate LATEST.md frontmatter, the next_todo_items[0] lint, "
            "RESUME_PROMPT.txt presence, and INDEX.yaml consistency. Exits "
            "non-zero if any problem is found."
        ),
    )
    validate.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Repository root that holds .agent-history/ (default: current directory).",
    )
    validate.add_argument(
        "--sessions",
        action="store_true",
        help="Also validate archived session files under sessions/.",
    )
    validate.add_argument(
        "--git",
        action="store_true",
        help=(
            "Opt-in git drift check: compare LATEST.md's recorded branch/commit "
            "against the actual repo (runs git). Advisory warning only — never "
            "changes the exit code. Default (no --git) runs no subprocess."
        ),
    )
    validate.set_defaults(func=_cmd_validate)

    status = subparsers.add_parser(
        "status",
        help="Show compact .agent-history/ status.",
        description=(
            "Print compact metadata from INDEX.yaml (latest session/file, "
            "branch, head commit, first next action) and a cheap validation "
            "summary. Does not print the full session narrative."
        ),
    )
    status.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Repository root that holds .agent-history/ (default: current directory).",
    )
    status.add_argument(
        "--git",
        action="store_true",
        help=(
            "Opt-in git drift check: compare INDEX.yaml's recorded branch/commit "
            "against the actual repo (runs git). Advisory only. Default (no "
            "--git) runs no subprocess."
        ),
    )
    status.set_defaults(func=_cmd_status)

    resume_prompt = subparsers.add_parser(
        "resume-prompt",
        help="Print .agent-history/RESUME_PROMPT.txt exactly.",
        description="Print the exact contents of .agent-history/RESUME_PROMPT.txt.",
    )
    resume_prompt.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Repository root that holds .agent-history/ (default: current directory).",
    )
    resume_prompt.set_defaults(func=_cmd_resume_prompt)

    close = subparsers.add_parser(
        "close",
        help="Set a session's lifecycle status in INDEX.yaml (archives stay immutable).",
        description=(
            "Update only the selected session's status in INDEX.yaml — archived "
            "sessions/*.md files and LATEST.md are never touched. Defaults to the "
            "latest session. Closing the latest session as DONE clears the "
            "pending top-level first_next_action; BLOCKED and ABANDONED leave it."
        ),
    )
    close.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Repository root that holds .agent-history/ (default: current directory).",
    )
    close.add_argument(
        "--session",
        default=None,
        metavar="ID",
        help="Session id to close (default: the latest session in INDEX.yaml).",
    )
    close.add_argument(
        "--status",
        required=True,
        choices=writer.CLOSE_STATUSES,
        help="New lifecycle status for the session.",
    )
    close.set_defaults(func=_cmd_close)

    install = subparsers.add_parser(
        "install",
        help="Show the managed instruction block for a coding agent (dry-run only).",
        description=(
            "Dry-run only: print the target instruction file and the managed "
            "Session Glue block that would be added for a coding agent. Never "
            "modifies user-home files; real installation is not implemented "
            "(operator-gated)."
        ),
    )
    install.add_argument(
        "agent",
        choices=(*installer.AGENT_ORDER, "all"),
        help="Coding agent to show the install block for (or 'all').",
    )
    install.add_argument(
        "--dry-run",
        action="store_true",
        help="Required: print the target path and proposed block without writing.",
    )
    install.set_defaults(func=_cmd_install)

    skill = subparsers.add_parser(
        "skill",
        help="Install, inspect, or remove bundled agent skill folders.",
        description=(
            "Manage dedicated agent skill folders bundled with Session Glue. "
            "Installs the bundled skill into the agent's dedicated skill folder "
            "(repo or user scope) — it never edits AGENTS.md, CLAUDE.md, or any "
            "global instruction file, and never writes outside that folder."
        ),
    )
    skill_sub = skill.add_subparsers(dest="skill_command", metavar="<subcommand>", required=True)

    skill_list = skill_sub.add_parser(
        "list",
        help="List supported agents and whether each bundled skill exists.",
    )
    skill_list.set_defaults(func=_cmd_skill_list)

    skill_show = skill_sub.add_parser(
        "show",
        help="Show repo/user target paths and the bundled SKILL.md for an agent.",
    )
    skill_show.add_argument("agent", choices=skills.SUPPORTED_AGENTS, help="Agent to show.")
    skill_show.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Repo root for the repo-scope target path (default: current directory).",
    )
    skill_show.set_defaults(func=_cmd_skill_show)

    skill_install = skill_sub.add_parser(
        "install",
        help="Install a bundled agent skill folder.",
        description=(
            "Copy the bundled agent skill (SKILL.md and its supporting files) "
            "into the agent's dedicated skill folder (Codex .agents/..., Claude "
            ".claude/...) under the repo or user scope."
        ),
    )
    skill_install.add_argument("agent", choices=skills.SUPPORTED_AGENTS)
    skill_install.add_argument(
        "--scope",
        choices=skills.SCOPES,
        default="repo",
        help="Install into the repo (recommended default) or user home scope.",
    )
    skill_install.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Repo root for repo scope (default: current directory).",
    )
    skill_install.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the exact writes/removals and touch nothing.",
    )
    skill_install.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite an existing skill folder (managed files only; refuses unmanaged extras).",
    )
    skill_install.set_defaults(func=_cmd_skill_install)

    skill_uninstall = skill_sub.add_parser(
        "uninstall",
        help="Remove an installed agent skill folder (managed files only).",
        description=(
            "Remove the managed skill files from the agent's dedicated skill "
            "folder and the folder itself when empty. Refuses if unmanaged files "
            "are present."
        ),
    )
    skill_uninstall.add_argument("agent", choices=skills.SUPPORTED_AGENTS)
    skill_uninstall.add_argument(
        "--scope",
        choices=skills.SCOPES,
        default="repo",
        help="Uninstall from the repo (default) or user home scope.",
    )
    skill_uninstall.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Repo root for repo scope (default: current directory).",
    )
    skill_uninstall.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the exact removals and touch nothing.",
    )
    skill_uninstall.set_defaults(func=_cmd_skill_uninstall)

    return parser


def _read_input(source: str) -> str:
    """Read handoff text from a file path or stdin (``-``)."""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


# Freeze-overuse guard: warn when the previous freeze was this recent.
OVERUSE_WINDOW = timedelta(minutes=30)


def _cmd_create(args: argparse.Namespace) -> int:
    """Implement ``glue create``."""
    # When defaulting to stdin at an interactive terminal, hint before blocking
    # on the read. Piped stdin (a file/agent, not a TTY) is untouched.
    if args.input == "-" and sys.stdin.isatty():
        print(
            "glue create: reading handoff from stdin — pipe a file or pass --input PATH",
            file=sys.stderr,
        )
    try:
        text = _read_input(args.input)
    except OSError as exc:
        print(f"glue create: cannot read input: {exc}", file=sys.stderr)
        return 1

    try:
        frontmatter, body = parse_frontmatter(text)
    except HandoffParseError as exc:
        print(f"glue create: invalid handoff: {exc}", file=sys.stderr)
        return 2

    handoff = Handoff.from_frontmatter(frontmatter, body)
    errors = handoff.validate()

    # Escape hatch: --allow-flagged-todo downgrades ONLY the resume-mechanic lint
    # on next_todo_items[0] to a loud stderr warning so a heuristic false
    # positive can never hard-block a freeze (losing context is the exact
    # failure Session Glue exists to prevent). Every other validation error —
    # including a missing/empty next_todo_items — still blocks.
    if args.allow_flagged_todo and handoff.first_next_action is not None:
        flagged = lint_first_next_action(handoff.first_next_action)
        if flagged is not None and flagged in errors:
            print(f"glue create: WARNING: {flagged}", file=sys.stderr)
            print(
                "glue create: proceeding anyway because --allow-flagged-todo "
                "was passed.",
                file=sys.stderr,
            )
            errors = [error for error in errors if error != flagged]

    if errors:
        print("glue create: handoff failed validation:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    repo_root = Path(args.repo_root)
    if not repo_root.is_dir():
        print(f"glue create: repo root is not a directory: {repo_root}", file=sys.stderr)
        return 1

    # Advisory (fail-open): warn when supersedes names a session not yet in the
    # index. Unknown references never block the freeze — the referenced session
    # may live in another checkout or predate this index. Checked against the
    # pre-write index, so it compares only against prior sessions.
    if handoff.supersedes and handoff.supersedes not in reader.existing_session_ids(repo_root):
        print(
            f"glue create: WARNING: supersedes references unknown session id "
            f"{handoff.supersedes!r} (not in INDEX.yaml sessions[])",
            file=sys.stderr,
        )

    # Freeze-overuse guard (advisory, fail-open): if the previous LATEST.md was
    # frozen less than 30 minutes before this handoff, warn that the session may
    # not be bloated enough to warrant a fresh freeze. Read the PRIOR LATEST.md
    # before create_handoff overwrites it; any missing/unparseable/mismatched
    # timestamp silently skips the check (never blocks, never crashes).
    prior_latest = repo_root / writer.AGENT_HISTORY_DIRNAME / writer.LATEST_FILENAME
    if prior_latest.is_file():
        try:
            prior_generated_at = Handoff.from_text(
                prior_latest.read_text(encoding="utf-8")
            ).generated_at
        except (OSError, HandoffParseError):
            prior_generated_at = None
        # Parse both ISO-8601 timestamps inline (tolerating a trailing ``Z``); a
        # missing or unparseable value becomes None so the comparison is skipped.
        parsed: list = []
        for raw in (prior_generated_at, handoff.generated_at):
            try:
                parsed.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except (AttributeError, TypeError, ValueError):
                parsed.append(None)
        prev_ts, curr_ts = parsed
        if prev_ts is not None and curr_ts is not None:
            try:
                elapsed = curr_ts - prev_ts
            except TypeError:
                elapsed = None  # naive/aware mismatch — fail-open, skip the check
            if elapsed is not None and timedelta(0) <= elapsed < OVERUSE_WINDOW:
                minutes = int(elapsed.total_seconds() // 60)
                print(
                    f"glue create: WARNING: you glued {minutes} minutes ago — "
                    "is this session actually bloated?",
                    file=sys.stderr,
                )

    try:
        written = writer.create_handoff(
            repo_root=repo_root,
            frontmatter=frontmatter,
            body=body,
            handoff=handoff,
        )
    except writer.HandoffWriteError as exc:
        print(f"glue create: {exc}", file=sys.stderr)
        return 1
    print("Wrote handoff for session " + str(handoff.session_id) + ":")
    for label in ("archive", "latest", "resume_prompt", "index"):
        print(f"  {label}: {written[label]}")

    # Advisory leak warnings: printed loudly but the freeze stays fail-open — a
    # detected secret or personal path never blocks the write or changes rc.
    warnings = leakscan.scan_handoff(text, repo_root)
    for warning in warnings:
        print(f"glue create: WARNING: {warning}", file=sys.stderr)
    if warnings:
        print(
            f"glue create: {len(warnings)} leak warning(s) — review before "
            "committing .agent-history/",
            file=sys.stderr,
        )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Implement ``glue validate``."""
    repo_root = Path(args.repo_root)
    problems = validator.validate_history(repo_root, check_sessions=args.sessions)

    # Advisory leak warnings from LATEST.md: printed as clearly-labeled warnings
    # but never flip the exit code — only real validation problems do that.
    latest = repo_root / ".agent-history" / "LATEST.md"
    if latest.is_file():
        for warning in leakscan.scan_handoff(latest.read_text(encoding="utf-8"), repo_root):
            print(f"glue validate: WARNING: {warning}", file=sys.stderr)

    # Opt-in git drift check (advisory only, never flips the exit code). Runs a
    # subprocess only when --git is passed.
    if args.git:
        handoff = None
        if latest.is_file():
            try:
                handoff = Handoff.from_text(latest.read_text(encoding="utf-8"))
            except HandoffParseError:
                handoff = None
        if handoff is None:
            print("glue validate: --git: no readable LATEST.md to compare against",
                  file=sys.stderr)
        else:
            for msg in gitcheck.check_git_drift(
                repo_root, handoff.current_branch, handoff.head_commit
            ):
                print(f"glue validate: {msg}", file=sys.stderr)

    if problems:
        print("glue validate: found problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("glue validate: OK")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Implement ``glue status``."""
    status = reader.collect_status(Path(args.repo_root))
    if not status.exists:
        print(f"glue status: no .agent-history/ found at {status.history_dir}")
        return 1

    print(".agent-history: present")
    index = status.index or {}
    for label, key in reader.STATUS_FIELDS:
        value = index.get(key)
        print(f"{label}: {value if value not in (None, '') else '(unknown)'}")

    # Lifecycle status of the latest session + a session count — both INDEX-only
    # (the writer keeps per-session status inside sessions[]; no narrative read).
    lifecycle = reader.latest_status(index)
    print(f"status: {lifecycle if lifecycle not in (None, '') else '(unknown)'}")
    print(f"sessions: {reader.session_count(index)}")
    # Cheap file-line count of the append-only decisions log (0 when absent).
    print(f"decisions: {reader.decision_count(Path(args.repo_root))}")

    # Single-hop supersession lineage for the latest session (INDEX-only). Only
    # printed when the latest entry links to a prior session; never walks the chain.
    prior = reader.latest_supersedes(index)
    if prior is not None:
        print(f"lineage: {index.get('latest_session')} <- supersedes {prior}")

    if status.problems:
        print(f"validation: {len(status.problems)} problem(s)")
        for problem in status.problems:
            print(f"  - {problem}")
    else:
        print("validation: OK")

    # Opt-in git drift check (advisory only). Runs a subprocess only with --git.
    if args.git:
        for msg in gitcheck.check_git_drift(
            Path(args.repo_root), index.get("current_branch"), index.get("head_commit")
        ):
            print(f"git: {msg}")

    return 0


def _cmd_close(args: argparse.Namespace) -> int:
    """Implement ``glue close`` — set a session's status in INDEX.yaml only."""
    try:
        closed = writer.close_session(Path(args.repo_root), args.session, args.status)
    except writer.HandoffWriteError as exc:
        print(f"glue close: {exc}", file=sys.stderr)
        return 1
    print(f"glue close: set session {closed} status to {args.status}")
    return 0


def _cmd_resume_prompt(args: argparse.Namespace) -> int:
    """Implement ``glue resume-prompt``."""
    text = reader.read_resume_prompt(Path(args.repo_root))
    if text is None:
        print("glue resume-prompt: no .agent-history/RESUME_PROMPT.txt found", file=sys.stderr)
        return 1
    # Print the file contents exactly (no added or stripped trailing newline).
    sys.stdout.write(text)
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    """Implement ``glue install <agent> --dry-run`` (dry-run only)."""
    if not args.dry_run:
        print(
            "glue install: only --dry-run is supported; real installation is "
            "operator-gated and not implemented. Re-run with --dry-run.",
            file=sys.stderr,
        )
        return 2

    block = installer.managed_block()
    for target in installer.resolve_agents(args.agent):
        print(f"# {target.name} (dry-run — no files modified)")
        print(f"target: {target.target}")
        if target.note:
            print(f"note: {target.note}")
        print("proposed block:")
        print(block)
        print()
    print(
        "note: 'glue install' is legacy (dry-run only). Use "
        "'glue skill install <agent>' to install a dedicated skill folder."
    )
    return 0


def _cmd_skill_list(args: argparse.Namespace) -> int:
    """Implement ``glue skill list``."""
    for agent in skills.SUPPORTED_AGENTS:
        state = "present" if skills.bundle_present(agent) else "MISSING"
        print(f"{agent}: bundled skill {state}")
    return 0


def _cmd_skill_show(args: argparse.Namespace) -> int:
    """Implement ``glue skill show <agent>``."""
    agent = args.agent
    print(f"agent: {agent}")
    print(f"repo target: {skills.skill_target(agent, 'repo', args.repo_root)}")
    print(f"user target: {skills.skill_target(agent, 'user')}")
    state = "present" if skills.bundle_present(agent) else "MISSING"
    print(f"bundled skill: {state}")
    print("--- SKILL.md ---")
    # Print the bundled SKILL.md exactly (no added/stripped trailing newline).
    sys.stdout.write(skills.bundled_skill_md(agent))
    return 0


def _print_skill_plan(label: str, plan: skills.SkillPlan, dry_run: bool) -> None:
    """Print a skill plan's exact writes/removals (dry-run marks them prospective)."""
    suffix = " (dry-run — nothing changed)" if dry_run else ""
    print(f"{label}: target {plan.target}{suffix}")
    verb = "would " if dry_run else ""
    for path in plan.removes:
        print(f"  {verb}remove {path}")
    for path in plan.writes:
        print(f"  {verb}write {path}")


def _cmd_skill_install(args: argparse.Namespace) -> int:
    """Implement ``glue skill install <agent> --scope repo|user``."""
    try:
        plan = skills.plan_install(
            args.agent, args.scope, repo_root=args.repo_root, replace=args.replace
        )
    except skills.SkillInstallError as exc:
        print(f"glue skill install: {exc}", file=sys.stderr)
        return 1

    _print_skill_plan("glue skill install", plan, args.dry_run)
    if args.dry_run:
        return 0

    try:
        skills.apply_install(plan)
    except skills.SkillInstallError as exc:
        print(f"glue skill install: {exc}", file=sys.stderr)
        return 1
    print(f"glue skill install: installed {args.agent} skill into {plan.target}")
    return 0


def _cmd_skill_uninstall(args: argparse.Namespace) -> int:
    """Implement ``glue skill uninstall <agent> --scope repo|user``."""
    try:
        plan = skills.plan_uninstall(args.agent, args.scope, repo_root=args.repo_root)
    except skills.SkillNotInstalledError as exc:
        # Not installed is a friendly no-op, not a failure.
        print(f"glue skill uninstall: {exc} — nothing to remove")
        return 0
    except skills.SkillInstallError as exc:
        print(f"glue skill uninstall: {exc}", file=sys.stderr)
        return 1

    _print_skill_plan("glue skill uninstall", plan, args.dry_run)
    if args.dry_run:
        return 0

    try:
        skills.apply_uninstall(plan)
    except skills.SkillInstallError as exc:
        print(f"glue skill uninstall: {exc}", file=sys.stderr)
        return 1
    print(f"glue skill uninstall: removed {args.agent} skill from {plan.target}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Program entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "func", None)
    if handler is None:
        # No subcommand given: show help and exit successfully.
        parser.print_help()
        return 0

    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
