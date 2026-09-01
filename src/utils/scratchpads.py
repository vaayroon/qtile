"""Data-driven scratchpad app registry loader.

This module discovers, parses, merges, validates, normalizes and derives a
list of :class:`ScratchpadApp` entries from ``scratchpads.toml`` (base,
committed) and an optional ``scratchpads.local.toml`` (gitignored override).

This module MUST NOT import ``libqtile`` (directly or transitively) and MUST
only return plain stdlib dataclasses, so it stays unit-testable without a
running window manager. Consumers (``modules.groups``, ``modules.keys``)
translate the returned dataclasses into ``libqtile`` objects.

Never-crash contract: nothing in this module may raise during qtile config
load. Every degradation (missing file, malformed TOML, an invalid entry, or
even an exception type nobody anticipated) is caught, logged via
``logger.warning``/``logger.exception``, and degrades gracefully. Zero valid
entries after the full pipeline falls back to :data:`BUILTIN_TERM`, so the
shipped terminal dropdown can never disappear.
"""

import logging
import math
import os
import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# Use the "libqtile" logger by name rather than importing
# `libqtile.log_utils.logger` directly. `logging.getLogger` returns the same
# singleton object regardless of who created it first, so once qtile's own
# `init_log()` attaches handlers to it, our warnings land in the same
# ~/.local/share/qtile/qtile.log target — without this module ever importing
# libqtile.
logger = logging.getLogger("libqtile")

# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchSpec:
    """Plain-data stand-in for a libqtile `Match`.

    `title_regex` is stored as the raw source STRING, never as a compiled
    `re.Pattern`: `re.Pattern` equality is identity-based and only
    accidentally `True` via CPython's internal compile cache, which would
    make dataclass equality assertions flaky in tests. The loader validates
    that the regex compiles, then discards the compiled object.
    """

    wm_class: str | None = None
    title_regex: str | None = None


@dataclass(frozen=True, slots=True)
class ScratchpadApp:
    """A fully-validated, ready-to-use scratchpad app entry."""

    name: str
    command: str
    key: str | None = None
    label: str = ""
    icon: str = "utilities-terminal"
    x: float = 0.25
    y: float = 0.15
    width: float = 0.5
    height: float = 0.6
    opacity: float = 1.0
    on_focus_lost_hide: bool = True
    warp_pointer: bool = True
    desktop_entry: bool = True
    match: MatchSpec | None = None


def _builtin_kitty_conf_path() -> str:
    """Path to the shipped scratchpad kitty config, resolved relative to this
    file so it works regardless of Qtile's working directory."""
    repo_src = Path(__file__).resolve().parent.parent
    return str(repo_src / "assets" / "scratchpad" / "kitty.conf")


# The built-in fallback entry, intentionally duplicated from
# `scratchpads.toml` rather than depending on it: the fallback must not
# depend on the artifact it protects against.
BUILTIN_TERM = ScratchpadApp(
    name="term",
    command=f"kitty --class scratchpad-term --config {_builtin_kitty_conf_path()}",
    key=None,
    label="term",
    icon="utilities-terminal",
    x=0.25,
    y=0.15,
    width=0.5,
    height=0.6,
    opacity=1.0,
    on_focus_lost_hide=True,
    warp_pointer=True,
    desktop_entry=True,
    match=MatchSpec(wm_class="scratchpad-term"),
)


# ---------------------------------------------------------------------------
# Internal: control flow + known schema
# ---------------------------------------------------------------------------


class _SkipEntry(Exception):
    """Internal control-flow signal: the current entry failed validation and
    must be skipped. Always caught within this module; never escapes it."""


# A raw TOML entry carries its source file alongside it through the pipeline
# so warnings can name the offending file (Observability requirement).
_RawEntry = tuple[dict[str, Any], str]

_KNOWN_FIELDS = {
    "name",
    "command",
    "key",
    "label",
    "icon",
    "x",
    "y",
    "width",
    "height",
    "opacity",
    "on_focus_lost_hide",
    "warp_pointer",
    "match_wm_class",
    "match_title_regex",
    "profile_dir",
    "desktop_entry",
    "enabled",
}

_RESERVED_VALIDATE_KEYS = {"Escape"}
_RESERVED_CHORD_KEY = "masculine"

