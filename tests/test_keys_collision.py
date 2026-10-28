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
def load_keys(monkeypatch):
    """Load keys.py and return its `init_keys`. With `registry`, the module
    sees that list instead of the shipped scratchpad registry."""
    monkeypatch.syspath_prepend(str(SRC))
    stub = types.ModuleType("settings")
    stub.mod = "mod4"
    stub.myTerm = "x"
    monkeypatch.setitem(sys.modules, "settings", stub)
    before = set(sys.modules)

    def load(registry=None):
        if registry is not None:
            scratchpads = importlib.import_module("utils.scratchpads")
            monkeypatch.setattr(scratchpads, "load_scratchpads", lambda: registry)
        spec = importlib.util.spec_from_file_location(
            "_keys_under_test", SRC / "modules" / "keys.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.init_keys

    try:
        yield load
    finally:
        for name in set(sys.modules) - before:
            if name == "utils" or name.startswith("utils."):
                del sys.modules[name]


@pytest.fixture
def init_keys(load_keys):
    return load_keys()


def _combo(key):
    return (frozenset(key.modifiers), str(key.key))


def _dropdown_targets(keys):
    """`{combo: dropdown name}` for every top-level dropdown_toggle key."""
    targets = {}
    for key in keys:
        for command in getattr(key, "commands", []):
            if command.name == "dropdown_toggle":
                targets[_combo(key)] = command.args[0]
    return targets


TERM_COMBO = (frozenset({"mod4"}), "masculine")
CALC_COMBO = (frozenset(), "XF86Calculator")


def test_shipped_registry_binds_the_term_and_calc_keys(init_keys):
    targets = _dropdown_targets(init_keys())
    assert targets == {TERM_COMBO: "term", CALC_COMBO: "calc"}


def test_keys_for_missing_entries_are_skipped_with_a_warning(load_keys, caplog):
    # A local override that disabled `term` and renamed `calc`.
    from utils.scratchpads import ScratchpadApp

    registry = [
        ScratchpadApp(name="files", command="nautilus", key="n"),
        ScratchpadApp(name="calculator", command="galculator", key="c"),
    ]
    keys = load_keys(registry)()

    assert _dropdown_targets(keys) == {}
    combos = {_combo(k) for k in keys}
    assert TERM_COMBO not in combos
    assert CALC_COMBO not in combos
    # The rest of the config, including the registry-driven chord, survives.
    assert (frozenset({"mod4"}), "s") in combos
    assert any("mod4+masculine" in m and "'term'" in m for m in caplog.messages)
    assert any("XF86Calculator" in m and "'calc'" in m for m in caplog.messages)


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
