import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FAST = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
FULL = (ROOT / ".github" / "workflows" / "ci-full.yml").read_text(encoding="utf-8")


def pull_request_types(workflow: str) -> set[str]:
    match = re.search(
        r"(?m)^  pull_request:\n    types: \[([^]]+)]$",
        workflow,
    )
    assert match is not None, "workflow has no single-line pull_request types declaration"
    return {item.strip() for item in match.group(1).split(",")}


def test_ordinary_pushes_have_one_canonical_smoke_job() -> None:
    assert pull_request_types(FAST) == {"opened", "synchronize", "reopened"}
    assert "branches: [main]" in FAST
    assert "python-version: \"3.12\"" in FAST
    assert "matrix:" not in FAST
    assert FAST.count("runs-on:") == 1


def test_full_matrix_is_candidate_triggered_not_synchronize_triggered() -> None:
    assert pull_request_types(FULL) == {"opened", "ready_for_review", "labeled"}
    assert "github.event.label.name == 'ci:full'" in FULL
    assert "github.event.pull_request.draft == false" in FULL


def test_full_matrix_preserves_every_supported_python_and_os() -> None:
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in FULL
    assert 'python-version: ["3.10", "3.11", "3.12", "3.13"]' in FULL
    assert "All 12 Python/OS candidate cells passed." in FULL


def test_release_and_canary_paths_keep_full_coverage() -> None:
    assert 'tags: ["v*"]' in FULL
    assert 'cron: "17 4 * * 1"' in FULL
    assert "workflow_dispatch:" in FULL


def test_both_lanes_install_package_test_dependencies() -> None:
    command = 'python -m pip install -e ".[dev]"'
    assert command in FAST
    assert command in FULL
    assert "python -m pytest" in FAST
    assert "python -m pytest" in FULL
