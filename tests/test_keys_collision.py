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

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


@pytest.fixture
def load_keys(monkeypatch):
    """Load keys.py and return its `init_keys`. With `registry`, the module
    sees that list instead of the shipped scratchpad registry."""
    monkeypatch.syspath_prepend(str(SRC))
    stub = types.ModuleType("settings")
    stub.mod = "mod4"
    monkeypatch.setitem(sys.modules, "settings", stub)
    before = set(sys.modules)

    def load(registry=None, launchers=None):
        if registry is not None:
            scratchpads = importlib.import_module("utils.scratchpads")
            monkeypatch.setattr(scratchpads, "load_scratchpads", lambda: registry)
        # Shipped launchers.toml only, unless a test passes its own provider,
        # so a developer's launchers.local.toml never changes the result.
        launcher_module = importlib.import_module("utils.launchers")
        if launchers is None:
            shipped = ROOT / "launchers.toml"

            def launchers(mod):
                return launcher_module.load_launchers_from(shipped, None, mod=mod)

        monkeypatch.setattr(launcher_module, "load_launchers", launchers)
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


@pytest.fixture
def keys_module(load_keys):
    # The module is loaded unregistered, so reach it through its globals.
    return types.SimpleNamespace(**load_keys().__globals__)


def test_cheatsheet_sections_cover_every_binding_once(keys_module):
    sectioned = [
        b for _, bindings in keys_module.cheatsheet_sections() for b in bindings
    ]
    # Same objects, same count: nothing bound is missing from the cheat sheet
    # and nothing appears twice.
    assert sorted(map(id, sectioned)) == sorted(map(id, keys_module.init_keys()))


def test_scratchpad_chord_is_listed_under_the_scratchpad_section(keys_module):
    sections = dict(keys_module.cheatsheet_sections())
    chords = [
        b
        for b in sections[keys_module.SCRATCHPADS_SECTION]
        if hasattr(b, "submappings")
    ]
    assert [(c.modifiers, c.key) for c in chords] == [(["mod4"], "s")]


# ---------------------------------------------------------------------------
# Launcher registry
# ---------------------------------------------------------------------------


def _spawned(key):
    (command,) = key.commands
    assert command.name == "spawn"
    return command.args[0]


def _shipped_launchers():
    import tomllib

    with (ROOT / "launchers.toml").open("rb") as handle:
        return tomllib.load(handle)["launcher"]


def test_every_shipped_launcher_is_bound(keys_module):
    from utils.launchers import parse_combo

    bound = {_combo(k): k for k in keys_module.init_keys()}
    entries = _shipped_launchers()
    assert entries
    for entry in entries:
        for text in entry["keys"]:
            combo = parse_combo(text, "mod4")
            assert combo is not None, text
            key = bound[combo.identity]
            assert _spawned(key) == entry["command"]
            assert key.desc == entry["desc"]


def test_core_launchers_stay_hard_coded(keys_module):
    core = keys_module.key_sections[keys_module.LAUNCHERS_SECTION]
    assert {_combo(k): _spawned(k) for k in core} == {
        (frozenset({"mod4"}), "Return"): "kitty",
        (frozenset({"mod4", "shift"}), "Return"): "dmenu_run -p 'Run: '",
        (frozenset(), "Menu"): "rofi -show drun",
        (frozenset(), "XF86Favorites"): "rofi -show drun",
        (frozenset(), "XF86HomePage"): "rofi -show drun",
    }


def test_registry_launchers_are_listed_under_the_launchers_section(keys_module):
    sections = dict(keys_module.cheatsheet_sections())
    listed = {_combo(k) for k in sections[keys_module.LAUNCHERS_SECTION]}
    assert (frozenset({"mod4", "mod1"}), "e") in listed


def test_launchers_cannot_take_hard_coded_keys_or_the_chord_leader(load_keys, caplog):
    from utils.launchers import LauncherApp, parse_combo

    def app(name, *combos):
        parsed = tuple(parse_combo(c, "mod4") for c in combos)
        return LauncherApp(name=name, command=name, combos=parsed, desc=name)

    apps = [
        app("terminal", "mod+Return"),
        app("leader", "mod+s"),
        app("group", "mod+1"),
        app("both", "mod+Return", "mod+alt+F12"),
    ]
    keys = load_keys(launchers=lambda _mod: apps)()

    by_combo = {_combo(k): k for k in keys}
    assert _spawned(by_combo[(frozenset({"mod4"}), "Return")]) == "kitty"
    assert _spawned(by_combo[(frozenset({"mod4", "mod1"}), "F12")]) == "both"
    # The leader stays the scratchpad chord.
    assert hasattr(by_combo[(frozenset({"mod4"}), "s")], "submappings")
    spawned = {
        _spawned(k)
        for k in keys
        if getattr(k, "commands", None) and k.commands[0].name == "spawn"
    }
    assert not {"terminal", "leader"} & spawned
    assert any(
        "mod4+s for entry 'leader' is already bound" in m for m in caplog.messages
    )


def test_a_failing_registry_keeps_the_rest_of_the_keys(load_keys, caplog):
    def boom(_mod):
        raise RuntimeError("boom")

    keys = load_keys(launchers=boom)()

    combos = {_combo(k) for k in keys}
    assert (frozenset({"mod4"}), "Return") in combos
    assert (frozenset({"mod4", "mod1"}), "e") not in combos
    assert any("failed to build the launcher keys" in m for m in caplog.messages)


def test_groups_section_starts_empty_for_modules_groups_to_fill(keys_module):
    assert keys_module.key_sections[keys_module.GROUPS_SECTION] == []


class _FakeQtile:
    def __init__(self):
        self.spawned = []

    def spawn(self, command):
        self.spawned.append(command)


def test_mod_f1_opens_the_cheat_sheet(init_keys):
    (binding,) = [k for k in init_keys() if _combo(k) == (frozenset({"mod4"}), "F1")]
    (command,) = binding.commands
    assert command.name == "function"
    assert command.args[0].__name__ == "show_cheatsheet"


def test_show_cheatsheet_writes_every_row_and_spawns_rofi(
    keys_module, monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    qtile = _FakeQtile()

    keys_module.show_cheatsheet(qtile)

    path = tmp_path / "run" / "qtile-keybindings.txt"
    lines = path.read_text().splitlines()
    assert any(line.startswith("mod + F1 ") for line in lines)
    assert any(line.startswith("mod + s, then n ") for line in lines)
    assert qtile.spawned == [keys_module.rofi_command(path)]


def test_show_cheatsheet_logs_and_skips_rofi_when_the_file_fails(
    keys_module, monkeypatch, tmp_path, caplog
):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(blocker))
    qtile = _FakeQtile()

    keys_module.show_cheatsheet(qtile)

    assert qtile.spawned == []
    assert any("cheat sheet" in m for m in caplog.messages)
