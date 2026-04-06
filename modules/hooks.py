import os
import subprocess

from libqtile import hook


@hook.subscribe.startup_once  # type: ignore[reportUnknownMemberType]
def start_once() -> None:
    home = os.path.expanduser("~")
    subprocess.call([home + "/.config/qtile/autostart.sh"])


def init_hooks() -> None:
    # Initialize hooks if needed
    subprocess.call(["xsetroot", "-cursor_name", "left_prt", "-solid", "#000000"])
