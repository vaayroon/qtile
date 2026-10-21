"""Tests for the startup hook glue in ``src/modules/hooks.py``.

The AST tests need nothing from Qtile. The glue tests load the REAL module from
disk (bypassing ``modules/__init__``), which needs ``libqtile``, and unsubscribe
the hook again afterwards so the global hook registry stays clean.
"""

import ast
import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
GLUE_FILES = [
    SRC / "modules" / "hooks.py",
    SRC / "modules" / "__init__.py",
    SRC / "config.py",
]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _import_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("path", GLUE_FILES, ids=lambda p: p.name)
def test_init_hooks_is_gone(path: Path) -> None:
    assert "init_hooks" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", GLUE_FILES, ids=lambda p: p.name)
def test_config_load_path_never_imports_subprocess(path: Path) -> None:
    assert "subprocess" not in _import_roots(_tree(path))


def test_modules_package_imports_hooks_module() -> None:
    """Without this import the ``startup_once`` hook would never be subscribed."""
    imports = [
        node
        for node in _tree(SRC / "modules" / "__init__.py").body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module is None
        and any(alias.name == "hooks" for alias in node.names)
    ]
    assert len(imports) == 1


# --- glue, loaded from disk --------------------------------------------------


@pytest.fixture
def subprocess_calls(monkeypatch) -> list[list[str]]:
    """Records (and refuses) any process started while the glue is loaded.

    ``run``, ``call`` and ``check_*`` all go through ``Popen``.
    """
    calls: list[list[str]] = []

    class RefusingPopen(subprocess.Popen):  # keeps `Popen[bytes]` annotations valid
        def __init__(self, args, *_args, **_kwargs) -> None:
            calls.append(list(args))
            raise AssertionError(f"no process may start: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", RefusingPopen)
    return calls


@pytest.fixture
def hooks_module(monkeypatch, request):
    request.getfixturevalue("subprocess_calls")  # refuse processes during load
    hook = pytest.importorskip("libqtile.hook")
    monkeypatch.syspath_prepend(str(SRC))
    spec = importlib.util.spec_from_file_location(
        "_hooks_under_test", SRC / "modules" / "hooks.py"
    )
    module = importlib.util.module_from_spec(spec)
    before = set(sys.modules)
    try:
        spec.loader.exec_module(module)
        try:
            yield module
        finally:
            hook.unsubscribe.startup_once(module.start_once)
    finally:
        for name in set(sys.modules) - before:
            if name == "utils" or name.startswith("utils."):
                del sys.modules[name]


@pytest.fixture
def steps(hooks_module, monkeypatch) -> list[str]:
    """Replaces the three startup steps with recorders; returns the call log."""
    ran: list[str] = []

    def layout() -> tuple[bool, str]:
        ran.append("layout")
        return True, "test"

    def background() -> bool:
        ran.append("background")
        return True

    def autostart() -> bool:
        ran.append("autostart")
        return True

    monkeypatch.setattr(hooks_module, "apply_best_effort_layout", layout)
    monkeypatch.setattr(hooks_module, "set_root_background", background)
    monkeypatch.setattr(hooks_module, "run_autostart", autostart)
    return ran


def test_loading_the_glue_runs_no_subprocess(hooks_module, subprocess_calls) -> None:
    assert callable(hooks_module.start_once)
    assert subprocess_calls == []


def test_start_once_is_subscribed_to_startup_once(hooks_module) -> None:
    from libqtile import hook

    assert hooks_module.start_once in hook.subscriptions["qtile"]["startup_once"]


def test_start_once_runs_steps_in_order(hooks_module, steps) -> None:
    hooks_module.start_once()
    assert steps == ["layout", "background", "autostart"]


@pytest.mark.parametrize("failing", ["layout", "background", "autostart"])
def test_start_once_isolates_a_raising_step(
    hooks_module, steps, monkeypatch, caplog, failing
) -> None:
    attr = {
        "layout": "apply_best_effort_layout",
        "background": "set_root_background",
        "autostart": "run_autostart",
    }[failing]

    def explode():
        steps.append(failing)
        raise RuntimeError(f"{failing} exploded")

    monkeypatch.setattr(hooks_module, attr, explode)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        hooks_module.start_once()
    assert steps == ["layout", "background", "autostart"]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert errors[0].exc_info[0] is RuntimeError
