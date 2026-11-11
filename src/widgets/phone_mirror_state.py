"""The remembered phone and the reconnect backoff: small, pure-ish helpers.

The only file written is the phone's identity under `$XDG_STATE_HOME`. It holds
the mDNS instance name (stable across port changes), the serial embedded in it
and the last `host:port`. The pairing password is never stored.
"""

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .phone_mirror_log import logger

STATE_VERSION = 1
STATE_FILE = "phone_mirror.json"

# Seconds to wait before each reconnect attempt, and how many there are per
# disconnect. After the last one the controller waits for a user action.
BACKOFF: tuple[float, ...] = (8.0, 16.0, 32.0, 64.0, 128.0, 300.0)
MAX_ATTEMPTS = len(BACKOFF)

_CONNECT_SUFFIX = "._adb-tls-connect._tcp"
MAX_FILE_BYTES = 64 * 1024  # the real file is ~200 bytes; refuse anything huge
_MAX_PORT = 65535

# ASCII only and fullmatch: `\d` matches other scripts and `$` a trailing newline.
_INSTANCE = re.compile(r"adb-(.+)-[A-Za-z0-9]+")
_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_ADDRESS = re.compile(r"([A-Za-z0-9\[][A-Za-z0-9.:\[\]-]*):([0-9]{1,5})")


def backoff_delay(attempt: int) -> float | None:
    """Delay before the zero-based `attempt`, or None once the attempts are spent."""
    if 0 <= attempt < MAX_ATTEMPTS:
        return BACKOFF[attempt]
    return None


def state_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_STATE_HOME", "").strip()
    if not base or not os.path.isabs(base):
        home = env.get("HOME", "").strip() or str(Path.home())
        base = os.path.join(home, ".local", "state")
    return Path(base) / "qtile" / STATE_FILE


def serial_from_instance(instance: str) -> str:
    """`adb-<serial>-<random>` carries the USB serial; empty when it does not."""
    match = _INSTANCE.fullmatch(instance)
    return match.group(1) if match and not match.group(1).startswith("-") else ""


def is_wireless_serial(serial: str) -> bool:
    """A `host:port` or an mDNS connect name, as listed by `adb devices`."""
    return ":" in serial or serial.endswith(_CONNECT_SUFFIX)


def transport_of(serial: str) -> str:
    """`wifi`, `emulator` or `usb`: how this adb serial reaches the phone."""
    if is_wireless_serial(serial):
        return "wifi"
    return "emulator" if serial.startswith("emulator-") else "usb"


@dataclass(frozen=True)
class RememberedDevice:
    service_name: str  # the mDNS instance name: the identity of the phone
    last_address: str  # host:port that worked last
    serial: str = ""
    paired_at: str = ""

    def matches(self, listed: str) -> bool:
        """Is this `adb devices` serial the remembered phone, over any transport?"""
        if not listed:
            return False
        return (
            listed == self.last_address
            or (bool(self.serial) and listed == self.serial)
            or listed == f"{self.service_name}{_CONNECT_SUFFIX}"
        )


def _from_data(data: object) -> RememberedDevice | None:
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    name = data.get("service_name")
    address = data.get("last_address")
    serial = data.get("serial", "")
    paired_at = data.get("paired_at", "")
    if not (isinstance(name, str) and isinstance(address, str)):
        return None
    if not (isinstance(serial, str) and isinstance(paired_at, str)):
        return None
    if not valid_identity(name, address):
        return None
    return RememberedDevice(name, address, serial, paired_at)


def valid_identity(name: str, address: str) -> bool:
    """Is this a mDNS instance name and a `host:port` worth keeping?"""
    found = _ADDRESS.fullmatch(address)
    return (
        _NAME.fullmatch(name) is not None
        and found is not None
        and 0 < int(found.group(2)) <= _MAX_PORT
    )


def load(path: Path) -> RememberedDevice | None:
    """The remembered phone, or None if the file is missing or not usable."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError(f"larger than {MAX_FILE_BYTES} bytes")
        data = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        logger.warning("PhoneMirror: ignoring unreadable state file %s: %s", path, exc)
        return None
    device = _from_data(data)
    if device is None:
        logger.warning("PhoneMirror: ignoring invalid state file %s", path)
    return device


def save(path: Path, device: RememberedDevice) -> bool:
    """Write atomically (`.part`, then rename) with mode 0600; never raises."""
    payload = {
        "version": STATE_VERSION,
        "serial": device.serial,
        "service_name": device.service_name,
        "last_address": device.last_address,
        "paired_at": device.paired_at,
    }
    part = Path(f"{path}.part")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(part, 0o600)
        os.replace(part, path)
    except OSError as exc:
        logger.warning("PhoneMirror: could not save the remembered phone: %s", exc)
        part.unlink(missing_ok=True)
        return False
    return True
