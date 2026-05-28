import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_XRANDR_CONNECTED_RE = re.compile(
    r"^(?P<port>\S+)\s+connected(?:\s+primary)?(?:\s+(?P<mode>\d+x\d+\+\d+\+\d+)\b)?"
)
_XRANDR_DISCONNECTED_RE = re.compile(r"^(?P<port>\S+)\s+disconnected\b")
_XRANDR_SERIAL_RE = re.compile(
    r"^\s*\t?serial number:\s*(?P<serial>\S+)", re.IGNORECASE
)
_XRANDR_EDID_HEX_RE = re.compile(r"^[\t ]+[0-9a-f]{32}$", re.IGNORECASE)

_DEFAULT_PORT_PRIORITY = ["DP-0", "HDMI-0", "DP-2"]
_INTERNAL_OUTPUT_PREFIXES = ("eDP", "LVDS", "DSI")


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    name: str
    connected: bool
    mode: str | None
    serial: str | None
    is_internal: bool


def _parse_mode_width(mode: str | None) -> int:
    if not mode:
        return 1920

    raw_width, _, _ = mode.partition("x")
    try:
        width = int(raw_width)
    except ValueError:
        return 1920

    return max(640, width)


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


def _read_lid_state() -> bool | None:
    lid_dir = Path("/proc/acpi/button/lid")
    if not lid_dir.exists():
        return None

    for state_file in lid_dir.glob("*/state"):
        try:
            state_text = state_file.read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue

        if "closed" in state_text:
            return True
        if "open" in state_text:
            return False

    return None


def _internal_output_overrides() -> set[str]:
    configured = os.environ.get("QTILE_INTERNAL_OUTPUTS", "")
    return {item.strip() for item in configured.split(",") if item.strip()}


def _is_internal_output(name: str, overrides: set[str]) -> bool:
    if name in overrides:
        return True

    return name.startswith(_INTERNAL_OUTPUT_PREFIXES)


