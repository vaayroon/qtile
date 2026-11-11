"""Remembered device file and reconnect backoff (R2.8, R2.9). tmp only."""

import json
import os
import stat
from pathlib import Path

import pytest
from src.widgets import phone_mirror_state as st
from src.widgets.phone_mirror_state import RememberedDevice

INSTANCE = "adb-56201FDCR0077W-I7p3gg"  # real mDNS instance name (Pixel 10, adb 37)
SERIAL = "56201FDCR0077W"
ADDRESS = "192.168.1.134:45135"


def make(**changes: str) -> RememberedDevice:
    fields = {
        "service_name": INSTANCE,
        "serial": SERIAL,
        "last_address": ADDRESS,
        "paired_at": "2026-11-11T20:00:00+00:00",
    }
    fields.update(changes)
    return RememberedDevice(**fields)


# --- where the file lives ------------------------------------------------------


def test_the_file_is_created_inside_xdg_state_home(tmp_path: Path) -> None:
    path = st.state_path({"XDG_STATE_HOME": str(tmp_path)})
    assert path == tmp_path / "qtile" / "phone_mirror.json"


def test_the_default_is_under_home_local_state() -> None:
    path = st.state_path({"HOME": "/home/someone"})
    assert path == Path("/home/someone/.local/state/qtile/phone_mirror.json")


def test_an_empty_or_relative_xdg_value_falls_back_to_the_default() -> None:
    expected = Path("/home/someone/.local/state/qtile/phone_mirror.json")
    assert st.state_path({"XDG_STATE_HOME": "", "HOME": "/home/someone"}) == expected
    relative = {"XDG_STATE_HOME": "relative/dir", "HOME": "/home/someone"}
    assert st.state_path(relative) == expected


# --- save / load ------------------------------------------------------------------


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "qtile" / "phone_mirror.json"

    assert st.save(path, make()) is True

    assert st.load(path) == make()


def test_the_file_holds_the_identity_and_the_last_endpoint(tmp_path: Path) -> None:
    path = tmp_path / "phone_mirror.json"
    st.save(path, make())

    data = json.loads(path.read_text())

    assert data == {
        "version": 1,
        "serial": SERIAL,
        "service_name": INSTANCE,
        "last_address": ADDRESS,
        "paired_at": "2026-11-11T20:00:00+00:00",
    }


def test_the_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "qtile" / "phone_mirror.json"
    st.save(path, make())

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_the_write_goes_through_a_part_file_and_a_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "phone_mirror.json"
    seen: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src: str | Path, dst: str | Path) -> None:
        seen.append((str(src), str(dst)))
        assert Path(src).exists()
        assert not Path(dst).exists()
        real_replace(src, dst)

    monkeypatch.setattr(st.os, "replace", spy)

    st.save(path, make())

    assert seen == [(f"{path}.part", str(path))]
    assert not Path(f"{path}.part").exists()


def test_a_failed_write_keeps_the_previous_file_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "phone_mirror.json"
    st.save(path, make())

    def boom(_src: object, _dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(st.os, "replace", boom)

    assert st.save(path, make(last_address="10.0.0.9:1111")) is False

    assert st.load(path) == make()
    assert not Path(f"{path}.part").exists()


def test_a_stale_part_file_from_a_crash_does_not_block_a_save(tmp_path: Path) -> None:
    path = tmp_path / "phone_mirror.json"
    Path(f"{path}.part").write_text("garbage")

    assert st.save(path, make()) is True

    assert st.load(path) == make()


# --- corrupt or odd files are ignored -------------------------------------------------


def test_a_missing_file_means_no_remembered_device(tmp_path: Path) -> None:
    assert st.load(tmp_path / "nope.json") is None


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{not json",
        "[]",
        "null",
        '"text"',
        json.dumps({"version": 2, "service_name": INSTANCE, "last_address": ADDRESS}),
        json.dumps({"version": 1}),
        json.dumps({"version": 1, "service_name": "", "last_address": ADDRESS}),
        json.dumps({"version": 1, "service_name": INSTANCE, "last_address": "x"}),
        json.dumps({"version": 1, "service_name": 5, "last_address": ADDRESS}),
        json.dumps({"version": 1, "service_name": INSTANCE, "last_address": "a b:1"}),
        json.dumps({"version": 1, "service_name": "a b", "last_address": ADDRESS}),
        "\x00\x01\x02",
    ],
)
def test_a_corrupt_file_is_ignored(tmp_path: Path, content: str) -> None:
    path = tmp_path / "phone_mirror.json"
    path.write_text(content)

    assert st.load(path) is None


