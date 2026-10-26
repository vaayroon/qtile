"""Contract tests for the uv-managed dependency declaration in ``pyproject.toml``.

The project is a virtual uv project: ``pyproject.toml`` declares the
dependencies, ``uv.lock`` pins them, and ``uv sync --locked`` converges ``.venv``.
These tests pin the declarations that tie everything together, so a Qtile bump
cannot be done halfway (pin, project version, README banner and installed
package must all agree).
"""

import importlib.metadata
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"
QTILE_PIN = re.compile(r"^qtile==(\d+(?:\.\d+)*)$")


def _load() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _name(requirement: str) -> str:
    """Return the normalized distribution name of a PEP 508 requirement."""
    base = re.split(r"[<>=!~\[;\s]", requirement, maxsplit=1)[0]
    return base.lower().replace("_", "-")


def _qtile_pin() -> str:
    """Return the exact Qtile version pinned in ``project.dependencies``."""
    for dep in _load()["project"]["dependencies"]:
        match = QTILE_PIN.match(dep)
        if match:
            return match.group(1)
    pytest.fail("qtile must be pinned exactly (qtile==X.Y.Z) in project.dependencies")


# --- Declaration shape ---------------------------------------------------------


def test_no_build_system() -> None:
    assert "build-system" not in _load()


def test_no_optional_dependencies() -> None:
    assert "optional-dependencies" not in _load()["project"]


def test_uv_project_is_virtual() -> None:
    assert _load()["tool"]["uv"]["package"] is False


def test_uv_uses_distro_python() -> None:
    assert _load()["tool"]["uv"]["python-preference"] == "only-system"


def test_requires_python_floor() -> None:
    assert _load()["project"]["requires-python"] == ">=3.12"


def test_runtime_dependencies_are_the_expected_set() -> None:
    names = {_name(d) for d in _load()["project"]["dependencies"]}
    assert names == {
        "qtile",
        "cairocffi",
        "xcffib",
        "aiohttp",
        "psutil",
        "dbus-fast",
        "python-dotenv",
    }


# --- Dev group -----------------------------------------------------------------


def test_dev_group_has_the_dev_tools() -> None:
    names = {_name(d) for d in _load()["dependency-groups"]["dev"]}
    assert {"ruff", "mypy", "pytest", "pytest-asyncio"} <= names


def test_dev_group_has_no_pip_tools() -> None:
    names = {_name(d) for d in _load()["dependency-groups"]["dev"]}
    assert "pip-tools" not in names


def test_name_normalization_handles_extras_and_markers() -> None:
    # Guards the helper used above: a broken parser would make the checks lie.
    assert _name("Pytest_Asyncio>=1.0") == "pytest-asyncio"
    assert _name("pip-tools; python_version >= '3.12'") == "pip-tools"
    assert _name("qtile[widgets]==0.37.1") == "qtile"


# --- Qtile version stays consistent everywhere ----------------------------------


def test_qtile_is_pinned_exactly() -> None:
    deps = _load()["project"]["dependencies"]
    assert [d for d in deps if _name(d) == "qtile"] == [f"qtile=={_qtile_pin()}"]


def test_project_version_mirrors_the_qtile_pin() -> None:
    assert _load()["project"]["version"] == _qtile_pin()


def test_installed_qtile_matches_the_pin() -> None:
    assert importlib.metadata.version("qtile") == _qtile_pin()


def test_readme_banner_states_the_qtile_version() -> None:
    assert f"Qtile {_qtile_pin()}" in README.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "legacy", ["requirements.txt", "requirements-dev.txt", "outdated.txt"]
)
def test_legacy_pip_tools_files_are_gone(legacy: str) -> None:
    assert (ROOT / "uv.lock").is_file()  # the lock replaces them
    assert not (ROOT / legacy).exists()
