"""Personal Vault core: canonical format, state, and conflict-safe transfer (issue #78).

This module is the provider-neutral half of the Personal Vault. It owns the
vault data model and every byte-level rule the transports depend on, and it
performs **no** subprocess, network, or CLI work — folder and Git invocation
belong to #79/#80.

Byte determinism is the load-bearing property here. Three separate comparisons
depend on it: canonical archives merge by byte identity, acknowledgements bind
to a canonical-content SHA-256, and divergence detection compares a digest of
the vault state. Every byte-producing routine therefore names its exact form:

- **Canonical archives** are a *targeted raw transform* of the on-disk document.
  Only the ``repo_root`` and ``project_root`` scalar lines change; every other
  frontmatter key, its ordering and quoting, and every body byte survive
  untouched. Nothing round-trips through :class:`~session_glue.schema.Handoff`,
  which would silently drop unknown frontmatter fields.
- **Vault YAML** (state, conflict candidates, manifest, marker) is
  ``dump_mapping(ordered_mapping) + "\\n"`` — the repository serializer plus one
  terminal newline, which it does not emit itself.

Standard library only: no network, no subprocess, no third-party deps.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .schema import HandoffParseError, dump_mapping, dump_scalar, parse_frontmatter, parse_mapping

# --------------------------------------------------------------------------- #
# Layout and format constants
# --------------------------------------------------------------------------- #

VAULT_ROOT_TOKEN = "<vault-root>"

PROJECTS_DIRNAME = "projects"
MARKER_FILENAME = "vault-project.yaml"
SESSIONS_DIRNAME = "sessions"
DECISIONS_FILENAME = "DECISIONS.md"
STATE_DIRNAME = "state"
STATE_FILENAME = "vault-state.yaml"
CONFLICTS_DIRNAME = "conflicts"
CONFLICT_ARCHIVES_DIRNAME = "archives"
CONFLICT_LIFECYCLE_DIRNAME = "lifecycle"
MANIFEST_FILENAME = "manifest.yaml"

VAULT_FORMAT = "session-glue-personal-vault-v1"
CONFLICTS_FORMAT = "session-glue-vault-conflicts-v1"

#: Local sync state, inside the ignored ``.agent-history/`` tree. Never exported.
SYNC_STATE_FILENAME = "VAULT-SYNC.yaml"

#: A valid project id: one lowercase alphanumeric, or alphanumeric-bounded with
#: ``._-`` inside, at most 64 characters.
PROJECT_ID_RE = re.compile(r"^[a-z0-9]$|^[a-z0-9][a-z0-9._-]{0,62}[a-z0-9]$")

#: Windows reserves these device *stems* regardless of extension, so ``con.log``
#: is reserved just as ``con`` is.
RESERVED_STEM_RE = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", re.IGNORECASE)


class VaultError(Exception):
    """Raised when a vault operation cannot proceed safely."""


class VaultUnavailable(VaultError):
    """The vault exists but is not fully readable (e.g. a mid-sync folder)."""


class VaultConflict(VaultError):
    """Local and vault state diverged; resolution requires explicit selectors."""


class PrivacyBlocked(VaultError):
    """A secret or personal-path pattern matched an artifact bound for the vault.

    Carries the acknowledgement challenges rather than the matched text: the
    match itself is never echoed, so a block never re-leaks the value.
    """

    def __init__(self, findings: list["Finding"]) -> None:
        self.findings = findings
        super().__init__(
            "blocked by privacy gate; acknowledge the exact triple to proceed:\n"
            + "\n".join(f.challenge() for f in findings)
        )


# --------------------------------------------------------------------------- #
# Project identity
# --------------------------------------------------------------------------- #


def validate_project_id(project_id: object) -> str:
    """Return ``project_id`` if it is a valid cross-device identity, else raise.

    The rule is cross-platform safe by construction: lowercase-only avoids
    case-insensitive filesystem collisions, the alphanumeric right anchor
    excludes trailing dots (Win32 strips them, silently merging two ids), and
    reserved device stems are rejected outright.
    """
    if not isinstance(project_id, str) or not PROJECT_ID_RE.match(project_id):
        raise VaultError(
            f"invalid --project-id {project_id!r}: must be lowercase alphanumeric, "
            "may contain '.', '_' or '-' internally, and is at most 64 characters"
        )
    if RESERVED_STEM_RE.match(project_id):
        raise VaultError(
            f"invalid --project-id {project_id!r}: reserved device name on Windows"
        )
    return project_id


def project_dir(vault_root: Path, project_id: str) -> Path:
    """Return ``<vault_root>/projects/<id>/`` after validating the id."""
    validate_project_id(project_id)
    return Path(vault_root) / PROJECTS_DIRNAME / project_id


# --------------------------------------------------------------------------- #
# Deterministic YAML rendering
# --------------------------------------------------------------------------- #


def render_vault_yaml(mapping: dict[str, Any]) -> str:
    """Render a vault YAML artifact: serializer output plus one terminal newline.

    ``dump_mapping`` joins with newlines and does *not* terminate the last line,
    so the ``+ "\\n"`` is part of the contract rather than a formatting nicety —
    an implementation that omits it produces a digest one byte short.
    """
    return dump_mapping(mapping) + "\n"


def render_vault_state(state: dict[str, Any]) -> str:
    """Render ``state/vault-state.yaml`` in its pinned canonical form.

    Keys appear in exactly ``head_session_id``, ``lifecycle``, ``acknowledgements``
    order; lifecycle entries sort by ``session_id``; acknowledgements sort by
    ``(path, sha256, label)``. Fixing the order matters because ``dump_mapping``
    iterates ``data.items()`` and Python preserves insertion order, so equal
    logical state built in a different order would otherwise hash differently.
    """
    lifecycle = sorted(
        (dict(entry) for entry in state.get("lifecycle") or []),
        key=lambda e: str(e.get("session_id", "")),
    )
    acknowledgements = sorted(
        (dict(entry) for entry in state.get("acknowledgements") or []),
        key=lambda e: (str(e.get("path", "")), str(e.get("sha256", "")), str(e.get("label", ""))),
    )
    ordered: dict[str, Any] = {
        "head_session_id": state.get("head_session_id", ""),
        "lifecycle": lifecycle,
        "acknowledgements": acknowledgements,
    }
    return render_vault_yaml(ordered)


def render_manifest(records: list[dict[str, Any]]) -> str:
    """Render ``conflicts/manifest.yaml`` with records in canonical order."""
    ordered_records = sorted(
        (dict(record) for record in records or []),
        key=lambda r: (
            str(r.get("session_id", "")),
            str(r.get("kind", "")),
            str(r.get("side", "")),
            str(r.get("sha256", "")),
        ),
    )
    return render_vault_yaml({"format": CONFLICTS_FORMAT, "conflicts": ordered_records})


def merge_manifest_records(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union two manifest record lists by exact record identity."""
    seen: set[tuple] = set()
    merged: list[dict[str, Any]] = []
    for record in list(left or []) + list(right or []):
        key = tuple(sorted((str(k), str(v)) for k, v in dict(record).items()))
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(record))
    return merged


