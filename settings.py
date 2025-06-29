import os
from dotenv import dotenv_values

# Mod key settings
mod = "mod4"  # Sets mod key to SUPER/WINDOWS
myTerm = "/usr/bin/qterminal"
myConfig = "/home/k3v1n/.config/qtile/config.py"

# Environment variables from .env file
config = dotenv_values()
for key, value in config.items():
    os.environ[f'{key}'] = f'{value}'

# Layout theme settings
layout_theme = {
    "border_width": 2,
    "margin": 6,
    "border_focus": "117af0",
    "border_normal": "1D2330"
}

# Color schemes
colors = [
    ["#000000", "#000000"],  # panel background
    ["#434758", "#434758"],  # background for current screen tab
    ["#ffffff", "#ffffff"],  # font color for group names
    ["#80b2ea", "#80b2ea"],  # border line color for current tab
    ["#6441a5", "#6441a5"],  # border line color for other tab and odd widgets
    ["#668bd7", "#668bd7"],  # color for the even widgets
    ["#117af0", "#117af0"]   # window name
]

colors2 = [
    ["#114ef0", "#114ef0"],  # panel background
    ["#d8f011", "#d8f011"],  # background for current screen tab
    ["#11f018", "#11f018"],  # font color for group names
    ["#11f08e", "#11f08e"],  # border line color for current tab
    ["#11dff0", "#11dff0"],  # border line color for other tab and odd widgets
    ["#11c1f0", "#11c1f0"],  # color for the even widgets
    ["#117af0", "#117af0"]   # window name
]

# Widget defaults
widget_defaults = dict(
    font="CaskaydiaCove Nerd Font",
    fontsize=12,
    padding=0,
    background=colors[2]
)
extension_defaults = widget_defaults.copy()