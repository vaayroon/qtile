"""Contract tests for the uv-managed dependency declaration.

The project is a virtual uv project: ``pyproject.toml`` declares the
dependencies, ``uv.lock`` pins them and ``uv sync --locked`` converges ``.venv``.
These tests only check what ties the files together, so a Qtile bump cannot be
done halfway: the pin, the project version, the lock, the README banner and the
interpreter policy must all agree. They deliberately do not restate individual
``pyproject.toml`` values.
"""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
LOCK = ROOT / "uv.lock"
README = ROOT / "README.md"
PYTHON_VERSION = ROOT / ".python-version"
INSTALL_SH = ROOT / "install.sh"
QTILE_PIN = re.compile(r"^qtile==(\d+(?:\.\d+)*)$")


def _load() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _name(requirement: str) -> str:
    """Return the normalized distribution name of a PEP 508 requirement."""
    base = re.split(r"[<>=!~\[;\s]", requirement, maxsplit=1)[0]
    return base.lower().replace("_", "-")


def _lock_packages() -> dict[str, dict]:
    """Return the ``[[package]]`` tables of ``uv.lock`` keyed by name."""
    with LOCK.open("rb") as fh:
        return {pkg["name"]: pkg for pkg in tomllib.load(fh)["package"]}


def _lock_names(entries: list[dict]) -> set[str]:
    return {entry["name"] for entry in entries}


def _qtile_pin() -> str:
    """Return the exact Qtile version pinned in ``project.dependencies``."""
    for dep in _load()["project"]["dependencies"]:
        match = QTILE_PIN.match(dep)
        if match:
            return match.group(1)
    pytest.fail("qtile must be pinned exactly (qtile==X.Y.Z) in project.dependencies")


# --- The helpers must not lie --------------------------------------------------


def test_name_normalization_handles_extras_and_markers() -> None:
    assert _name("Pytest_Asyncio>=1.0") == "pytest-asyncio"
    assert _name("pip-tools; python_version >= '3.12'") == "pip-tools"
    assert _name("qtile[widgets]==0.37.1") == "qtile"


# --- Qtile version stays consistent everywhere ----------------------------------


def test_qtile_is_pinned_exactly() -> None:
    deps = _load()["project"]["dependencies"]
    assert [d for d in deps if _name(d) == "qtile"] == [f"qtile=={_qtile_pin()}"]


def test_project_version_mirrors_the_qtile_pin() -> None:
    assert _load()["project"]["version"] == _qtile_pin()


def test_readme_banner_states_the_qtile_version() -> None:
    assert f"Qtile {_qtile_pin()}" in README.read_text(encoding="utf-8")


# --- uv.lock agrees with pyproject.toml ------------------------------------------


def test_lock_pins_the_qtile_version_of_pyproject() -> None:
    assert _lock_packages()["qtile"]["version"] == _qtile_pin()


def test_lock_project_entry_mirrors_the_project_version() -> None:
    project = _lock_packages()["qtile-config"]
    assert project["version"] == _load()["project"]["version"] == _qtile_pin()


def test_lock_records_the_exact_qtile_requirement() -> None:
    requires = _lock_packages()["qtile-config"]["metadata"]["requires-dist"]
    qtile = [r for r in requires if r["name"] == "qtile"]
    assert qtile == [{"name": "qtile", "specifier": f"=={_qtile_pin()}"}]


def test_lock_project_is_virtual() -> None:
    # A virtual project is never built or installed, only its dependencies are.
    assert _lock_packages()["qtile-config"]["source"] == {"virtual": "."}


def test_lock_runtime_dependencies_match_pyproject() -> None:
    declared = {_name(d) for d in _load()["project"]["dependencies"]}
    locked = _lock_names(_lock_packages()["qtile-config"]["dependencies"])
    assert declared and locked == declared


def test_lock_dev_group_matches_pyproject() -> None:
    declared = {_name(d) for d in _load()["dependency-groups"]["dev"]}
    locked_group = _lock_packages()["qtile-config"]["dev-dependencies"]
    assert declared and set(locked_group) == {"dev"}
    assert _lock_names(locked_group["dev"]) == declared


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_uv_agrees_the_lock_is_current() -> None:
    # The same check as `uv lock --check`, done offline by the real uv.
    result = subprocess.run(
        ["uv", "lock", "--check", "--offline", "--project", str(ROOT)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --- Python interpreter policy ----------------------------------------------------


def _python_floor() -> tuple[int, int]:
    match = re.fullmatch(r">=(\d+)\.(\d+)", _load()["project"]["requires-python"])
    assert match, "requires-python must be a plain '>=X.Y' floor"
    return int(match.group(1)), int(match.group(2))


def test_python_version_file_meets_the_requires_python_floor() -> None:
    major, minor = PYTHON_VERSION.read_text().strip().split(".")[:2]
    assert (int(major), int(minor)) >= _python_floor()


def test_install_sh_defaults_to_the_distro_interpreter_of_python_version() -> None:
    # pyproject says "only system Pythons"; install.sh names the exact one,
    # because only-system alone still accepts Homebrew/pyenv Pythons on PATH.
    pinned = PYTHON_VERSION.read_text().strip()
    assert _load()["tool"]["uv"]["python-preference"] == "only-system"
    assert f'DEFAULT_PYTHON="/usr/bin/python{pinned}"' in INSTALL_SH.read_text()


# --- Legacy pip-tools workflow is gone --------------------------------------------


@pytest.mark.parametrize(
    "legacy", ["requirements.txt", "requirements-dev.txt", "outdated.txt"]
)
def test_legacy_pip_tools_files_are_gone(legacy: str) -> None:
    assert LOCK.is_file()  # the lock replaces them
    assert not (ROOT / legacy).exists()
