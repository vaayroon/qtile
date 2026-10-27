"""Contract tests tying the CI workflow to the rest of the repository.

These read the files as text (no YAML library is a project dependency) and only
check what would otherwise break silently: a missing ``--locked`` that re-locks
behind our back, an action pinned to a movable tag, a renamed job that branch
protection no longer matches, a CI interpreter that drifts from
``.python-version``, a README that documents other commands than CI runs. They
deliberately do not restate workflow values.
"""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
HOOKS = ROOT / ".pre-commit-config.yaml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
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


def _commands(text: str) -> list[str]:
    """Return every single-line ``run:`` command of the workflow, in order."""
    return [m.group(1) for m in re.finditer(r"(?m)^\s*run:\s+(.+?)\s*$", text)]


# --- The scans below must be able to fail ----------------------------------------
# Every guard in this file is only as good as its scan: a regex that matches
# nothing passes forever.


def test_the_lock_scan_flags_uv_commands_without_locked() -> None:
    text = "run: uv run ruff check .\nrun: uv sync\nrun: uv run --locked pytest\n"

    assert _unlocked_uv_commands(text) == ["run: uv run ruff check .", "run: uv sync"]


def test_the_pin_scan_flags_movable_refs_and_accepts_pinned_ones() -> None:
    sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
    text = (
        "      - uses: actions/checkout@v7\n"
        f"      - uses: actions/checkout@{sha}\n"
        f"      - uses: actions/checkout@{sha} # v7.0.1\n"
    )

    assert _unpinned_uses(text) == [
        "- uses: actions/checkout@v7",
        f"- uses: actions/checkout@{sha}",
    ]


# --- The workflow is locked, pinned and wired to the repo ------------------------


def test_every_uv_run_and_sync_in_the_workflow_is_locked() -> None:
    assert _unlocked_uv_commands(_text(CI_WORKFLOW)) == []


def test_every_action_is_pinned_to_a_commit_sha() -> None:
    text = _text(CI_WORKFLOW)

    assert re.search(r"(?m)^\s*-?\s*uses:", text), "the workflow uses no actions?"
    assert _unpinned_uses(text) == []


def test_checkout_does_not_persist_credentials() -> None:
    steps = re.split(r"(?m)^(?=      - )", _text(CI_WORKFLOW))[1:]
    checkouts = [step for step in steps if "actions/checkout@" in step]

    assert checkouts
    assert all("persist-credentials: false" in step for step in checkouts)


def test_the_single_job_is_named_checks() -> None:
    # Branch protection requires the check by this name: renaming the job
    # leaves every PR waiting for a check that never reports.
    jobs = _block(_text(CI_WORKFLOW), "jobs")

    assert [m.group(1) for line in jobs if (m := re.match(r"^  ([\w-]+):$", line))] == [
        "checks"
    ]
    assert "    name: checks" in jobs


def test_ci_uses_the_distro_interpreter_of_python_version() -> None:
    pinned = PYTHON_VERSION.read_text().strip()
    major_minor = ".".join(pinned.split(".")[:2])

    assert f"UV_PYTHON: /usr/bin/python{major_minor}" in _text(CI_WORKFLOW)


def test_the_token_is_read_only() -> None:
    # Repository default for workflow permissions is `write`: this block is
    # what keeps the token read-only.
    assert _block(_text(CI_WORKFLOW), "permissions") == ["  contents: read"]


def test_the_test_count_is_defined_once_and_passed_to_the_gate() -> None:
    text = _text(CI_WORKFLOW)
    counts = re.findall(r'(?m)^\s*EXPECTED_TESTS:\s*"(\d+)"', text)

    assert len(counts) == 1 and int(counts[0]) > 0
    assert any(
        "tools/check_junit.py" in command and '"$EXPECTED_TESTS"' in command
        for command in _commands(text)
    )


# --- Local hooks use the same locked tools as CI ---------------------------------


