"""Bar composition over the REAL ``src/modules/widgets.py``.

The module is loaded from disk under a throwaway name with ``src`` on
``sys.path`` and ``dotenv.dotenv_values`` stubbed, so the developer's own
``.env`` never leaks into the toggles. ``get_my_net_ip`` is patched so no
network probing runs. Every ``QTILE_WIDGET_*`` toggle is cleared first: the
tests must not depend on the developer's shell.
"""

import importlib.util
import itertools
import logging
import sys
from pathlib import Path

import pytest

pytest.importorskip("libqtile.widget")

SRC = Path(__file__).resolve().parent.parent / "src"
TOGGLES = {
    "updates": "QTILE_WIDGET_UPDATES",
    "crypto": "QTILE_WIDGET_CRYPTO",
    "thermal": "QTILE_WIDGET_THERMAL",
    "nvidia": "QTILE_WIDGET_NVIDIA",
    "phone_mirror": "QTILE_WIDGET_PHONE_MIRROR",
}
# Widget classes each toggle owns (labels are TextBoxes, checked separately).
OWNED = {
    "updates": "CheckUpdates",
    "crypto": "CryptoTicker",
    "thermal": "ThermalSensor",
    "nvidia": "NvidiaSensors",
    "phone_mirror": "PhoneMirrorWidget",
}
_OWN_PREFIXES = ("settings", "utils", "widgets")


@pytest.fixture
def widgets_module(monkeypatch, tmp_path):
    for var in TOGGLES.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("dotenv.dotenv_values", lambda *_a, **_k: {})
    monkeypatch.syspath_prepend(str(SRC))

    def _owned(name: str) -> bool:
        return any(name == p or name.startswith(p + ".") for p in _OWN_PREFIXES)

    # Drop cached copies so `settings` runs again under the stubbed dotenv.
    for name in [n for n in sys.modules if _owned(n)]:
        monkeypatch.delitem(sys.modules, name)

    import utils.network

    monkeypatch.setattr(utils.network, "get_my_net_ip", lambda: ("eth0", "E"))

    spec = importlib.util.spec_from_file_location(
        "_widgets_under_test", SRC / "modules" / "widgets.py"
    )
    module = importlib.util.module_from_spec(spec)
    before = set(sys.modules)
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        for name in set(sys.modules) - before:
            if _owned(name):
                del sys.modules[name]


def _names(widgets) -> list[str]:
    return [type(w).__name__ for w in widgets]


def _segments(module, widgets):
    """(arrow, segment widgets) pairs for the powerline part of the bar."""
    arrows = [
        i
        for i, w in enumerate(widgets)
        if type(w).__name__ == "TextBox" and w.text == module.ARROW
    ]
    ends = [*arrows[1:], _names(widgets).index("Sep", arrows[-1])]
    return [
        (widgets[a], widgets[a + 1 : end]) for a, end in zip(arrows, ends, strict=True)
    ]


def _bar(module, *, include_systray: bool = True):
    return module.init_widgets_list(include_systray=include_systray)


def test_default_bar_keeps_every_widget(widgets_module):
    m = widgets_module
    c0, c4, c3 = m.colors[0], m.colors2[4], m.colors2[3]

    pairs = _segments(m, _bar(m))

    assert [_names(seg) for _, seg in pairs] == [
        ["CheckUpdates"],
        ["CryptoTicker"],
        ["TextBox", "ThermalSensor", "TextBox", "NvidiaSensors"],
        ["Memory"],
        ["Net"],
        ["PhoneMirrorWidget"],
        ["Clock"],
    ]
    backgrounds = [seg[0].background for _, seg in pairs]
    assert backgrounds == [c4, c3, c4, c3, c4, c3, c4]
    arrows = [(arrow.background, arrow.foreground) for arrow, _ in pairs]
    # Each arrow sits on the previous background and is drawn in the next one.
    assert arrows == list(zip([c0, *backgrounds[:-1]], backgrounds, strict=True))


def test_fixed_widgets_around_the_powerline(widgets_module):
    names = _names(_bar(widgets_module))

    assert names[:5] == ["Sep", "GroupBox", "Prompt", "Sep", "WindowName"]
    assert names[-3:] == ["Sep", "CurrentLayout", "Systray"]


def test_systray_only_when_requested(widgets_module):
    assert "Systray" not in _names(_bar(widgets_module, include_systray=False))


@pytest.mark.parametrize("toggle", sorted(TOGGLES))
def test_disabled_toggle_removes_only_its_widget(widgets_module, monkeypatch, toggle):
    monkeypatch.setenv(TOGGLES[toggle], "false")

    names = _names(_bar(widgets_module))

    assert OWNED[toggle] not in names
    for other in set(OWNED) - {toggle}:
        assert OWNED[other] in names


@pytest.mark.parametrize(
    ("toggle", "kept"), [("thermal", "NvidiaSensors"), ("nvidia", "ThermalSensor")]
)
def test_one_sensor_off_drops_its_label_too(widgets_module, monkeypatch, toggle, kept):
    monkeypatch.setenv(TOGGLES[toggle], "off")

    pairs = _segments(widgets_module, _bar(widgets_module))

    assert [_names(seg) for _, seg in pairs][2] == ["TextBox", kept]


def test_both_sensors_off_drops_the_segment(widgets_module, monkeypatch):
    monkeypatch.setenv(TOGGLES["thermal"], "0")
    monkeypatch.setenv(TOGGLES["nvidia"], "no")

    pairs = _segments(widgets_module, _bar(widgets_module))

    assert [_names(seg) for _, seg in pairs] == [
        ["CheckUpdates"],
        ["CryptoTicker"],
        ["Memory"],
        ["Net"],
        ["PhoneMirrorWidget"],
        ["Clock"],
    ]


@pytest.mark.parametrize(
    "states",
    list(itertools.product([True, False], repeat=len(TOGGLES))),
    ids=lambda s: "".join("1" if on else "0" for on in s),
)
def test_powerline_alternates_for_every_combination(
    widgets_module, monkeypatch, states
):
    m = widgets_module
    for var, on in zip(TOGGLES.values(), states, strict=True):
        monkeypatch.setenv(var, "true" if on else "false")

    pairs = _segments(m, _bar(m))

    previous = m.colors[0]
    for index, (arrow, seg) in enumerate(pairs):
        expected = m.SEGMENT_BACKGROUNDS[index % 2]
        assert all(w.background == expected for w in seg)
        assert (arrow.background, arrow.foreground) == (previous, expected)
        previous = expected
    assert _names(pairs[-1][1]) == ["Clock"]


def test_bad_value_keeps_the_widget_and_warns(widgets_module, monkeypatch, caplog):
    monkeypatch.setenv(TOGGLES["crypto"], "nope")

    with caplog.at_level(logging.WARNING, logger="libqtile"):
        names = _names(_bar(widgets_module))

    assert "CryptoTicker" in names
    assert any(TOGGLES["crypto"] in r.getMessage() for r in caplog.records)


def test_toggle_table_matches_the_module(widgets_module):
    assert widgets_module.WIDGET_TOGGLES == TOGGLES
