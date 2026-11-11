"""Pure helpers for wireless pairing: no I/O, no subprocesses.

Holds the one-time QR secret, the `adb mdns services` parser and the manual
pairing form. Discovery is read-only: the only thing ever asked of the network
is `adb mdns services`, and the pairing password never leaves this process
except through adb's stdin.
"""

import math
import re
import secrets
import string
from collections.abc import Sequence
from dataclasses import dataclass, field

from .phone_mirror_commands import build_adb_argv

PAIRING_SERVICE = "_adb-tls-pairing._tcp"
CONNECT_SERVICE = "_adb-tls-connect._tcp"

DEFAULT_TTL = 180.0  # seconds a pairing QR stays valid
NAME_PREFIX = "qtile-"
NAME_LENGTH = 10
PASSWORD_LENGTH = 12
_ALPHABET = string.ascii_letters + string.digits

_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")
_MDNS_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]*")
_CODE = re.compile(r"[0-9]{6}")  # ASCII only: \d would match other scripts
_PORT = re.compile(r"[0-9]{1,5}")
_MAX_PORT = 65535


def _random_text(length: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


@dataclass
class PairingSession:
    """One pairing attempt: its own name and password, a deadline, single use."""

    name: str
    password: str = field(repr=False)
    started: float
    ttl: float = DEFAULT_TTL
    _used: bool = False

    @property
    def payload(self) -> str:
        return f"WIFI:T:ADB;S:{self.name};P:{self.password};;"

    def remaining(self, now: float) -> float:
        return max(0.0, self.started + self.ttl - now)

    def expired(self, now: float) -> bool:
        return self.remaining(now) <= 0.0

    def countdown(self, now: float) -> str:
        seconds = math.ceil(self.remaining(now))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def consume(self, now: float) -> bool:
        """Claim the secret once; False if it is expired or already used."""
        if self._used or self.expired(now):
            return False
        self._used = True
        return True


def new_session(now: float, ttl: float = DEFAULT_TTL) -> PairingSession:
    return PairingSession(
        name=NAME_PREFIX + _random_text(NAME_LENGTH),
        password=_random_text(PASSWORD_LENGTH),
        started=now,
        ttl=ttl,
    )


@dataclass(frozen=True)
class MdnsEntry:
    instance: str
    service: str
    address: str  # host:port

    @property
    def host(self) -> str:
        return self.address.rsplit(":", 1)[0].strip("[]")

    @property
    def port(self) -> int:
        return int(self.address.rsplit(":", 1)[1])


def _valid_port(text: str) -> bool:
    return _PORT.fullmatch(text) is not None and 0 < int(text) <= _MAX_PORT


def parse_mdns(output: str) -> list[MdnsEntry]:
    """Parse `adb mdns services`: TAB-separated instance, type, host:port."""
    entries: list[MdnsEntry] = []
    for line in output.splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 3:
            continue
        instance, service, address = (part.strip() for part in parts)
        host, _, port = address.rpartition(":")
        if not (instance and service.startswith("_") and _valid_port(port)):
            continue
        if not _MDNS_HOST.fullmatch(host.strip("[]")):
            continue
        entries.append(MdnsEntry(instance, service, address))
    return entries


def find_pairing(entries: Sequence[MdnsEntry], name: str) -> MdnsEntry | None:
    """The pairing entry the phone advertises under OUR instance name."""
    for entry in entries:
        if entry.service == PAIRING_SERVICE and entry.instance == name:
            return entry
    return None


def find_connect(entries: Sequence[MdnsEntry], host: str) -> MdnsEntry | None:
    """The connect entry of the same host; the instance names differ on purpose."""
    for entry in entries:
        if entry.service == CONNECT_SERVICE and entry.host == host:
            return entry
    return None


def find_connect_by_instance(
    entries: Sequence[MdnsEntry], instance: str
) -> MdnsEntry | None:
    """The connect entry of one phone, by its stable mDNS instance name."""
    for entry in entries:
        if entry.service == CONNECT_SERVICE and entry.instance == instance:
            return entry
    return None


def connect_succeeded(rc: int, text: str) -> bool:
    """`adb connect` can print "failed to connect" with rc 0, so read the text."""
    lowered = text.lower()
    return rc == 0 and "connected to" in lowered and "failed" not in lowered


def parse_endpoint(text: str) -> str | None:
    """A validated `host:port`, or None."""
    value = text.strip()
    host, _, port = value.rpartition(":")
    if _HOST.fullmatch(host) and _valid_port(port):
        return value
    return None


def parse_code(text: str) -> str | None:
    """The 6-digit pairing code shown by the phone, or None."""
    value = text.strip()
    return value if _CODE.fullmatch(value) else None


def build_mdns_argv(adb_path: str, action: str) -> list[str]:
    return build_adb_argv(adb_path, ["mdns", action])


def build_pair_argv(adb_path: str, endpoint: str) -> list[str]:
    """`adb pair host:port`; the code is fed through stdin, never through argv."""
    return build_adb_argv(adb_path, ["pair", endpoint])


def build_zenity_pair_argv() -> list[str]:
    """The manual form: the phone's pairing address and 6-digit code."""
    return [
        "zenity",
        "--forms",
        "--title=Pair phone over Wi-Fi",
        "--text=On the phone open Wireless debugging and choose "
        "Pair device with pairing code",
        "--separator=|",
        "--add-entry=Pairing address host:port",
        "--add-entry=Pairing code (6 digits)",
    ]


def parse_zenity_pair(stdout: str) -> tuple[str, str] | None:
    """Parse the form output into (endpoint, code); None if malformed."""
    values = stdout.strip().split("|")
    if len(values) != 2:
        return None
    endpoint, code = parse_endpoint(values[0]), parse_code(values[1])
    if endpoint is None or code is None:
        return None
    return endpoint, code


def redact(text: str, secret: str) -> str:
    """Hide the secret in any text that is about to be logged."""
    return text.replace(secret, "***") if secret else text
