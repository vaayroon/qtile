import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.utils.scratchpad_size import (
    MIN_FRACTION,
    Geometry,
    compute_placement,
    current_index,
    cycle_focused_dropdown,
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


# ---------------------------------------------------------------------------
# Glue: cycle_focused_dropdown against a duck-typed fake qtile
# ---------------------------------------------------------------------------


class FakeWindow:
    """Records place() calls and every attribute assignment."""

    def __init__(self, fail_place: bool = False) -> None:
        object.__setattr__(self, "assigned", [])
        self.bordercolor = "#fff"
        self.placed: list[tuple] = []
        self._fail_place = fail_place

    def __setattr__(self, name: str, value) -> None:
        self.assigned.append(name)
        object.__setattr__(self, name, value)

    def place(self, *args, **kwargs) -> None:
        if self._fail_place:
            raise RuntimeError("boom")
        self.placed.append((args, kwargs))


def _toggler(window, name: str = "term", geometry: Geometry = TERM) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        x=geometry.x,
        y=geometry.y,
        width=geometry.width,
        height=geometry.height,
        border_width=2,
        window=window,
    )


def _qtile(window, *togglers, screen=None, group: bool = True) -> SimpleNamespace:
    screen = screen or SimpleNamespace(dx=0, dy=0, dwidth=1000, dheight=800)
    groups_map = {}
    if group:
        groups_map["scratchpad"] = SimpleNamespace(
            dropdowns={t.name: t for t in togglers}
        )
    return SimpleNamespace(
        current_window=window, groups_map=groups_map, current_screen=screen
    )


def _defaults(*geometries: tuple[str, Geometry]):
    apps = [
        SimpleNamespace(name=n, x=g.x, y=g.y, width=g.width, height=g.height)
        for n, g in geometries
    ]
    return lambda: apps


TERM_DEFAULTS = _defaults(("term", TERM), ("calc", CALC))


def test_cycle_grows_to_medium_and_places_window() -> None:
    win = FakeWindow()
    dd = _toggler(win)
    cycle_focused_dropdown(_qtile(win, dd), "grow", TERM_DEFAULTS)
    assert (dd.x, dd.y, dd.width, dd.height) == pytest.approx((0.125, 0.05, 0.75, 0.8))
    ((args, kwargs),) = win.placed
    assert args[:4] == pytest.approx((125, 40, 746, 636), abs=1)
    assert args[4:] == (2, "#fff")
    assert kwargs == {"respect_hints": True}
    assert (win.float_x, win.float_y) == args[:2]
    assert not {"floating", "_float_state"} & set(win.assigned)


def test_cycle_shrink_then_grow_restores_default() -> None:
    win = FakeWindow()
    dd = _toggler(win)
    q = _qtile(win, dd)
    cycle_focused_dropdown(q, "shrink", TERM_DEFAULTS)
    assert (dd.width, dd.height) == pytest.approx((0.3, 0.36))
    cycle_focused_dropdown(q, "grow", TERM_DEFAULTS)
    assert (dd.x, dd.y, dd.width, dd.height) == pytest.approx(_as_tuple(TERM))


def test_cycle_uses_screen_offsets() -> None:
    win = FakeWindow()
    dd = _toggler(win)
    screen = SimpleNamespace(dx=1920, dy=100, dwidth=1000, dheight=800)
    cycle_focused_dropdown(_qtile(win, dd, screen=screen), "grow", TERM_DEFAULTS)
    assert win.placed[0][0][:2] == pytest.approx((2045, 140), abs=1)


def test_other_dropdowns_are_untouched() -> None:
    win, other_win = FakeWindow(), FakeWindow()
    dd, other = _toggler(win), _toggler(other_win, "calc", CALC)
    cycle_focused_dropdown(_qtile(win, dd, other), "grow", TERM_DEFAULTS)
    assert (other.x, other.width) == (CALC.x, CALC.width)
    assert other_win.placed == []


@pytest.mark.parametrize("case", ["no_window", "not_dropdown", "no_group"])
def test_noop_cases_log_debug(case: str, caplog: pytest.LogCaptureFixture) -> None:
    win = FakeWindow()
    dd = _toggler(win)
    if case == "no_window":
        q = _qtile(None, dd)
    elif case == "not_dropdown":
        q = _qtile(FakeWindow(), dd)
    else:
        q = _qtile(win, dd, group=False)
    with caplog.at_level("DEBUG", logger="libqtile"):
        cycle_focused_dropdown(q, "grow", TERM_DEFAULTS)
    assert win.placed == []
    assert (dd.x, dd.width) == (TERM.x, TERM.width)
    assert any(r.levelname == "DEBUG" for r in caplog.records)