_CHROMIUM_BINARY_MARKERS = ("brave", "chrom", "vivaldi", "opera", "microsoft-edge")
# Empirically verified (see project memory: profile_dir-derivation
# discovery) — Chromium/Brave always emits this literal base string in
# WM_CLASS, regardless of the invoked binary's own basename.
_CHROMIUM_BASE_WM_CLASS = "brave-browser"


def _entry_identity(raw_entry: dict[str, Any], index: int, source: str) -> str:
    name = raw_entry.get("name")
    if isinstance(name, str) and name.strip():
        return f"{name!r} ({source})"
    return f"#{index} ({source})"


# ---------------------------------------------------------------------------
# Discover + parse stage
# ---------------------------------------------------------------------------


def _parse_toml_file(path: Path, source: str) -> list[_RawEntry]:
    """Parse one already-existing TOML file into raw entry dicts.

    Never raises: any failure (not a regular file, malformed TOML, an
    unanticipated exception from `tomllib.load`) degrades to "this file
    contributes zero entries" plus a logged warning/exception.
    """
    if not path.is_file():
        logger.warning(
            "scratchpad registry: %s is not a regular file, skipping", source
        )
        return []

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        logger.warning("scratchpad registry: %s has invalid TOML: %s", source, error)
        return []
    except Exception:
        # Catches anything else tomllib (or the filesystem) can throw:
        # UnicodeDecodeError, OSError family, RecursionError, MemoryError,
        # or an exception type nobody anticipated (see the monkeypatch test).
        logger.exception("scratchpad registry: unexpected error reading %s", source)
        return []

    if not isinstance(data, dict):
        logger.warning(
            "scratchpad registry: %s root is not a table, skipping", source
        )
        return []

    raw_entries = data.get("scratchpad", [])
    if not isinstance(raw_entries, list):
        logger.warning(
            "scratchpad registry: %s 'scratchpad' key is not an array of "
            "tables, skipping",
            source,
        )
        return []

    entries: list[_RawEntry] = []
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            logger.warning(
                "scratchpad registry: %s entry #%d is not a table, skipping",
                source,
                index,
            )
            continue
        entries.append((raw_entry, source))
    return entries


def _read_registry_file(
    path: Path | None, *, required: bool
) -> list[_RawEntry]:
    """Discover stage: catches a missing file, a directory, or an unreadable
    path. `required` controls whether a missing file is worth a warning
    (the base file should always exist; the local override file is
    optional and its absence is the normal case)."""
    if path is None:
        return []

    source = str(path)
    try:
        exists = path.exists()
    except OSError:
        logger.warning("scratchpad registry: could not stat %s", source)
        return []

    if not exists:
        if required:
            logger.warning(
                "scratchpad registry: %s not found, treating as empty", source
            )
        return []

    return _parse_toml_file(path, source)


# ---------------------------------------------------------------------------
# Merge stage
# ---------------------------------------------------------------------------


def _dedupe_named(entries: list[_RawEntry], file_label: str) -> list[_RawEntry]:
    """Keep the first entry per `name` within a single file; entries with a
    missing/blank name pass through untouched (the validate stage handles
    the missing-name case with the right identity)."""
    seen: set[str] = set()
    result: list[_RawEntry] = []
    for raw_entry, source in entries:
        name = raw_entry.get("name")
        if not (isinstance(name, str) and name.strip()):
            result.append((raw_entry, source))
            continue
        if name in seen:
            logger.warning(
                "scratchpad registry: duplicate entry name=%r in %s, keeping "
                "first occurrence",
                name,
                file_label,
            )
            continue
        seen.add(name)
        result.append((raw_entry, source))
    return result


