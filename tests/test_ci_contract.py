"""Contract tests tying the CI workflow to the rest of the repository.

These read the workflow as text (no YAML library is a project dependency) and
only check what would otherwise break silently: a missing ``--locked`` that
re-locks behind our back, an action pinned to a movable tag, a renamed job that
branch protection no longer matches, a CI interpreter that drifts from
``.python-version``. They deliberately do not restate every workflow value.
"""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
HOOKS = ROOT / ".pre-commit-config.yaml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
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


# --- Local hooks use the same locked tools as CI ---------------------------------


def _hooks(text: str) -> dict[str, str]:
    """Return the text of every hook, keyed by its ``id``."""
    ids = re.findall(r"(?m)^      - id: (\S+)", text)
    chunks = re.split(r"(?m)^(?=      - id: )", text)[1:]
    return dict(zip(ids, chunks, strict=True))


def _pre_commit_floor() -> str:
    """Return ``X`` of the ``pre-commit>=X`` requirement of the dev group."""
    with PYPROJECT.open("rb") as fh:
        dev = tomllib.load(fh)["dependency-groups"]["dev"]
    floors = [
        m.group(1) for d in dev if (m := re.fullmatch(r"pre-commit>=([\d.]+)", d))
    ]
    assert len(floors) == 1, "pin pre-commit as 'pre-commit>=X' in the dev group"
    return floors[0]


def test_hook_scan_splits_hooks_by_id() -> None:
    text = (
        "repos:\n  - repo: local\n    hooks:\n"
        "      - id: a\n        x: 1\n      - id: b\n"
    )

    assert _hooks(text) == {
        "a": "      - id: a\n        x: 1\n",
        "b": "      - id: b\n",
    }


def test_hooks_are_all_local_and_unsupported_language() -> None:
    text = _text(HOOKS)
    hooks = _hooks(text)

    assert re.findall(r"(?m)^\s*-?\s*repo:\s*(\S+)", text) == ["local"]
    assert hooks, "no hooks found"
    # `unsupported` runs the entry from the active environment, so every tool
    # comes from uv.lock and there is no second set of pinned versions.
    assert all("language: unsupported" in hook for hook in hooks.values())


def test_hooks_never_run_uv_unlocked() -> None:
    assert _unlocked_uv_commands(_text(HOOKS)) == []


def test_hooks_minimum_version_is_the_pre_commit_floor_of_the_dev_group() -> None:
    # `language: unsupported` needs pre-commit >= 4.4.0 in the lock too.
    declared = re.search(r'(?m)^minimum_pre_commit_version:\s*"([\d.]+)"', _text(HOOKS))

    assert declared and declared.group(1) == _pre_commit_floor()


def test_both_hook_types_are_installed_by_pre_commit_install() -> None:
    assert re.search(
        r"(?m)^default_install_hook_types:\s*\[pre-commit, pre-push\]$", _text(HOOKS)
    )


def test_only_mypy_runs_on_pre_push() -> None:
    text = _text(HOOKS)
    on_push = [i for i, hook in _hooks(text).items() if "pre-push" in hook]

    assert re.search(r"(?m)^default_stages:\s*\[pre-commit\]$", text)
    assert on_push == ["mypy"]
    assert "stages: [pre-push]" in _hooks(text)["mypy"]


def test_the_lock_hook_only_runs_when_the_lock_inputs_change() -> None:
    hook = _hooks(_text(HOOKS))["uv-lock-check"]
    files = re.search(r"(?m)^\s*files:\s*(\S+)$", hook)

    assert "entry: uv lock --check" in hook
    assert "pass_filenames: false" in hook
    assert files
    pattern = re.compile(files.group(1))
    assert pattern.search("pyproject.toml") and pattern.search("uv.lock")
    assert not pattern.search("src/pyproject.toml")
    assert not pattern.search("pyproject.toml.bak")
    assert not pattern.search("src/config.py")


def test_there_is_no_pytest_hook() -> None:
    # The suite runs in CI and on demand; a hook would slow every commit down.
    assert "pytest" not in _text(HOOKS)


# --- Dependabot keeps the lock and the action pins fresh --------------------------


def _ecosystems(text: str) -> dict[str, str]:
    """Return the text of every ``updates`` entry, keyed by its ecosystem."""
    ids = re.findall(r'(?m)^  - package-ecosystem: "([\w-]+)"', text)
    chunks = re.split(r"(?m)^(?=  - package-ecosystem: )", text)[1:]
    return dict(zip(ids, chunks, strict=True))


def test_ecosystem_scan_splits_updates_by_ecosystem() -> None:
    text = 'version: 2\nupdates:\n  - package-ecosystem: "uv"\n    x: 1\n'
    text += '  - package-ecosystem: "github-actions"\n'

    assert _ecosystems(text) == {
        "uv": '  - package-ecosystem: "uv"\n    x: 1\n',
        "github-actions": '  - package-ecosystem: "github-actions"\n',
    }


def test_dependabot_watches_the_lock_and_the_actions() -> None:
    assert list(_ecosystems(_text(DEPENDABOT))) == ["uv", "github-actions"]


def test_every_ecosystem_is_weekly_grouped_and_has_a_cooldown() -> None:
    ecosystems = _ecosystems(_text(DEPENDABOT))

    assert ecosystems
    for name, entry in ecosystems.items():
        assert 'directory: "/"' in entry, name
        assert 'interval: "weekly"' in entry, name
        assert "    groups:" in entry, name
        assert "    cooldown:" in entry, name


def test_dependabot_leaves_the_qtile_pin_to_manual_bumps() -> None:
    # qtile is pinned exactly and bumped by hand with the version and banner.
    uv = _ecosystems(_text(DEPENDABOT))["uv"]

    assert re.search(r'(?m)^    ignore:\n      - dependency-name: "qtile"', uv)


def test_dependabot_uses_options_each_ecosystem_supports() -> None:
    uv = _ecosystems(_text(DEPENDABOT))["uv"]
    actions = _ecosystems(_text(DEPENDABOT))["github-actions"]

    assert "dependency-type" not in uv  # groups by dependency-type: not for uv
    assert "semver-" not in actions  # cooldown: only default-days for actions


def test_dependabot_commit_prefixes_fit_the_50_character_limit() -> None:
    prefixes = re.findall(r'(?m)^\s*prefix: "([^"]+)"', _text(DEPENDABOT))

    assert len(prefixes) == 2
    assert all(len(prefix) <= 50 for prefix in prefixes)
