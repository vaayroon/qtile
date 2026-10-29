"""End-to-end tests for ``tools/generate_scratchpad_desktops.py``.

The tool runs as a subprocess against a copy of the repo layout in a temp
dir, so the developer's own ``scratchpads.local.toml`` never leaks in.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = Path("tools") / "generate_scratchpad_desktops.py"

REGISTRY = """\
[[scratchpad]]
name = "term"
command = "kitty"
label = "My Terminal"

[[scratchpad]]
name = "files"
command = "nautilus"
desktop_entry = false
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(
        ROOT / "src" / "utils",
        repo / "src" / "utils",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (repo / "tools").mkdir()
    shutil.copy(ROOT / TOOL, repo / TOOL)
    (repo / "scratchpads.toml").write_text(REGISTRY)
    return repo


def _run(repo: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / TOOL), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_writes_launchers_for_the_registry_into_the_target(
    repo: Path, tmp_path: Path
) -> None:
    target = tmp_path / "out"

    result = _run(repo, str(target), env={"HOME": str(tmp_path / "home")})

    assert result.returncode == 0, result.stderr
    assert [p.name for p in target.iterdir()] == ["qtile-scratchpad-term.desktop"]
    text = (target / "qtile-scratchpad-term.desktop").read_text()
    toggle = repo / "src" / "assets" / "scratchpad" / "scratchpad-toggle.sh"
    assert f'Exec="{toggle}" term' in text.splitlines()
    assert "Name=My Terminal" in text.splitlines()
    assert "written: qtile-scratchpad-term.desktop" in result.stdout


def test_default_target_follows_xdg_data_home(repo: Path, tmp_path: Path) -> None:
    data_home = tmp_path / "data"

    result = _run(
        repo, env={"HOME": str(tmp_path / "home"), "XDG_DATA_HOME": str(data_home)}
    )

    assert result.returncode == 0, result.stderr
    assert (data_home / "applications" / "qtile-scratchpad-term.desktop").is_file()


@pytest.mark.parametrize(("args", "dropdown"), [([], "term"), (["calc"], "calc")])
def test_toggle_script_toggles_the_named_dropdown(
    tmp_path: Path, args: list[str], dropdown: str
) -> None:
    # The launchers call `scratchpad-toggle.sh <name>`; a legacy launcher
    # passes no name and must still toggle `term`.
    assets = tmp_path / "src" / "assets" / "scratchpad"
    assets.mkdir(parents=True)
    script = assets / "scratchpad-toggle.sh"
    shutil.copy(ROOT / "src" / "assets" / "scratchpad" / "scratchpad-toggle.sh", script)
    fake_qtile = tmp_path / ".venv" / "bin" / "qtile"
    fake_qtile.parent.mkdir(parents=True)
    fake_qtile.write_text('#!/bin/bash\nprintf "%s\\n" "$*"\n')
    fake_qtile.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(script), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        f"cmd-obj -o group scratchpad -f dropdown_toggle -a {dropdown}\n"
    )
