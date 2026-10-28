import logging
from pathlib import Path

import pytest
from src.utils.desktop_entries import (
    LEGACY_FILENAME,
    MARKER,
    desktop_filename,
    render_desktop_entry,
    sync_desktop_entries,
)
from src.utils.scratchpads import ScratchpadApp

TOGGLE = Path("/opt/qtile/src/assets/scratchpad/scratchpad-toggle.sh")


def _app(name: str = "files", **fields: object) -> ScratchpadApp:
    return ScratchpadApp(name=name, command="nautilus", **fields)


def _keys(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines()[1:])


# ---------------------------------------------------------------------------
# desktop_filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["term", "my-notes", "app_2", "v1.0"])
def test_desktop_filename_for_safe_names(name: str) -> None:
    assert desktop_filename(name) == f"qtile-scratchpad-{name}.desktop"


@pytest.mark.parametrize("name", ["../evil", "a/b", "two words", "café", "x;y", ""])
def test_desktop_filename_rejects_unsafe_names(name: str) -> None:
    assert desktop_filename(name) is None


# ---------------------------------------------------------------------------
# render_desktop_entry
# ---------------------------------------------------------------------------


def test_render_uses_label_icon_and_toggles_the_entry_by_name() -> None:
    app = _app(label="Scratchpad Files", icon="org.gnome.Nautilus")

    keys = _keys(render_desktop_entry(app, TOGGLE))

    assert keys["Name"] == "Scratchpad Files"
    assert keys["Icon"] == "org.gnome.Nautilus"
    assert keys["Exec"] == f'"{TOGGLE}" files'
    assert keys["Type"] == "Application"
    assert keys["Terminal"] == "false"
    assert keys["X-QtileScratchpadName"] == "files"


def test_render_falls_back_to_the_name_without_a_label() -> None:
    keys = _keys(render_desktop_entry(_app(label=""), TOGGLE))

    assert keys["Name"] == "files"


def test_render_is_deterministic_and_carries_the_marker() -> None:
    app = _app(label="Files")

    first = render_desktop_entry(app, TOGGLE)

    assert first == render_desktop_entry(app, TOGGLE)
    assert first.startswith("[Desktop Entry]\n")
    assert first.endswith("\n")
    assert MARKER in first.splitlines()


def test_render_escapes_a_newline_in_the_label() -> None:
    # A TOML label may hold "\n"; written raw it would inject a key.
    text = render_desktop_entry(_app(label="Files\nExec=rm -rf ~"), TOGGLE)

    assert "Exec=rm -rf ~" not in text.splitlines()
    assert _keys(text)["Name"] == "Files\\nExec=rm -rf ~"


def test_render_quotes_reserved_characters_in_the_toggle_path() -> None:
    toggle = Path('/home/me/my "qtile" $dir/100%/toggle.sh')

    exec_line = _keys(render_desktop_entry(_app(), toggle))["Exec"]

    assert exec_line == r'"/home/me/my \\"qtile\\" \\$dir/100%%/toggle.sh" files'


# ---------------------------------------------------------------------------
# sync_desktop_entries
# ---------------------------------------------------------------------------


def _sync(apps: list[ScratchpadApp], target: Path):
    return sync_desktop_entries(apps, target, TOGGLE)


def test_sync_writes_one_launcher_per_entry(tmp_path: Path) -> None:
    target = tmp_path / "applications"

    report = _sync([_app("term"), _app("files")], target)

    assert report.written == [
        "qtile-scratchpad-term.desktop",
        "qtile-scratchpad-files.desktop",
    ]
    assert sorted(p.name for p in target.iterdir()) == [
        "qtile-scratchpad-files.desktop",
        "qtile-scratchpad-term.desktop",
    ]


def test_sync_is_idempotent(tmp_path: Path) -> None:
    apps = [_app("term"), _app("files")]
    _sync(apps, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    report = _sync(apps, tmp_path)

    assert report.written == []
    assert sorted(report.unchanged) == sorted(before)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_sync_rewrites_a_launcher_whose_entry_changed(tmp_path: Path) -> None:
    _sync([_app(label="Old")], tmp_path)

    report = _sync([_app(label="New")], tmp_path)

    assert report.written == ["qtile-scratchpad-files.desktop"]
    text = (tmp_path / "qtile-scratchpad-files.desktop").read_text()
    assert _keys(text)["Name"] == "New"


def test_sync_skips_entries_with_desktop_entry_false(tmp_path: Path) -> None:
    report = _sync([_app("term"), _app("files", desktop_entry=False)], tmp_path)

    assert report.written == ["qtile-scratchpad-term.desktop"]
    assert not (tmp_path / "qtile-scratchpad-files.desktop").exists()


def test_sync_removes_launchers_no_entry_wants(tmp_path: Path) -> None:
    _sync([_app("term"), _app("files"), _app("calc")], tmp_path)

    # `files` was removed from the registry, `calc` opted out.
    report = _sync([_app("term"), _app("calc", desktop_entry=False)], tmp_path)

    assert sorted(report.removed) == [
        "qtile-scratchpad-calc.desktop",
        "qtile-scratchpad-files.desktop",
    ]
    assert [p.name for p in tmp_path.iterdir()] == ["qtile-scratchpad-term.desktop"]


def test_sync_never_touches_an_unmarked_lookalike(tmp_path: Path, caplog) -> None:
    stale = tmp_path / "qtile-scratchpad-mine.desktop"
    clash = tmp_path / "qtile-scratchpad-files.desktop"
    stale.write_text("[Desktop Entry]\nName=Mine\n")
    clash.write_text("[Desktop Entry]\nName=Also mine\n")

    with caplog.at_level(logging.WARNING):
        report = _sync([_app("files")], tmp_path)

    assert stale.read_text() == "[Desktop Entry]\nName=Mine\n"
    assert clash.read_text() == "[Desktop Entry]\nName=Also mine\n"
    assert report.skipped == ["qtile-scratchpad-files.desktop"]
    assert report.removed == []
    assert any("not written by this config" in m for m in caplog.messages)


def test_sync_skips_an_unsafe_name_with_a_warning(tmp_path: Path, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        report = _sync([_app("../evil"), _app("term")], tmp_path)

    assert report.skipped == ["../evil"]
    assert report.written == ["qtile-scratchpad-term.desktop"]
    assert [p.name for p in tmp_path.iterdir()] == ["qtile-scratchpad-term.desktop"]
    assert any("'../evil'" in m for m in caplog.messages)


def test_sync_removes_the_legacy_launcher(tmp_path: Path) -> None:
    legacy = tmp_path / LEGACY_FILENAME
    legacy.write_text(f"[Desktop Entry]\nExec={TOGGLE}\n")

    report = _sync([_app("term")], tmp_path)

    assert not legacy.exists()
    assert LEGACY_FILENAME in report.removed


def test_sync_keeps_a_legacy_named_file_it_did_not_write(tmp_path: Path) -> None:
    legacy = tmp_path / LEGACY_FILENAME
    legacy.write_text("[Desktop Entry]\nExec=my-own-thing\n")

    _sync([_app("term")], tmp_path)

    assert legacy.exists()


def test_sync_creates_the_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "share" / "applications"

    _sync([_app("term")], target)

    assert (target / "qtile-scratchpad-term.desktop").is_file()
