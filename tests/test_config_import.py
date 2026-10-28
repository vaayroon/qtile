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


def test_config_imports_headless_and_builds_one_screen():
    env = os.environ.copy()
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

    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"