def sha256_hex(text: str) -> str:
    """Lowercase-hex SHA-256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def state_digest(state: dict[str, Any]) -> str:
    """Digest of a vault state: SHA-256 over its canonical rendering."""
    return sha256_hex(render_vault_state(state))


# --------------------------------------------------------------------------- #
# Canonical archive transform (targeted, raw)
# --------------------------------------------------------------------------- #


def _frontmatter_bounds(text: str) -> tuple[list[str], int, int]:
    """Return ``(lines, start, end)`` delimiting the frontmatter block.

    ``start`` is the first frontmatter line index and ``end`` the closing
    ``---`` index, so the keys live in ``lines[start:end]``.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise HandoffParseError("handoff must begin with a '---' frontmatter delimiter")
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return lines, 1, idx
    raise HandoffParseError("unterminated frontmatter (missing closing '---')")


def _replace_root_scalars(text: str, repo_root: str, project_root: str) -> str:
    """Rewrite only the two root scalar lines, preserving every other byte.

    Deliberately line-targeted rather than a parse/re-render round trip: the
    latter would normalise quoting, reorder keys, and drop any frontmatter field
    the schema does not know about.
    """
    lines, start, end = _frontmatter_bounds(text)
    replacements = {"repo_root": repo_root, "project_root": project_root}
    found: set[str] = set()
    for idx in range(start, end):
        key, sep, _ = lines[idx].partition(":")
        if not sep or key != key.strip():  # indented continuation or non-key line
            continue
        name = key.strip()
        if name in replacements:
            lines[idx] = f"{name}: {dump_scalar(replacements[name])}"
            found.add(name)
    missing = sorted(set(replacements) - found)
    if missing:
        raise VaultError(f"archive is missing required root field(s): {', '.join(missing)}")
    return "\n".join(lines)


def contained_offset(project_root: str, repo_root: str) -> str:
    """Return the normalized POSIX offset of ``project_root`` under ``repo_root``.

    Returns ``""`` when the two are equal. Raises :class:`VaultError` when the
    project root lies outside the repository root — that case is never silently
    flattened, and is recoverable only through :func:`migrate_roots`.
    """
    parent = os.path.normpath(str(repo_root))
    child = os.path.normpath(str(project_root))
    if parent == child:
        return ""
    relative = os.path.relpath(child, parent)
    parts = relative.split(os.sep)
    if relative == os.pardir or os.pardir in parts or os.path.isabs(relative):
        raise VaultError(
            f"project_root {project_root!r} is outside repo_root {repo_root!r}; "
            "run 'glue sync migrate-roots' to bring it inside before exporting"
        )
    return PurePosixPath(*parts).as_posix()


def canonicalize_document(text: str) -> str:
    """Return the canonical vault form of a local handoff document.

    ``repo_root`` becomes exactly ``<vault-root>``. ``project_root`` becomes
    exactly ``<vault-root>`` when the two are equal — the ordinary case — and
    otherwise ``<vault-root>/<offset>`` with no trailing separator.
    """
    frontmatter, _ = parse_frontmatter(text)
    repo_root = frontmatter.get("repo_root")
    project_root = frontmatter.get("project_root")
    if not isinstance(repo_root, str) or not repo_root:
        raise VaultError("archive has no usable repo_root")
    if not isinstance(project_root, str) or not project_root:
        raise VaultError("archive has no usable project_root")
    offset = contained_offset(project_root, repo_root)
    canonical_project = VAULT_ROOT_TOKEN if offset == "" else f"{VAULT_ROOT_TOKEN}/{offset}"
    return _replace_root_scalars(text, VAULT_ROOT_TOKEN, canonical_project)


def materialize_document(text: str, repo_root: Path | str) -> str:
    """Reverse :func:`canonicalize_document` into the importing checkout.

    The exact root token becomes the importing root; a contained offset is
    re-joined with native separators. A relative escape is refused rather than
    resolved.
    """
    frontmatter, _ = parse_frontmatter(text)
    canonical_repo = frontmatter.get("repo_root")
    canonical_project = frontmatter.get("project_root")
    if canonical_repo != VAULT_ROOT_TOKEN:
        raise VaultError(
            f"canonical archive has repo_root {canonical_repo!r}, expected {VAULT_ROOT_TOKEN!r}"
        )
    root = str(repo_root)
    if canonical_project == VAULT_ROOT_TOKEN:
        materialized_project = root
    elif isinstance(canonical_project, str) and canonical_project.startswith(
        VAULT_ROOT_TOKEN + "/"
    ):
        offset = canonical_project[len(VAULT_ROOT_TOKEN) + 1 :]
        parts = offset.split("/")
        if not offset or "" in parts or os.pardir in parts or PurePosixPath(offset).is_absolute():
            raise VaultError(f"canonical project_root offset {offset!r} escapes the repo root")
        materialized_project = str(Path(root, *parts))
    else:
        raise VaultError(
            f"canonical archive has project_root {canonical_project!r}, "
            f"expected {VAULT_ROOT_TOKEN!r} or {VAULT_ROOT_TOKEN!r} plus an offset"
        )
    return _replace_root_scalars(text, root, materialized_project)


def canonical_digest(canonical_text: str) -> str:
    """Acknowledgement digest for an artifact: SHA-256 over its canonical bytes."""
    return sha256_hex(canonical_text)


# --------------------------------------------------------------------------- #
# Marker
# --------------------------------------------------------------------------- #


def render_marker(project_id: str) -> str:
    """Render ``vault-project.yaml`` for ``project_id``."""
    return render_vault_yaml({"format": VAULT_FORMAT, "project_id": project_id})


