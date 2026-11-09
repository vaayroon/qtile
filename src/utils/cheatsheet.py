"""Keybinding cheat sheet, rendered from ``Key.desc`` and ``KeyChord.desc``.

Free of any ``libqtile`` import so it is testable without Qtile: bindings
are read by duck typing. A binding with ``submappings`` is a chord; its
rows come out as ``mod + s``, then ``mod + s, then n`` for each sub-key. A
key without commands is the ``Escape`` that ``KeyChord`` appends itself and
is skipped.

``modules.keys.cheatsheet_sections`` provides the input; ``to_markdown``
and ``to_lines`` render it.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

# Display order and label of the X11 modifiers this config uses. Any other
# modifier (mod2, mod3, mod5, lock) keeps its raw name and sorts after these.
_MODIFIER_LABELS = {"mod4": "mod", "control": "Ctrl", "mod1": "Alt", "shift": "Shift"}
_MODIFIER_ORDER = list(_MODIFIER_LABELS)

# Keysyms whose name hides the key printed on the keycap.
_KEY_LABELS = {"masculine": "º"}


@dataclass(frozen=True)
class Row:
    keys: str
    desc: str


@dataclass(frozen=True)
class Section:
    title: str
    rows: tuple[Row, ...]


def format_combo(modifiers: Sequence[str], key: str | int) -> str:
    """`["shift", "mod4"], "c"` -> `"mod + Shift + c"`, whatever the
    modifier order in the binding."""
    known = [m for m in _MODIFIER_ORDER if m in modifiers]
    unknown = sorted(m for m in modifiers if m not in _MODIFIER_LABELS)
    labels = [_MODIFIER_LABELS[m] for m in known] + unknown
    key_label = hex(key) if isinstance(key, int) else _KEY_LABELS.get(key, key)
    return " + ".join([*labels, key_label])


def binding_rows(binding: Any, prefix: str = "") -> list[Row]:
    """The rows of one `Key` or `KeyChord`, chord submappings included."""
    combo = format_combo(binding.modifiers, binding.key)
    if prefix:
        combo = f"{prefix}, then {combo}"
    submappings = getattr(binding, "submappings", None)
    if submappings is not None:
        rows = [Row(combo, binding.desc)]
        for sub in submappings:
            rows.extend(binding_rows(sub, combo))
        return rows
    if not binding.commands:
        return []
    return [Row(combo, binding.desc)]


def build_sections(sections: Iterable[tuple[str, Sequence[Any]]]) -> list[Section]:
    """`(title, bindings)` pairs -> `Section`s, dropping empty ones."""
    built = []
    for title, bindings in sections:
        rows = tuple(row for binding in bindings for row in binding_rows(binding))
        if rows:
            built.append(Section(title, rows))
    return built


def _markdown_cell(text: str) -> str:
    return text.replace("|", "\\|")


def to_markdown(sections: Sequence[Section], heading: str = "###") -> str:
    """One `Keys | Action` table per section, under a `heading` title."""
    blocks = []
    for section in sections:
        lines = [f"{heading} {section.title}", "", "| Keys | Action |", "|---|---|"]
        lines += [
            f"| `{row.keys}` | {_markdown_cell(row.desc)} |" for row in section.rows
        ]
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


def to_lines(sections: Sequence[Section]) -> list[str]:
    """One aligned `keys  desc  [section]` line per row, for a rofi list."""
    width = max((len(row.keys) for s in sections for row in s.rows), default=0)
    return [
        f"{row.keys.ljust(width)}  {row.desc}  [{section.title}]"
        for section in sections
        for row in section.rows
    ]
