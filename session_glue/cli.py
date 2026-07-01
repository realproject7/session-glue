"""Command-line entry point for Session Glue.

This module wires up the ``glue`` (and fallback ``session-glue``) console
scripts. ``glue create`` and ``glue validate`` are implemented (see
:mod:`session_glue.writer` and :mod:`session_glue.validator`); the remaining
subcommands are placeholders for later tickets. The CLI is built on
:mod:`argparse` from the standard library so the package has no required
runtime dependencies.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, validator, writer
from .schema import Handoff, HandoffParseError, parse_frontmatter

# Subcommands still awaiting implementation in later tickets. Registered as
# placeholders so the help output reflects the intended command surface.
_PLACEHOLDER_COMMANDS: tuple[tuple[str, str], ...] = (
    ("status", "Show current .agent-history status (not yet implemented)."),
    ("resume-prompt", "Print the current resume prompt (not yet implemented)."),
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
    validate.set_defaults(func=_cmd_validate)

    for name, help_text in _PLACEHOLDER_COMMANDS:
        sub = subparsers.add_parser(name, help=help_text, description=help_text)
        sub.set_defaults(func=_not_implemented)

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
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Implement ``glue validate``."""
    problems = validator.validate_history(
        Path(args.repo_root), check_sessions=args.sessions
    )
    if problems:
        print("glue validate: found problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("glue validate: OK")
    return 0


def _not_implemented(args: argparse.Namespace) -> int:
    """Placeholder handler for commands that are not implemented yet."""
    print(f"'glue {args.command}' is not implemented yet.")
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