def _pre_commit_floor() -> str:
    """Return ``X`` of the ``pre-commit>=X`` requirement of the dev group."""
    with PYPROJECT.open("rb") as fh:
        dev = tomllib.load(fh)["dependency-groups"]["dev"]
    counts = [
        m.group(1) for d in dev if (m := re.fullmatch(r"pre-commit>=([\d.]+)", d))
    ]
    assert len(counts) == 1, "pin pre-commit as 'pre-commit>=X' in the dev group"
    return counts[0]


def test_hooks_never_run_uv_unlocked() -> None:
    text = _text(HOOKS)

    assert UV_RUN_OR_SYNC.search(text), "the hooks run no uv command?"
    assert _unlocked_uv_commands(text) == []


def test_hooks_minimum_version_is_the_pre_commit_floor_of_the_dev_group() -> None:
    # `language: unsupported` needs pre-commit >= 4.4.0 in the lock too.
    declared = re.search(r'(?m)^minimum_pre_commit_version:\s*"([\d.]+)"', _text(HOOKS))

    assert declared and declared.group(1) == _pre_commit_floor()


def test_the_lock_hook_only_runs_when_the_lock_inputs_change() -> None:
    hooks = re.split(r"(?m)^(?=      - id: )", _text(HOOKS))
    lock_hook = next(h for h in hooks if h.startswith("      - id: uv-lock"))
    files = re.search(r"(?m)^\s*files:\s*(\S+)$", lock_hook)

    assert "pass_filenames: false" in lock_hook
    assert files
    pattern = re.compile(files.group(1))
    assert pattern.search("pyproject.toml") and pattern.search("uv.lock")
    assert not pattern.search("src/pyproject.toml")
    assert not pattern.search("pyproject.toml.bak")
    assert not pattern.search("src/config.py")


# --- Dependabot must not touch the exact qtile pin --------------------------------


def test_dependabot_leaves_the_qtile_pin_to_manual_bumps() -> None:
    # qtile is pinned exactly and bumped by hand with the version and banner.
    text = _text(DEPENDABOT)
    uv = text.split('package-ecosystem: "uv"', 1)[1].split("package-ecosystem:")[0]

    assert re.search(r'(?m)^    ignore:\n      - dependency-name: "qtile"', uv)


# --- The README documents what CI and the hooks actually run ----------------------


def test_readme_commands_never_run_uv_unlocked() -> None:
    assert _unlocked_uv_commands(_text(README)) == []


@pytest.mark.parametrize(
    "command",
    [
        "uv run --locked ruff check .",
        "uv run --locked ruff format --check .",
        "uv run --locked mypy src tools",
    ],
)
def test_readme_documents_each_check_ci_runs(command: str) -> None:
    # What a contributor runs locally must be what the CI job runs.
    assert command in _commands(_text(CI_WORKFLOW))
    assert command in _text(README)


def test_readme_names_the_required_check_after_the_job() -> None:
    # Branch protection matches the job name, so the README must give that name.
    job = re.search(r"(?m)^    name: (\S+)", _text(CI_WORKFLOW))
    section = _text(README).split("### Continuous integration", 1)[-1]

    assert job
    assert f"`{job.group(1)}`" in section
    assert "required" in section


def test_readme_states_the_uv_version_ci_installs() -> None:
    version = re.search(r'(?m)^\s*version: "([\d.]+)"', _text(CI_WORKFLOW))

    assert version
    assert version.group(1) in _text(README).split("### Continuous integration")[-1]


def test_readme_names_the_variable_that_holds_the_expected_test_count() -> None:
    # Contributors are told to update it in the commit that changes the suite.
    variable = re.search(r'(?m)^\s*([A-Z_]+):\s*"\d+"', _text(CI_WORKFLOW))
    section = _text(README).split("### Continuous integration", 1)[-1]

    assert variable
    assert f"`{variable.group(1)}`" in section
