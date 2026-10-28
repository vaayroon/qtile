import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.utils.scratchpad_size import (
    MIN_FRACTION,
    Geometry,
    PresetOverrides,
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
    g = _by_label(derive_presets(Geometry(0.4, 0.4, 0.06, 0.5)))
    assert MIN_FRACTION == 0.05
    assert g["small"].width == pytest.approx(0.05)
    assert g["small"].height == pytest.approx(0.3)


def test_small_preset_never_grows_a_tiny_default() -> None:
    g = _by_label(derive_presets(Geometry(0.4, 0.4, 0.02, 0.5)))
    assert g["small"].width == pytest.approx(0.02)
    assert g["small"].width <= g["default"].width
    assert g["small"].height == pytest.approx(0.3)


def test_small_equal_to_default_is_dropped() -> None:
    default = Geometry(0.4, 0.4, 0.02, 0.02)
    presets = derive_presets(default)
    assert [p.label for p in presets] == ["full", "medium", "default"]
    assert _by_label(presets)["default"] == default


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


SQUARE = Geometry(0.1, 0.1, 0.8, 0.8)


def _labels(presets) -> list[str]:
    return [p.label for p in presets]


@pytest.mark.parametrize("default", [TERM, CALC, SQUARE])
def test_no_overrides_forms_are_identical(default: Geometry) -> None:
    baseline = derive_presets(default)
    assert derive_presets(default, None) == baseline
    assert derive_presets(default, PresetOverrides()) == baseline


def test_full_override_replaces_derived_sizes_centered() -> None:
    o = PresetOverrides(0.95, 0.95, 0.3, 0.2)
    g = _by_label(derive_presets(SQUARE, o))
    assert _as_tuple(g["medium"]) == pytest.approx((0.025, 0.025, 0.95, 0.95))
    assert _as_tuple(g["small"]) == pytest.approx((0.35, 0.4, 0.3, 0.2))
    assert _as_tuple(g["full"]) == (0, 0, 1, 1)
    assert _as_tuple(g["default"]) == _as_tuple(SQUARE)


def test_partial_override_keeps_derived_other_dimension() -> None:
    g = _by_label(derive_presets(SQUARE, PresetOverrides(medium_width=0.95)))
    assert _as_tuple(g["medium"]) == pytest.approx((0.025, 0.05, 0.95, 0.9))
    g = _by_label(derive_presets(SQUARE, PresetOverrides(small_height=0.3)))
    assert _as_tuple(g["small"]) == pytest.approx((0.26, 0.35, 0.48, 0.3))


def test_override_near_edge_is_clamped_inside_canvas() -> None:
    edge = Geometry(0.7, 0.7, 0.3, 0.3)
    g = _by_label(derive_presets(edge, PresetOverrides(medium_width=0.9)))
    assert g["medium"].x == pytest.approx(0.1)
    assert g["medium"].x + g["medium"].width <= 1 + 1e-9


def test_override_of_one_spans_the_axis() -> None:
    g = _by_label(derive_presets(SQUARE, PresetOverrides(medium_width=1.0)))
    assert (g["medium"].x, g["medium"].width) == (0.0, 1.0)


def test_small_override_may_exceed_default_without_cap() -> None:
    g = _by_label(derive_presets(TERM, PresetOverrides(small_width=0.6)))
    assert g["small"].width == pytest.approx(0.6)


def test_medium_override_equal_to_default_is_dropped() -> None:
    o = PresetOverrides(medium_width=0.8, medium_height=0.8)
    assert _labels(derive_presets(SQUARE, o)) == ["full", "default", "small"]


def test_small_override_equal_to_default_is_dropped() -> None:
    o = PresetOverrides(small_width=0.8, small_height=0.8)
    assert _labels(derive_presets(SQUARE, o)) == ["full", "medium", "default"]


def test_small_override_equal_to_medium_drops_small() -> None:
    o = PresetOverrides(small_width=0.9, small_height=0.9)
    assert _labels(derive_presets(SQUARE, o)) == ["full", "medium", "default"]


def test_medium_override_equal_to_full_is_dropped() -> None:
    o = PresetOverrides(medium_width=1.0, medium_height=1.0)
    assert _labels(derive_presets(SQUARE, o)) == ["full", "default", "small"]


def test_all_collapsing_overrides_leave_a_single_default() -> None:
    full = Geometry(0.0, 0.0, 1.0, 1.0)
    o = PresetOverrides(1.0, 1.0, 1.0, 1.0)
    assert _labels(derive_presets(full, o)) == ["default"]


def test_out_of_order_overrides_are_kept_in_label_order() -> None:
    o = PresetOverrides(medium_width=0.5, medium_height=0.5, small_width=0.85)
    presets = derive_presets(SQUARE, o)
    assert _labels(presets) == ["full", "medium", "default", "small"]
    g = _by_label(presets)
    assert g["medium"].width < g["default"].width < g["small"].width


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
        geometry=_as_tuple(geometry),  # qtile >= 0.37: what show() reads
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


def _entry_defaults(**overrides: float):
    entry = SimpleNamespace(
        name="term",
        x=SQUARE.x,
        y=SQUARE.y,
        width=SQUARE.width,
        height=SQUARE.height,
        **overrides,
    )
    return lambda: [entry]


def test_cycle_uses_entry_overrides() -> None:
    win = FakeWindow()
    dd = _toggler(win, geometry=SQUARE)
    defaults = _entry_defaults(medium_width=0.95, medium_height=0.95)
    cycle_focused_dropdown(_qtile(win, dd), "grow", defaults)
    assert (dd.x, dd.y, dd.width, dd.height) == pytest.approx(
        (0.025, 0.025, 0.95, 0.95)
    )
    ((args, _kwargs),) = win.placed
    assert args[:4] == pytest.approx((25, 20, 946, 756), abs=1)


def test_cycle_wraps_and_is_stateless_over_overridden_list() -> None:
    win = FakeWindow()
    dd = _toggler(win, geometry=SQUARE)
    q = _qtile(win, dd)
    defaults = _entry_defaults(small_width=0.3, small_height=0.2)
    cycle_focused_dropdown(q, "shrink", defaults)
    assert (dd.width, dd.height) == pytest.approx((0.3, 0.2))
    cycle_focused_dropdown(q, "shrink", defaults)  # wraps small -> full
    assert (dd.x, dd.y, dd.width, dd.height) == (0.0, 0.0, 1.0, 1.0)
    cycle_focused_dropdown(q, "grow", defaults)  # full -> small (wrap back)
    assert (dd.width, dd.height) == pytest.approx((0.3, 0.2))


def test_entry_without_override_attributes_behaves_as_no_overrides() -> None:
    win = FakeWindow()
    dd = _toggler(win)
    cycle_focused_dropdown(_qtile(win, dd), "grow", TERM_DEFAULTS)  # bare fakes
    assert (dd.x, dd.y, dd.width, dd.height) == pytest.approx((0.125, 0.05, 0.75, 0.8))


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


def test_place_failure_keeps_old_fractions_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    win = FakeWindow(fail_place=True)
    dd = _toggler(win)
    with caplog.at_level("ERROR", logger="libqtile"):
        cycle_focused_dropdown(_qtile(win, dd), "grow", TERM_DEFAULTS)
    assert (dd.x, dd.y, dd.width, dd.height) == _as_tuple(TERM)
    assert any(r.exc_info for r in caplog.records)


def test_cycle_keeps_geometry_in_sync_with_fractions() -> None:
    win = FakeWindow()
    dd = _toggler(win)
    q = _qtile(win, dd)
    cycle_focused_dropdown(q, "grow", TERM_DEFAULTS)
    assert dd.geometry == pytest.approx((0.125, 0.05, 0.75, 0.8))
    cycle_focused_dropdown(q, "shrink", TERM_DEFAULTS)  # back to default
    assert dd.geometry == pytest.approx(_as_tuple(TERM))


def test_place_failure_keeps_old_geometry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    win = FakeWindow(fail_place=True)
    dd = _toggler(win)
    with caplog.at_level("ERROR", logger="libqtile"):
        cycle_focused_dropdown(_qtile(win, dd), "grow", TERM_DEFAULTS)
    assert dd.geometry == _as_tuple(TERM)


@pytest.mark.parametrize(
    ("direction", "label"), [("grow", "medium"), ("shrink", "small")]
)
def test_failed_place_then_cycle_lands_on_adjacent_preset(
    caplog: pytest.LogCaptureFixture, direction, label
) -> None:
    # A failed place() must not count as a step: the next cycle starts from
    # the size the window still has, so it reaches the adjacent preset.
    win = FakeWindow(fail_place=True)
    dd = _toggler(win)
    q = _qtile(win, dd)
    with caplog.at_level("ERROR", logger="libqtile"):
        cycle_focused_dropdown(q, direction, TERM_DEFAULTS)
    win._fail_place = False
    cycle_focused_dropdown(q, direction, TERM_DEFAULTS)
    preset = _by_label(derive_presets(TERM))[label]
    assert (dd.x, dd.y, dd.width, dd.height) == pytest.approx(_as_tuple(preset))
    ((args, _kwargs),) = win.placed
    assert args[:4] == compute_placement(preset, q.current_screen, 2)


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
    assert any(r.levelname == "ERROR" and r.exc_info for r in caplog.records)


def test_single_remaining_preset_is_a_logged_noop(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.utils.scratchpad_size as module

    only = module.Preset("default", TERM)
    monkeypatch.setattr(module, "derive_presets", lambda *_args: [only])
    win = FakeWindow()
    dd = _toggler(win)
    with caplog.at_level("DEBUG", logger="libqtile"):
        cycle_focused_dropdown(_qtile(win, dd), "grow", TERM_DEFAULTS)
    assert win.placed == []
    assert (dd.x, dd.y, dd.width, dd.height) == _as_tuple(TERM)
    assert any("single preset" in r.getMessage() for r in caplog.records)


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
    expected = {
        "name",
        "x",
        "y",
        "width",
        "height",
        "geometry",  # show() reads this tuple, not x/y/width/height
        "border_width",
        "window",
        "shown",
    }
    assert expected <= assigned
    assert isinstance(ls.WindowVisibilityToggler.visible, property)
    assert "dropdowns" in _assigned_attrs(ls.ScratchPad, "__init__")


def _real_toggler(libqtile_scratchpad, window, geometry: Geometry, name: str = "term"):
    """A real DropDownToggler without running __init__ (needs a live qtile)."""
    real = object.__new__(libqtile_scratchpad.DropDownToggler)
    real.__dict__.update(
        name=name,
        window=window,
        shown=False,
        _hooked=False,
        on_focus_lost_hide=False,
        warp_pointer=False,
        scratchpad_name="scratchpad",
        border_width=3,
        x=geometry.x,
        y=geometry.y,
        width=geometry.width,
        height=geometry.height,
        geometry=_as_tuple(geometry),
    )
    return real


def test_contract_formula_parity_with_real_show(libqtile_scratchpad) -> None:
    screen = SimpleNamespace(dx=70, dy=30, dwidth=1366, dheight=767)
    medium = _by_label(derive_presets(CALC))["medium"]

    # What the real libqtile show() passes to place() for the medium geometry.
    real_calls: list[tuple] = []
    real_win = SimpleNamespace(
        group=None,
        bordercolor="#abc",
        place=lambda *a, **k: real_calls.append((a, k)),
        togroup=lambda *_a, **_k: None,
        bring_to_front=lambda: None,
        qtile=SimpleNamespace(current_screen=screen),
    )
    _real_toggler(libqtile_scratchpad, real_win, medium).show()

    # What our glue passes when growing the calc default to the same preset.
    win = FakeWindow()
    win.bordercolor = "#abc"
    dd = _toggler(win, "calc", CALC)
    dd.border_width = 3
    cycle_focused_dropdown(
        _qtile(win, dd, screen=screen), "grow", _defaults(("calc", CALC))
    )

    assert len(real_calls) == len(win.placed) == 1
    assert win.placed[0] == real_calls[0]


def test_failed_place_next_real_show_keeps_old_size(libqtile_scratchpad) -> None:
    # A failed place() stores nothing, so the next show() (libqtile >= 0.37
    # builds the size from toggler.geometry only) keeps the size the window has.
    screen = SimpleNamespace(dx=0, dy=0, dwidth=1000, dheight=800)
    win = FakeWindow(fail_place=True)
    win.group = None
    win.togroup = lambda *_a, **_k: None
    win.bring_to_front = lambda: None
    win.qtile = SimpleNamespace(current_screen=screen)
    dd = _real_toggler(libqtile_scratchpad, win, TERM)
    dd.border_width = 2

    cycle_focused_dropdown(_qtile(win, dd, screen=screen), "grow", TERM_DEFAULTS)
    assert win.placed == []  # the failed place() left the window untouched

    win._fail_place = False
    dd.show()
    ((args, _kwargs),) = win.placed
    assert args[:4] == compute_placement(TERM, screen, 2)  # still the default


class LiveWindow:
    """A window with live geometry, enough for the real hide()/show() cycle.

    ``place()`` moves the window (like the X11 backend does) unless it is set
    to fail; ``togroup()`` moves it between a visible group (on a screen) and
    the scratchpad group (on no screen).
    """

    def __init__(self, screen, geometry: Geometry, border_width: int) -> None:
        self.screen = screen
        self.bordercolor = "#abc"
        self.fail_place = False
        self.placed: list[tuple] = []
        self._scratchpad = SimpleNamespace(name="scratchpad", screen=None)
        self._visible = SimpleNamespace(name="1", screen=screen)
        self.qtile = SimpleNamespace(current_screen=screen, current_group=self._visible)
        self.group = self._visible
        self.x, self.y, self.width, self.height = compute_placement(
            geometry, screen, border_width
        )

    def place(self, x, y, width, height, *_args, **_kwargs) -> None:
        if self.fail_place:
            raise RuntimeError("boom")
        self.placed.append((x, y, width, height))
        self.x, self.y, self.width, self.height = x, y, width, height

    def togroup(self, name=None, **_kwargs) -> None:
        self.group = self._scratchpad if name == "scratchpad" else self._visible

    def bring_to_front(self) -> None:
        pass


def _shown_dropdown(libqtile_scratchpad, screen, geometry: Geometry = TERM):
    """A real DropDownToggler currently visible on `screen` at `geometry`."""
    win = LiveWindow(screen, geometry, border_width=2)
    dd = _real_toggler(libqtile_scratchpad, win, geometry)
    dd.border_width = 2
    dd.shown = True
    return win, dd


@pytest.mark.parametrize(
    ("direction", "label"), [("grow", "medium"), ("shrink", "small")]
)
@pytest.mark.parametrize(
    "screen",
    [
        SimpleNamespace(dx=0, dy=0, dwidth=1000, dheight=800),
        SimpleNamespace(dx=1920, dy=40, dwidth=1600, dheight=900),
    ],
)
def test_size_survives_a_real_hide_and_show(
    libqtile_scratchpad, screen, direction, label
) -> None:
    # hide() re-reads the geometry from the live window (the dropdown is on a
    # screen), so what the next show() uses is what place() actually applied.
    win, dd = _shown_dropdown(libqtile_scratchpad, screen)
    q = _qtile(win, dd, screen=screen)
    cycle_focused_dropdown(q, direction, TERM_DEFAULTS)
    preset = _by_label(derive_presets(TERM))[label]
    expected = compute_placement(preset, screen, 2)
    assert win.placed == [expected]
    assert expected != compute_placement(TERM, screen, 2)  # it really changed size

    dd.hide()
    assert win.group.name == "scratchpad"  # hidden for real
    dd.show()
    assert win.group.name == "1"
    assert len(win.placed) == 2
    assert win.placed[-1] == pytest.approx(expected, abs=1)  # int() truncation


def test_failed_place_keeps_old_size_across_a_real_hide_and_show(
    libqtile_scratchpad,
) -> None:
    # A failed place() that raised before touching the window stores nothing,
    # so the toggler agrees with the live window that hide() re-reads, and
    # show() restores the old size.
    screen = SimpleNamespace(dx=0, dy=0, dwidth=1000, dheight=800)
    win, dd = _shown_dropdown(libqtile_scratchpad, screen)
    win.fail_place = True
    cycle_focused_dropdown(_qtile(win, dd, screen=screen), "grow", TERM_DEFAULTS)
    assert dd.geometry == _as_tuple(TERM)

    win.fail_place = False
    dd.hide()
    dd.show()
    assert win.placed == [compute_placement(TERM, screen, 2)]  # still the default


@pytest.mark.parametrize(
    ("direction", "label"), [("grow", "medium"), ("shrink", "small")]
)
def test_failed_place_then_real_hide_show_then_cycle_lands_on_adjacent_preset(
    libqtile_scratchpad, direction, label
) -> None:
    # hide() rewrites only geometry, never x/y/width/height (what the glue reads
    # back), so a failed place() must not have left the new preset there.
    screen = SimpleNamespace(dx=0, dy=0, dwidth=1000, dheight=800)
    win, dd = _shown_dropdown(libqtile_scratchpad, screen)
    q = _qtile(win, dd, screen=screen)
    win.fail_place = True
    cycle_focused_dropdown(q, direction, TERM_DEFAULTS)

    win.fail_place = False
    dd.hide()
    dd.show()
    cycle_focused_dropdown(q, direction, TERM_DEFAULTS)
    preset = _by_label(derive_presets(TERM))[label]
    assert win.placed[-1] == compute_placement(preset, screen, 2)
