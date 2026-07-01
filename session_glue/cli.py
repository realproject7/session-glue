"""Command-line entry point for Session Glue.

This module wires up the ``glue`` (and fallback ``session-glue``) console
scripts. In this scaffolding ticket the subcommands are placeholders only —
no ``.agent-history/`` writing, validation, or installer behavior is
implemented yet. The CLI is built on :mod:`argparse` from the standard library
so the package has no required runtime dependencies.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__

# Subcommands planned for later tickets. Registered here as placeholders so the
# help output reflects the intended command surface without implementing behavior.
_PLACEHOLDER_COMMANDS: tuple[tuple[str, str], ...] = (
    ("create", "Write a session handoff (not yet implemented)."),
    ("validate", "Validate handoff frontmatter and index (not yet implemented)."),
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
    for name, help_text in _PLACEHOLDER_COMMANDS:
        sub = subparsers.add_parser(name, help=help_text, description=help_text)
        sub.set_defaults(func=_not_implemented)

    return parser


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
