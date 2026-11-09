"""Data-driven app launcher registry loader.

Reads ``launchers.toml`` (base, committed) and an optional
``launchers.local.toml`` (gitignored override) into a list of
:class:`LauncherApp` entries: a shell-free command plus the key combos that
spawn it. The merge rules are the scratchpad registry's (see
``utils.toml_registry``): a local entry REPLACES the base entry of the same
``name`` in full, ``enabled = false`` removes it, and a new name is appended.

The core launchers (terminal, dmenu, rofi) stay hard-coded in
``modules.keys`` so a broken registry never takes them away; an empty
registry is therefore valid and has no built-in fallback.

Like ``utils.scratchpads``, this module MUST NOT import ``libqtile`` and
MUST NOT raise during qtile config load. ``modules.keys`` turns the entries
into ``Key`` objects after dropping the combos `bindable_launchers` finds
already taken.
"""

import functools
import logging
import re
import shlex
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .toml_registry import load_raw_entries

# The "libqtile" logger by name, so warnings reach qtile.log without
# importing libqtile (see utils.scratchpads).
logger = logging.getLogger("libqtile")

_LABEL = "launcher registry"
_TABLE = "launcher"

_REPO_ROOT = Path(__file__).resolve().parents[2]  # src/utils/<this> -> repo

_KNOWN_FIELDS = {"name", "command", "keys", "desc", "enabled"}

# Same rule as the scratchpad launchers' filenames: a name stays usable as a
# file or option-free argument if launchers ever get `.desktop` files.
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

# Friendly modifier spellings for a `keys` combo. `mod` is the config's
# `settings.mod`, passed in by the caller. The raw X11 names are accepted
# too, so `mod4+e` and `mod+e` mean the same with the default mod.
_MODIFIER_ALIASES = {"alt": "mod1", "ctrl": "control"}
_X11_MODIFIERS = {"shift", "lock", "control", "mod1", "mod2", "mod3", "mod4", "mod5"}

# A `(frozenset(modifiers), key)` pair, the shape `utils.scratchpads` uses
# for its leader collision check.
ComboId = tuple[frozenset[str], str]


@dataclass(frozen=True, slots=True)
class Combo:
    """One key combo: X11 modifier names (in written order) and a keysym."""

    modifiers: tuple[str, ...]
    key: str

    @property
    def identity(self) -> ComboId:
        # Qtile looks keysyms up lowercased, so `E` and `e` grab the same key.
        return (frozenset(self.modifiers), self.key.lower())

    def __str__(self) -> str:
        return "+".join([*self.modifiers, self.key])


@dataclass(frozen=True, slots=True)
class LauncherApp:
    """A fully-validated launcher entry with at least one combo."""

    name: str
    command: str
    combos: tuple[Combo, ...]
    desc: str


class _SkipEntry(Exception):
    """Internal: the current entry failed validation. Never escapes."""


def parse_combo(text: str, mod: str) -> Combo | None:
    """`"mod+alt+e"` -> `Combo(("mod4", "mod1"), "e")` with `mod="mod4"`.

    Modifiers are case-insensitive; the key (the last `+`-separated part)
    is a keysym and keeps its case for display (Qtile ignores it, and so
    does `Combo.identity`). Whether the keysym exists is checked by
    `bindable_launchers`, given the known names. Returns None for a blank part,
    whitespace, an unknown or repeated modifier. Write `plus` for the `+`
    key itself."""
    if not text or any(character.isspace() for character in text):
        return None
    *raw_modifiers, key = text.split("+")
    if not key:
        return None
    modifiers: list[str] = []
    for raw in raw_modifiers:
        lowered = raw.lower()
        name = mod if lowered == "mod" else _MODIFIER_ALIASES.get(lowered, lowered)
        if name not in _X11_MODIFIERS or name in modifiers:
            return None
        modifiers.append(name)
    return Combo(tuple(modifiers), key)


def _require_str(raw_entry: dict[str, Any], field: str, identity: str) -> str:
    value = raw_entry.get(field)
    if not isinstance(value, str) or not value.strip():
        logger.warning(
            "%s: entry %s missing required field %r", _LABEL, identity, field
        )
        raise _SkipEntry
    return value


def _parse_combos(
    raw_entry: dict[str, Any], identity: str, mod: str
) -> tuple[Combo, ...]:
    """The entry's valid, distinct combos. An invalid combo is dropped on
    its own; no valid combo at all skips the entry."""
    raw_keys = raw_entry.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        logger.warning(
            "%s: entry %s needs 'keys', a non-empty array of combos such as "
            '["mod+alt+e"]',
            _LABEL,
            identity,
        )
        raise _SkipEntry
    combos: list[Combo] = []
    for raw in raw_keys:
        combo = parse_combo(raw, mod) if isinstance(raw, str) else None
        if combo is None:
            logger.warning(
                "%s: entry %s has an invalid combo %r, ignoring it",
                _LABEL,
                identity,
                raw,
            )
            continue
        if any(combo.identity == seen.identity for seen in combos):
            logger.warning(
                "%s: entry %s lists combo %r twice, ignoring the repeat",
                _LABEL,
                identity,
                raw,
            )
            continue
        combos.append(combo)
    if not combos:
        logger.warning("%s: entry %s has no valid combo, skipping", _LABEL, identity)
        raise _SkipEntry
    return tuple(combos)


