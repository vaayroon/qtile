import re
import subprocess
from collections.abc import Callable
from typing import Any

from libqtile import bar
from libqtile.config import Output, Screen
from libqtile.log_utils import logger

from utils.system import effective_monitor_count

from .widgets import init_widgets_screen1, init_widgets_screen2, init_widgets_screen3

BAR_SIZE = 20
BAR_OPACITY = 1.0
_ACTIVE_OUTPUT_RE = re.compile(
    r"^(?P<port>\S+)\s+connected(?:\s+primary)?\s+(?P<mode>\d+x\d+\+\d+\+\d+)\b"
)


def _build_screen(widget_factory: Callable[[], list[Any]]) -> Screen:
    return Screen(
        top=bar.Bar(
            widgets=widget_factory(),
            opacity=BAR_OPACITY,
            size=BAR_SIZE,
        )
    )


def _detect_active_monitor_count() -> tuple[int, str]:
    # Preferred source: xrandr reports only currently active monitors.
    try:
        list_output = subprocess.check_output(
            ["xrandr", "--listactivemonitors"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        list_output = ""

    for raw_line in list_output.splitlines():
        if raw_line.startswith("Monitors:"):
            _, _, value = raw_line.partition(":")
            try:
                return max(0, int(value.strip())), "xrandr --listactivemonitors"
            except ValueError:
                break

    # Secondary source: active outputs have current geometry in xrandr --query.
    try:
        query_output = subprocess.check_output(
            ["xrandr", "--query"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return 0, "no-xrandr-fallback"

    return (
        sum(
            1
            for raw_line in query_output.splitlines()
            if _ACTIVE_OUTPUT_RE.match(raw_line)
        ),
        "xrandr --query",
    )


def _format_backend_outputs(outputs: list[Output]) -> str:
    if not outputs:
        return "none"

    parts: list[str] = []
    for index, output in enumerate(outputs):
        port = getattr(output, "port", "unknown")
        make = getattr(output, "make", "unknown")
        model = getattr(output, "model", "unknown")
        serial = getattr(output, "serial", "unknown")
        parts.append(f"#{index}:{port} {make} {model} (serial={serial})")

    return "; ".join(parts)


def _screen_count_from_outputs(outputs: list[Output]) -> int:
    if not outputs:
        return 0

    connected = [output for output in outputs if getattr(output, "connected", True)]
    return len(connected) or len(outputs)


def _build_screens_for_count(monitor_count: int) -> list[Screen]:
    monitor_count = max(1, monitor_count)

    widget_factories: list[Callable[[], list[Any]]] = [
        init_widgets_screen1,
        init_widgets_screen2,
        init_widgets_screen3,
    ]

    screens: list[Screen] = []
    for index in range(monitor_count):
        factory_index = min(index, len(widget_factories) - 1)
        screens.append(_build_screen(widget_factories[factory_index]))

    return screens


def generate_screens_module(outputs: list[Output]) -> list[Screen]:
    logger.error(
        "Qtile backend outputs (%d): %s",
        len(outputs),
        _format_backend_outputs(outputs),
    )

    monitor_count = _screen_count_from_outputs(outputs)
    if monitor_count == 0:
        monitor_count, source = effective_monitor_count()
        if monitor_count == 0:
            # Final fallback for sessions where xrandr --props cannot be read.
            monitor_count, source = _detect_active_monitor_count()

        logger.error(
            "Fallback active monitor count: %d (source=%s)",
            monitor_count,
            source,
        )

    return _build_screens_for_count(monitor_count)


def init_screens() -> list[Screen]:
    # Compatibility helper for code paths still expecting eager screen creation.
    return generate_screens_module([])