def read_marker(namespace: Path, project_id: str) -> None:
    """Validate the marker in ``namespace``; raise on any mismatch.

    A malformed or mismatched marker is a hard error rather than something to
    repair in place: the vault path never gets a fail-open rebuild.
    """
    marker_path = Path(namespace) / MARKER_FILENAME
    try:
        raw = marker_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VaultError(f"cannot read vault marker at {marker_path}: {exc}") from exc
    try:
        data = parse_mapping(raw)
    except HandoffParseError as exc:
        raise VaultError(f"malformed vault marker at {marker_path}: {exc}") from exc
    if data.get("format") != VAULT_FORMAT:
        raise VaultError(
            f"vault marker at {marker_path} has format {data.get('format')!r}, "
            f"expected {VAULT_FORMAT!r}"
        )
    if data.get("project_id") != project_id:
        raise VaultError(
            f"vault marker at {marker_path} belongs to project "
            f"{data.get('project_id')!r}, not {project_id!r}"
        )


# --------------------------------------------------------------------------- #
# Privacy gate
# --------------------------------------------------------------------------- #

#: Label used for a personal-path hit. The matched path is deliberately not the
#: label: a challenge must be printable without re-leaking what it found.
PERSONAL_PATH_LABEL = "personal absolute path"


class Finding:
    """One blocking privacy hit, expressed as the acknowledgement triple.

    Holds the artifact's logical path, its canonical-content digest, and the
    warning *label* — never the matched text.
    """

    __slots__ = ("path", "sha256", "label")

    def __init__(self, path: str, sha256: str, label: str) -> None:
        self.path = path
        self.sha256 = sha256
        self.label = label

    def triple(self) -> tuple[str, str, str]:
        return (self.path, self.sha256, self.label)

    def challenge(self) -> str:
        """Render the copy/pasteable acknowledgement challenge."""
        return f"  --acknowledge {self.path}:{self.sha256}:{self.label}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Finding) and self.triple() == other.triple()

    def __hash__(self) -> int:
        return hash(self.triple())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Finding(path={self.path!r}, sha256={self.sha256!r}, label={self.label!r})"


def scan_artifact(logical_path: str, canonical_text: str) -> list[Finding]:
    """Return findings for one canonical artifact.

    Runs the project's existing detectors directly rather than through
    ``leakscan.scan_handoff``: that helper suppresses personal-path warnings when
    ``.agent-history/`` is gitignored, which is the right call for a local freeze
    and the wrong one for content leaving the machine.
    """
    from . import leakscan

    digest = canonical_digest(canonical_text)
    findings = [
        Finding(logical_path, digest, label) for label in leakscan.scan_secrets(canonical_text)
    ]
    if leakscan.find_personal_paths(canonical_text):
        findings.append(Finding(logical_path, digest, PERSONAL_PATH_LABEL))
    return findings


def gate_artifacts(
    artifacts: dict[str, str], acknowledgements: list[dict[str, Any]] | None = None
) -> None:
    """Raise :class:`PrivacyBlocked` unless every finding is acknowledged exactly.

    An acknowledgement binds to the immutable ``(path, sha256, label)`` triple,
    so a changed artifact — a different digest — blocks again, and a second
    artifact carrying the same label is unaffected by the first's acknowledgement.
    """
    acknowledged = {
        (str(a.get("path", "")), str(a.get("sha256", "")), str(a.get("label", "")))
        for a in acknowledgements or []
    }
    blocking: list[Finding] = []
    for logical_path in sorted(artifacts):
        for finding in scan_artifact(logical_path, artifacts[logical_path]):
            if finding.triple() not in acknowledged:
                blocking.append(finding)
    if blocking:
        raise PrivacyBlocked(blocking)


# --------------------------------------------------------------------------- #
# DECISIONS.md merge
# --------------------------------------------------------------------------- #

_DECISION_LINE_RE = re.compile(r"^- \[(?P<date>[^\]]*)\]\[(?P<session_id>[^\]]*)\] ")


def _decision_sort_key(line: str, ordinal: int) -> tuple[str, str, int]:
    match = _DECISION_LINE_RE.match(line)
    if match is None:
        # Unrecognised lines sort last but keep their relative order, so a
        # hand-edited log is never silently discarded.
        return ("￿", "￿", ordinal)
    return (match.group("date"), match.group("session_id"), ordinal)


def merge_decisions(*texts: str) -> str:
    """Merge decision logs into exactly one header plus canonically ordered lines.

    Lines are unioned by exact text and ordered by
    ``(session_date, session_id, within-session ordinal)``. Because the order is
    a pure function of the line set, two devices holding the same decisions
    render byte-identical files — which is what stops a re-ordering commit on
    every sync in Git mode.
    """
    from . import writer

    seen: set[str] = set()
    collected: list[tuple[tuple[str, str, int], str]] = []
    per_session: dict[tuple[str, str], int] = {}
    for text in texts:
        for raw in (text or "").split("\n"):
            line = raw.rstrip("\r")
            if not line.strip() or line in seen:
                continue
            if line.startswith("#") or line.startswith("Append-only log"):
                continue  # header material; re-emitted once below
            seen.add(line)
            match = _DECISION_LINE_RE.match(line)
            group = (
                (match.group("date"), match.group("session_id")) if match else ("￿", "￿")
            )
            ordinal = per_session.get(group, 0)
            per_session[group] = ordinal + 1
            collected.append((_decision_sort_key(line, ordinal), line))
    collected.sort(key=lambda item: item[0])
    if not collected:
        return ""
    return writer.DECISIONS_HEADER + "\n".join(line for _, line in collected) + "\n"


# --------------------------------------------------------------------------- #
# Local sync state (.agent-history/VAULT-SYNC.yaml)
# --------------------------------------------------------------------------- #


def sync_state_path(repo_root: Path | str) -> Path:
    from . import writer

    return Path(repo_root) / writer.AGENT_HISTORY_DIRNAME / SYNC_STATE_FILENAME


def read_sync_state(repo_root: Path | str) -> dict[str, Any] | None:
    """Return the local sync record, or ``None`` when this checkout is unsynced."""
    path = sync_state_path(repo_root)
    if not path.is_file():
        return None
    try:
        data = parse_mapping(path.read_text(encoding="utf-8"))
    except (OSError, HandoffParseError) as exc:
        raise VaultError(f"malformed local sync state at {path}: {exc}") from exc
    return data


