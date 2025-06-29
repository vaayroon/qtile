from libqtile.config import Group, Key
from libqtile.lazy import lazy
from ..settings import mod
from .keys import keys

group_names = [
    ("󱐡 ", {'layout': 'ratiotile'}),
    (" ", {'layout': 'ratiotile'}),
    ("󰨞 ", {'layout': 'max'}),
    ("󰢹 ", {'layout': 'max'}),
    (" ", {'layout': 'max'}),
    ("󰇩 ", {'layout': 'max'}),
    ("󰒒 ", {'layout': 'ratiotile'})
]

groups = [Group(name, **kwargs) for name, kwargs in group_names]

for i, (name, kwargs) in enumerate(group_names, 1):
    # fix toggle in qtile from to 0.18
    keys.append(Key([mod], str(i), lazy.group[name].toscreen(toggle=True)))
    # Send current window to another group
    keys.append(Key([mod, "shift"], str(i), lazy.window.togroup(name)))

def init_groups():
    return groups