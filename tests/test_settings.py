"""Terminal resolution over the REAL ``src/settings.py``.

The module is loaded from disk with ``dotenv_values`` patched, so the
developer's own ``.env`` never leaks into the result and ``QTILE_TERMINAL``
set through ``.env`` is exercised the same way the real load order does it.
"""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("dotenv")

SETTINGS = Path(__file__).resolve().parent.parent / "src" / "settings.py"
DEFAULT_TERMINAL = "/usr/bin/qterminal"


@pytest.fixture
def load_settings(monkeypatch):
    def _load(dotenv: dict[str, str | None] | None = None):
        monkeypatch.setattr("dotenv.dotenv_values", lambda *_a, **_k: dotenv or {})
        spec = importlib.util.spec_from_file_location("_settings_under_test", SETTINGS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


def test_terminal_defaults_when_unset(load_settings, monkeypatch):
    monkeypatch.delenv("QTILE_TERMINAL", raising=False)

    assert load_settings().myTerm == DEFAULT_TERMINAL


def test_terminal_defaults_when_empty(load_settings, monkeypatch):
    monkeypatch.setenv("QTILE_TERMINAL", "")

    assert load_settings().myTerm == DEFAULT_TERMINAL


def test_terminal_from_process_environment(load_settings, monkeypatch):
    monkeypatch.setenv("QTILE_TERMINAL", "/usr/bin/kitty")

    assert load_settings().myTerm == "/usr/bin/kitty"


def test_terminal_from_dotenv_file(load_settings, monkeypatch):
    # setenv first so monkeypatch restores whatever settings.py writes later.
    monkeypatch.setenv("QTILE_TERMINAL", "")

    settings = load_settings({"QTILE_TERMINAL": "/usr/bin/alacritty"})

    assert settings.myTerm == "/usr/bin/alacritty"


def test_terminal_defaults_for_bare_dotenv_key(load_settings, monkeypatch):
    # A `QTILE_TERMINAL` line without `=` parses to None and must not export "None".
    monkeypatch.delenv("QTILE_TERMINAL", raising=False)

    assert load_settings({"QTILE_TERMINAL": None}).myTerm == DEFAULT_TERMINAL