def require_project_id(repo_root: Path | str, project_id: str) -> dict[str, Any] | None:
    """Enforce one project id per checkout, before any write.

    V1 has no relink or multiple-baseline workflow, so a command naming a
    different id than the stored one fails rather than overwriting the baseline
    that protects the existing sync relationship.
    """
    validate_project_id(project_id)
    state = read_sync_state(repo_root)
    if state is None:
        return None
    stored = state.get("project_id")
    if stored != project_id:
        raise VaultError(
            f"this checkout is linked to project {stored!r}, not {project_id!r}; "
            "v1 permits one project ID per checkout and has no relink workflow"
        )
    return state


def render_sync_state(project_id: str, last_remote_state_sha256: str) -> str:
    return render_vault_yaml(
        {"project_id": project_id, "last_remote_state_sha256": last_remote_state_sha256}
    )


# --------------------------------------------------------------------------- #
# Staged local writes
# --------------------------------------------------------------------------- #

#: Fixed replacement order. Archives land before `DECISIONS.md` — authoritative
#: merged content, not a derived view — and derived views land last, so a torn
#: state is one an index-consistency check can see.
_REPLACE_TAIL = ("DECISIONS.md", "LATEST.md", "INDEX.yaml", "RESUME_PROMPT.txt")


def guard_write_path(containment_root: Path, target: Path) -> None:
    """Reject a symlink at *any* level from ``containment_root`` down to ``target``.

    Guarding only the leaf is not enough: a symlinked ``.agent-history`` or
    ``sessions`` ancestor leaves ``target.is_symlink()`` false while the write
    still lands outside the tree. Mirrors what ``create_handoff`` does for the
    local history, applied to every write path this module owns.
    """
    from . import writer

    root = Path(containment_root)
    target = Path(target)
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise VaultError(f"refusing to write outside {root}: {target}") from exc
    writer.reject_symlink(root)
    current = root
    for part in relative.parts:
        current = current / part
        writer.reject_symlink(current)


def _prepare_target(
    containment_root: Path, target: Path, created_dirs: list[Path] | None = None
) -> None:
    """Guard the whole ancestry, create parents, then re-assert containment.

    ``created_dirs`` collects the directories this call brings into existence,
    deepest last, so a rollback can prune exactly those and leave any directory
    that was already there alone (#87).
    """
    from . import writer

    guard_write_path(containment_root, target)
    if created_dirs is not None:
        missing = [p for p in [target.parent, *target.parent.parents] if not p.exists()]
        created_dirs.extend(reversed(missing))
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.assert_within(target.parent, Path(containment_root).resolve())


class Creations:
    """Every path one publication brought into existence, and how to undo it.

    Public because the Git transport owns the failure window this exists for:
    a publication can succeed and the push that makes it real can still fail,
    and only the transport knows that.

    #87's contract is asymmetric on purpose: a rollback removes what the
    operation *created* and never touches anything that was already there, so an
    operator file sitting inside the transport namespace survives a failed sync.
    Restoring the bytes of a *replaced* file is a different guarantee and belongs
    to #93.
    """

    def __init__(self) -> None:
        self.files: list[Path] = []
        self.dirs: list[Path] = []

    def undo(self) -> None:
        """Delete created files, then prune the directories they needed.

        Directories matter beyond tidiness: an empty ``projects/<id>/sessions/``
        left behind makes :func:`_namespace_is_empty` report a populated
        namespace, so a failed first sync would be read as an unavailable vault
        on every later attempt.
        """
        for target in reversed(self.files):
            Path(target).unlink(missing_ok=True)
        for directory in reversed(self.dirs):
            try:
                Path(directory).rmdir()
            except OSError:
                # Not empty: something pre-existing lives here, so it stays.
                pass


class LocalWrite:
    """Staged replacement for every local-write path, with reverse rollback.

    Collects the whole output, then applies it in a fixed order while retaining
    each displaced original and recording each created target. Any failure
    restores the originals in reverse and deletes what the operation created, so
    the history ends with the same *file set* and the same bytes — not merely
    unchanged bytes for files that happened to exist already.
    """

    def __init__(self, history_dir: Path) -> None:
        self.history_dir = Path(history_dir)
        self._staged: dict[str, str] = {}

    def stage(self, relative_path: str, text: str) -> None:
        self._staged[relative_path] = text

    def _ordered(self) -> list[str]:
        archives = sorted(p for p in self._staged if p.startswith(f"{SESSIONS_DIRNAME}/"))
        tail = [p for p in _REPLACE_TAIL if p in self._staged]
        others = sorted(set(self._staged) - set(archives) - set(tail))
        return archives + tail + others

    def commit(self, fault_after: int | None = None) -> None:
        """Apply the staged writes, rolling back completely on any failure.

        ``fault_after`` injects a failure once that many targets have been
        replaced; it exists so the rollback path is exercised by a test rather
        than asserted.
        """
        applied: list[tuple[Path, bytes | None]] = []
        try:
            for count, relative_path in enumerate(self._ordered()):
                if fault_after is not None and count == fault_after:
                    raise VaultError("injected replace-phase fault")
                target = self.history_dir / relative_path
                _prepare_target(self.history_dir, target)
                original = target.read_bytes() if target.is_file() else None
                applied.append((target, original))
                target.write_text(self._staged[relative_path], encoding="utf-8", newline="\n")
        except Exception:
            for target, original in reversed(applied):
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(original)
            raise


# --------------------------------------------------------------------------- #
# Vault state
# --------------------------------------------------------------------------- #


def state_path(namespace: Path) -> Path:
    return Path(namespace) / STATE_DIRNAME / STATE_FILENAME


def read_state(namespace: Path, required: bool = False) -> dict[str, Any]:
    """Read ``state/vault-state.yaml``; a malformed state is a hard error.

    Never falls back to a rebuilt-from-scratch state the way ``create_handoff``
    does for a corrupt local index: on a vault path that behaviour is
    last-writer-wins, which the conflict contract forbids.
    """
    path = state_path(namespace)
    if not path.is_file():
        if required:
            raise VaultUnavailable(
                f"vault not fully available: {path} is missing while the namespace is populated"
            )
        return {"head_session_id": "", "lifecycle": [], "acknowledgements": []}
    try:
        data = parse_mapping(path.read_text(encoding="utf-8"))
    except (OSError, HandoffParseError) as exc:
        raise VaultError(f"malformed vault state at {path}: {exc}") from exc
    for key in ("lifecycle", "acknowledgements"):
        value = data.get(key)
        if value is None:
            data[key] = []
        elif not isinstance(value, list):
            raise VaultError(f"malformed vault state at {path}: {key} is not a list")
    return data


