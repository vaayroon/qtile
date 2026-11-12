"""Map adb/scrcpy output and exceptions to a user-facing failure reason."""

from enum import Enum


class Reason(Enum):
    MISSING_BINARY = "missing_binary"
    UNAUTHORIZED = "unauthorized"
    OFFLINE = "offline"
    UNREACHABLE = "unreachable"
    NO_DEVICE = "no_device"
    MULTIPLE_DEVICES = "multiple_devices"
    PAIR_REJECTED = "pair_rejected"
    PAIR_CONNECTION_LOST = "pair_connection_lost"
    MDNS_UNAVAILABLE = "mdns_unavailable"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


_MESSAGES: dict[Reason, str] = {
    Reason.MISSING_BINARY: "adb or scrcpy was not found. Check the configured paths.",
    Reason.UNAUTHORIZED: (
        "Device unauthorized. Accept the USB/Wi-Fi debugging prompt on the phone."
    ),
    Reason.OFFLINE: "Device offline. Unlock the phone and reconnect it.",
    Reason.UNREACHABLE: (
        "Phone unreachable. Check that it is on the same Wi-Fi network."
    ),
    Reason.NO_DEVICE: "No device found. Connect or pair the phone first.",
    Reason.MULTIPLE_DEVICES: (
        "More than one device is connected. Set QTILE_PHONE_MIRROR_DEVICE."
    ),
    # Flow-aware: only a flow where the user typed a code may blame the code.
    Reason.PAIR_REJECTED: "Pairing failed. Start pairing again.",
    Reason.PAIR_CONNECTION_LOST: (
        "Connection lost during pairing. Try again and keep the phone "
        "on the same Wi-Fi network."
    ),
    Reason.MDNS_UNAVAILABLE: "Automatic discovery (mDNS) is not available.",
    Reason.EXPIRED: "The pairing code expired. Start pairing again.",
    Reason.UNKNOWN: "Unexpected failure. See the qtile log for details.",
}

_REJECTED_TYPED_CODE = "Pairing was rejected. Check the pairing code."

# Ordered: the first matching rule wins.
_RULES: list[tuple[tuple[str, ...], Reason]] = [
    (("protocol fault", "connection reset"), Reason.PAIR_CONNECTION_LOST),
    (("unauthorized",), Reason.UNAUTHORIZED),
    (("offline",), Reason.OFFLINE),
    (("command not found", "no such file or directory"), Reason.MISSING_BINARY),
    (("more than one device",), Reason.MULTIPLE_DEVICES),
    (("no devices", "device not found"), Reason.NO_DEVICE),
    (("wrong password", "pairing failed", "failed to pair"), Reason.PAIR_REJECTED),
    (("expired",), Reason.EXPIRED),
    (
        (
            "failed to connect",
            "unable to connect",
            "cannot connect",
            "connection refused",
            "timed out",
            "no route to host",
            "unreachable",
        ),
        Reason.UNREACHABLE,
    ),
]


def map_failure(text: str, rc: int | None = None) -> Reason:
    """Classify combined stdout+stderr; adb exit codes are not reliable."""
    lowered = text.lower()
    if rc == 127:  # the shell convention for "command not found"
        return Reason.MISSING_BINARY
    if "mdns" in lowered and ("not available" in lowered or "unavailable" in lowered):
        return Reason.MDNS_UNAVAILABLE
    for needles, reason in _RULES:
        if any(needle in lowered for needle in needles):
            return reason
    return Reason.UNKNOWN


def map_exception(exc: BaseException) -> Reason:
    if isinstance(exc, FileNotFoundError):
        return Reason.MISSING_BINARY
    return map_failure(str(exc) or type(exc).__name__)


def message_for(reason: Reason, *, typed_code: bool = False) -> str:
    """The user-facing text; `typed_code` is True when the user entered the code."""
    if reason is Reason.PAIR_REJECTED and typed_code:
        return _REJECTED_TYPED_CODE
    return _MESSAGES[reason]