def test_unknown_name_warns_and_noops(caplog: pytest.LogCaptureFixture) -> None:
    win = FakeWindow()
    dd = _toggler(win, "ghost")
    with caplog.at_level("WARNING", logger="libqtile"):
        cycle_focused_dropdown(_qtile(win, dd), "grow", TERM_DEFAULTS)
    assert win.placed == [] and dd.width == TERM.width
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_place_failure_keeps_new_fractions_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    win = FakeWindow(fail_place=True)
    dd = _toggler(win)
    with caplog.at_level("ERROR", logger="libqtile"):
        cycle_focused_dropdown(_qtile(win, dd), "grow", TERM_DEFAULTS)
    assert (dd.x, dd.y, dd.width, dd.height) == pytest.approx((0.125, 0.05, 0.75, 0.8))
    assert any(r.exc_info for r in caplog.records)


def test_provider_failure_is_caught(caplog: pytest.LogCaptureFixture) -> None:
    win = FakeWindow()
    dd = _toggler(win)

    def broken():
        raise OSError("no registry")

    with caplog.at_level("ERROR", logger="libqtile"):
        cycle_focused_dropdown(_qtile(win, dd), "grow", broken)
    assert win.placed == [] and dd.width == TERM.width
    assert any(r.exc_info for r in caplog.records)


def test_bad_direction_is_caught(caplog: pytest.LogCaptureFixture) -> None:
    win = FakeWindow()
    dd = _toggler(win)
    with caplog.at_level("ERROR", logger="libqtile"):
        cycle_focused_dropdown(_qtile(win, dd), "sideways", TERM_DEFAULTS)
    assert win.placed == []


# ---------------------------------------------------------------------------
# Contract against the installed libqtile (guards upstream drift)
# ---------------------------------------------------------------------------


@pytest.fixture
def libqtile_scratchpad():
    # Import order matters: backend first avoids a circular import.
    pytest.importorskip("libqtile.backend.x11.window")
    return pytest.importorskip("libqtile.scratchpad")


def _assigned_attrs(cls, method: str) -> set[str]:
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(cls, method))))
    return {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.ctx, ast.Store)
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
    }


@pytest.mark.usefixtures("libqtile_scratchpad")
def test_contract_window_place_signature() -> None:
    import inspect

    from libqtile.backend.x11.window import Window

    params = inspect.signature(Window.place).parameters
    for name in (
        "x",
        "y",
        "width",
        "height",
        "borderwidth",
        "bordercolor",
        "respect_hints",
    ):
        assert name in params


def test_contract_toggler_attributes(libqtile_scratchpad) -> None:
    ls = libqtile_scratchpad
    assigned = _assigned_attrs(ls.DropDownToggler, "__init__") | _assigned_attrs(
        ls.WindowVisibilityToggler, "__init__"
    )
    expected = {"name", "x", "y", "width", "height", "border_width", "window", "shown"}
    assert expected <= assigned
    assert isinstance(ls.WindowVisibilityToggler.visible, property)
    assert "dropdowns" in _assigned_attrs(ls.ScratchPad, "__init__")


def test_contract_formula_parity_with_real_show(libqtile_scratchpad) -> None:
    placed: list[tuple] = []
    win = SimpleNamespace(
        group=None,
        bordercolor="#abc",
        place=lambda *a, **_k: placed.append(a),
        togroup=lambda *_a, **_k: None,
        bring_to_front=lambda: None,
        qtile=SimpleNamespace(
            current_screen=SimpleNamespace(dx=70, dy=30, dwidth=1366, dheight=767)
        ),
    )
    toggler = object.__new__(libqtile_scratchpad.DropDownToggler)
    toggler.__dict__.update(
        window=win,
        shown=False,
        on_focus_lost_hide=False,
        warp_pointer=False,
        scratchpad_name="scratchpad",
        border_width=3,
        x=CALC.x,
        y=CALC.y,
        width=CALC.width,
        height=CALC.height,
    )
    toggler.show()
    expected = compute_placement(CALC, win.qtile.current_screen, 3)
    assert placed[0][:4] == expected
