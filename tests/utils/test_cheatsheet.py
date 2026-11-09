"""Tests for ``utils.cheatsheet``, with duck-typed stand-ins for libqtile's
``Key`` and ``KeyChord``."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.utils import cheatsheet
from src.utils.cheatsheet import (
    Row,
    Section,
    binding_rows,
    build_sections,
    format_combo,
    popup_input_path,
    rofi_command,
    to_lines,
    to_markdown,
)


def _key(modifiers, key, desc="", commands=("cmd",)):
    return SimpleNamespace(modifiers=modifiers, key=key, desc=desc, commands=commands)


def _chord(modifiers, key, submappings, desc=""):
    return SimpleNamespace(
        modifiers=modifiers, key=key, desc=desc, submappings=submappings
    )


def test_module_has_no_libqtile_import() -> None:
    tree = ast.parse(Path(cheatsheet.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "libqtile" not in roots


@pytest.mark.parametrize(
    ("modifiers", "key", "expected"),
    [
        ([], "XF86AudioMute", "XF86AudioMute"),
        (["mod4"], "Return", "mod + Return"),
        (["shift", "mod4"], "s", "mod + Shift + s"),
        (["mod1", "control"], "l", "Ctrl + Alt + l"),
        (["mod4", "shift", "mod1", "control"], "x", "mod + Ctrl + Alt + Shift + x"),
        (["mod4"], "masculine", "mod + º"),
        (["mod5", "mod4", "lock"], "a", "mod + lock + mod5 + a"),
        ([], 0x41, "0x41"),
    ],
)
def test_format_combo(modifiers, key, expected) -> None:
    assert format_combo(modifiers, key) == expected


def test_key_row() -> None:
    assert binding_rows(_key(["mod4"], "Tab", "Next layout")) == [
        Row("mod + Tab", "Next layout")
    ]


def test_key_without_commands_is_skipped() -> None:
    # KeyChord appends Key([], "Escape") with no command.
    assert binding_rows(_key([], "Escape", commands=())) == []


def test_chord_rows_include_the_leader_and_each_sub_key() -> None:
    chord = _chord(
        ["mod4"],
        "s",
        [_key([], "n", "Files"), _key([], "Escape", commands=())],
        desc="Scratchpads",
    )

    assert binding_rows(chord) == [
        Row("mod + s", "Scratchpads"),
        Row("mod + s, then n", "Files"),
    ]


def test_nested_chord_rows_chain_the_prefix() -> None:
    inner = _chord([], "a", [_key([], "b", "Deep")], desc="Inner")
    outer = _chord(["mod4"], "x", [inner], desc="Outer")

    assert [row.keys for row in binding_rows(outer)] == [
        "mod + x",
        "mod + x, then a",
        "mod + x, then a, then b",
    ]


def test_build_sections_keeps_order_and_drops_empty_sections() -> None:
    sections = build_sections(
        [
            ("First", [_key(["mod4"], "a", "A")]),
            ("Empty", []),
            ("Only escape", [_key([], "Escape", commands=())]),
            ("Last", [_key([], "b", "B")]),
        ]
    )

    assert [s.title for s in sections] == ["First", "Last"]


def test_to_markdown_renders_one_table_per_section() -> None:
    sections = [
        Section("One", (Row("mod + a", "Do A"),)),
        Section("Two", (Row("b", "Play | Pause"),)),
    ]

    assert to_markdown(sections) == (
        "### One\n"
        "\n"
        "| Keys | Action |\n"
        "|---|---|\n"
        "| `mod + a` | Do A |\n"
        "\n"
        "### Two\n"
        "\n"
        "| Keys | Action |\n"
        "|---|---|\n"
        "| `b` | Play \\| Pause |\n"
    )


def test_to_markdown_of_nothing_is_empty() -> None:
    assert to_markdown([]) == ""


def test_to_lines_aligns_the_keys_column() -> None:
    sections = [
        Section("One", (Row("mod + a", "Do A"),)),
        Section("Two", (Row("b", "Do B"),)),
    ]

    assert to_lines(sections) == [
        "mod + a  Do A  [One]",
        "b        Do B  [Two]",
    ]


def test_to_lines_of_nothing_is_empty() -> None:
    assert to_lines([]) == []


def test_popup_input_path_prefers_the_runtime_dir() -> None:
    environ = {"XDG_RUNTIME_DIR": "/run/user/1000", "XDG_CACHE_HOME": "/c"}

    assert popup_input_path(environ) == Path("/run/user/1000/qtile-keybindings.txt")


@pytest.mark.parametrize("runtime_dir", [None, "", "relative/run"])
def test_popup_input_path_falls_back_to_the_cache_home(runtime_dir) -> None:
    environ = {"XDG_CACHE_HOME": "/c"}
    if runtime_dir is not None:
        environ["XDG_RUNTIME_DIR"] = runtime_dir

    assert popup_input_path(environ) == Path("/c/qtile/qtile-keybindings.txt")


@pytest.mark.parametrize("cache_home", [None, "", "relative/cache"])
def test_popup_input_path_falls_back_to_dot_cache(
    monkeypatch: pytest.MonkeyPatch, cache_home
) -> None:
    monkeypatch.setenv("HOME", "/home/tester")
    environ = {} if cache_home is None else {"XDG_CACHE_HOME": cache_home}

    assert popup_input_path(environ) == Path(
        "/home/tester/.cache/qtile/qtile-keybindings.txt"
    )


def test_rofi_command_reads_the_file_without_custom_input() -> None:
    command = rofi_command(Path("/run/user/1000/k.txt"))

    assert command[:2] == ["rofi", "-dmenu"]
    assert "-no-custom" in command
    assert command[-2:] == ["-input", "/run/user/1000/k.txt"]
