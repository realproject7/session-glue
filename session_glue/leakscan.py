"""Advisory leak scanning for handoff documents (issue #38).

These checks are **warnings, never blockers**: Session Glue's freeze must stay
fail-open, so losing context is never worse than a false positive here. The CLI
prints these loudly to stderr on ``glue create`` and ``glue validate`` but they
do not, by themselves, change any exit code.

Two families of heuristic:

- **Secret patterns** — a small set of high-signal, ``re``-only markers (API
  keys, tokens, private-key blocks). Deliberately narrow (charset/length
  anchors) to keep false positives low; this is a nudge, not a vault scanner.
- **Personal absolute paths** — home-directory paths that would leak a username
  if committed, warned about only when ``.agent-history/`` is *not* covered by
  the repo's ``.gitignore`` (if it is ignored, the path never gets committed).

Standard library only: no network, no subprocess, no git, no third-party deps.
"""

from __future__ import annotations

import re
from pathlib import Path

# High-signal secret markers: (human label, pattern). The label is what gets
# surfaced — the matched secret itself is never echoed back, so a warning never
# re-leaks the credential into logs.
_SECRET_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("OpenAI-style key (sk-)", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}")),
    ("GitHub token (ghp_/gho_)", re.compile(r"\bgh[po]_[A-Za-z0-9]{16,}")),
    ("AWS access key id (AKIA)", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY")),
    ("JWT (eyJ)", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}")),
    ("Slack token (xoxb-/xoxp-)", re.compile(r"\bxox[bp]-[A-Za-z0-9-]{10,}")),
)

# Home-directory absolute paths that would leak a personal username if committed.
_PERSONAL_PATH_PATTERNS: tuple["re.Pattern[str]", ...] = (
    re.compile(r"/Users/[^/\s\"']+/"),
    re.compile(r"/home/[^/\s\"']+/"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+\\"),
)


def scan_secrets(text: str) -> list[str]:
    """Return one label per secret *type* found in ``text`` (order-stable, deduped)."""
    return [label for label, pattern in _SECRET_PATTERNS if pattern.search(text)]


def find_personal_paths(text: str) -> list[str]:
    """Return the distinct home-directory absolute paths present in ``text``."""
    matches: list[str] = []
    seen: set[str] = set()
    for pattern in _PERSONAL_PATH_PATTERNS:
        for match in pattern.findall(text):
            if match not in seen:
                seen.add(match)
                matches.append(match)
    return matches


def _read_ignore_lines(path: Path) -> list[str]:
    """Return the lines of ``path``, or ``[]`` if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _covers_agent_history(lines: list[str]) -> bool:
    """Return True if any non-comment ``lines`` entry ignores ``.agent-history``."""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lstrip("/").rstrip("/") == ".agent-history":
            return True
    return False


def agent_history_ignored(repo_root: Path) -> bool:
    """Return True if ``.agent-history`` is ignored for ``repo_root``.

    Checks the two ignore surfaces that keep ``.agent-history/`` out of a commit:
    the committed ``<repo_root>/.gitignore`` and the personal, never-committed
    ``<repo_root>/.git/info/exclude`` (which ``glue create`` auto-registers,
    issue #66). Both use the same ``.gitignore`` pattern syntax, so the same
    intentionally-simple line scan applies to each — no full grammar, no git
    subprocess: a non-comment line that is ``.agent-history`` — bare, with a
    trailing slash, or with a leading anchor slash — counts as coverage.
    """
    root = Path(repo_root)
    if _covers_agent_history(_read_ignore_lines(root / ".gitignore")):
        return True
    return _covers_agent_history(_read_ignore_lines(root / ".git" / "info" / "exclude"))


def scan_handoff(text: str, repo_root: Path) -> list[str]:
    """Return advisory leak warnings for a handoff document.

    Secret warnings always fire. Personal-path warnings fire only when
    ``.agent-history/`` is not gitignored (otherwise the path is never
    committed, so there is nothing to warn about).
    """
    warnings = [f"possible secret in handoff: {label}" for label in scan_secrets(text)]
    if not agent_history_ignored(repo_root):
        for path in find_personal_paths(text):
            warnings.append(
                f"personal absolute path in handoff: {path} "
                "(.agent-history/ is not gitignored, so it may be committed)"
            )
    return warnings
