import ast
import logging
from pathlib import Path

import pytest
import src.utils.launchers as launchers
from src.utils.launchers import (
    Combo,
    LauncherApp,
    bindable_launchers,
    load_launchers,
    load_launchers_from,
    parse_combo,
)


def _write(tmp_path: Path, text: str, name: str = "launchers.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _app(name: str, *combos: Combo, desc: str = "") -> LauncherApp:
    return LauncherApp(name=name, command=name, combos=combos, desc=desc or name)


ALT_E = Combo(("mod4", "mod1"), "e")


def test_module_has_no_libqtile_import() -> None:
    tree = ast.parse(Path(launchers.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "libqtile" not in roots


# ---------------------------------------------------------------------------
# parse_combo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mod+alt+e", ALT_E),
        ("MOD+Alt+e", ALT_E),
        ("mod4+mod1+e", ALT_E),
        ("ctrl+1", Combo(("control",), "1")),
        ("shift+mod+s", Combo(("shift", "mod4"), "s")),
        ("XF86Explorer", Combo((), "XF86Explorer")),
        ("mod+plus", Combo(("mod4",), "plus")),
    ],
)
def test_parse_combo_accepts(text: str, expected: Combo) -> None:
    assert parse_combo(text, "mod4") == expected


@pytest.mark.parametrize(
    "text",
    ["", "mod+", "+e", "mod++", "mod + e", "hyper+e", "mod+mod4+e", "alt+alt+e"],
)
def test_parse_combo_rejects(text: str) -> None:
    assert parse_combo(text, "mod4") is None


def test_parse_combo_uses_the_given_mod() -> None:
    assert parse_combo("mod+e", "mod1") == Combo(("mod1",), "e")


def test_combo_identity_ignores_modifier_order() -> None:
    assert (
        Combo(("shift", "mod4"), "s").identity == Combo(("mod4", "shift"), "s").identity
    )
    assert str(ALT_E) == "mod4+mod1+e"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_full_entry(tmp_path: Path) -> None:
    base = _write(
        tmp_path,
        '[[launcher]]\nname = "spotify"\ncommand = "spotify --x"\n'
        'keys = ["mod+alt+e", "XF86Music"]\ndesc = "Music"\n',
    )
    assert load_launchers_from(base) == [
        LauncherApp(
            name="spotify",
            command="spotify --x",
            combos=(ALT_E, Combo((), "XF86Music")),
            desc="Music",
        )
    ]


def test_desc_defaults_to_launch_name(tmp_path: Path) -> None:
    base = _write(tmp_path, '[[launcher]]\nname = "a"\ncommand = "a"\nkeys = ["F9"]\n')
    assert load_launchers_from(base)[0].desc == "Launch a"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('command = "a"\nkeys = ["F9"]', "missing required field 'name'"),
        ('name = "a"\nkeys = ["F9"]', "missing required field 'command'"),
        ('name = "a"\ncommand = "  "\nkeys = ["F9"]', "missing required field"),
        ('name = "-a"\ncommand = "a"\nkeys = ["F9"]', "name must be"),
        ('name = "a b"\ncommand = "a"\nkeys = ["F9"]', "name must be"),
        ('name = "a"\ncommand = "a"', "needs 'keys'"),
        ('name = "a"\ncommand = "a"\nkeys = "F9"', "needs 'keys'"),
        ('name = "a"\ncommand = "a"\nkeys = []', "needs 'keys'"),
        ('name = "a"\ncommand = "a"\nkeys = ["hyper+x", 3]', "no valid combo"),
    ],
)
def test_invalid_entry_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, body: str, message: str
) -> None:
    base = _write(tmp_path, f"[[launcher]]\n{body}\n")
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert load_launchers_from(base) == []
    assert message in caplog.text


def test_invalid_and_repeated_combos_are_dropped_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    base = _write(
        tmp_path,
        '[[launcher]]\nname = "a"\ncommand = "a"\n'
        'keys = ["mod+alt+e", "bogus+e", "alt+mod+e", 7]\n',
    )
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        [app] = load_launchers_from(base)
    assert app.combos == (ALT_E,)
    assert "invalid combo 'bogus+e'" in caplog.text
    assert "invalid combo 7" in caplog.text
    assert "lists combo 'alt+mod+e' twice" in caplog.text


