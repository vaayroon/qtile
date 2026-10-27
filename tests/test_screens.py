"""Screen generation over the REAL ``src/modules/screens.py``.

The module is loaded from disk under a throwaway package (bypassing
``modules/__init__``) with only its sibling ``widgets`` module stubbed, so the
tests never import the real widget stack. ``effective_monitor_count`` is patched
where ``screens`` looks it up.
"""

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("libqtile.config")

from libqtile import widget  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src"
PACKAGE = "_screens_pkg"


def _factory(name: str):
    return lambda: [widget.TextBox(name)]


@pytest.fixture
def screens_module(monkeypatch):
    monkeypatch.syspath_prepend(str(SRC))

    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(SRC / "modules")]
    stub = types.ModuleType(f"{PACKAGE}.widgets")
    stub.init_widgets_screen1 = _factory("screen1")
    stub.init_widgets_screen2 = _factory("screen2")
    stub.init_widgets_screen3 = _factory("screen3")
    monkeypatch.setitem(sys.modules, PACKAGE, package)
    monkeypatch.setitem(sys.modules, f"{PACKAGE}.widgets", stub)

    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.screens", SRC / "modules" / "screens.py"
    )
    module = importlib.util.module_from_spec(spec)
    before = set(sys.modules)
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        for name in set(sys.modules) - before:
            if name == "utils" or name.startswith("utils."):
                del sys.modules[name]


def _bar_labels(screens) -> list[str]:
    return [screen.top.widgets[0].text for screen in screens]


def _output(port: str, *, connected: bool = True):
    return SimpleNamespace(
        port=port, make="make", model="model", serial="1", connected=connected
    )


def test_backend_outputs_are_used_without_fallback(screens_module, monkeypatch):
    fallback = MagicMock(return_value=(3, "mock"))
    monkeypatch.setattr(screens_module, "effective_monitor_count", fallback)

    screens = screens_module.generate_screens_module(
        [_output("DP-0"), _output("HDMI-0")]
    )

    assert _bar_labels(screens) == ["screen1", "screen2"]
    fallback.assert_not_called()


def test_disconnected_backend_outputs_are_not_counted(screens_module, monkeypatch):
    monkeypatch.setattr(
        screens_module, "effective_monitor_count", MagicMock(return_value=(3, "mock"))
    )

    screens = screens_module.generate_screens_module(
        [_output("DP-0"), _output("HDMI-0"), _output("DP-2", connected=False)]
    )

    assert len(screens) == 2


@pytest.mark.parametrize("count", [1, 2, 3])
def test_fallback_count_builds_that_many_screens(screens_module, monkeypatch, count):
    monkeypatch.setattr(
        screens_module,
        "effective_monitor_count",
        MagicMock(return_value=(count, "mock")),
    )

    screens = screens_module.generate_screens_module([])

    assert _bar_labels(screens) == ["screen1", "screen2", "screen3"][:count]


def test_zero_fallback_count_builds_exactly_one_screen(screens_module, monkeypatch):
    monkeypatch.setattr(
        screens_module,
        "effective_monitor_count",
        MagicMock(return_value=(0, "xrandr --props")),
    )

    screens = screens_module.generate_screens_module([])

    assert _bar_labels(screens) == ["screen1"]


def test_extra_screens_reuse_the_screen3_widgets(screens_module, monkeypatch):
    monkeypatch.setattr(
        screens_module, "effective_monitor_count", MagicMock(return_value=(5, "mock"))
    )

    screens = screens_module.generate_screens_module([])

    assert _bar_labels(screens) == [
        "screen1",
        "screen2",
        "screen3",
        "screen3",
        "screen3",
    ]


def test_fallback_never_shells_out_to_xrandr_itself(screens_module, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("screens.py must not call xrandr directly")

    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(
        screens_module, "effective_monitor_count", MagicMock(return_value=(0, "mock"))
    )

    assert len(screens_module.generate_screens_module([])) == 1
