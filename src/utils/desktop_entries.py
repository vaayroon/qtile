"""Rofi launchers (``.desktop`` files) for the scratchpad registry.

One file per entry with ``desktop_entry = true``, named
``qtile-scratchpad-<name>.desktop``, so ``rofi -show drun`` can toggle any
scratchpad through ``scratchpad-toggle.sh <name>``. Every file carries the
``X-QtileScratchpad=true`` marker: a sync only ever overwrites or removes a
file that has it, so a user's own launcher that happens to share the
filename pattern is left alone.

Like ``utils.scratchpads``, this module MUST NOT import ``libqtile``.
``tools/generate_scratchpad_desktops.py`` (run by ``install.sh``) calls
`sync_desktop_entries`, which may raise: the caller decides how to degrade.
Qtile's ``startup`` hook calls `refresh_desktop_entries` instead, which only
writes from the runtime clone and turns an ``OSError`` into a warning.
"""

import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .scratchpads import ScratchpadApp

logger = logging.getLogger("libqtile")

FILENAME_PREFIX = "qtile-scratchpad-"
MARKER = "X-QtileScratchpad=true"
# The single launcher install.sh wrote before this module existed.
LEGACY_FILENAME = "qtile-scratchpad.desktop"
_LEGACY_SIGNATURE = "scratchpad-toggle.sh"

_REPO_ROOT = Path(__file__).resolve().parents[2]  # src/utils/<this> -> repo
# The launchers run this script, by the absolute path of the clone that wrote
# them.
_TOGGLE_RELPATH = Path("src") / "assets" / "scratchpad" / "scratchpad-toggle.sh"
TOGGLE_SCRIPT = _REPO_ROOT / _TOGGLE_RELPATH

# A name becomes part of a filename and of the Exec line, so only names that
# are safe in both are written. Anything else is skipped with a warning. The
# first character is alphanumeric so `qtile cmd-obj -a <name>` never reads
# the name as an option.
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


@dataclass(frozen=True, slots=True)
class SyncReport:
    """What `sync_desktop_entries` did, one filename (or name) per item."""

    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def default_target_dir() -> Path:
    """`$XDG_DATA_HOME/applications`, defaulting to `~/.local/share`."""
    data_home = Path(os.environ.get("XDG_DATA_HOME", "").strip())
    # The XDG spec says relative values must be ignored.
    if not data_home.is_absolute():
        data_home = Path.home() / ".local" / "share"
    return data_home / "applications"


