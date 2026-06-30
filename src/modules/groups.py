from typing import TypedDict

from libqtile.config import DropDown, Group, Key, Match, ScratchPad
from libqtile.lazy import lazy

from settings import SCRATCHPAD_WM_CLASS, mod, myScratchpadTerm

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

# Floating dropdown terminal (quake-style). Centered popup: x=0.25 + width=0.5
# leaves equal 0.25 margins left/right; y=0.15 + height=0.6 leaves 0.25 below.
# on_focus_lost_hide makes it auto-dismiss when you click away.
groups.append(
    ScratchPad(
        "scratchpad",
        [
            DropDown(
                "term",
                myScratchpadTerm,
                x=0.25,
                y=0.15,
                width=0.5,
                height=0.6,
                opacity=1.0,
                on_focus_lost_hide=True,
                warp_pointer=True,
                match=Match(wm_class=SCRATCHPAD_WM_CLASS),
            ),
        ],
    )
)

for i, (name, _cfg) in enumerate(group_names, 1):
    keys.append(Key([mod], str(i), lazy.group[name].toscreen(toggle=True)))
    keys.append(Key([mod, "shift"], str(i), lazy.window.togroup(name)))


def init_groups() -> list[Group]:
    return groups
