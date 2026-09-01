import logging
import os
import tomllib
from pathlib import Path

import pytest
from src.utils.scratchpads import (
    BUILTIN_TERM,
    MatchSpec,
    ScratchpadApp,
    dedupe_chord_keys,
    leader_is_free,
    load_scratchpads,
    load_scratchpads_from,
)


def _write_registry(tmp_path: Path, text: str, name: str = "scratchpads.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _write_bytes(tmp_path: Path, data: bytes, name: str = "scratchpads.toml") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# 1.1 — dataclass shape, minimal-entry defaults, full-entry-preserves-values
# ---------------------------------------------------------------------------


def test_module_has_no_libqtile_import() -> None:
    """The loader must be importable and unit-testable without a window
    manager: it must never import libqtile, directly or transitively.

    Inspects actual `import`/`from ... import` statements via the AST
    rather than a raw substring search, since the module's own docstrings
    and comments legitimately mention "libqtile" when explaining this very
    constraint.
    """
    import ast

    import src.utils.scratchpads as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert "libqtile" not in imported_roots
    assert "libqtile" not in module.__dict__


def test_matchspec_stores_title_regex_as_string() -> None:
    spec = MatchSpec(wm_class="foo", title_regex="bar.*")
    assert isinstance(spec.title_regex, str)
    assert spec.title_regex == "bar.*"


def test_minimal_entry_gets_defaults(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "minimal"
        command = "kitty"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert len(apps) == 1
    app = apps[0]
    assert app.name == "minimal"
    assert app.command == "kitty"
    assert app.key is None
    assert app.label == "minimal"
    assert app.icon == "utilities-terminal"
    assert app.x == 0.25
    assert app.y == 0.15
    assert app.width == 0.5
    assert app.height == 0.6
    assert app.opacity == 1.0
    assert app.on_focus_lost_hide is True
    assert app.warp_pointer is True
    assert app.desktop_entry is True
    assert app.match is None


def test_full_entry_preserves_explicit_values(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "full"
        command = "gnome-calculator"
        key = "c"
        label = "Calculator"
        icon = "gnome-calculator"
        x = 0.1
        y = 0.2
        width = 0.3
        height = 0.4
        opacity = 0.9
        on_focus_lost_hide = false
        warp_pointer = false
        desktop_entry = false
        match_wm_class = "gnome-calculator"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert len(apps) == 1
    app = apps[0]
    assert app.name == "full"
    assert app.command == "gnome-calculator"
    assert app.key == "c"
    assert app.label == "Calculator"
    assert app.icon == "gnome-calculator"
    assert app.x == 0.1
    assert app.y == 0.2
    assert app.width == 0.3
    assert app.height == 0.4
    assert app.opacity == 0.9
    assert app.on_focus_lost_hide is False
    assert app.warp_pointer is False
    assert app.desktop_entry is False
    assert app.match == MatchSpec(wm_class="gnome-calculator", title_regex=None)


# ---------------------------------------------------------------------------
# 1.3 — discover/parse/merge
# ---------------------------------------------------------------------------


def test_missing_base_file_falls_back_to_builtin(tmp_path: Path, caplog) -> None:
    missing = tmp_path / "does-not-exist.toml"

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(missing, None)

    assert apps == [BUILTIN_TERM]
    assert any("not found" in message for message in caplog.messages)


def test_malformed_toml_falls_back_to_builtin(tmp_path: Path, caplog) -> None:
    registry = _write_registry(tmp_path, "this is not [ valid toml")

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]
    assert any("invalid TOML" in message for message in caplog.messages)


def test_local_override_replaces_base_entry_in_full(tmp_path: Path) -> None:
    base = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "calc"
        command = "gnome-calculator"
        key = "c"
        """,
        name="scratchpads.toml",
    )
    local = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "calc"
        command = "gnome-calculator --custom"
        key = "x"
        """,
        name="scratchpads.local.toml",
    )

    apps = load_scratchpads_from(base, local)

    calc_entries = [app for app in apps if app.name == "calc"]
    assert len(calc_entries) == 1
    assert calc_entries[0].key == "x"
    assert calc_entries[0].command == "gnome-calculator --custom"


def test_local_only_entry_is_appended(tmp_path: Path) -> None:
    base = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "term"
        command = "kitty"
        """,
        name="scratchpads.toml",
    )
    local = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "extra"
        command = "xterm"
        """,
        name="scratchpads.local.toml",
    )

    apps = load_scratchpads_from(base, local)

    names = {app.name for app in apps}
    assert names == {"term", "extra"}


