from pathlib import Path
import subprocess


type NetworkDevice = tuple[str, str]


def _run_ip_command(*args: str) -> str:
    result = subprocess.run(
        ["ip", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


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


def get_my_net_ip() -> NetworkDevice:
    if _is_device_active("eth0"):
        return ("eth0", "󰈀 ")

    if _is_device_active("wlan0"):
        return ("wlan0", "󱚻 ")

    return ("", " ")