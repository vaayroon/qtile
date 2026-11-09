"""The README "Keybindings" tables must match ``tools/generate_keybindings.py``.

The tool runs as a headless subprocess (no ``DISPLAY``, no ``QTILE_*``
monitor variables, a throwaway ``HOME``), like ``test_config_import``: it
imports the config's modules, which would otherwise pollute this process.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("libqtile.config")

ROOT = Path(__file__).resolve().parent.parent
TOOL = Path("tools") / "generate_keybindings.py"

LOCAL_ENTRY = """\
[[scratchpad]]
name = "localonly"
command = "xterm"
key = "z"
"""


def _env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    for name in (
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "QTILE_PRIMARY_MONITOR",
        "QTILE_INTERNAL_OUTPUTS",
        "QTILE_SCREEN_SERIAL_ORDER",
        "QTILE_SCREEN_PORT_ORDER",
    ):
        env.pop(name, None)
    return env


def _run(repo: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / TOOL), *args],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of the parts of the repo the tool reads."""
    repo = tmp_path / "repo"
    shutil.copytree(
        ROOT / "src", repo / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    (repo / "tools").mkdir()
    shutil.copy(ROOT / TOOL, repo / TOOL)
    shutil.copy(ROOT / "scratchpads.toml", repo / "scratchpads.toml")
    shutil.copy(ROOT / "README.md", repo / "README.md")
    return repo


def test_readme_keybindings_are_up_to_date(tmp_path: Path) -> None:
    result = _run(ROOT, tmp_path, "--check")

    assert result.returncode == 0, result.stdout + result.stderr


def test_stale_readme_fails_check_and_write_fixes_it(
    repo: Path, tmp_path: Path
) -> None:
    readme = repo / "README.md"
    stale = readme.read_text().replace("| Reload Qtile |", "| Reload |")
    readme.write_text(stale)

    check = _run(repo, tmp_path, "--check")
    assert check.returncode == 1
    assert "out of date" in check.stderr
    assert readme.read_text() == stale

    assert _run(repo, tmp_path).returncode == 0
    assert "| Reload Qtile |" in readme.read_text()
    assert _run(repo, tmp_path, "--check").returncode == 0


def test_missing_markers_exit_2(repo: Path, tmp_path: Path) -> None:
    readme = repo / "README.md"
    readme.write_text("# No markers\n")

    result = _run(repo, tmp_path)

    assert result.returncode == 2
    assert "markers not found" in result.stderr
    assert readme.read_text() == "# No markers\n"


def test_local_scratchpad_overrides_stay_out_of_the_readme(
    repo: Path, tmp_path: Path
) -> None:
    (repo / "scratchpads.local.toml").write_text(LOCAL_ENTRY)

    result = _run(repo, tmp_path, "--check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "localonly" not in (repo / "README.md").read_text()