@pytest.mark.parametrize("desc", ['""', "3"])
def test_invalid_desc_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, desc: str
) -> None:
    base = _write(
        tmp_path,
        f'[[launcher]]\nname = "a"\ncommand = "a"\nkeys = ["F9"]\ndesc = {desc}\n',
    )
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert load_launchers_from(base)[0].desc == "Launch a"
    assert "invalid 'desc'" in caplog.text


def test_unknown_field_warns_but_loads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    base = _write(
        tmp_path, '[[launcher]]\nname = "a"\ncommand = "a"\nkeys = ["F9"]\nicon = "x"\n'
    )
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert len(load_launchers_from(base)) == 1
    assert "unknown field 'icon'" in caplog.text


# ---------------------------------------------------------------------------
# Files and the local override
# ---------------------------------------------------------------------------

BASE = (
    '[[launcher]]\nname = "a"\ncommand = "a"\nkeys = ["F1"]\n'
    '[[launcher]]\nname = "b"\ncommand = "b"\nkeys = ["F2"]\n'
)


def test_local_entry_replaces_removes_and_appends(tmp_path: Path) -> None:
    base = _write(tmp_path, BASE)
    local = _write(
        tmp_path,
        '[[launcher]]\nname = "a"\ncommand = "a2"\nkeys = ["F3"]\n'
        '[[launcher]]\nname = "b"\nenabled = false\n'
        '[[launcher]]\nname = "c"\ncommand = "c"\nkeys = ["F4"]\n',
        "launchers.local.toml",
    )
    apps = load_launchers_from(base, local)
    assert [(app.name, app.command, str(app.combos[0])) for app in apps] == [
        ("a", "a2", "F3"),
        ("c", "c", "F4"),
    ]


def test_missing_base_warns_and_missing_local_does_not(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert load_launchers_from(tmp_path / "nope.toml", tmp_path / "x.toml") == []
    assert "launcher registry:" in caplog.text
    assert "nope.toml not found" in caplog.text
    assert "x.toml" not in caplog.text


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[[launcher]\n", "invalid TOML"),
        ('launcher = "x"\n', "'launcher' key is not an array of tables"),
        ("launcher = [1]\n", "entry #0 is not a table"),
    ],
)
def test_malformed_file_contributes_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, text: str, message: str
) -> None:
    base = _write(tmp_path, text)
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert load_launchers_from(base) == []
    assert message in caplog.text


def test_loader_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(launchers, "load_raw_entries", _boom)
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert load_launchers_from(tmp_path / "launchers.toml") == []
    assert "unexpected loader failure" in caplog.text


def test_load_launchers_reads_the_repo_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write(tmp_path, BASE)
    _write(
        tmp_path, '[[launcher]]\nname = "a"\nenabled = false\n', "launchers.local.toml"
    )
    monkeypatch.setattr(launchers, "_REPO_ROOT", tmp_path)
    load_launchers.cache_clear()
    try:
        assert [app.name for app in load_launchers("mod4")] == ["b"]
    finally:
        load_launchers.cache_clear()


# ---------------------------------------------------------------------------
# bindable_launchers
# ---------------------------------------------------------------------------


def test_taken_combos_are_dropped(caplog: pytest.LogCaptureFixture) -> None:
    taken = {(frozenset({"mod4", "mod1"}), "e")}
    apps = [_app("a", ALT_E, Combo((), "F9"))]
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert bindable_launchers(apps, taken) == [_app("a", Combo((), "F9"), desc="a")]
    assert "mod4+mod1+e for entry 'a' is already bound" in caplog.text


def test_first_entry_wins_and_an_entry_with_no_combo_left_is_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    flipped = Combo(("mod1", "mod4"), "e")
    apps = [_app("a", ALT_E), _app("b", flipped)]
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert bindable_launchers(apps, set()) == [_app("a", ALT_E)]
    assert "entry 'b' has no free combo left" in caplog.text


def test_bindable_launchers_does_not_mutate_taken() -> None:
    taken: set[tuple[frozenset[str], str]] = set()
    bindable_launchers([_app("a", ALT_E)], taken)
    assert taken == set()
