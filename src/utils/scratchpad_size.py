"""Size presets for scratchpad dropdowns.

Pure preset math (derive, detect, step, pixel placement) plus a duck-typed
glue function that re-places the focused dropdown. This module MUST NOT
import ``libqtile``: Qtile wiring lives in ``modules.keys``.

Never-crash contract: the glue entry point catches every exception and logs
it, so a bad keypress can never take Qtile down.
"""

import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

# Same logger object qtile configures, without importing libqtile.
logger = logging.getLogger("libqtile")

MIN_FRACTION = 0.05
_ABS_TOL = 1e-6
_SMALL_FACTOR = 0.6

Direction = Literal["grow", "shrink"]


@dataclass(frozen=True, slots=True)
class Geometry:
    """Window geometry as fractions of the screen."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Preset:
    label: str  # full | medium | default | small
    geometry: Geometry


@dataclass(frozen=True, slots=True)
class PresetOverrides:
    """Optional user-chosen medium/small sizes (fractions of the screen).

    `None` means "derive this dimension"; `PresetOverrides()` derives all.
    """

    medium_width: float | None = None
    medium_height: float | None = None
    small_width: float | None = None
    small_height: float | None = None


def _close(a: Geometry, b: Geometry) -> bool:
    return all(
        math.isclose(p, q, abs_tol=_ABS_TOL)
        for p, q in (
            (a.x, b.x),
            (a.y, b.y),
            (a.width, b.width),
            (a.height, b.height),
        )
    )


def _centered(center: float, size: float) -> float:
    """Start coordinate of a span of `size` around `center`, kept in [0, 1]."""
    return min(max(center - size / 2, 0.0), 1.0 - size)


def _derived(default: Geometry, width: float, height: float) -> Geometry:
    width, height = min(width, 1.0), min(height, 1.0)
    return Geometry(
        _centered(default.x + default.width / 2, width),
        _centered(default.y + default.height / 2, height),
        width,
        height,
    )


def derive_presets(
    default: Geometry, overrides: PresetOverrides | None = None
) -> list[Preset]:
    """Return the distinct presets ordered largest to smallest.

    Order is full, medium, default, small. Derived presets that coincide with
    the default or an earlier one are dropped; the default is never altered.
    An override replaces the derived width/height of its preset as given
    (the small cap does not apply); the preset stays centered and clamped.
    """
    o = overrides or PresetOverrides()
    w, h = default.width, default.height
    mw = o.medium_width if o.medium_width is not None else (w + 1) / 2
    mh = o.medium_height if o.medium_height is not None else (h + 1) / 2
    sw = (
        o.small_width
        if o.small_width is not None
        else min(w, max(w * _SMALL_FACTOR, MIN_FRACTION))
    )
    sh = (
        o.small_height
        if o.small_height is not None
        else min(h, max(h * _SMALL_FACTOR, MIN_FRACTION))
    )
    candidates = [
        Preset("full", Geometry(0.0, 0.0, 1.0, 1.0)),
        Preset("medium", _derived(default, mw, mh)),
        Preset("default", default),
        Preset("small", _derived(default, sw, sh)),
    ]
    kept: list[Preset] = []
    for preset in candidates:
        if preset.label != "default" and (
            _close(preset.geometry, default)
            or any(_close(preset.geometry, k.geometry) for k in kept)
        ):
            continue
        kept.append(preset)
    return kept


def current_index(presets: list[Preset], current: Geometry) -> int:
    """Index of the preset matching `current`, else the default's index."""
    fallback = 0
    for i, preset in enumerate(presets):
        if _close(preset.geometry, current):
            return i
        if preset.label == "default":
            fallback = i
    return fallback


def step(index: int, n: int, direction: Direction) -> int:
    """Next preset index; grow moves toward full, shrink toward small."""
    if direction == "grow":
        return (index - 1) % n
    if direction == "shrink":
        return (index + 1) % n
    raise ValueError(f"invalid direction: {direction!r}")


def compute_placement(
    g: Geometry, screen: Any, border_width: int
) -> tuple[int, int, int, int]:
    """Pixel x, y, width, height; mirrors Qtile's DropDownToggler.show()."""
    return (
        int(screen.dx + g.x * screen.dwidth),
        int(screen.dy + g.y * screen.dheight),
        int(screen.dwidth * g.width) - 2 * border_width,
        int(screen.dheight * g.height) - 2 * border_width,
    )


def _overrides_of(entry: Any) -> PresetOverrides:
    """Preset overrides carried by a registry entry; missing attributes (older
    entries, duck-typed fakes) mean "no override"."""
    return PresetOverrides(
        *(
            getattr(entry, field, None)
            for field in (
                "medium_width",
                "medium_height",
                "small_width",
                "small_height",
            )
        )
    )


def find_focused_dropdown(qtile: Any) -> tuple[str, Any] | None:
    """The (name, toggler) owning the focused window, or None."""
    win = qtile.current_window
    pad = qtile.groups_map.get("scratchpad")
    if win is None or pad is None:
        return None
    for name, toggler in pad.dropdowns.items():
        if toggler.window is win:
            return name, toggler
    return None


def cycle_focused_dropdown(
    qtile: Any, direction: Direction, defaults: Callable[[], Iterable[Any]]
) -> None:
    """Move the focused dropdown to its next size preset.

    `defaults` returns the registry entries (name, x, y, width, height) the
    dropdowns were built from. The new fractions are stored on the toggler
    BEFORE placing, so a failing place() still converges on the next show().
    Qtile >= 0.37 builds that size from ``toggler.geometry`` (a tuple) and
    ignores ``x/y/width/height``, so both are kept in sync.
    Never raises and never touches the window's floating state. The chosen
    size intentionally persists across hide/show until the config is reloaded.
    """
    try:
        found = find_focused_dropdown(qtile)
        if found is None:
            logger.debug("scratchpad size: focused window is not a dropdown")
            return
        name, dd = found
        entry = next((e for e in defaults() if e.name == name), None)
        if entry is None:
            logger.warning("scratchpad size: no registry entry for %r", name)
            return
        presets = derive_presets(
            Geometry(entry.x, entry.y, entry.width, entry.height),
            _overrides_of(entry),
        )
        if len(presets) < 2:
            logger.debug("scratchpad size: %r has a single preset", name)
            return
        current = Geometry(dd.x, dd.y, dd.width, dd.height)
        target = presets[step(current_index(presets, current), len(presets), direction)]
        g = target.geometry
        dd.x, dd.y, dd.width, dd.height = g.x, g.y, g.width, g.height
        dd.geometry = (g.x, g.y, g.width, g.height)
        x, y, w, h = compute_placement(g, qtile.current_screen, dd.border_width)
        win = dd.window
        win.float_x, win.float_y = x, y
        win.place(x, y, w, h, dd.border_width, win.bordercolor, respect_hints=True)
    except Exception:
        logger.exception("scratchpad size: failed to cycle focused dropdown")
