"""Shared discover, parse and merge stages for the TOML registries.

A registry is a committed base file (``scratchpads.toml``,
``launchers.toml``) plus an optional gitignored local override file next to
it. Each file holds an array of tables (``[[scratchpad]]``, ``[[launcher]]``)
whose entries are keyed by ``name``. This module turns both files into one
ordered list of raw entry dicts; each registry validates the dicts itself.

Like its callers, this module MUST NOT import ``libqtile`` and MUST NOT
raise: a missing, unreadable or malformed file contributes zero entries plus
a logged warning. ``label`` (e.g. ``"scratchpad registry"``) prefixes every
message so the log names the registry at fault.
"""

import logging
import tomllib
from pathlib import Path
from typing import Any

# The "libqtile" logger by name, so messages reach qtile.log without
# importing libqtile (see utils.scratchpads).
logger = logging.getLogger("libqtile")

# A raw TOML entry carries its source file alongside it through the pipeline
# so warnings can name the offending file.
RawEntry = tuple[dict[str, Any], str]


def _parse_toml_file(path: Path, source: str, table: str, label: str) -> list[RawEntry]:
    """Parse one already-existing TOML file into raw entry dicts.

    Never raises: any failure (not a regular file, malformed TOML, an
    unanticipated exception from `tomllib.load`) degrades to "this file
    contributes zero entries" plus a logged warning/exception.
    """
    if not path.is_file():
        logger.warning("%s: %s is not a regular file, skipping", label, source)
        return []

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        logger.warning("%s: %s has invalid TOML: %s", label, source, error)
        return []
    except Exception:
        # Catches anything else tomllib (or the filesystem) can throw:
        # UnicodeDecodeError, OSError family, RecursionError, MemoryError,
        # or an exception type nobody anticipated.
        logger.exception("%s: unexpected error reading %s", label, source)
        return []

    if not isinstance(data, dict):
        logger.warning("%s: %s root is not a table, skipping", label, source)
        return []

    raw_entries = data.get(table, [])
    if not isinstance(raw_entries, list):
        logger.warning(
            "%s: %s %r key is not an array of tables, skipping",
            label,
            source,
            table,
        )
        return []

    entries: list[RawEntry] = []
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            logger.warning(
                "%s: %s entry #%d is not a table, skipping", label, source, index
            )
            continue
        entries.append((raw_entry, source))
    return entries


def read_registry_file(
    path: Path | None, *, required: bool, table: str, label: str
) -> list[RawEntry]:
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
        logger.warning("%s: could not stat %s", label, source)
        return []

    if not exists:
        if required:
            logger.warning("%s: %s not found, treating as empty", label, source)
        return []

    return _parse_toml_file(path, source, table, label)


def _has_name(raw_entry: dict[str, Any]) -> bool:
    name = raw_entry.get("name")
    return isinstance(name, str) and bool(name.strip())


def _dedupe_named(
    entries: list[RawEntry], file_label: str, label: str
) -> list[RawEntry]:
    """Keep the first entry per `name` within a single file; entries with a
    missing/blank name pass through untouched (the validate stage handles
    the missing-name case with the right identity)."""
    seen: set[str] = set()
    result: list[RawEntry] = []
    for raw_entry, source in entries:
        if not _has_name(raw_entry):
            result.append((raw_entry, source))
            continue
        name = raw_entry["name"]
        if name in seen:
            logger.warning(
                "%s: duplicate entry name=%r in %s, keeping first occurrence",
                label,
                name,
                file_label,
            )
            continue
        seen.add(name)
        result.append((raw_entry, source))
    return result


def merge_raw_entries(
    base_entries: list[RawEntry], local_entries: list[RawEntry], label: str
) -> list[RawEntry]:
    """Merge the local override file into the base registry by `name`.

    A local entry sharing a `name` with a base entry REPLACES it in full
    (whole-entry override, not per-field merge). A local entry with a new
    `name` is appended. A local entry with `enabled = false` removes the
    matching base entry entirely.
    """
    base = _dedupe_named(base_entries, "base file", label)
    local = _dedupe_named(local_entries, "local file", label)

    by_name: dict[str, RawEntry] = {}
    order: list[str] = []
    unnamed: list[RawEntry] = []

    for raw_entry, source in base:
        if _has_name(raw_entry):
            name = raw_entry["name"]
            by_name[name] = (raw_entry, source)
            order.append(name)
        else:
            unnamed.append((raw_entry, source))

    for raw_entry, source in local:
        if not _has_name(raw_entry):
            unnamed.append((raw_entry, source))
            continue
        name = raw_entry["name"]
        if raw_entry.get("enabled") is False:
            if name in by_name:
                by_name.pop(name)
                order.remove(name)
            continue
        if name not in by_name:
            order.append(name)
        by_name[name] = (raw_entry, source)  # whole-entry replace

    return [by_name[name] for name in order] + unnamed


def load_raw_entries(
    base_path: Path, local_path: Path | None, *, table: str, label: str
) -> list[RawEntry]:
    """Read both files and merge them: the input of a registry's validate
    stage. Never raises for file problems (see `read_registry_file`)."""
    base_entries = read_registry_file(
        base_path, required=True, table=table, label=label
    )
    local_entries = read_registry_file(
        local_path, required=False, table=table, label=label
    )
    return merge_raw_entries(base_entries, local_entries, label)
