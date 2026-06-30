from typing import TypedDict

from libqtile.config import Group, Key
from libqtile.lazy import lazy

from settings import mod

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

for i, (name, _cfg) in enumerate(group_names, 1):
    keys.append(Key([mod], str(i), lazy.group[name].toscreen(toggle=True)))
    keys.append(Key([mod, "shift"], str(i), lazy.window.togroup(name)))


def init_groups() -> list[Group]:
    return groups
