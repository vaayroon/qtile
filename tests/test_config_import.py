"""Headless smoke test: ``config.py`` must import in a fresh interpreter.

It runs in a subprocess for two reasons. Importing ``modules`` subscribes the
global ``startup_once`` hook and would pollute ``sys.modules`` for the other
tests (``test_screens``, ``test_hooks``). And a fresh interpreter mirrors how
Qtile itself loads the config: a new process with ``src`` on ``sys.path``.

The child gets no ``DISPLAY``/``WAYLAND_DISPLAY`` and none of the
``QTILE_*`` monitor variables, and ``dotenv.dotenv_values`` is stubbed so the
developer's own ``.env`` never leaks in (``settings.py`` calls it). Without a
display ``xrandr`` fails, and without the binary it is missing; both paths yield
an empty monitor detection, so the config must still build exactly one screen.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("libqtile.config")

REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPT = """
import dotenv
dotenv.dotenv_values = lambda *a, **k: {}

import sys
sys.path.insert(0, "src")

import config

print(len(config.screens))
"""


def _headless_env(tmp_path):
    env = os.environ.copy()
    # widget.Prompt creates ~/.cache/qtile on import; keep that out of the
    # developer's home.
    env["HOME"] = str(tmp_path)
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
    env["USER"] = "tester"
    return env


def _run(script, tmp_path):
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=_headless_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_config_imports_headless_and_builds_one_screen(tmp_path):
    result = _run(SCRIPT, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


MISSING_DESC_SCRIPT = """
import dotenv
dotenv.dotenv_values = lambda *a, **k: {}

import sys
sys.path.insert(0, "src")

from libqtile.config import KeyChord

import config

def walk(bindings, prefix):
    for binding in bindings:
        combo = prefix + "+".join([*binding.modifiers, str(binding.key)])
        if isinstance(binding, KeyChord):
            if not binding.desc:
                print(combo)
            walk(binding.submappings, combo + " ")
        elif binding.commands and not binding.desc:
            # A command-less Key is the Escape that KeyChord appends itself.
            print(combo)

walk(config.keys, "")
"""


def test_every_binding_has_a_desc(tmp_path):
    # The keybinding cheat sheet is generated from Key.desc / KeyChord.desc.
    result = _run(MISSING_DESC_SCRIPT, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split("\n")[:-1] == []


RELOAD_SCRIPT = """
import dotenv
dotenv.dotenv_values = lambda *a, **k: {}

import collections
import json
import os

from libqtile.confreader import Config

# Absolute, as Qtile passes it: the reload only covers modules whose file is
# under this path's folder, and a relative path never matches.
CONFIG = os.path.abspath("src/config.py")

def combos(keys):
    return ["+".join(sorted(k.modifiers)) + ":" + str(k.key) for k in keys]

first = Config(CONFIG)
first.load()
# A second load of an imported config takes Qtile's reload path: every
# module of the config folder is importlib.reload()-ed, as on mod+shift+r.
second = Config(CONFIG)
second.load()

before, after = combos(first.keys), combos(second.keys)
print(json.dumps({
    "same": sorted(before) == sorted(after),
    "groups": [c for c in after if c in ("mod4:1", "mod4+shift:7")],
    "reloaded": first.keys[0] is not second.keys[0],
    "dupes": sorted(c for c, n in collections.Counter(after).items() if n > 1),
}))
"""


def test_reload_keeps_every_binding_including_group_keys(tmp_path):
    # modules.groups fills modules.keys.key_sections on import; a reload
    # must re-run it against the reloaded keys module, not the stale one.
    result = _run(RELOAD_SCRIPT, tmp_path)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {
        "same": True,
        "groups": ["mod4:1", "mod4+shift:7"],
        "reloaded": True,
        "dupes": [],
    }
