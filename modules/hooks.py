import os
import subprocess

from libqtile import hook


@hook.subscribe.startup_once
def start_once() -> None:
    home = os.path.expanduser("~")
    subprocess.call([home + "/.config/qtile/autostart.sh"])


def init_hooks() -> None:
    # Initialize hooks if needed
    subprocess.call(["xsetroot", "-cursor_name", "left_ptr", "-solid", "#000000"])