def test_a_file_with_undecodable_bytes_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "phone_mirror.json"
    path.write_bytes(b"\xff\xfe\xfa")

    assert st.load(path) is None


def test_a_directory_in_place_of_the_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "phone_mirror.json"
    path.mkdir()

    assert st.load(path) is None


def test_missing_optional_fields_load_with_empty_values(tmp_path: Path) -> None:
    path = tmp_path / "phone_mirror.json"
    path.write_text(
        json.dumps({"version": 1, "service_name": INSTANCE, "last_address": ADDRESS})
    )

    loaded = st.load(path)

    assert loaded is not None
    assert loaded.serial == ""
    assert loaded.paired_at == ""


# --- identity helpers ---------------------------------------------------------------


def test_the_serial_is_embedded_in_the_instance_name() -> None:
    assert st.serial_from_instance(INSTANCE) == SERIAL


@pytest.mark.parametrize("name", ["", "qtile-AbCdEfGhIj", "adb-", "adb--x", "plain"])
def test_names_without_an_embedded_serial_give_nothing(name: str) -> None:
    assert st.serial_from_instance(name) == ""


def test_a_serial_with_a_dash_keeps_everything_before_the_random_suffix() -> None:
    assert st.serial_from_instance("adb-AB-CD-Zz9") == "AB-CD"


@pytest.mark.parametrize(
    ("serial", "wireless"),
    [
        ("192.168.1.134:45135", True),
        ("[fe80::1]:5555", True),
        (f"{INSTANCE}._adb-tls-connect._tcp", True),
        (SERIAL, False),
        ("emulator-5554", False),
        ("", False),
    ],
)
def test_wireless_serials(serial: str, wireless: bool) -> None:
    assert st.is_wireless_serial(serial) is wireless


@pytest.mark.parametrize(
    "listed",
    [
        ADDRESS,  # connected by host:port
        SERIAL,  # the same phone over USB
        f"{INSTANCE}._adb-tls-connect._tcp",  # connected by its mDNS name
    ],
)
def test_the_remembered_device_matches_its_listed_forms(listed: str) -> None:
    assert make().matches(listed) is True


@pytest.mark.parametrize("listed", ["192.168.1.134:9999", "OTHERSERIAL", "", "adb-x-y"])
def test_other_devices_do_not_match(listed: str) -> None:
    assert make().matches(listed) is False


def test_a_device_without_a_serial_never_matches_an_empty_listing() -> None:
    assert make(serial="").matches("") is False


# --- backoff -------------------------------------------------------------------


def test_the_backoff_is_8_16_32_64_128_300() -> None:
    assert st.BACKOFF == (8.0, 16.0, 32.0, 64.0, 128.0, 300.0)
    assert [st.backoff_delay(n) for n in range(6)] == [8, 16, 32, 64, 128, 300]


def test_at_most_six_attempts_per_disconnect() -> None:
    assert st.MAX_ATTEMPTS == 6


@pytest.mark.parametrize("attempt", [6, 7, 100])
def test_no_delay_after_the_last_attempt(attempt: int) -> None:
    assert st.backoff_delay(attempt) is None


def test_a_negative_attempt_is_not_a_delay() -> None:
    assert st.backoff_delay(-1) is None


def test_the_delays_never_shrink_and_stay_capped() -> None:
    delays = [st.backoff_delay(n) for n in range(st.MAX_ATTEMPTS)]
    assert all(d is not None for d in delays)
    values = [d for d in delays if d is not None]
    assert values == sorted(values)
    assert max(values) == 300.0
