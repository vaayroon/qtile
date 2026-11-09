"""Pure scrcpy/adb argv builders and the `adb devices` parser (R1.3, R1.8)."""

import pytest
from src.widgets import phone_mirror_runner as runner
from src.widgets.phone_mirror_commands import (
    QUALITY_PRESETS,
    Device,
    MirrorOptions,
    build_adb_argv,
    build_connect_argv,
    build_devices_argv,
    build_disconnect_argv,
    build_keyevent_argv,
    build_scrcpy_argv,
    normalize_quality,
    parse_devices,
    ready_device,
)


def _value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


@pytest.mark.parametrize("quality", ["low", "balanced", "high"])
def test_quality_presets_map_to_scrcpy_flags(quality: str) -> None:
    argv = build_scrcpy_argv("scrcpy", MirrorOptions(quality=quality))
    max_size, bit_rate, fps = QUALITY_PRESETS[quality]

    assert _value(argv, "--video-bit-rate") == bit_rate
    assert _value(argv, "--max-fps") == str(fps)
    if max_size is None:
        assert "--max-size" not in argv
    else:
        assert _value(argv, "--max-size") == str(max_size)


def test_low_preset_values() -> None:
    assert QUALITY_PRESETS["low"] == (1024, "4M", 30)
    assert QUALITY_PRESETS["balanced"] == (1600, "8M", 60)
    assert QUALITY_PRESETS["high"] == (None, "16M", 60)


def test_defaults_are_balanced_screen_off_no_audio() -> None:
    options = MirrorOptions()
    argv = build_scrcpy_argv("scrcpy", options)

    assert options.quality == "balanced"
    assert argv[0] == "scrcpy"
    assert "-S" in argv
    assert "--no-audio" in argv


@pytest.mark.parametrize("screen_off", [True, False])
def test_screen_off_flag(screen_off: bool) -> None:
    argv = build_scrcpy_argv("scrcpy", MirrorOptions(screen_off=screen_off))
    assert ("-S" in argv) is screen_off


@pytest.mark.parametrize("audio", [True, False])
def test_audio_flag(audio: bool) -> None:
    argv = build_scrcpy_argv("scrcpy", MirrorOptions(audio=audio))
    assert ("--no-audio" in argv) is (not audio)


def test_window_title_is_always_present_and_non_empty() -> None:
    for options in (MirrorOptions(), MirrorOptions(window_title="")):
        argv = build_scrcpy_argv("scrcpy", options)
        assert _value(argv, "--window-title")


def test_serial_targets_the_device() -> None:
    argv = build_scrcpy_argv("scrcpy", MirrorOptions(serial="192.168.1.10:5555"))
    assert _value(argv, "-s") == "192.168.1.10:5555"
    assert "-s" not in build_scrcpy_argv("scrcpy", MirrorOptions())


def test_unknown_quality_falls_back_to_balanced() -> None:
    assert normalize_quality("ultra") == "balanced"
    assert normalize_quality(" LOW ") == "low"
    assert normalize_quality("") == "balanced"
    argv = build_scrcpy_argv("scrcpy", MirrorOptions(quality="ultra"))
    assert _value(argv, "--max-size") == "1600"


def test_all_built_argv_pass_the_runner_allowlist() -> None:
    argvs = [
        build_scrcpy_argv("/opt/genymobile/scrcpy", MirrorOptions(serial="SER")),
        build_devices_argv("adb"),
        build_connect_argv("adb", "192.168.1.20:5555"),
        build_disconnect_argv("adb"),
        build_disconnect_argv("adb", "192.168.1.20:5555"),
        build_keyevent_argv("adb", 24),
        build_keyevent_argv("adb", 25, serial="SER"),
    ]
    for argv in argvs:
        runner.validate(argv)


def test_adb_argv_builders() -> None:
    assert build_adb_argv("adb", ["devices"]) == ["adb", "devices"]
    assert build_adb_argv("adb", ["devices"], serial="S") == [
        "adb",
        "-s",
        "S",
        "devices",
    ]
    assert build_devices_argv("adb") == ["adb", "devices"]
    assert build_connect_argv("adb", "1.2.3.4:5555") == [
        "adb",
        "connect",
        "1.2.3.4:5555",
    ]
    assert build_disconnect_argv("adb") == ["adb", "disconnect"]
    assert build_disconnect_argv("adb", "1.2.3.4:5555") == [
        "adb",
        "disconnect",
        "1.2.3.4:5555",
    ]
    assert build_keyevent_argv("adb", 24, serial="S") == [
        "adb",
        "-s",
        "S",
        "shell",
        "input",
        "keyevent",
        "24",
    ]


# --- devices parser ----------------------------------------------------------


def test_parse_devices_one_device() -> None:
    out = "List of devices attached\n192.168.1.10:5555\tdevice\n\n"
    assert parse_devices(out) == [Device("192.168.1.10:5555", "device")]


def test_parse_devices_empty() -> None:
    assert parse_devices("List of devices attached\n\n") == []
    assert parse_devices("") == []


def test_parse_devices_skips_daemon_noise_and_keeps_states() -> None:
    out = (
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n"
        "ABC123\tunauthorized\n"
        "XYZ789\toffline\n"
        "192.168.1.10:5555\tdevice product:x model:Y\n"
    )
    assert parse_devices(out) == [
        Device("ABC123", "unauthorized"),
        Device("XYZ789", "offline"),
        Device("192.168.1.10:5555", "device"),
    ]


def test_ready_device_filters_by_expected_serial() -> None:
    devices = [Device("A", "offline"), Device("B", "device"), Device("C", "device")]
    assert ready_device(devices, "") == "B"
    assert ready_device(devices, "C") == "C"
    assert ready_device(devices, "A") is None
    assert ready_device(devices, "Z") is None
    assert ready_device([], "") is None
