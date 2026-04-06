import json
import subprocess
from pathlib import Path

type NetworkDevice = tuple[str, str]


def _run_ip_command(*args: str) -> str:
    result = subprocess.run(
        ["ip", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _default_route_device() -> str:
    output = _run_ip_command("-j", "route", "show", "default")
    if not output:
        return ""

    try:
        routes = json.loads(output)
    except json.JSONDecodeError:
        return ""

    for route in routes:
        if route.get("dev"):
            return str(route["dev"])

    return ""


def _read_sysfs(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8").strip()


def _is_device_active(device: str) -> bool:
    default_route = _run_ip_command("route", "show", "default", "dev", device)
    if default_route:
        return True

    operstate = _read_sysfs(f"/sys/class/net/{device}/operstate")
    carrier = _read_sysfs(f"/sys/class/net/{device}/carrier")
    return operstate == "up" or carrier == "1"


def _is_wireless(device: str) -> bool:
    return Path(f"/sys/class/net/{device}/wireless").exists()


def _active_devices() -> list[str]:
    net_dir = Path("/sys/class/net")
    if not net_dir.exists():
        return []

    devices: list[str] = []
    for device_path in net_dir.iterdir():
        device = device_path.name
        if device == "lo":
            continue
        if _is_device_active(device):
            devices.append(device)

    return devices


def _device_icon(device: str) -> str:
    if _is_wireless(device):
        return "󱚻 "
    return "󰈀 "


def get_my_net_ip() -> NetworkDevice:
    default_device = _default_route_device()
    if default_device and _is_device_active(default_device):
        return (default_device, _device_icon(default_device))

    active_devices = _active_devices()
    if active_devices:
        device = active_devices[0]
        return (device, _device_icon(device))

    return ("", " ")