def runtime_clone_dir() -> Path:
    """`$XDG_CONFIG_HOME/qtile`, defaulting to `~/.config/qtile`: the clone
    the live session runs from."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", "").strip())
    # The XDG spec says relative values must be ignored.
    if not config_home.is_absolute():
        config_home = Path.home() / ".config"
    return config_home / "qtile"


def desktop_filename(name: str) -> str | None:
    """`qtile-scratchpad-<name>.desktop`, or None when `name` is not safe to
    use in a filename and an Exec line."""
    if not _SAFE_NAME.fullmatch(name):
        return None
    return f"{FILENAME_PREFIX}{name}.desktop"


def _escape_value(text: str) -> str:
    """Escape a string value per the Desktop Entry spec, so a newline in a
    TOML `label` cannot inject another key."""
    return (
        text.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def _quote_exec_arg(arg: str) -> str:
    """Quote one Exec argument: inside double quotes, `"`, backtick, `$` and
    `\\` are backslash-escaped, and `%` is doubled so it is not read as a
    field code. The result is then escaped again as a string value."""
    quoted = re.sub(r'(["`$\\])', r"\\\1", arg).replace("%", "%%")
    return _escape_value(f'"{quoted}"')


def render_desktop_entry(app: ScratchpadApp, toggle_script: Path) -> str:
    """The `.desktop` text for `app`. Pure and deterministic (no timestamps),
    so re-rendering an unchanged entry gives byte-identical output.

    `app.name` must already be safe (see `desktop_filename`)."""
    exec_line = f"{_quote_exec_arg(str(toggle_script))} {app.name}"
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={_escape_value(app.label or app.name)}",
        f"Comment=Toggle the {app.name} scratchpad",
        f"Exec={exec_line}",
        f"Icon={_escape_value(app.icon)}",
        "Terminal=false",
        "Categories=System;",
        f"Keywords=scratchpad;dropdown;{app.name};",
        MARKER,
        f"X-QtileScratchpadName={app.name}",
    ]
    return "\n".join(lines) + "\n"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _has_marker(text: str | None) -> bool:
    # split("\n"), not splitlines(): the spec only knows "\n", and splitlines
    # would also split on form feeds or U+2028 in a foreign file.
    return text is not None and MARKER in text.split("\n")


def _write_atomically(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def sync_desktop_entries(
    apps: Iterable[ScratchpadApp], target_dir: Path, toggle_script: Path
) -> SyncReport:
    """Make `target_dir` hold exactly one launcher per entry that wants one.

    - Writes `qtile-scratchpad-<name>.desktop` for each entry with
      `desktop_entry = true`, only when the content changed.
    - Skips (with a warning) an entry whose name is not filename-safe, an
      existing file without the marker (it belongs to the user), and a file
      it cannot write or remove, so one failure never stops the rest.
    - Removes marked `qtile-scratchpad-*.desktop` files no entry wants any
      more (a removed, renamed or `desktop_entry = false` entry), and the
      legacy `qtile-scratchpad.desktop` when it runs `scratchpad-toggle.sh`.
    """
    report = SyncReport()
    target_dir.mkdir(parents=True, exist_ok=True)

    wanted: dict[str, str] = {}
    for app in apps:
        if not app.desktop_entry:
            continue
        filename = desktop_filename(app.name)
        if filename is None:
            logger.warning(
                "scratchpad desktop: entry name %r is not filename-safe "
                "(a letter or digit, then letters, digits, '.', '_', '-'); "
                "no launcher written",
                app.name,
            )
            report.skipped.append(app.name)
            continue
        wanted[filename] = render_desktop_entry(app, toggle_script)

    for filename, text in wanted.items():
        path = target_dir / filename
        if path.exists() or path.is_symlink():
            current = _read(path)
            if current == text:
                report.unchanged.append(filename)
                continue
            if not _has_marker(current):
                logger.warning(
                    "scratchpad desktop: %s exists and was not written by "
                    "this config; leaving it alone",
                    path,
                )
                report.skipped.append(filename)
                continue
        try:
            _write_atomically(path, text)
        except OSError as error:
            logger.warning("scratchpad desktop: cannot write %s: %s", path, error)
            report.skipped.append(filename)
            continue
        report.written.append(filename)

    stale = [
        path
        for path in sorted(target_dir.glob(f"{FILENAME_PREFIX}*.desktop"))
        if path.name not in wanted and path.is_file() and _has_marker(_read(path))
    ]
    legacy = target_dir / LEGACY_FILENAME
    legacy_text = _read(legacy) if legacy.is_file() else None
    if legacy_text is not None and _LEGACY_SIGNATURE in legacy_text:
        stale.append(legacy)
    for path in stale:
        try:
            path.unlink()
        except OSError as error:
            logger.warning("scratchpad desktop: cannot remove %s: %s", path, error)
            continue
        report.removed.append(path.name)

    return report


def refresh_desktop_entries(
    apps: Iterable[ScratchpadApp], repo_root: Path = _REPO_ROOT
) -> SyncReport | None:
    """Sync the launchers for `apps`, but only when `repo_root` is the runtime
    clone. Returns None when it wrote nothing for that reason or on an error.

    Any other clone is left out on purpose: `test-xephyr.sh` runs the dev
    clone's config, and syncing from there would point every launcher at the
    dev clone. An ``OSError`` (a read-only or unusable target directory, an
    unresolvable path) is logged as a warning, never raised.
    """
    try:
        runtime_dir = runtime_clone_dir().resolve()
        if repo_root.resolve() != runtime_dir:
            logger.info(
                "scratchpad desktop: %s is not the runtime clone %s; "
                "rofi launchers left as they are",
                repo_root,
                runtime_dir,
            )
            return None
        target_dir = default_target_dir()
        return sync_desktop_entries(apps, target_dir, repo_root / _TOGGLE_RELPATH)
    except (OSError, RuntimeError) as error:  # RuntimeError: no home directory
        logger.warning("scratchpad desktop: cannot refresh rofi launchers: %s", error)
        return None
