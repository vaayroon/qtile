import os
import subprocess

from libqtile import hook
from libqtile.log_utils import logger

from utils.system import apply_best_effort_layout


@hook.subscribe.startup_once
def start_once() -> None:
    applied, source = apply_best_effort_layout()
    logger.info("Display layout applied=%s source=%s", applied, source)

    home = os.path.expanduser("~")
    subprocess.call([home + "/.config/qtile/autostart.sh"])


def init_hooks() -> None:
    # Initialize hooks if needed
    subprocess.call(["xsetroot", "-cursor_name", "left_ptr", "-solid", "#000000"])
