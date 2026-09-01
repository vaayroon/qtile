import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

# Mod key settings
mod = "mod4"  # Sets mod key to SUPER/WINDOWS
myTerm = "/usr/bin/qterminal"

# Scratchpad (floating dropdown) terminal.
# A dedicated kitty instance with its own config and a fixed WM class so the
# DropDown can reliably match its window. Path is resolved relative to this
# file so it works regardless of Qtile's working directory.
SCRATCHPAD_WM_CLASS = "scratchpad-term"
_SCRATCHPAD_KITTY_CONF = (
    Path(__file__).resolve().parent / "assets" / "scratchpad" / "kitty.conf"
)
myScratchpadTerm = (
    f"kitty --class {SCRATCHPAD_WM_CLASS} --config {_SCRATCHPAD_KITTY_CONF}"
)

# Environment variables from .env file.
# Resolve the path relative to this file (repo root) so the config loads
# regardless of the working directory Qtile is launched from.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
config = dotenv_values(ENV_FILE)
for key, value in config.items():
    os.environ[f"{key}"] = f"{value}"

# Layout theme settings
layout_theme: dict[str, Any] = {
    "border_width": 2,
    "margin": 6,
    "border_focus": "#117af0",
    "border_normal": "#1D2330",
}

# Color schemes
colors = [
    ["#000000", "#000000"],  # panel background
    ["#434758", "#434758"],  # background for current screen tab
    ["#ffffff", "#ffffff"],  # font color for group names
    ["#80b2ea", "#80b2ea"],  # border line color for current tab
    ["#6441a5", "#6441a5"],  # border line color for other tab and odd widgets
    ["#668bd7", "#668bd7"],  # color for the even widgets
    ["#117af0", "#117af0"],  # window name
]

colors2 = [
    ["#114ef0", "#114ef0"],  # panel background
    ["#d8f011", "#d8f011"],  # background for current screen tab
    ["#11f018", "#11f018"],  # font color for group names
    ["#11f08e", "#11f08e"],  # border line color for current tab
    ["#11dff0", "#11dff0"],  # border line color for other tab and odd widgets
    ["#11c1f0", "#11c1f0"],  # color for the even widgets
    ["#117af0", "#117af0"],  # window name
]

# Widget defaults
widget_defaults = {
    "font": "CaskaydiaCove Nerd Font",
    "fontsize": 12,
    "padding": 0,
    "background": colors[2],
}

extension_defaults = widget_defaults.copy()