def _merge_raw_entries(
    base_entries: list[_RawEntry], local_entries: list[_RawEntry]
) -> list[_RawEntry]:
    """Merge the local override file into the base registry by `name`.

    A local entry sharing a `name` with a base entry REPLACES it in full
    (whole-entry override, not per-field merge). A local entry with a new
    `name` is appended. A local entry with `enabled = false` removes the
    matching base entry entirely.
    """
    base = _dedupe_named(base_entries, "base file")
    local = _dedupe_named(local_entries, "local file")

    by_name: dict[str, _RawEntry] = {}
    order: list[str] = []
    unnamed: list[_RawEntry] = []

    for raw_entry, source in base:
        name = raw_entry.get("name")
        if isinstance(name, str) and name.strip():
            by_name[name] = (raw_entry, source)
            order.append(name)
        else:
            unnamed.append((raw_entry, source))

    for raw_entry, source in local:
        name = raw_entry.get("name")
        if not (isinstance(name, str) and name.strip()):
            unnamed.append((raw_entry, source))
            continue
        if raw_entry.get("enabled") is False:
            if name in by_name:
                by_name.pop(name)
                order.remove(name)
            continue
        if name not in by_name:
            order.append(name)
        by_name[name] = (raw_entry, source)  # whole-entry replace

    return [by_name[name] for name in order] + unnamed


# ---------------------------------------------------------------------------
# Validate + normalize + derive stage
# ---------------------------------------------------------------------------


def _require_str(raw_entry: dict[str, Any], field: str, identity: str) -> str:
    value = raw_entry.get(field)
    if not isinstance(value, str) or not value.strip():
        logger.warning(
            "scratchpad registry: entry %s missing required field %r",
            identity,
            field,
        )
        raise _SkipEntry
    return value


def _optional_str(raw_entry: dict[str, Any], field: str, identity: str) -> str | None:
    if field not in raw_entry or raw_entry[field] is None:
        return None
    value = raw_entry[field]
    if not isinstance(value, str):
        logger.warning(
            "scratchpad registry: entry %s field %r expected a string, got %r",
            identity,
            field,
            value,
        )
        raise _SkipEntry
    return value


def _optional_key(raw_entry: dict[str, Any], identity: str) -> str | None:
    if "key" not in raw_entry or raw_entry["key"] is None:
        return None
    value = raw_entry["key"]
    if not isinstance(value, str):
        logger.warning(
            "scratchpad registry: entry %s field 'key' expected a string, "
            "got %r",
            identity,
            value,
        )
        raise _SkipEntry
    if not value.strip() or any(character.isspace() for character in value):
        logger.warning(
            "scratchpad registry: entry %s has an invalid 'key' %r (blank "
            "or contains whitespace)",
            identity,
            value,
        )
        raise _SkipEntry
    if value in _RESERVED_VALIDATE_KEYS:
        logger.warning(
            "scratchpad registry: entry %s uses reserved key %r", identity, value
        )
        raise _SkipEntry
    return value


def _coerce_geometry(
    raw_entry: dict[str, Any],
    field: str,
    identity: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
    exclusive_min: bool = False,
) -> float:
    if field not in raw_entry:
        return default
    value = raw_entry[field]
    # TOML `true`/`false` are `bool`, which is an `int` subclass in Python —
    # reject explicitly so `x = true` is not silently coerced to `1.0`.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        logger.warning(
            "scratchpad registry: entry %s field %r expected a number, got %r",
            identity,
            field,
            value,
        )
        raise _SkipEntry

    numeric_value = float(value)
    if math.isnan(numeric_value) or math.isinf(numeric_value):
        logger.warning(
            "scratchpad registry: entry %s field %r has a non-finite value "
            "%r",
            identity,
            field,
            numeric_value,
        )
        raise _SkipEntry

    below_range = (
        numeric_value <= minimum if exclusive_min else numeric_value < minimum
    )
    if below_range or numeric_value > maximum:
        logger.warning(
            "scratchpad registry: entry %s field %r out of range: %r",
            identity,
            field,
            numeric_value,
        )
        raise _SkipEntry

    return numeric_value


def _coerce_bool(
    raw_entry: dict[str, Any], field: str, identity: str, default: bool
) -> bool:
    if field not in raw_entry:
        return default
    value = raw_entry[field]
    if not isinstance(value, bool):
        logger.warning(
            "scratchpad registry: entry %s field %r expected a boolean, got "
            "%r",
            identity,
            field,
            value,
        )
        raise _SkipEntry
    return value