def test_local_entry_with_enabled_false_removes_base_entry(tmp_path: Path) -> None:
    base = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "term"
        command = "kitty"

        [[scratchpad]]
        name = "calc"
        command = "gnome-calculator"
        """,
        name="scratchpads.toml",
    )
    local = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "calc"
        command = "irrelevant"
        enabled = false
        """,
        name="scratchpads.local.toml",
    )

    apps = load_scratchpads_from(base, local)

    names = {app.name for app in apps}
    assert names == {"term"}


def test_missing_optional_local_file_is_silent(tmp_path: Path, caplog) -> None:
    base = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "term"
        command = "kitty"
        """,
    )
    missing_local = tmp_path / "scratchpads.local.toml"

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(base, missing_local)

    assert [app.name for app in apps] == ["term"]
    assert caplog.messages == []


# ---------------------------------------------------------------------------
# 1.5 — validation stage
# ---------------------------------------------------------------------------


def test_missing_required_field_is_skipped(tmp_path: Path, caplog) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        command = "kitty"
        """,
    )

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]
    assert any("name" in message for message in caplog.messages)


def test_wrong_field_type_is_skipped(tmp_path: Path, caplog) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "bad-x"
        command = "kitty"
        x = "not-a-number"
        """,
    )

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]
    assert any("bad-x" in message for message in caplog.messages)


def test_out_of_range_geometry_is_skipped(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "bad-opacity"
        command = "kitty"
        opacity = 1.5

        [[scratchpad]]
        name = "bad-width"
        command = "kitty"
        width = -0.1
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]


def test_unknown_field_is_ignored_not_fatal(tmp_path: Path, caplog) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "future"
        command = "kitty"
        totally_unknown_field = "value"
        """,
    )

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(registry, None)

    assert [app.name for app in apps] == ["future"]
    assert any("totally_unknown_field" in message for message in caplog.messages)


def test_duplicate_name_within_single_file_keeps_first(tmp_path: Path, caplog) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "dup"
        command = "first"

        [[scratchpad]]
        name = "dup"
        command = "second"
        """,
    )

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(registry, None)

    assert len(apps) == 1
    assert apps[0].command == "first"
    assert any("duplicate" in message.lower() for message in caplog.messages)


def test_profile_dir_without_match_wm_class_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`profile_dir` alone provides no base WM_CLASS to derive from — there
    is no single Chromium-family literal base string (Chrome and Brave emit
    different bases; see obs #927/measured xprop evidence), so
    `match_wm_class` is REQUIRED input whenever `profile_dir` is set. The
    entry must be skipped with a warning, never raise."""
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "private"
        command = "brave-browser-stable --incognito --new-window"
        profile_dir = "~/.cache/qtile-scratchpad/brave-private"
        """,
    )

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]
    assert any("match_wm_class" in message for message in caplog.messages)


def test_bare_title_regex_without_wm_class_is_skipped(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "bare-title"
        command = "kitty"
        match_title_regex = "^Foo$"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]


def test_invalid_title_regex_skips_whole_entry(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "bad-regex"
        command = "kitty"
        match_wm_class = "somewindow"
        match_title_regex = "["
        """,
    )

    apps = load_scratchpads_from(registry, None)

    # Never degrade to a bare wm_class match: the whole entry is dropped.
    assert apps == [BUILTIN_TERM]


def test_reserved_key_escape_is_skipped(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "reserved"
        command = "kitty"
        key = "Escape"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]


def test_whitespace_key_is_skipped(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "whitespace-key"
        command = "kitty"
        key = "a b"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]


# ---------------------------------------------------------------------------
# 1.7 — guarantee fallback
# ---------------------------------------------------------------------------


def test_zero_valid_entries_falls_back_to_builtin_term(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path, "")

    apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]


