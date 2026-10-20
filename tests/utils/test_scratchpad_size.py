import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.utils.scratchpad_size import (
    MIN_FRACTION,
    Geometry,
    compute_placement,
    current_index,
    derive_presets,
    step,
)

TERM = Geometry(0.25, 0.15, 0.5, 0.6)
CALC = Geometry(0.375, 0.2, 0.25, 0.5)


def _as_tuple(g: Geometry) -> tuple[float, float, float, float]:
    return (g.x, g.y, g.width, g.height)


def _by_label(presets):
    return {p.label: p.geometry for p in presets}


def _area(g: Geometry) -> float:
    return g.width * g.height


def test_module_has_no_libqtile_import() -> None:
    import src.utils.scratchpad_size as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "libqtile" not in roots
    assert "libqtile" not in module.__dict__


def test_derive_presets_for_term_default() -> None:
    presets = derive_presets(TERM)
    assert [p.label for p in presets] == ["full", "medium", "default", "small"]
    g = _by_label(presets)
    assert _as_tuple(g["full"]) == (0, 0, 1, 1)
    assert _as_tuple(g["default"]) == _as_tuple(TERM)
    assert _as_tuple(g["medium"]) == pytest.approx((0.125, 0.05, 0.75, 0.8))
    assert _as_tuple(g["small"]) == pytest.approx((0.35, 0.27, 0.3, 0.36))


def test_derive_presets_for_calc_default_is_strictly_ordered() -> None:
    presets = derive_presets(CALC)
    g = _by_label(presets)
    assert _as_tuple(g["medium"]) == pytest.approx((0.1875, 0.075, 0.625, 0.75))
    assert _as_tuple(g["small"]) == pytest.approx((0.425, 0.3, 0.15, 0.3))
    areas = [_area(p.geometry) for p in presets]
    assert areas == sorted(areas, reverse=True)
    assert len(set(areas)) == 4


def test_derive_presets_square_default() -> None:
    g = _by_label(derive_presets(Geometry(0.1, 0.1, 0.8, 0.8)))
    assert _as_tuple(g["medium"]) == pytest.approx((0.05, 0.05, 0.9, 0.9))
    assert _as_tuple(g["small"]) == pytest.approx((0.26, 0.26, 0.48, 0.48))


def test_derived_presets_are_clamped_near_edge() -> None:
    g = _by_label(derive_presets(Geometry(0.7, 0.7, 0.3, 0.3)))
    assert _as_tuple(g["medium"]) == pytest.approx((0.35, 0.35, 0.65, 0.65))
    for label in ("medium", "small"):
        p = g[label]
        assert p.x >= 0 and p.y >= 0
        assert p.x + p.width <= 1 + 1e-9 and p.y + p.height <= 1 + 1e-9


def test_small_preset_respects_floor() -> None:
    g = _by_label(derive_presets(Geometry(0.4, 0.4, 0.02, 0.5)))
    assert MIN_FRACTION == 0.05
    assert g["small"].width == pytest.approx(0.05)
    assert g["small"].height == pytest.approx(0.3)


def test_default_already_full_collapses_to_two_presets() -> None:
    presets = derive_presets(Geometry(0, 0, 1, 1))
    assert [p.label for p in presets] == ["default", "small"]


def test_off_canvas_default_is_kept_verbatim() -> None:
    default = Geometry(0.5, 0.5, 0.8, 0.8)
    presets = derive_presets(default)
    assert _by_label(presets)["default"] == default
    for p in presets:
        if p.label not in ("default", "full"):
            g = p.geometry
            assert 0 <= g.x and g.x + g.width <= 1 + 1e-9


def test_current_index_matches_with_noise_and_falls_back_to_default() -> None:
    presets = derive_presets(TERM)
    medium = presets[1].geometry
    noisy = Geometry(medium.x + 1e-9, medium.y, medium.width, medium.height - 1e-9)
    assert current_index(presets, noisy) == 1
    assert current_index(presets, Geometry(0.9, 0.9, 0.05, 0.05)) == 2


@pytest.mark.parametrize(
    ("index", "direction", "expected"),
    [
        (2, "grow", 1),
        (1, "grow", 0),
        (0, "grow", 3),
        (2, "shrink", 3),
        (3, "shrink", 0),
    ],
)
def test_step_wraps_both_ways(index: int, direction: str, expected: int) -> None:
    assert step(index, 4, direction) == expected


def test_step_full_cycle_returns_to_start() -> None:
    for direction in ("grow", "shrink"):
        i = 2
        for _ in range(4):
            i = step(i, 4, direction)
        assert i == 2
    assert step(step(2, 4, "grow"), 4, "shrink") == 2
    assert step(0, 1, "grow") == 0


def test_step_rejects_bad_direction() -> None:
    with pytest.raises(ValueError):
        step(0, 4, "sideways")


def test_compute_placement_uses_screen_offsets_and_border() -> None:
    screen = SimpleNamespace(dx=100, dy=50, dwidth=1000, dheight=800)
    assert compute_placement(TERM, screen, 2) == (
        int(100 + 0.25 * 1000),
        int(50 + 0.15 * 800),
        int(1000 * 0.5) - 4,
        int(800 * 0.6) - 4,
    )
