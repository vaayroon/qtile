"""Pure builders and parsers for the phone mirror: no I/O, no subprocesses."""

from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_QUALITY = "balanced"

# quality -> (max size in px or None for native, video bit rate, max fps)
QUALITY_PRESETS: dict[str, tuple[int | None, str, int]] = {
    "low": (1024, "4M", 30),
    "balanced": (1600, "8M", 60),
    "high": (None, "16M", 60),
}


@dataclass(frozen=True)
class MirrorOptions:
    quality: str = DEFAULT_QUALITY
    screen_off: bool = True
    audio: bool = False
    window_title: str = "Phone"
    serial: str = ""


@dataclass(frozen=True)
class Device:
    serial: str
    state: str


def normalize_quality(value: str) -> str:
    """Return a known preset name; anything else becomes the default."""
    name = value.strip().lower()
    return name if name in QUALITY_PRESETS else DEFAULT_QUALITY


def build_scrcpy_argv(scrcpy_path: str, options: MirrorOptions) -> list[str]:
    max_size, bit_rate, fps = QUALITY_PRESETS[normalize_quality(options.quality)]
    argv = [scrcpy_path]
    if options.serial:
        argv += ["-s", options.serial]
    if max_size is not None:
        argv += ["--max-size", str(max_size)]
    argv += ["--video-bit-rate", bit_rate, "--max-fps", str(fps)]
    if options.screen_off:
        argv.append("-S")
    if not options.audio:
        argv.append("--no-audio")
    argv += ["--window-title", options.window_title.strip() or "Phone"]
    return argv


def build_adb_argv(adb_path: str, args: Sequence[str], serial: str = "") -> list[str]:
    argv = [adb_path]
    if serial:
        argv += ["-s", serial]
    return [*argv, *args]


def build_devices_argv(adb_path: str) -> list[str]:
    return build_adb_argv(adb_path, ["devices"])


def build_connect_argv(adb_path: str, target: str) -> list[str]:
    return build_adb_argv(adb_path, ["connect", target])


def build_disconnect_argv(adb_path: str, target: str = "") -> list[str]:
    return build_adb_argv(adb_path, ["disconnect", *([target] if target else [])])


def build_keyevent_argv(adb_path: str, keycode: int, serial: str = "") -> list[str]:
    return build_adb_argv(
        adb_path, ["shell", "input", "keyevent", str(keycode)], serial=serial
    )


def parse_devices(output: str) -> list[Device]:
    """Parse `adb devices` output into (serial, state) pairs."""
    devices: list[Device] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append(Device(parts[0], parts[1]))
    return devices


def ready_device(devices: Sequence[Device], expected: str = "") -> str | None:
    """Serial of the first usable device (matching `expected` when given)."""
    for device in devices:
        if device.state == "device" and (not expected or device.serial == expected):
            return device.serial
    return None


def build_zenity_argv(initial: dict[str, str]) -> list[str]:
    """The setup form shown when no device could be reached."""
    return [
        "zenity",
        "--forms",
        "--title=Phone Mirror Setup",
        "--text=Enter only what is needed to connect the phone",
        "--separator=|",
        (
            "--add-entry=ADB host:port "
            f"({initial['wireless_target'] or '192.168.1.10:5555'})"
        ),
        f"--add-entry=Device serial, optional ({initial['device'] or 'auto'})",
        f"--add-entry=ADB path ({initial['adb_path']})",
        f"--add-entry=scrcpy path ({initial['scrcpy_path']})",
    ]


def parse_zenity_values(stdout: str, initial: dict[str, str]) -> dict[str, str] | None:
    """Parse the `|`-separated form output; blanks keep the current value."""
    values = stdout.strip().split("|")
    if len(values) < 4:
        return None
    keys = ("wireless_target", "device", "adb_path", "scrcpy_path")
    return {
        key: values[index].strip() or initial[key] for index, key in enumerate(keys)
    }
