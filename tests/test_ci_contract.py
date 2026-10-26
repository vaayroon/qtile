"""Contract tests tying the CI workflow to the rest of the repository.

These read the workflow as text (no YAML library is a project dependency) and
only check what would otherwise break silently: a missing ``--locked`` that
re-locks behind our back, an action pinned to a movable tag, a renamed job that
branch protection no longer matches, a CI interpreter that drifts from
``.python-version``. They deliberately do not restate every workflow value.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PYTHON_VERSION = ROOT / ".python-version"

UV_RUN_OR_SYNC = re.compile(r"\buv\s+(?:run|sync)\b")
USES_LINE = re.compile(r"^\s*-?\s*uses:\s*(\S+)(.*)$")
PINNED_USES = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s*#\s*v\d+\.\d+\.\d+\s*$")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_lines(text: str) -> list[str]:
    """Return the non-blank lines with ``#`` comments stripped."""
    stripped = (re.sub(r"\s#.*$", "", line).rstrip() for line in text.splitlines())
    return [
        line for line in stripped if line.strip() and not line.lstrip().startswith("#")
    ]


def _unlocked_uv_commands(text: str) -> list[str]:
    """Return the ``uv run`` / ``uv sync`` lines that lack ``--locked``."""
    return [
        line.strip()
        for line in _code_lines(text)
        if UV_RUN_OR_SYNC.search(line) and "--locked" not in line
    ]


def _unpinned_uses(text: str) -> list[str]:
    """Return the ``uses:`` lines not pinned as ``owner/repo@<sha> # vX.Y.Z``."""
    bad = []
    for line in text.splitlines():
        match = USES_LINE.match(line)
        if match and not (
            PINNED_USES.match(match.group(1)) and VERSION_COMMENT.match(match.group(2))
        ):
            bad.append(line.strip())
    return bad


def _block(text: str, key: str) -> list[str]:
    """Return the indented lines under the top-level ``key:`` (comments dropped)."""
    lines = text.splitlines()
    start = lines.index(f"{key}:") + 1
    body = []
    for line in lines[start:]:
        if line.strip() and not line.startswith(" "):
            break
        body.append(line)
    return _code_lines("\n".join(body))


def _child_keys(block: list[str], indent: int = 2) -> list[str]:
    pattern = re.compile(rf"^ {{{indent}}}([\w-]+):")
    return [m.group(1) for line in block if (m := pattern.match(line))]


def _steps(text: str) -> list[str]:
    """Split the workflow into its steps (each starting at ``      - ``)."""
    return re.split(r"(?m)^(?=      - )", text)[1:]


def _commands(text: str) -> list[str]:
    """Return every single-line ``run:`` command of the workflow, in order."""
    return [m.group(1) for m in re.finditer(r"(?m)^\s*run:\s+(.+?)\s*$", text)]


# --- The helpers must not lie ---------------------------------------------------


def test_unlocked_scan_flags_uv_commands_without_locked() -> None:
    text = "run: uv run ruff check .\nrun: uv sync\nrun: uv run --locked pytest\n"

    assert _unlocked_uv_commands(text) == ["run: uv run ruff check .", "run: uv sync"]


def test_unlocked_scan_ignores_other_uv_commands_and_comments() -> None:
    text = "run: uv lock --check\n# uv run pytest\nrun: uv run --locked pytest  # ok\n"

    assert _unlocked_uv_commands(text) == []


@pytest.mark.parametrize(
    "line",
    [
        "uses: actions/checkout@v7",
        "uses: actions/checkout@v7.0.1",
        "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "uses: actions/checkout@3d3c42e5aac5 # v7.0.1",
        "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # latest",
    ],
)
def test_pin_scan_flags_movable_or_undocumented_refs(line: str) -> None:
    assert _unpinned_uses(f"      - {line}\n") == [f"- {line}"]


def test_pin_scan_accepts_a_sha_with_a_version_comment() -> None:
    sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"

    assert _unpinned_uses(f"      - uses: actions/checkout@{sha} # v7.0.1\n") == []


# --- The workflow is locked, pinned and wired to the repo ------------------------


def test_every_uv_run_and_sync_in_the_workflow_is_locked() -> None:
    assert _unlocked_uv_commands(_text(CI_WORKFLOW)) == []


def test_every_action_is_pinned_to_a_commit_sha() -> None:
    text = _text(CI_WORKFLOW)

    assert re.search(r"(?m)^\s*-?\s*uses:", text), "the workflow uses no actions?"
    assert _unpinned_uses(text) == []


def test_checkout_does_not_persist_credentials() -> None:
    checkouts = [s for s in _steps(_text(CI_WORKFLOW)) if "actions/checkout@" in s]

    assert checkouts
    assert all("persist-credentials: false" in step for step in checkouts)


def test_the_single_job_is_named_checks() -> None:
    # Branch protection requires the check by this name: renaming the job
    # leaves every PR waiting for a check that never reports.
    text = _text(CI_WORKFLOW)
    jobs = _block(text, "jobs")

    assert _child_keys(jobs) == ["checks"]
    assert "    name: checks" in jobs


def test_ci_uses_the_distro_interpreter_of_python_version() -> None:
    pinned = PYTHON_VERSION.read_text().strip()
    major_minor = ".".join(pinned.split(".")[:2])

    assert f"UV_PYTHON: /usr/bin/python{major_minor}" in _text(CI_WORKFLOW)


def test_the_workflow_runs_on_pushes_and_pull_requests_to_main_only() -> None:
    triggers = _block(_text(CI_WORKFLOW), "on")

    assert sorted(_child_keys(triggers)) == ["pull_request", "push"]
    assert triggers.count("    branches: [main]") == 2


def test_the_token_is_read_only() -> None:
    assert _block(_text(CI_WORKFLOW), "permissions") == ["  contents: read"]


def test_stale_runs_are_cancelled_on_pull_requests_but_not_on_main() -> None:
    concurrency = _block(_text(CI_WORKFLOW), "concurrency")

    assert "  group: ci-${{ github.ref }}" in concurrency
    assert (
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}"
        in concurrency
    )


def test_the_checks_run_in_order_and_the_floor_is_defined_once() -> None:
    text = _text(CI_WORKFLOW)
    floors = re.findall(r'(?m)^\s*MIN_TESTS:\s*"(\d+)"', text)
    expected = [
        "uv lock --check",
        "uv sync --locked",
        "uv run --locked ruff check .",
        "uv run --locked ruff format --check .",
        "uv run --locked mypy src tools",
        'uv run --locked pytest -rs --junitxml="$RUNNER_TEMP/pytest.xml"',
        'uv run --locked python tools/check_junit.py "$RUNNER_TEMP/pytest.xml" '
        '--min-tests "$MIN_TESTS"',
    ]

    assert len(floors) == 1 and int(floors[0]) > 0
    commands = iter(_commands(text))
    assert all(wanted in commands for wanted in expected), _commands(text)
