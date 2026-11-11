"""Failure reason mapping for adb/scrcpy output (R1.5)."""

import pytest
from src.widgets.phone_mirror_reasons import (
    Reason,
    map_exception,
    map_failure,
    message_for,
)

# Real line from a live pairing run where the phone dropped the connection.
PROTOCOL_FAULT = (
    "adb pair 192.168.1.134:44667: Enter pairing code: \n"
    "error: protocol fault (couldn't read status message): Success"
)


@pytest.mark.parametrize(
    ("text", "rc", "expected"),
    [
        ("adb: device unauthorized.", 1, Reason.UNAUTHORIZED),
        ("ABC123\tunauthorized", 0, Reason.UNAUTHORIZED),
        ("error: device offline", 1, Reason.OFFLINE),
        ("failed to connect to '192.168.1.20:5555'", 0, Reason.UNREACHABLE),
        ("cannot connect: Connection refused", 1, Reason.UNREACHABLE),
        ("unable to connect: timed out", 1, Reason.UNREACHABLE),
        ("error: no devices/emulators found", 1, Reason.NO_DEVICE),
        ("adb: more than one device/emulator", 1, Reason.MULTIPLE_DEVICES),
        ("Failed: Wrong password or connection was dropped.", 1, Reason.PAIR_REJECTED),
        ("mDNS discovery is not available", 1, Reason.MDNS_UNAVAILABLE),
        (PROTOCOL_FAULT, 1, Reason.PAIR_CONNECTION_LOST),
        ("error: connection reset by peer", 1, Reason.PAIR_CONNECTION_LOST),
        ("sh: adb: command not found", 127, Reason.MISSING_BINARY),
        ("something completely different", 1, Reason.UNKNOWN),
        ("", 1, Reason.UNKNOWN),
    ],
)
def test_map_failure(text: str, rc: int, expected: Reason) -> None:
    assert map_failure(text, rc) is expected


def test_map_failure_is_case_insensitive() -> None:
    assert map_failure("DEVICE UNAUTHORIZED", 1) is Reason.UNAUTHORIZED


def test_exit_code_127_maps_to_missing_binary() -> None:
    assert map_failure("", 127) is Reason.MISSING_BINARY


def test_file_not_found_maps_to_missing_binary() -> None:
    assert map_exception(FileNotFoundError("adb")) is Reason.MISSING_BINARY


def test_other_exceptions_map_by_text_or_unknown() -> None:
    assert map_exception(TimeoutError("timed out")) is Reason.UNREACHABLE
    assert map_exception(RuntimeError("boom")) is Reason.UNKNOWN


@pytest.mark.parametrize("reason", list(Reason))
def test_every_reason_has_a_distinct_english_message(reason: Reason) -> None:
    text = message_for(reason)
    assert text
    assert text.isascii()
    assert text == message_for(reason)


def test_messages_are_unique() -> None:
    messages = [message_for(r) for r in Reason]
    assert len(set(messages)) == len(messages)


def test_unauthorized_message_names_the_reason() -> None:
    assert "unauthorized" in message_for(Reason.UNAUTHORIZED).lower()


def test_connection_lost_message_suggests_retrying_on_the_same_wifi() -> None:
    text = message_for(Reason.PAIR_CONNECTION_LOST).lower()
    assert "connection lost" in text
    assert "again" in text
    assert "same wi-fi network" in text
    assert "code" not in text


def test_the_rejected_message_only_blames_the_code_when_one_was_typed() -> None:
    assert "code" in message_for(Reason.PAIR_REJECTED, typed_code=True).lower()
    assert "code" not in message_for(Reason.PAIR_REJECTED).lower()
    assert "code" not in message_for(Reason.PAIR_REJECTED, typed_code=False).lower()
