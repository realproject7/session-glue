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
from pathlib import Path

from . import __version__, gitcheck, installer, leakscan, reader, validator, writer
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

    return parser


def _read_input(source: str) -> str:
    """Read handoff text from a file path or stdin (``-``)."""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def _cmd_create(args: argparse.Namespace) -> int:
    """Implement ``glue create``."""
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