def test_unanticipated_tomllib_exception_still_returns_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "term"
        command = "kitty"
        """,
    )

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom: unanticipated failure")

    monkeypatch.setattr(tomllib, "load", _raise)

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]


# ---------------------------------------------------------------------------
# 1.9 — Chromium profile_dir derivation
# ---------------------------------------------------------------------------


def test_profile_dir_derivation_does_not_resolve_symlinks(tmp_path: Path) -> None:
    """Regression test for the empirically-verified finding (obs #927):
    Chromium echoes --user-data-dir verbatim and does NOT resolve symlinks,
    so the loader must not call Path.resolve() either."""
    real_dir = tmp_path / "sp-real"
    real_dir.mkdir()
    symlink_dir = tmp_path / "sp-link"
    symlink_dir.symlink_to(real_dir, target_is_directory=True)
    literal_path = str(symlink_dir)

    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    registry = _write_registry(
        registry_dir,
        f"""
        [[scratchpad]]
        name = "private"
        command = "brave-browser-stable --incognito --new-window"
        match_wm_class = "brave-browser"
        profile_dir = "{literal_path}"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert len(apps) == 1
    app = apps[0]
    assert f"--user-data-dir={literal_path}" in app.command
    assert app.match is not None
    assert app.match.wm_class == f"brave-browser ({literal_path})"
    # The realpath must NOT leak in; only the literal symlink path is used.
    assert str(real_dir) not in app.command
    assert str(real_dir) not in (app.match.wm_class or "")


def test_profile_dir_expands_home_tilde(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "private"
        command = "brave-browser-stable --incognito --new-window"
        match_wm_class = "brave-browser"
        profile_dir = "~/brave-private"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert len(apps) == 1
    expected = str(tmp_path / "brave-private")
    assert f"--user-data-dir={expected}" in apps[0].command
    assert apps[0].match is not None
    assert apps[0].match.wm_class == f"brave-browser ({expected})"


def test_profile_dir_does_not_create_directory(tmp_path: Path) -> None:
    target = tmp_path / "never-created"
    registry_dir = tmp_path / "reg"
    registry_dir.mkdir()
    registry = _write_registry(
        registry_dir,
        f"""
        [[scratchpad]]
        name = "private"
        command = "brave-browser-stable --incognito --new-window"
        match_wm_class = "brave-browser"
        profile_dir = "{target}"
        """,
    )

    load_scratchpads_from(registry, None)

    assert not target.exists()


def test_profile_dir_with_non_chromium_binary_is_skipped(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "not-chromium"
        command = "xterm"
        match_wm_class = "xterm"
        profile_dir = "~/.cache/qtile-scratchpad/whatever"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]


def test_profile_dir_with_preexisting_user_data_dir_flag_is_skipped(
    tmp_path: Path,
) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "double-specified"
        command = "brave-browser-stable --user-data-dir=/already/set"
        match_wm_class = "brave-browser"
        profile_dir = "~/.cache/qtile-scratchpad/whatever"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert apps == [BUILTIN_TERM]


def test_profile_dir_derives_brave_base_wm_class(tmp_path: Path) -> None:
    """Brave-shaped entry: `match_wm_class = "brave-browser"` + `profile_dir`
    derives `"brave-browser (<expanded>)"`. Measured via xprop on this
    machine: `brave-browser-stable --user-data-dir=<P> --new-window` emits
    `WM_CLASS = "brave-browser (<P>)", "Brave-browser"`."""
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "private"
        command = "brave-browser-stable --incognito --new-window"
        match_wm_class = "brave-browser"
        profile_dir = "~/.cache/qtile-scratchpad/brave-private"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert len(apps) == 1
    expected = os.path.expanduser("~/.cache/qtile-scratchpad/brave-private")
    assert apps[0].match is not None
    assert apps[0].match.wm_class == f"brave-browser ({expected})"


def test_profile_dir_derives_chrome_base_wm_class(tmp_path: Path) -> None:
    """Chrome-shaped entry: `match_wm_class = "google-chrome"` + `profile_dir`
    derives `"google-chrome (<expanded>)"`. This is the regression test that
    fails against a hardcoded `"brave-browser"` base: measured via xprop,
    `google-chrome --user-data-dir=<P> --new-window` emits
    `WM_CLASS = "google-chrome (<P>)", "Google-chrome"` — a DIFFERENT base
    string than Brave's."""
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "chrome-private"
        command = "google-chrome --incognito --new-window"
        match_wm_class = "google-chrome"
        profile_dir = "~/.cache/qtile-scratchpad/chrome-private"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert len(apps) == 1
    expected = os.path.expanduser("~/.cache/qtile-scratchpad/chrome-private")
    assert apps[0].match is not None
    assert apps[0].match.wm_class == f"google-chrome ({expected})"


# ---------------------------------------------------------------------------
# 1.11 — leader_is_free
# ---------------------------------------------------------------------------


def test_leader_is_free_when_combo_not_taken() -> None:
    taken = {(frozenset(["mod4", "shift"]), "s"), (frozenset(["mod4", "mod1"]), "s")}

    assert leader_is_free(taken, ["mod4"], "s") is True


def test_leader_is_free_returns_false_when_exact_combo_taken() -> None:
    taken = {(frozenset(["mod4"]), "s")}

    assert leader_is_free(taken, ["mod4"], "s") is False


def test_leader_is_free_shift_mod_combo_does_not_collide() -> None:
    # keys.py:220 — Key(["shift", mod], "s", ...) is flameshot.
    taken = {(frozenset(["shift", "mod4"]), "s")}

    assert leader_is_free(taken, ["mod4"], "s") is True


def test_leader_is_free_mod_mod1_combo_does_not_collide() -> None:
    # keys.py:168 — Key([mod, "mod1"], "s", ...) is code-insiders.
    taken = {(frozenset(["mod4", "mod1"]), "s")}

    assert leader_is_free(taken, ["mod4"], "s") is True


# ---------------------------------------------------------------------------
# 1.13 — dedupe_chord_keys
# ---------------------------------------------------------------------------


def test_dedupe_chord_keys_drops_second_entry_sharing_a_key(caplog) -> None:
    first = ScratchpadApp(name="files", command="nautilus", key="n")
    second = ScratchpadApp(name="notes", command="gnome-todo", key="n")

    with caplog.at_level(logging.WARNING):
        result = dedupe_chord_keys([first, second])

    assert result[0] == first
    assert result[1].key is None
    # Everything else about the losing entry is untouched.
    assert result[1].name == "notes"
    assert result[1].command == "gnome-todo"
    assert any("notes" in message for message in caplog.messages)


def test_dedupe_chord_keys_drops_reserved_masculine_key(caplog) -> None:
    entry = ScratchpadApp(name="sneaky", command="xterm", key="masculine")

    with caplog.at_level(logging.WARNING):
        result = dedupe_chord_keys([entry])

    assert result[0].key is None
    assert result[0].name == "sneaky"
    assert any("sneaky" in message for message in caplog.messages)


def test_dedupe_chord_keys_leaves_unkeyed_entries_untouched() -> None:
    entry = ScratchpadApp(name="term", command="kitty", key=None)

    result = dedupe_chord_keys([entry])

    assert result == [entry]


# ---------------------------------------------------------------------------
# 1.15 — hostile-input suite
# ---------------------------------------------------------------------------

_HOSTILE_TEXT_PAYLOADS = [
    pytest.param("", id="empty-file"),
    pytest.param("this is not [ valid toml at all", id="malformed-syntax"),
    pytest.param(
        "[scratchpad]\nname = \"x\"\ncommand = \"y\"\n", id="table-not-array"
    ),
    pytest.param('scratchpad = ["a", "b"]\n', id="entries-as-bare-strings"),
    pytest.param('name = "unterminated\n', id="unterminated-string"),
    pytest.param(
        "[[scratchpad]]\nname = \"n\"\ncommand = \"c\"\nopacity = inf\n",
        id="infinite-opacity",
    ),
    pytest.param(
        "[[scratchpad]]\nname = \"n\"\ncommand = \"c\"\nwidth = nan\n",
        id="nan-width",
    ),
    pytest.param(
        "[[scratchpad]]\nname = \"☕✨\"\ncommand = \"kitty\"\n",
        id="non-ascii-name",
    ),
    pytest.param(
        "top_level_key = \"no-scratchpad-table-here\"\n", id="no-scratchpad-key"
    ),
    pytest.param("a" * 5000 + " = 1\n", id="absurdly-long-key"),
]


@pytest.mark.parametrize("content", _HOSTILE_TEXT_PAYLOADS)
def test_hostile_text_payloads_never_crash(tmp_path: Path, content: str) -> None:
    registry = _write_registry(tmp_path, content)

    result = load_scratchpads_from(registry, None)

    assert isinstance(result, list)
    assert len(result) >= 1


def test_hostile_invalid_utf8_bytes_never_crash(tmp_path: Path) -> None:
    registry = _write_bytes(tmp_path, b"\xff\xfe\x00\x01name=1")

    result = load_scratchpads_from(registry, None)

    assert isinstance(result, list)
    assert len(result) >= 1


def test_hostile_ten_thousand_entries_never_crash(tmp_path: Path) -> None:
    chunks = [
        f'[[scratchpad]]\nname = "entry-{i}"\ncommand = "cmd-{i}"\n'
        for i in range(10_000)
    ]
    registry = _write_registry(tmp_path, "\n".join(chunks))

    result = load_scratchpads_from(registry, None)

    assert isinstance(result, list)
    assert len(result) >= 1


def test_hostile_missing_path_never_crashes() -> None:
    result = load_scratchpads_from(Path("/nonexistent/path/scratchpads.toml"), None)

    assert isinstance(result, list)
    assert len(result) >= 1


def test_hostile_directory_as_registry_path_never_crashes(tmp_path: Path) -> None:
    result = load_scratchpads_from(tmp_path, None)

    assert isinstance(result, list)
    assert len(result) >= 1


def test_hostile_broken_symlink_never_crashes(tmp_path: Path) -> None:
    broken = tmp_path / "broken.toml"
    broken.symlink_to(tmp_path / "does-not-exist.toml")

    result = load_scratchpads_from(broken, None)

    assert isinstance(result, list)
    assert len(result) >= 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permissions")
def test_hostile_unreadable_file_never_crashes(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "term"
        command = "kitty"
        """,
    )
    registry.chmod(0o000)

    try:
        result = load_scratchpads_from(registry, None)
    finally:
        registry.chmod(0o644)

    assert isinstance(result, list)
    assert len(result) >= 1


# ---------------------------------------------------------------------------
# 2.1/2.2 — `{repo}` command token expansion, real registry regression,
# memoized `load_scratchpads()` wrapper
# ---------------------------------------------------------------------------


def _src_dir() -> Path:
    """The `src/` directory as the loader itself computes it (mirrors
    `_builtin_kitty_conf_path`'s own base), independent of this test file's
    own location."""
    import src.utils.scratchpads as module

    return Path(module.__file__).resolve().parent.parent


def test_command_repo_token_is_expanded_to_src_dir(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "term-like"
        command = "kitty --config {repo}/assets/scratchpad/kitty.conf"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert len(apps) == 1
    expected = f"kitty --config {_src_dir()}/assets/scratchpad/kitty.conf"
    assert apps[0].command == expected
    assert "{repo}" not in apps[0].command


def test_command_without_repo_token_is_left_untouched(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        """
        [[scratchpad]]
        name = "plain"
        command = "gnome-calculator --no-braces-here"
        """,
    )

    apps = load_scratchpads_from(registry, None)

    assert apps[0].command == "gnome-calculator --no-braces-here"


def test_real_registry_term_entry_matches_builtin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression pin (task 2.2): the committed `scratchpads.toml` must load
    a `term` entry that is byte-for-behaviour identical to `BUILTIN_TERM`,
    with zero warnings (proving nothing was skipped/malformed)."""
    repo_root = Path(__file__).resolve().parents[2]
    registry = repo_root / "scratchpads.toml"
    local = repo_root / "scratchpads.local.toml"

    assert registry.is_file(), "scratchpads.toml must exist at the repo root"

    with caplog.at_level(logging.WARNING):
        apps = load_scratchpads_from(registry, local)

    assert caplog.messages == []
    term_entries = [app for app in apps if app.name == "term"]
    assert len(term_entries) == 1
    assert term_entries[0] == BUILTIN_TERM


def test_load_scratchpads_wrapper_is_memoized() -> None:
    first = load_scratchpads()
    second = load_scratchpads()

    assert first is second
    assert any(app.name == "term" for app in first)
