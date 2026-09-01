import re
from typing import TypedDict

from libqtile.config import DropDown, Group, Key, Match, ScratchPad
from libqtile.lazy import lazy

from settings import mod
from utils.scratchpads import MatchSpec, load_scratchpads

from .keys import keys


class GroupCfg(TypedDict):
    layout: str


group_names = [
    (" ", {"layout": "ratiotile"}),
    (" ", {"layout": "ratiotile"}),
    ("󰨞 ", {"layout": "max"}),
    (" ", {"layout": "max"}),
    (" ", {"layout": "max"}),
    (" ", {"layout": "max"}),
    (" ", {"layout": "max"}),
]

""" groups = [Group(name, **kwargs) for name, kwargs in group_names]

for i, (name, kwargs) in enumerate(group_names, 1):
    # fix toggle in qtile from to 0.18
    keys.append(Key([mod], str(i), lazy.group[name].toscreen(toggle=True)))
    # Send current window to another group
    keys.append(Key([mod, "shift"], str(i), lazy.window.togroup(name))) """

groups = [Group(name, layout=cfg["layout"]) for name, cfg in group_names]


def _to_match(spec: MatchSpec | None) -> Match | None:
    """Translate a loader-owned `MatchSpec` into a libqtile `Match`. This is
    the only place `MatchSpec.title_regex` gets compiled (see design D2):
    the loader validates it compiles but stores the source string, so
    dataclass equality stays flaky-free in tests."""
    if spec is None:
        return None
    wm_class = spec.wm_class or None
    title = re.compile(spec.title_regex) if spec.title_regex else None
    if wm_class is None and title is None:
        return None
    return Match(wm_class=wm_class, title=title)


# Floating dropdown apps (quake-style), built from the scratchpad registry
# (`scratchpads.toml` + `scratchpads.local.toml`, see `utils.scratchpads`).
groups.append(
    ScratchPad(
        "scratchpad",
        [
            DropDown(
                app.name,
                app.command,
                x=app.x,
                y=app.y,
                width=app.width,
                height=app.height,
                opacity=app.opacity,
                on_focus_lost_hide=app.on_focus_lost_hide,
                warp_pointer=app.warp_pointer,
                match=_to_match(app.match),
            )
            for app in load_scratchpads()
        ],
    )
)

for i, (name, _cfg) in enumerate(group_names, 1):
    keys.append(Key([mod], str(i), lazy.group[name].toscreen(toggle=True)))
    keys.append(Key([mod, "shift"], str(i), lazy.window.togroup(name)))


def init_groups() -> list[Group]:
    return groups