def merge_lifecycle(
    local: list[dict[str, Any]], vault: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge lifecycle entries: absent → adopt, equal → no-op, different → conflict.

    Returns ``(merged, conflicting_session_ids)``. The one-sided case is the
    ordinary flow — a device closes a session and pushes while the other has no
    entry at all — so adopting rather than conflicting there is what lets a
    close propagate.
    """
    by_id: dict[str, str] = {}
    conflicts: list[str] = []
    for entry in list(local or []):
        by_id[str(entry.get("session_id", ""))] = str(entry.get("status", ""))
    for entry in list(vault or []):
        session_id = str(entry.get("session_id", ""))
        status = str(entry.get("status", ""))
        if session_id not in by_id:
            by_id[session_id] = status
        elif by_id[session_id] != status:
            conflicts.append(session_id)
    merged = [{"session_id": sid, "status": by_id[sid]} for sid in sorted(by_id)]
    return merged, sorted(conflicts)


# --------------------------------------------------------------------------- #
# Derived local views
# --------------------------------------------------------------------------- #


def rebuild_derived(
    archives: dict[str, str], head_session_id: str, lifecycle: list[dict[str, Any]]
) -> dict[str, str]:
    """Rebuild ``LATEST.md``, ``INDEX.yaml`` and ``RESUME_PROMPT.txt``.

    ``archives`` maps ``sessions/<name>.md`` to the *materialized* document text,
    and must already be the union of imported and pre-existing local archives —
    rebuilding from the vault's set alone would silently orphan a local-only
    session, which nothing downstream would detect.

    ``LATEST.md`` is a byte copy of the head archive rather than a re-render, so
    an unknown frontmatter field survives there as well as in ``sessions/``.
    """
    from .schema import Handoff, build_index_entry, build_resume_prompt, join_search_tags

    if not archives:
        raise VaultError("cannot rebuild derived views from an empty archive set")
    statuses = {str(e.get("session_id", "")): str(e.get("status", "")) for e in lifecycle or []}

    parsed: dict[str, Handoff] = {}
    for relative_path, text in archives.items():
        try:
            parsed[relative_path] = Handoff.from_text(text)
        except HandoffParseError as exc:
            raise VaultError(f"malformed archive {relative_path}: {exc}") from exc

    head_path = next(
        (p for p, h in parsed.items() if h.session_id == head_session_id),
        None,
    )
    if head_path is None:
        raise VaultError(f"head session {head_session_id!r} is not present in the archive union")
    head = parsed[head_path]

    entries: list[dict[str, Any]] = []
    for relative_path in sorted(parsed):
        handoff = parsed[relative_path]
        entry = build_index_entry(handoff)
        entry["file"] = relative_path
        status = statuses.get(str(handoff.session_id))
        if status:
            entry["status"] = status
        entries.append(entry)
    entries.sort(key=lambda e: (str(e.get("session_date", "")), str(e.get("session_id", ""))))

    first_next_action = head.first_next_action or ""
    if statuses.get(str(head.session_id)) == "DONE":
        first_next_action = ""

    index = {
        "schema_version": head.schema_version if head.schema_version is not None else 1,
        "latest_session": head.session_id,
        "latest_file": head_path,
        "repo_root": head.repo_root,
        "current_branch": head.current_branch,
        "head_commit": head.head_commit,
        "primary_goal": head.primary_goal,
        "search_tags": join_search_tags(head.search_tags),
        "first_next_action": first_next_action,
        "sessions": entries,
    }
    return {
        "LATEST.md": archives[head_path],
        "INDEX.yaml": dump_mapping(index) + "\n",
        "RESUME_PROMPT.txt": build_resume_prompt(head),
    }


# --------------------------------------------------------------------------- #
# Local archive access
# --------------------------------------------------------------------------- #


def read_local_archives(repo_root: Path | str) -> dict[str, str]:
    """Read every ``sessions/*.md`` under the local history, fully."""
    from . import writer

    sessions_dir = Path(repo_root) / writer.AGENT_HISTORY_DIRNAME / SESSIONS_DIRNAME
    archives: dict[str, str] = {}
    if not sessions_dir.is_dir():
        return archives
    for path in sorted(sessions_dir.glob("*.md")):
        writer.reject_symlink(path)
        archives[f"{SESSIONS_DIRNAME}/{path.name}"] = path.read_text(encoding="utf-8")
    return archives


def read_vault_archives(namespace: Path) -> dict[str, str]:
    """Fully read every canonical archive in the vault namespace.

    A referenced artifact that is missing or unreadable raises
    :class:`VaultUnavailable` rather than being treated as absent — on a
    sync-client folder those two look identical from a directory listing, and
    only a full read distinguishes them.
    """
    sessions_dir = Path(namespace) / SESSIONS_DIRNAME
    archives: dict[str, str] = {}
    if not sessions_dir.is_dir():
        return archives
    for path in sorted(sessions_dir.glob("*.md")):
        try:
            archives[f"{SESSIONS_DIRNAME}/{path.name}"] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise VaultUnavailable(
                f"vault not fully available: cannot read {path}: {exc}"
            ) from exc
    return archives


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #


def migrate_roots(repo_root: Path | str, session_id: str, project_root: Path | str) -> str:
    """Bring one archive's ``project_root`` inside ``repo_root``, atomically.

    Rewrites only the two raw root scalars of the named archive and rebuilds the
    derived views through the same staged-replace protocol import uses, so a
    fault partway leaves the history with the same file set and bytes.
    """
    from . import writer

    root = Path(repo_root)
    history_dir = root / writer.AGENT_HISTORY_DIRNAME
    archives = read_local_archives(root)
    target = next(
        (
            relative_path
            for relative_path, text in archives.items()
            if _session_id_of(text) == session_id
        ),
        None,
    )
    if target is None:
        raise VaultError(f"unknown session id {session_id!r}: no archive carries it")

    new_project_root = os.path.normpath(str(project_root))
    contained_offset(new_project_root, str(root.resolve()))  # refuses an escape
    rewritten = _replace_root_scalars(archives[target], str(root.resolve()), new_project_root)
    archives[target] = rewritten

    state = read_state_local(root)
    write = LocalWrite(history_dir)
    write.stage(target, rewritten)
    for name, text in rebuild_derived(
        archives, _head_session_id(root, archives), state.get("lifecycle", [])
    ).items():
        write.stage(name, text)
    write.commit()
    return target


def _session_id_of(text: str) -> str | None:
    try:
        frontmatter, _ = parse_frontmatter(text)
    except HandoffParseError:
        return None
    value = frontmatter.get("session_id")
    return str(value) if value is not None else None


def _head_session_id(repo_root: Path, archives: dict[str, str]) -> str:
    """The local head: ``INDEX.yaml``'s ``latest_session`` when it is usable."""
    from . import writer

    index_path = Path(repo_root) / writer.AGENT_HISTORY_DIRNAME / writer.INDEX_FILENAME
    if index_path.is_file():
        try:
            index = parse_mapping(index_path.read_text(encoding="utf-8"))
        except (OSError, HandoffParseError) as exc:
            raise VaultError(f"malformed local index at {index_path}: {exc}") from exc
        latest = index.get("latest_session")
        if isinstance(latest, str) and latest:
            return latest
    ids = sorted(filter(None, (_session_id_of(t) for t in archives.values())))
    if not ids:
        raise VaultError("local history has no sessions")
    return ids[-1]


def read_state_local(repo_root: Path | str) -> dict[str, Any]:
    """Lifecycle state as recorded in the local ``INDEX.yaml``."""
    from . import writer

    index_path = Path(repo_root) / writer.AGENT_HISTORY_DIRNAME / writer.INDEX_FILENAME
    if not index_path.is_file():
        return {"lifecycle": []}
    try:
        index = parse_mapping(index_path.read_text(encoding="utf-8"))
    except (OSError, HandoffParseError) as exc:
        raise VaultError(f"malformed local index at {index_path}: {exc}") from exc
    lifecycle = [
        {"session_id": str(s.get("session_id", "")), "status": str(s.get("status", ""))}
        for s in index.get("sessions") or []
        if isinstance(s, dict) and s.get("status")
    ]
    return {"lifecycle": lifecycle}


def _namespace_is_empty(namespace: Path) -> bool:
    """True when ``projects/<id>/`` is absent or holds nothing."""
    path = Path(namespace)
    if not path.exists():
        return True
    return not any(path.iterdir())


def _namespace_is_bootstrap(namespace: Path, sync_state: dict[str, Any] | None) -> bool:
    """True only for a genuine first push — an empty namespace *and* no baseline.

    Keying this on the vault side alone would reopen the transport's defining
    failure: on a sync-client folder "never existed" and "not yet materialized"
    are indistinguishable from there. A caller holding a
    ``last_remote_state_sha256`` for this project has demonstrably synced a real
    vault before, so an absent namespace is unavailability rather than a first
    push. A device with no stored digest still cannot tell the two apart — that
    residue is irreducible, and v1 answers it with user-serialized operation
    rather than a lock.
    """
    if not _namespace_is_empty(namespace):
        return False
    if sync_state and sync_state.get("last_remote_state_sha256"):
        raise VaultUnavailable(
            f"vault not fully available: {namespace} is absent or empty, but this "
            "checkout has synced this project before; wait for the sync client "
            "rather than re-initializing"
        )
    return True


def _require_populated_namespace(namespace: Path, project_id: str) -> None:
    """Validate a populated namespace: marker, then state, then referenced content."""
    path = Path(namespace)
    if not (path / MARKER_FILENAME).is_file():
        raise VaultError(
            f"vault namespace {path} is populated but has no {MARKER_FILENAME}; "
            "refusing to adopt a marker-less namespace"
        )
    read_marker(path, project_id)
    # A marker without state is a torn namespace, not an empty one: treating it
    # as empty would let an export overwrite state it never read.
    state = read_state(path, required=True)
    require_referenced_archives(path, state)


def require_referenced_archives(namespace: Path, state: dict[str, Any]) -> dict[str, str]:
    """Fully read every archive the vault state references, before any write.

    Reading is the check: on a sync-client folder an online-only placeholder is
    present in a listing and stats with a plausible size, so only reading the
    bytes distinguishes "not synced yet" from "not there". A state that names a
    session no archive carries is a torn vault, not an empty one.
    """
    archives = read_vault_archives(namespace)
    present = {_session_id_of(text) for text in archives.values()}
    referenced = {str(state.get("head_session_id") or "")}
    referenced.update(
        str(entry.get("session_id", "")) for entry in state.get("lifecycle") or []
    )
    missing = sorted(sid for sid in referenced if sid and sid not in present)
    if missing:
        raise VaultUnavailable(
            "vault not fully available: state references session(s) with no readable "
            f"archive: {', '.join(missing)}"
        )
    return archives


def _publish(
    vault_root: Path,
    namespace: Path,
    content: dict[str, str],
    state: dict[str, Any],
    project_id: str,
    fault_after: int | None = None,
    created: "Creations | None" = None,
) -> None:
    """Write content, then state, then the marker — in that order.

    The ordering is what makes a torn vault detectable rather than authoritative:
    a failure can leave unreferenced content, but never a state or marker
    pointing at content that is not there.

    Every target is guarded the same way the local side is: a symlink at any
    level between the vault root and the file is refused before the first write,
    so a symlinked namespace or nested parent cannot redirect a write out of the
    vault root.

    ``created`` records every path this call brings into existence but never
    undoes anything itself: the caller decides. #87 gives that decision to the
    Git transport, which needs it because a ``git reset --hard`` restores tracked
    bytes and cannot remove a file that was never committed. Folder-mode recovery
    on a failed publication is #93's, so a folder caller that passes no record
    keeps today's behaviour exactly.
    """
    root = Path(vault_root)
    path = Path(namespace)
    targets = [path / relative_path for relative_path in sorted(content)]
    targets.append(state_path(path))
    targets.append(path / MARKER_FILENAME)
    for target in targets:
        guard_write_path(root, target)

    record = Creations() if created is None else created
    written = 0
    for relative_path in sorted(content):
        if fault_after is not None and written == fault_after:
            raise VaultError("injected publication fault")
        target = path / relative_path
        _write_recorded(root, target, content[relative_path], record)
        written += 1
    _write_recorded(root, state_path(path), render_vault_state(state), record)
    _write_recorded(root, path / MARKER_FILENAME, render_marker(project_id), record)


def _write_recorded(root: Path, target: Path, text: str, record: "Creations") -> None:
    """Write one publication target, noting it if it did not exist before."""
    _prepare_target(root, target, record.dirs)
    if not target.exists():
        record.files.append(target)
    target.write_text(text, encoding="utf-8", newline="\n")


def export_project(
    repo_root: Path | str,
    vault_root: Path | str,
    project_id: str,
    acknowledgements: list[dict[str, Any]] | None = None,
    fault_after: int | None = None,
    write_local_state: bool = True,
    created: "Creations | None" = None,
) -> str:
    """Export the local history into the vault; return the resulting state digest.

    ``write_local_state=False`` leaves the local baseline untouched so a
    transport with a later success condition — #80's upstream push — can record
    it only once that condition holds.

    Refuses before any write on: a project-id mismatch, an out-of-repo project
    root, a marker-less populated namespace, a privacy finding without its exact
    acknowledgement, or a same-session byte divergence.
    """
    root = Path(repo_root)
    require_project_id(root, project_id)
    namespace = project_dir(Path(vault_root), project_id)

    local_archives = read_local_archives(root)
    if not local_archives:
        raise VaultError("local history has no archives to export")
    canonical = {path: canonicalize_document(text) for path, text in local_archives.items()}

    bootstrap = _namespace_is_bootstrap(namespace, read_sync_state(root))
    if not bootstrap:
        _require_populated_namespace(namespace, project_id)
    vault_archives = {} if bootstrap else read_vault_archives(namespace)
    vault_state = {"head_session_id": "", "lifecycle": [], "acknowledgements": []}
    if not bootstrap:
        vault_state = read_state(namespace)

    diverged = sorted(
        path
        for path, text in canonical.items()
        if path in vault_archives and vault_archives[path] != text
    )
    if diverged:
        raise VaultConflict(
            "same-session archive bytes differ between local and vault: "
            + ", ".join(diverged)
            + "; run 'glue sync resolve' with an explicit selector for each"
        )

    local_lifecycle = read_state_local(root).get("lifecycle", [])
    merged_lifecycle, lifecycle_conflicts = merge_lifecycle(
        local_lifecycle, vault_state.get("lifecycle", [])
    )
    if lifecycle_conflicts:
        raise VaultConflict(
            "lifecycle values disagree for: " + ", ".join(lifecycle_conflicts)
        )

    decisions_local = _read_text(_local_decisions_path(root))
    decisions_vault = _read_text(Path(namespace) / DECISIONS_FILENAME)
    merged_decisions = merge_decisions(decisions_local, decisions_vault)

    sync_state = read_sync_state(root)
    first_sync = sync_state is None
    changed = {
        path: text
        for path, text in canonical.items()
        if first_sync or vault_archives.get(path) != text
    }
    gate_input = dict(changed)
    if merged_decisions and (first_sync or merged_decisions != decisions_vault):
        gate_input[DECISIONS_FILENAME] = merged_decisions
    gate_artifacts(gate_input, vault_state.get("acknowledgements", []) + list(acknowledgements or []))

    head_session_id = _head_session_id(root, local_archives)
    if not bootstrap:
        stored = (sync_state or {}).get("last_remote_state_sha256")
        if stored != state_digest(vault_state):
            raise VaultConflict(
                "the vault moved since this checkout last synced; "
                "pull first, or run 'glue sync resolve' to choose a head"
            )

    content = dict(vault_archives)
    content.update(canonical)
    if merged_decisions:
        content[DECISIONS_FILENAME] = merged_decisions
    new_state = {
        "head_session_id": head_session_id,
        "lifecycle": merged_lifecycle,
        "acknowledgements": merge_manifest_records(
            vault_state.get("acknowledgements", []), list(acknowledgements or [])
        ),
    }
    _publish(Path(vault_root), namespace, content, new_state, project_id,
             fault_after=fault_after, created=created)

    digest = state_digest(new_state)
    if write_local_state:
        write_sync_state(root, project_id, digest)
    return digest


def import_project(repo_root: Path | str, vault_root: Path | str, project_id: str) -> str:
    """Import the vault into the local history; return the resulting state digest."""
    from . import writer

    root = Path(repo_root)
    require_project_id(root, project_id)
    namespace = project_dir(Path(vault_root), project_id)
    if _namespace_is_empty(namespace):
        raise VaultUnavailable(
            f"vault not fully available: {namespace} is absent or empty"
        )
    _require_populated_namespace(namespace, project_id)

    vault_state = read_state(namespace)
    vault_archives = read_vault_archives(namespace)
    if not vault_archives:
        raise VaultUnavailable("vault not fully available: no archives under sessions/")

    materialized = {
        path: materialize_document(text, root) for path, text in vault_archives.items()
    }
    local_archives = read_local_archives(root)
    union = dict(local_archives)
    union.update(materialized)

    head = vault_state.get("head_session_id") or ""
    lifecycle = vault_state.get("lifecycle", [])
    derived = rebuild_derived(union, head, lifecycle)

    decisions = merge_decisions(
        _read_text(_local_decisions_path(root)), _read_text(Path(namespace) / DECISIONS_FILENAME)
    )

    history_dir = root / writer.AGENT_HISTORY_DIRNAME
    history_dir.mkdir(parents=True, exist_ok=True)
    write = LocalWrite(history_dir)
    for path, text in materialized.items():
        write.stage(path, text)
    if decisions:
        write.stage(DECISIONS_FILENAME, decisions)
    for name, text in derived.items():
        write.stage(name, text)
    write.commit()

    digest = state_digest(vault_state)
    write_sync_state(root, project_id, digest)
    return digest


def _local_decisions_path(repo_root: Path) -> Path:
    from . import writer

    return Path(repo_root) / writer.AGENT_HISTORY_DIRNAME / DECISIONS_FILENAME


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def write_sync_state(repo_root: Path, project_id: str, digest: str) -> None:
    """Record the baseline as the final local write of a successful operation.

    Public because the Git transport (issue #80) must *defer* it until the exact
    upstream push succeeds: in Git mode the vault is the remote, so a local
    commit that has not been pushed is not a vault change that succeeded, and
    advancing the digest there records a baseline the other device can never
    observe.
    """
    path = sync_state_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_sync_state(project_id, digest), encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- #
# Conflict retention and resolution
# --------------------------------------------------------------------------- #


def conflict_archive_path(session_id: str, digest: str, side: str) -> str:
    return f"{CONFLICTS_DIRNAME}/{CONFLICT_ARCHIVES_DIRNAME}/{session_id}/{digest}-{side}.md"


def conflict_lifecycle_path(session_id: str, side: str) -> str:
    return f"{CONFLICTS_DIRNAME}/{CONFLICT_LIFECYCLE_DIRNAME}/{session_id}/{side}.yaml"


def build_conflict_candidates(
    archive_conflicts: dict[str, tuple[str, str]],
    lifecycle_conflicts: dict[str, tuple[str, str]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Build retained candidate artifacts and their manifest records.

    ``archive_conflicts`` maps ``session_id`` to ``(local_text, vault_text)`` and
    ``lifecycle_conflicts`` maps ``session_id`` to ``(local_status, vault_status)``.
    Every candidate is canonical content, so it passes the same privacy gate as
    an active archive before it is written.
    """
    artifacts: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for session_id, sides in sorted(archive_conflicts.items()):
        for side, text in zip(("local", "vault"), sides, strict=True):
            digest = canonical_digest(text)
            path = conflict_archive_path(session_id, digest, side)
            artifacts[path] = text
            records.append(
                {
                    "session_id": session_id,
                    "kind": "archive",
                    "side": side,
                    "path": path,
                    "sha256": digest,
                }
            )
    for session_id, sides in sorted(lifecycle_conflicts.items()):
        for side, status in zip(("local", "vault"), sides, strict=True):
            path = conflict_lifecycle_path(session_id, side)
            rendered = render_vault_yaml({"session_id": session_id, "status": status})
            artifacts[path] = rendered
            records.append(
                {
                    "session_id": session_id,
                    "kind": "lifecycle",
                    "side": side,
                    "path": path,
                    "sha256": sha256_hex(rendered),
                }
            )
    return artifacts, records


def read_manifest(namespace: Path) -> list[dict[str, Any]]:
    path = Path(namespace) / CONFLICTS_DIRNAME / MANIFEST_FILENAME
    if not path.is_file():
        return []
    try:
        data = parse_mapping(path.read_text(encoding="utf-8"))
    except (OSError, HandoffParseError) as exc:
        raise VaultError(f"malformed conflicts manifest at {path}: {exc}") from exc
    records = data.get("conflicts")
    return list(records) if isinstance(records, list) else []


def resolve_project(
    repo_root: Path | str,
    vault_root: Path | str,
    project_id: str,
    head_session: str,
    archive_choices: dict[str, str] | None = None,
    lifecycle_choices: dict[str, str] | None = None,
    acknowledgements: list[dict[str, Any]] | None = None,
    write_local_state: bool = True,
    created: "Creations | None" = None,
) -> str:
    """Resolve every named conflict with explicit selectors and publish the result.

    Every archive this writes — the chosen active one as well as each retained
    candidate — is canonicalized and passes the privacy gate before any vault
    write, so a resolution cannot become the path by which blocked content
    reaches the vault. Non-chosen candidates are retained under ``conflicts/``,
    never dropped, and never enter the active archive union or the index rebuild.
    """
    root = Path(repo_root)
    require_project_id(root, project_id)
    namespace = project_dir(Path(vault_root), project_id)
    _require_populated_namespace(namespace, project_id)

    archive_choices = dict(archive_choices or {})
    lifecycle_choices = dict(lifecycle_choices or {})
    for side in list(archive_choices.values()) + list(lifecycle_choices.values()):
        if side not in ("local", "vault"):
            raise VaultError(f"unknown conflict side {side!r}: expected 'local' or 'vault'")

    local_canonical = {
        path: canonicalize_document(text) for path, text in read_local_archives(root).items()
    }
    vault_state = read_state(namespace)
    vault_archives = read_vault_archives(namespace)

    by_session_local = {_session_id_of(t): (p, t) for p, t in local_canonical.items()}
    by_session_vault = {_session_id_of(t): (p, t) for p, t in vault_archives.items()}

    archive_conflicts = {
        session_id: (by_session_local[session_id][1], by_session_vault[session_id][1])
        for session_id in sorted(set(by_session_local) & set(by_session_vault))
        if by_session_local[session_id][1] != by_session_vault[session_id][1]
    }
    merged_lifecycle, disagreeing = merge_lifecycle(
        read_state_local(root).get("lifecycle", []), vault_state.get("lifecycle", [])
    )
    local_status = {
        str(e.get("session_id")): str(e.get("status"))
        for e in read_state_local(root).get("lifecycle", [])
    }
    vault_status = {
        str(e.get("session_id")): str(e.get("status")) for e in vault_state.get("lifecycle", [])
    }
    lifecycle_conflicts = {sid: (local_status[sid], vault_status[sid]) for sid in disagreeing}

    missing = sorted(
        [sid for sid in archive_conflicts if sid not in archive_choices]
        + [sid for sid in lifecycle_conflicts if sid not in lifecycle_choices]
    )
    if missing:
        raise VaultError(
            "resolution requires an explicit selector for every named conflict; "
            f"missing: {', '.join(missing)}"
        )

    active = dict(vault_archives)
    active.update(local_canonical)
    for session_id, choice in archive_choices.items():
        chosen = (by_session_local if choice == "local" else by_session_vault)[session_id]
        active[chosen[0]] = chosen[1]
    for session_id, choice in lifecycle_choices.items():
        status = (local_status if choice == "local" else vault_status)[session_id]
        merged_lifecycle = [e for e in merged_lifecycle if e.get("session_id") != session_id]
        merged_lifecycle.append({"session_id": session_id, "status": status})
    merged_lifecycle.sort(key=lambda e: str(e.get("session_id", "")))

    if head_session not in {_session_id_of(text) for text in active.values()}:
        raise VaultError(
            f"--head-session {head_session!r} is not present in the resolved active archive union"
        )

    candidates, records = build_conflict_candidates(archive_conflicts, lifecycle_conflicts)
    gate_artifacts(
        {**active, **candidates},
        vault_state.get("acknowledgements", []) + list(acknowledgements or []),
    )

    content = dict(active)
    content.update(candidates)
    merged_records = merge_manifest_records(read_manifest(namespace), records)
    if merged_records:
        content[f"{CONFLICTS_DIRNAME}/{MANIFEST_FILENAME}"] = render_manifest(merged_records)
    decisions = merge_decisions(
        _read_text(_local_decisions_path(root)), _read_text(Path(namespace) / DECISIONS_FILENAME)
    )
    if decisions:
        content[DECISIONS_FILENAME] = decisions

    new_state = {
        "head_session_id": head_session,
        "lifecycle": merged_lifecycle,
        "acknowledgements": merge_manifest_records(
            vault_state.get("acknowledgements", []), list(acknowledgements or [])
        ),
    }
    _publish(Path(vault_root), namespace, content, new_state, project_id, created=created)
    digest = state_digest(new_state)
    if write_local_state:
        write_sync_state(root, project_id, digest)
    return digest