def _run_xrandr_props() -> str:
    try:
        return subprocess.check_output(
            ["xrandr", "--props"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def detect_connected_monitors() -> list[MonitorInfo]:
    xrandr_output = _run_xrandr_props()
    if not xrandr_output:
        return []

    overrides = _internal_output_overrides()
    monitors: list[MonitorInfo] = []

    current_name: str | None = None
    current_mode: str | None = None
    current_serial: str | None = None
    current_connected = False
    pending_edid: list[str] = []

    def flush_current_monitor() -> None:
        nonlocal current_name
        nonlocal current_mode
        nonlocal current_serial
        nonlocal current_connected
        nonlocal pending_edid
        if current_name is None:
            return

        serial = current_serial
        if serial is None and pending_edid:
            serial = _serial_from_edid(pending_edid)

        if current_connected:
            monitors.append(
                MonitorInfo(
                    name=current_name,
                    connected=True,
                    mode=current_mode,
                    serial=serial,
                    is_internal=_is_internal_output(current_name, overrides),
                )
            )

        current_name = None
        current_mode = None
        current_serial = None
        current_connected = False
        pending_edid = []

    for raw_line in xrandr_output.splitlines():
        connected_match = _XRANDR_CONNECTED_RE.match(raw_line)
        disconnected_match = _XRANDR_DISCONNECTED_RE.match(raw_line)

        if connected_match or disconnected_match:
            flush_current_monitor()

            if connected_match:
                current_name = connected_match.group("port")
                current_connected = True
                current_mode = connected_match.group("mode")
            else:
                current_name = (
                    disconnected_match.group("port") if disconnected_match else None
                )
                current_connected = False
            continue

        if current_name is None or not current_connected:
            continue

        serial_match = _XRANDR_SERIAL_RE.match(raw_line)
        if serial_match:
            current_serial = serial_match.group("serial")
            continue

        if raw_line.strip() == "EDID:":
            pending_edid = []
            continue

        if _XRANDR_EDID_HEX_RE.match(raw_line):
            pending_edid.append(raw_line)
            continue

        if pending_edid:
            edid_serial = _serial_from_edid(pending_edid)
            if edid_serial is not None:
                current_serial = edid_serial
            pending_edid = []

    flush_current_monitor()
    return monitors


def _serial_priority() -> list[str]:
    configured = os.environ.get("QTILE_SCREEN_SERIAL_ORDER", "")
    return [item.strip() for item in configured.split(",") if item.strip()]


def _port_priority() -> list[str]:
    configured = os.environ.get("QTILE_SCREEN_PORT_ORDER", "")
    if configured.strip():
        return [item.strip() for item in configured.split(",") if item.strip()]
    return list(_DEFAULT_PORT_PRIORITY)


def _monitor_sort_key(
    monitor: MonitorInfo,
    serial_index: dict[str, int],
    port_index: dict[str, int],
) -> tuple[int, int, str]:
    serial_rank = serial_index.get(monitor.serial or "", len(serial_index))
    port_rank = port_index.get(monitor.name, len(port_index))
    return (serial_rank, port_rank, monitor.name)


def select_layout_monitors(monitors: list[MonitorInfo]) -> list[MonitorInfo]:
    if not monitors:
        return []

    lid_closed = _read_lid_state()
    external_monitors = [monitor for monitor in monitors if not monitor.is_internal]

    candidates = monitors
    if lid_closed is True and external_monitors:
        candidates = external_monitors

    serial_priority = _serial_priority()
    port_priority = _port_priority()
    serial_index = {serial: index for index, serial in enumerate(serial_priority)}
    port_index = {port: index for index, port in enumerate(port_priority)}

    return sorted(
        candidates,
        key=lambda monitor: _monitor_sort_key(monitor, serial_index, port_index),
    )


def _primary_output_name(outputs: list[str]) -> str:
    if not outputs:
        return ""

    if len(outputs) == 1:
        return outputs[0]

    env_primary = os.environ.get("QTILE_PRIMARY_MONITOR", "").strip()
    if env_primary and env_primary in outputs:
        return env_primary

    if "HDMI-0" in outputs:
        return "HDMI-0"

    if "DP-2" in outputs:
        return "DP-2"

    return outputs[0]


def _build_dynamic_layout_command(
    monitors: list[MonitorInfo],
    all_connected: list[MonitorInfo] | None = None,
) -> list[str]:
    if not monitors:
        return []

    selected = monitors[:3]
    selected_names = {monitor.name for monitor in selected}
    primary = _primary_output_name(list(selected_names))

    command = ["xrandr"]
    x_position = 0
    for monitor in selected:
        command.extend(["--output", monitor.name, "--auto", "--pos", f"{x_position}x0"])
        if monitor.name == primary:
            command.append("--primary")
        x_position += _parse_mode_width(monitor.mode)

    off_pool = all_connected if all_connected is not None else monitors
    for monitor in off_pool:
        if monitor.name in selected_names:
            continue
        command.extend(["--output", monitor.name, "--off"])

    return command


def _legacy_fallback_commands() -> list[list[str]]:
    return [
        [
            "xrandr",
            "--output",
            "DP-0",
            "--mode",
            "1920x1080",
            "--pos",
            "0x0",
            "--rotate",
            "normal",
            "--output",
            "HDMI-0",
            "--primary",
            "--mode",
            "1920x1080",
            "--pos",
            "1920x0",
            "--rotate",
            "normal",
            "--output",
            "DP-2",
            "--mode",
            "1920x1080",
            "--pos",
            "3840x0",
            "--rotate",
            "normal",
        ],
        [
            "xrandr",
            "--output",
            "HDMI-0",
            "--primary",
            "--mode",
            "1920x1080",
            "--pos",
            "0x0",
            "--rotate",
            "normal",
            "--output",
            "DP-2",
            "--mode",
            "1920x1080",
            "--pos",
            "1920x0",
            "--rotate",
            "normal",
        ],
        [
            "xrandr",
            "--output",
            "DP-2",
            "--primary",
            "--mode",
            "1920x1080",
            "--pos",
            "0x0",
            "--rotate",
            "normal",
        ],
    ]


def apply_best_effort_layout() -> tuple[bool, str]:
    monitors = detect_connected_monitors()
    ordered_monitors = select_layout_monitors(monitors)
    dynamic_command = _build_dynamic_layout_command(
        ordered_monitors, all_connected=monitors
    )

    commands = [dynamic_command] if dynamic_command else []
    commands.extend(_legacy_fallback_commands())

    for command in commands:
        if not command:
            continue

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True, " ".join(command)

    return False, "all-layout-commands-failed"


def effective_monitor_count() -> tuple[int, str]:
    monitors = detect_connected_monitors()
    selected = select_layout_monitors(monitors)
    if not selected:
        return 0, "xrandr --props"
    return len(selected), "xrandr --props + lid-aware"
