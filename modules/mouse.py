from typing import Any

from libqtile.config import Click, Drag
from libqtile.lazy import lazy

from settings import mod

mouse: list[Any] = [
    Drag(
        [mod],
        "Button1",
        lazy.window.set_position_floating(),
        start=lazy.window.get_position(),
    ),
    Drag(
        [mod], "Button3", lazy.window.set_size_floating(), start=lazy.window.get_size()
    ),
    Click([mod], "Button2", lazy.window.bring_to_front()),
]


def init_mouse() -> list[Any]:
    return mouse
