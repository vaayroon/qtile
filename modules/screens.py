import os
import re
import subprocess
from collections.abc import Callable
from typing import Any

from libqtile import bar
from libqtile.config import Output, Screen
from libqtile.log_utils import logger

from .widgets import init_widgets_screen1, init_widgets_screen2, init_widgets_screen3

BAR_SIZE = 20
BAR_OPACITY = 1.0
_CONNECTED_RE = re.compile(r"^(?P<port>\S+) connected(?:\s+primary)?")
_SERIAL_RE = re.compile(r"^\s*\t?serial number:\s*(?P<serial>\S+)", re.IGNORECASE)
_HEX_RE = re.compile(r"^[\t ]+[0-9a-f]{32}$", re.IGNORECASE)


def _build_screen(widget_factory: Callable[[], list[Any]]) -> Screen:
    return Screen(
        top=bar.Bar(
            widgets=widget_factory(),
            opacity=BAR_OPACITY,
            size=BAR_SIZE,
        )
    )


def _serial_from_edid(edid_lines: list[str]) -> str | None:
    hex_blob = "".join(line.strip() for line in edid_lines)
    if len(hex_blob) < 32:
        return None

    try:
        serial_bytes = bytes.fromhex(hex_blob)[12:16]
    except ValueError:
        return None

    if len(serial_bytes) != 4:
        return None

    serial_value = int.from_bytes(serial_bytes, byteorder="little", signed=False)
    return None if serial_value == 0 else str(serial_value)


def _parse_connected_monitor_serials(xrandr_output: str) -> list[str]:
    serials_with_ports: list[tuple[str, str]] = []
    current_port: str | None = None
    pending_edid: list[str] = []

    for raw_line in xrandr_output.splitlines():
        connected_match = _CONNECTED_RE.match(raw_line)
        if connected_match:
            current_port = connected_match.group("port")
            pending_edid = []
            continue

        if current_port is None:
            continue

        serial_match = _SERIAL_RE.match(raw_line)
        if serial_match:
            serials_with_ports.append((serial_match.group("serial"), current_port))
            current_port = None
            pending_edid = []
            continue

        if raw_line.strip() == "EDID:":
            pending_edid = []
            continue

        if pending_edid is not None and _HEX_RE.match(raw_line):
            pending_edid.append(raw_line)
            continue

        if pending_edid:
            edid_serial = _serial_from_edid(pending_edid)
            if edid_serial is not None:
                serials_with_ports.append((edid_serial, current_port))
            current_port = None
            pending_edid = []

    if pending_edid and current_port is not None:
        edid_serial = _serial_from_edid(pending_edid)
        if edid_serial is not None:
            serials_with_ports.append((edid_serial, current_port))

    serial_priority = [
        item.strip()
        for item in os.environ.get("QTILE_SCREEN_SERIAL_ORDER", "").split(",")
        if item.strip()
    ]

    priority_index = {serial: index for index, serial in enumerate(serial_priority)}
    serials_with_ports.sort(
        key=lambda item: (
            priority_index.get(item[0], len(serial_priority)),
            item[0],
            item[1],
        )
    )

    return [serial for serial, _port in serials_with_ports]


def _detect_monitor_serials() -> list[str]:
    try:
        xrandr_output = subprocess.check_output(
            ["xrandr", "--props"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    return _parse_connected_monitor_serials(xrandr_output)


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


def generate_screens(outputs: list[Output]) -> list[Screen]:
    output_names = [str(getattr(output, "name", "unknown")) for output in outputs]
    logger.error("Qtile outputs reported by backend: %s", output_names)

    monitor_count = _screen_count_from_outputs(outputs)
    if monitor_count == 0:
        # Fallback for backends/sessions where output metadata is unavailable.
        monitor_serials = _detect_monitor_serials()
        logger.error("Fallback monitor serial detection: %s", monitor_serials)
        monitor_count = len(monitor_serials)

    return _build_screens_for_count(monitor_count)


def init_screens() -> list[Screen]:
    # Compatibility helper for code paths still expecting eager screen creation.
    return generate_screens([])