def _build_entry(
    raw_entry: dict[str, Any], source: str, index: int, mod: str
) -> LauncherApp | None:
    """Validate one raw entry, or return None (with a warning) to skip it."""
    raw_name = raw_entry.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        identity = f"{raw_name!r} ({source})"
    else:
        identity = f"#{index} ({source})"
    try:
        for field in raw_entry:
            if field not in _KNOWN_FIELDS:
                logger.warning(
                    "%s: entry %s has unknown field %r, ignoring",
                    _LABEL,
                    identity,
                    field,
                )
        name = _require_str(raw_entry, "name", identity)
        if not _SAFE_NAME.fullmatch(name):
            logger.warning(
                "%s: entry %s name must be a letter or digit, then letters, "
                "digits, '.', '_' or '-'; skipping",
                _LABEL,
                identity,
            )
            raise _SkipEntry
        command = _require_str(raw_entry, "command", identity)
        try:
            # What Qtile's spawn does with a string; fail here, not on keypress.
            split_ok = "\0" not in command and bool(shlex.split(command))
        except ValueError:
            split_ok = False
        if not split_ok:
            logger.warning(
                "%s: entry %s has a 'command' that cannot be split into "
                "arguments (unbalanced quotes?): %r; skipping",
                _LABEL,
                identity,
                command,
            )
            raise _SkipEntry
        combos = _parse_combos(raw_entry, identity, mod)
        desc = raw_entry.get("desc", f"Launch {name}")
        if not isinstance(desc, str) or not desc.strip():
            logger.warning(
                "%s: entry %s has an invalid 'desc' %r, using the default",
                _LABEL,
                identity,
                desc,
            )
            desc = f"Launch {name}"
        return LauncherApp(name=name, command=command, combos=combos, desc=desc)
    except _SkipEntry:
        return None
    except Exception:
        logger.warning(
            "%s: entry %s failed validation with an unexpected error, skipping",
            _LABEL,
            identity,
            exc_info=True,
        )
        return None


def load_launchers_from(
    base_path: Path, local_path: Path | None = None, *, mod: str = "mod4"
) -> list[LauncherApp]:
    """Read, merge and validate the registry. `mod` is what a `mod` combo
    modifier stands for. NEVER raises; any failure skips the file or entry
    at fault, and an empty result is valid."""
    try:
        merged = load_raw_entries(base_path, local_path, table=_TABLE, label=_LABEL)
        apps = [
            _build_entry(raw_entry, source, index, mod)
            for index, (raw_entry, source) in enumerate(merged)
        ]
        return [app for app in apps if app is not None]
    except Exception:
        logger.exception("%s: unexpected loader failure", _LABEL)
        return []


@functools.lru_cache(maxsize=1)
def load_launchers(mod: str) -> list[LauncherApp]:
    """Memoized entrypoint for `modules.keys`: `launchers.toml` and
    `launchers.local.toml` from the repo root, read once per config load."""
    return load_launchers_from(
        _REPO_ROOT / "launchers.toml", _REPO_ROOT / "launchers.local.toml", mod=mod
    )


def bindable_launchers(
    apps: list[LauncherApp],
    taken: set[ComboId],
    known_keys: Collection[str] | None = None,
) -> list[LauncherApp]:
    """`apps` without the combos that cannot or must not be bound.

    `taken` holds the hard-coded combos, which always win; compare keys
    lowercased, as `Combo.identity` does. A combo in `taken` or used by an
    earlier entry is dropped with a warning naming both. With `known_keys`
    (lowercase keysym names), a combo whose key is not one of them is
    dropped too: Qtile rejects the whole config over a single unknown key.
    An entry left with no combo is dropped, since no key could launch it."""
    used = set(taken)
    result: list[LauncherApp] = []
    for app in apps:
        free: list[Combo] = []
        for combo in app.combos:
            if known_keys is not None and combo.key.lower() not in known_keys:
                logger.warning(
                    "%s: %s for entry %r is not a known key name; combo skipped",
                    _LABEL,
                    combo,
                    app.name,
                )
                continue
            if combo.identity in used:
                logger.warning(
                    "%s: %s for entry %r is already bound; combo skipped",
                    _LABEL,
                    combo,
                    app.name,
                )
                continue
            used.add(combo.identity)
            free.append(combo)
        if not free:
            logger.warning(
                "%s: entry %r has no free combo left; launcher skipped",
                _LABEL,
                app.name,
            )
            continue
        result.append(
            LauncherApp(
                name=app.name, command=app.command, combos=tuple(free), desc=app.desc
            )
        )
    return result
