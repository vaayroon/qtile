"""Collision test over the REAL ``src/modules/keys.py``.

Nothing is hand-maintained: the module is loaded from disk (bypassing
``modules/__init__``) with only ``settings`` stubbed, so a new top-level
binding that clashes with another one fails loudly.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("libqtile.config")

SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.fixture
def init_keys(monkeypatch):
    monkeypatch.syspath_prepend(str(SRC))
    stub = types.ModuleType("settings")
    stub.mod = "mod4"
    stub.myTerm = "x"
    monkeypatch.setitem(sys.modules, "settings", stub)
    spec = importlib.util.spec_from_file_location(
        "_keys_under_test", SRC / "modules" / "keys.py"
    )
    module = importlib.util.module_from_spec(spec)
    before = set(sys.modules)
    try:
        spec.loader.exec_module(module)
        yield module.init_keys
    finally:
        for name in set(sys.modules) - before:
            if name == "utils" or name.startswith("utils."):
                del sys.modules[name]


def _combo(key):
    return (frozenset(key.modifiers), str(key.key))


def test_top_level_bindings_are_unique(init_keys):
    combos = [_combo(k) for k in init_keys()]
    dupes = {c for c in combos if combos.count(c) > 1}
    assert not dupes


@pytest.mark.parametrize(("key_name", "direction"), [("h", "shrink"), ("l", "grow")])
def test_scratchpad_size_bindings_exist_once(init_keys, key_name, direction):
    combo = (frozenset({"mod4", "control"}), key_name)
    matches = [k for k in init_keys() if _combo(k) == combo]
    assert len(matches) == 1
    (binding,) = matches
    (command,) = binding.commands
    assert command.name == "function"
    # LazyCall args: (function, direction, registry provider)
    assert command.args[1] == direction
