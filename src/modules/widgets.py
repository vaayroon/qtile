import os
import socket
from collections.abc import Callable
from typing import Any

from libqtile import qtile as _qtile_raw
from libqtile import widget

from settings import colors, colors2, myTerm
from utils.env import env_flag
from utils.network import get_my_net_ip
from widgets.phone_mirror import PhoneMirrorWidget

qtile: Any = _qtile_raw

# Get network info
network_info = get_my_net_ip()
webdevice = network_info[0]
websymbol = network_info[1]

# Initialize prompt
prompt = "{}@{}: ".format(os.environ["USER"], socket.gethostname())


# Optional widgets, keyed by name. Each one depends on hardware, an external
# tool or a personal preference, defaults to on and can be switched off in .env.
WIDGET_TOGGLES: dict[str, str] = {
    "updates": "QTILE_WIDGET_UPDATES",
    "crypto": "QTILE_WIDGET_CRYPTO",
    "thermal": "QTILE_WIDGET_THERMAL",
    "nvidia": "QTILE_WIDGET_NVIDIA",
    "phone_mirror": "QTILE_WIDGET_PHONE_MIRROR",
}

# Powerline segments alternate between these backgrounds, left to right, over
# the segments that are enabled.
SEGMENT_BACKGROUNDS = (colors2[4], colors2[3])
ARROW = "\uf0d9"

# A segment builds its widgets on the background it is given.
Segment = Callable[[Any], list[Any]]


def enabled_widgets() -> dict[str, bool]:
    """Toggle state of every optional widget, read from the environment."""
    return {name: env_flag(var, True) for name, var in WIDGET_TOGGLES.items()}


def _arrow(*, background: Any, foreground: Any) -> Any:
    return widget.TextBox(
        text=ARROW,
        background=background,
        foreground=foreground,
        padding=-2,
        fontsize=37,
    )


def _powerline(segments: list[Segment], *, start: Any) -> list[Any]:
    """Segments with alternating backgrounds, each one preceded by an arrow.

    The arrow is drawn in the segment's own background on top of the previous
    segment's background (`start` for the first one).
    """
    widgets: list[Any] = []
    previous = start
    for index, segment in enumerate(segments):
        background = SEGMENT_BACKGROUNDS[index % len(SEGMENT_BACKGROUNDS)]
        widgets.append(_arrow(background=previous, foreground=background))
        widgets.extend(segment(background))
        previous = background
    return widgets


def _joined(parts: list[Segment]) -> Segment:
    """One segment holding `parts` side by side on a shared background."""

    def segment(background: Any) -> list[Any]:
        return [item for part in parts for item in part(background)]

    return segment


def _updates(background: Any) -> list[Any]:
    """Pending apt upgrades; click to upgrade."""
    return [
        widget.CheckUpdates(
            foreground=colors[0],
            background=background,
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
    ]


def _crypto(background: Any) -> list[Any]:
    """BTC price in EUR; click for cointop."""
    return [
        widget.CryptoTicker(
            currency="EUR",
            crypto="BTC",
            symbol=" ",
            format=" : {symbol}{amount:.2f}",
            foreground=colors[0],
            background=background,
            mouse_callbacks={
                "Button1": lambda: qtile.spawn(
                    myTerm + " -e cointop -name cointop -title virtual-shell"
                )
            },
            padding=5,
        ),
    ]


def _thermal(background: Any) -> list[Any]:
    """CPU temperature (`Tctl`, AMD); click for psensor."""
    return [
        widget.TextBox(
            text=" :",
            padding=0,
            foreground=colors[0],
            background=background,
            fontsize=12,
        ),
        widget.ThermalSensor(
            foreground=colors[0],
            background=background,
            threshold=90,
            tag_sensor="Tctl",  # Tccd2, Tdie, Tctl, etc. Check with `sensors` command
            mouse_callbacks={"Button1": lambda: qtile.spawn("psensor")},
            padding=2,
        ),
    ]


def _nvidia(background: Any) -> list[Any]:
    """NVIDIA GPU temperature, fan and perf level; click for psensor."""
    return [
        widget.TextBox(
            text="󱤓 :", padding=2, foreground=colors[0], background=background
        ),
        widget.NvidiaSensors(
            foreground=colors[0],
            background=background,
            threshold=90,
            format=": {temp}°C, 󰈐 : {fan_speed}, 󰓅 : {perf}",
            mouse_callbacks={"Button1": lambda: qtile.spawn("psensor")},
            padding=2,
        ),
    ]


def _memory(background: Any) -> list[Any]:
    """Used and total RAM; click for htop."""
    return [
        widget.Memory(
            foreground=colors[0],
            background=background,
            mouse_callbacks={
                "Button1": lambda: qtile.spawn(
                    myTerm + " -e htop -name htop -title virtual-shell"
                )
            },
            format=" :{MemUsed: .0f}{mm}/{MemTotal:.0f}{mm}",
            padding=5,
        ),
    ]


def _net(background: Any) -> list[Any]:
    """Throughput of the detected interface; click for glances."""
    return [
        widget.Net(
            interface=webdevice,
            foreground=colors[0],
            background=background,
            padding=5,
            mouse_callbacks={
                "Button1": lambda: qtile.spawn(
                    myTerm + " -e glances -name sys-monit -title virtual-shell"
                )
            },
            format=str(websymbol) + ": {down}↓↑{up}",
        ),
    ]


def _phone_mirror(background: Any) -> list[Any]:
    """Android mirroring through adb and scrcpy."""
    return [
        PhoneMirrorWidget(
            foreground=colors[0],
            background=background,
            padding=6,
            adb_path="/opt/genymobile/adb",
            scrcpy_path="/opt/genymobile/scrcpy",
            wireless_target="",
            device="",
            turn_screen_off=True,
            quality="balanced",
            audio=False,
            restart_on_switch=True,
            show_device=False,
            update_interval=8,
        ),
    ]


def _clock(background: Any) -> list[Any]:
    """Date and time; click for khal."""
    return [
        widget.Clock(
            padding=3,
            foreground=colors[0],
            background=background,
            mouse_callbacks={
                "Button1": lambda: qtile.spawn(
                    myTerm + " -e khal interactive -name calendar -title virtual-shell"
                )
            },
            format=" : %d/%m/%Y - %H:%M:%S",
        ),
    ]


def _segments(enabled: dict[str, bool]) -> list[Segment]:
    """The bar's powerline segments, left to right, without the disabled ones."""
    segments: list[Segment] = []
    if enabled["updates"]:
        segments.append(_updates)
    if enabled["crypto"]:
        segments.append(_crypto)
    sensors: list[Segment] = [
        part
        for name, part in (("thermal", _thermal), ("nvidia", _nvidia))
        if enabled[name]
    ]
    if sensors:
        segments.append(_joined(sensors))
    segments.append(_memory)
    segments.append(_net)
    if enabled["phone_mirror"]:
        segments.append(_phone_mirror)
    segments.append(_clock)
    return segments


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
        *_powerline(_segments(enabled_widgets()), start=colors[0]),
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
