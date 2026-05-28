import os
import socket
from typing import Any

from libqtile import qtile as _qtile_raw
from libqtile import widget

from settings import colors, colors2, myTerm
from utils.network import get_my_net_ip
from widgets import PhoneMirrorWidget

qtile: Any = _qtile_raw

# Get network info
network_info = get_my_net_ip()
webdevice = network_info[0]
websymbol = network_info[1]

# Initialize prompt
prompt = "{}@{}: ".format(os.environ["USER"], socket.gethostname())


def init_widgets_list(*, include_systray: bool) -> list[Any]:
    widgets_list = [
        widget.Sep(linewidth=0, padding=6, foreground=colors[2], background=colors[0]),
        widget.GroupBox(
            fontsize=19,
            margin_y=4,
            margin_x=2,
            padding_y=8,
            padding_x=10,
            borderwidth=1,
            active=colors[2],
            inactive=colors[2],
            rounded=False,
            highlight_color=colors[1],
            highlight_method="block",
            this_current_screen_border=colors[6],
            this_screen_border=colors2[3],
            other_current_screen_border=colors[0],
            other_screen_border=colors[0],
            foreground=colors[2],
            background=colors[0],
        ),
        widget.Prompt(
            prompt=prompt, padding=10, foreground=colors[3], background=colors[1]
        ),
        widget.Sep(linewidth=0, padding=40, foreground=colors[2], background=colors[0]),
        widget.WindowName(foreground=colors[6], background=colors[0], padding=0),
        widget.TextBox(
            text="",
            background=colors[0],
            foreground=colors2[4],
            padding=-2,
            fontsize=37,
        ),
        widget.CheckUpdates(
            foreground=colors[0],
            background=colors2[4],
            colour_have_updates=colors[0],
            colour_no_updates=colors[0],
            no_update_string=" ",
            display_format=" :{updates}",
            update_interval=1800,
            padding=5,
            fontsize=14,
            mouse_callbacks={
                "Button1": lambda: qtile.spawn(
                    myTerm + " -e --title virtual-shell sudo apt dist-upgrade"
                )
            },
            distro="Debian",
        ),
        widget.TextBox(
            text="",
            background=colors2[4],
            foreground=colors2[3],
            padding=-2,
            fontsize=37,
        ),
        widget.CryptoTicker(
            currency="EUR",
            crypto="BTC",
            symbol=" ",
            format=" : {symbol}{amount:.2f}",
            foreground=colors[0],
            background=colors2[3],
            mouse_callbacks={
                "Button1": lambda: qtile.spawn(
                    myTerm + " -e ~/go/bin/cointop -name cointop -title virtual-shell"
                )
            },
            padding=5,
        ),
        widget.TextBox(
            text="",
            background=colors2[3],
            foreground=colors2[4],
            padding=-2,
            fontsize=37,
        ),
        widget.TextBox(
            text=" :",
            padding=0,
            foreground=colors[0],
            background=colors2[4],
            fontsize=12,
        ),
        widget.ThermalSensor(
            foreground=colors[0],
            background=colors2[4],
            threshold=90,
            tag_sensor="Tctl",  # Tccd2, Tdie, Tctl, etc. Check with `sensors` command
            mouse_callbacks={"Button1": lambda: qtile.spawn("psensor")},
            padding=2,
        ),
        widget.TextBox(
            text="󱤓 :", padding=2, foreground=colors[0], background=colors2[4]
        ),
        widget.NvidiaSensors(
            foreground=colors[0],
            background=colors2[4],
            threshold=90,
            format=": {temp}°C, 󰈐 : {fan_speed}, 󰓅 : {perf}",
            mouse_callbacks={"Button1": lambda: qtile.spawn("psensor")},
            padding=2,
        ),
        widget.TextBox(
            text="",
            background=colors2[4],
            foreground=colors2[3],
            padding=-2,
            fontsize=37,
        ),
        widget.Memory(
            foreground=colors[0],
            background=colors2[3],
            mouse_callbacks={
                "Button1": lambda: qtile.spawn(
                    myTerm + " -e htop -name htop -title virtual-shell"
                )
            },
            format=" :{MemUsed: .0f}{mm}/{MemTotal:.0f}{mm}",
            padding=5,
        ),
        widget.TextBox(
            text="",
            background=colors2[3],
            foreground=colors2[4],
            padding=-2,
            fontsize=37,
        ),
        widget.Net(
            interface=webdevice,
            foreground=colors[0],
            background=colors2[4],
            padding=5,
            mouse_callbacks={
                "Button1": lambda: qtile.spawn(
                    myTerm + " -e glances -name sys-monit -title virtual-shell"
                )
            },
            format=str(websymbol) + ": {down}↓↑{up}",
        ),
        widget.TextBox(
            text="",
            background=colors2[4],
            foreground=colors2[3],
            padding=-2,
            fontsize=37,
        ),
        PhoneMirrorWidget(
            foreground=colors[0],
            background=colors2[3],
            padding=6,
            adb_path="/opt/genymobile/adb",
            scrcpy_path="scrcpy",
            wireless_target="",
            device="",
            turn_screen_off=True,
            show_device=False,
            update_interval=8,
        ),
        widget.TextBox(
            text="",
            background=colors2[3],
            foreground=colors2[4],
            padding=-2,
            fontsize=37,
        ),
        widget.Clock(
            padding=3,
            foreground=colors[0],
            background=colors2[3],
            mouse_callbacks={"Button1": lambda: qtile.spawn("gnome-calendar")},
            format=" : %d/%m/%Y - %H:%M:%S",
        ),
        widget.Sep(linewidth=0, padding=10, foreground=colors[0], background=colors[0]),
        widget.CurrentLayout(foreground=colors[2], background=colors[0], padding=5),
    ]

    if include_systray:
        widgets_list.append(widget.Systray(background=colors[0], padding=5))

    return widgets_list


def init_widgets_screen1() -> list[Any]:
    return init_widgets_list(include_systray=True)


def init_widgets_screen2() -> list[Any]:
    return init_widgets_list(include_systray=False)


def init_widgets_screen3() -> list[Any]:
    return init_widgets_list(include_systray=False)