def _apply_chromium_profile(
    command: str, profile_dir: str, identity: str
) -> tuple[str, str]:
    """Derive the final spawn command and match wm_class for a
    Chromium-family `profile_dir` entry.

    IMPORTANT: `profile_dir` is expanded with `os.path.expanduser` ONLY.
    `Path.resolve()` is deliberately NOT called: Chromium echoes the
    `--user-data-dir` argument back verbatim in WM_CLASS and does NOT
    resolve symlinks (verified empirically). Resolving the path here would
    make the derived match silently never fire for a symlinked profile dir.

    No filesystem write happens here either: Chromium creates the profile
    directory itself on first launch.
    """
    argv0 = command.split()[0] if command.split() else ""
    binary_name = os.path.basename(argv0).lower()
    if not any(marker in binary_name for marker in _CHROMIUM_BINARY_MARKERS):
        logger.warning(
            "scratchpad registry: entry %s sets profile_dir but command %r "
            "is not a recognized Chromium-family binary, skipping",
            identity,
            command,
        )
        raise _SkipEntry

    if "--user-data-dir" in command:
        logger.warning(
            "scratchpad registry: entry %s sets profile_dir but command %r "
            "already contains --user-data-dir, skipping",
            identity,
            command,
        )
        raise _SkipEntry

    expanded = os.path.expanduser(profile_dir)
    final_command = f"{command} --user-data-dir={expanded}"
    derived_wm_class = f"{_CHROMIUM_BASE_WM_CLASS} ({expanded})"
    return final_command, derived_wm_class


def _build_entry(
    raw_entry: dict[str, Any], source: str, index: int
) -> ScratchpadApp | None:
    """Validate, normalize and derive a single raw entry into a
    `ScratchpadApp`, or `None` if it must be skipped.

    Never raises: any failure (anticipated via `_SkipEntry`, or an
    unanticipated exception) is caught here and logged as a warning.
    """
    identity = _entry_identity(raw_entry, index, source)
    try:
        for field in raw_entry:
            if field not in _KNOWN_FIELDS:
                logger.warning(
                    "scratchpad registry: entry %s has unknown field %r, "
                    "ignoring",
                    identity,
                    field,
                )

        name = _require_str(raw_entry, "name", identity)
        command = _require_str(raw_entry, "command", identity)
        key = _optional_key(raw_entry, identity)
        label = _optional_str(raw_entry, "label", identity) or name
        icon = _optional_str(raw_entry, "icon", identity) or "utilities-terminal"

        x = _coerce_geometry(raw_entry, "x", identity, 0.25, minimum=0.0, maximum=1.0)
        y = _coerce_geometry(raw_entry, "y", identity, 0.15, minimum=0.0, maximum=1.0)
        width = _coerce_geometry(
            raw_entry,
            "width",
            identity,
            0.5,
            minimum=0.0,
            maximum=1.0,
            exclusive_min=True,
        )
        height = _coerce_geometry(
            raw_entry,
            "height",
            identity,
            0.6,
            minimum=0.0,
            maximum=1.0,
            exclusive_min=True,
        )
        opacity = _coerce_geometry(
            raw_entry, "opacity", identity, 1.0, minimum=0.0, maximum=1.0
        )

        on_focus_lost_hide = _coerce_bool(
            raw_entry, "on_focus_lost_hide", identity, True
        )
        warp_pointer = _coerce_bool(raw_entry, "warp_pointer", identity, True)
        desktop_entry = _coerce_bool(raw_entry, "desktop_entry", identity, True)

        match_wm_class = _optional_str(raw_entry, "match_wm_class", identity)
        match_title_regex = _optional_str(raw_entry, "match_title_regex", identity)
        profile_dir = _optional_str(raw_entry, "profile_dir", identity)

        if match_title_regex is not None:
            try:
                re.compile(match_title_regex)
            except re.error as error:
                logger.warning(
                    "scratchpad registry: entry %s has invalid "
                    "match_title_regex %r: %s",
                    identity,
                    match_title_regex,
                    error,
                )
                raise _SkipEntry from error

        if profile_dir is not None and match_wm_class is not None:
            logger.warning(
                "scratchpad registry: entry %s sets both profile_dir and "
                "match_wm_class, which are mutually exclusive",
                identity,
            )
            raise _SkipEntry

        if (
            match_title_regex is not None
            and match_wm_class is None
            and profile_dir is None
        ):
            logger.warning(
                "scratchpad registry: entry %s sets match_title_regex "
                "without match_wm_class or profile_dir; a bare title match "
                "is not permitted",
                identity,
            )
            raise _SkipEntry

        match: MatchSpec | None
        if profile_dir is not None:
            command, derived_wm_class = _apply_chromium_profile(
                command, profile_dir, identity
            )
            match = MatchSpec(wm_class=derived_wm_class, title_regex=match_title_regex)
        elif match_wm_class is not None or match_title_regex is not None:
            match = MatchSpec(wm_class=match_wm_class, title_regex=match_title_regex)
        else:
            match = None

        return ScratchpadApp(
            name=name,
            command=command,
            key=key,
            label=label,
            icon=icon,
            x=x,
            y=y,
            width=width,
            height=height,
            opacity=opacity,
            on_focus_lost_hide=on_focus_lost_hide,
            warp_pointer=warp_pointer,
            desktop_entry=desktop_entry,
            match=match,
        )
    except _SkipEntry:
        return None
    except Exception:
        logger.warning(
            "scratchpad registry: entry %s failed validation with an "
            "unexpected error, skipping",
            identity,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Public loader entrypoint
# ---------------------------------------------------------------------------


def load_scratchpads_from(
    base_path: Path, local_path: Path | None = None
) -> list[ScratchpadApp]:
    """Discover, parse, merge, validate, normalize and derive the scratchpad
    registry from `base_path` (e.g. `scratchpads.toml`) and an optional
    `local_path` override file (e.g. `scratchpads.local.toml`).

    NEVER raises. Any failure degrades to skipping the offending file or
    entry; zero valid entries after the full pipeline falls back to a single
    `BUILTIN_TERM` entry so the shipped terminal dropdown can never
    disappear.
    """
    try:
        base_entries = _read_registry_file(base_path, required=True)
        local_entries = _read_registry_file(local_path, required=False)
        merged = _merge_raw_entries(base_entries, local_entries)

        apps: list[ScratchpadApp] = []
        for index, (raw_entry, source) in enumerate(merged):
            app = _build_entry(raw_entry, source, index)
            if app is not None:
                apps.append(app)

        if not apps:
            logger.warning(
                "scratchpad registry: no valid entries found, falling back "
                "to the built-in terminal"
            )
            return [BUILTIN_TERM]

        return apps
    except Exception:
        # Absolute last-resort guard. Every stage above already catches
        # broadly, but a bug in the loader itself must never take qtile
        # down with it.
        logger.exception("scratchpad registry: unexpected loader failure")
        return [BUILTIN_TERM]


# ---------------------------------------------------------------------------
# Keybind collision helpers (no libqtile import — pure data)
# ---------------------------------------------------------------------------


def leader_is_free(
    taken: set[tuple[frozenset[str], str]], modifiers: list[str], key: str
) -> bool:
    """Whether the `(modifiers, key)` combo is free among already-bound
    top-level keys. Compares `(frozenset(modifiers), key)` tuples so
    modifier order never matters, and a superset/subset of modifiers is
    correctly treated as a different combo (e.g. `[mod] "s"` does not
    collide with `["shift", mod] "s"`)."""
    return (frozenset(modifiers), key) not in taken


def dedupe_chord_keys(entries: list[ScratchpadApp]) -> list[ScratchpadApp]:
    """Drop the chord submapping (`key`) of any entry whose `key` collides
    with an earlier entry's, or whose `key` is the reserved top-level term
    binding (`masculine`). The first-processed entry with a given key wins;
    losers keep their `DropDown` and `.desktop` entry (still reachable via
    rofi/IPC) but lose their chord submapping."""
    seen_keys: set[str] = set()
    result: list[ScratchpadApp] = []
    for entry in entries:
        if entry.key is None:
            result.append(entry)
            continue
        if entry.key == _RESERVED_CHORD_KEY or entry.key in seen_keys:
            logger.warning(
                "scratchpad registry: dropping chord key %r for entry %r "
                "(reserved or already used by another entry)",
                entry.key,
                entry.name,
            )
            result.append(replace(entry, key=None))
            continue
        seen_keys.add(entry.key)
        result.append(entry)
    return result
