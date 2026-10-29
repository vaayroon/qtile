"""Unit tests for ``src/utils/system.py``.

Nothing here touches the real machine. ``xrandr`` is never spawned: the
``subprocess`` functions are replaced on the module under test with fakes that
record their argv and return canned ``CompletedProcess`` objects (or raise).
``/proc`` is never read: the module's ``Path`` name is redirected into
``tmp_path`` so the lid-state lookup walks a fake tree. The environment
variables the code reads are cleared by an autouse fixture, because a
developer's shell may export them; each test sets only what it depends on.
Every test therefore passes identically on a CI runner with no X server and no
``xrandr`` binary.
"""

import errno
import subprocess

import pytest
from src.utils import system
from src.utils.system import (
    MonitorInfo,
    _build_dynamic_layout_command,
    _internal_output_overrides,
    _is_internal_output,
    _legacy_fallback_commands,
    _monitor_sort_key,
    _parse_mode_width,
    _port_priority,
    _primary_output_name,
    _read_lid_state,
    _run_xrandr_props,
    _serial_from_edid,
    _serial_priority,
    apply_best_effort_layout,
    detect_connected_monitors,
    effective_monitor_count,
    select_layout_monitors,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "QTILE_INTERNAL_OUTPUTS",
        "QTILE_SCREEN_SERIAL_ORDER",
        "QTILE_SCREEN_PORT_ORDER",
        "QTILE_PRIMARY_MONITOR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_primary_output_name_single_monitor_ignores_env(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "HDMI-0")

    assert _primary_output_name(["DP-2"]) == "DP-2"


def test_primary_output_name_multi_monitor_returns_env_match(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "DP-1")

    assert _primary_output_name(["DP-1", "HDMI-1"]) == "DP-1"


def test_primary_output_name_multi_monitor_env_not_set_uses_heuristic(monkeypatch):
    monkeypatch.delenv("QTILE_PRIMARY_MONITOR", raising=False)

    assert _primary_output_name(["DP-1", "HDMI-0"]) == "HDMI-0"


def test_primary_output_name_multi_monitor_empty_env_uses_heuristic(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "")

    assert _primary_output_name(["DP-1", "HDMI-0"]) == "HDMI-0"


def test_primary_output_name_multi_monitor_whitespace_env_uses_heuristic(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "   ")

    assert _primary_output_name(["DP-1", "HDMI-0"]) == "HDMI-0"


def test_primary_output_name_multi_monitor_invalid_env_uses_heuristic(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "FAKE-99")

    assert _primary_output_name(["DP-1", "HDMI-0"]) == "HDMI-0"


# --- helpers -----------------------------------------------------------------

EDID_HEADER = bytes.fromhex("00ffffffffffff00")


def _edid_lines(serial_bytes: bytes) -> list[str]:
    """128-byte EDID as xrandr prints it: 8 lines of 32 hex chars, two tabs."""
    blob = bytearray(128)
    blob[0:8] = EDID_HEADER
    blob[12:16] = serial_bytes
    hex_blob = blob.hex()
    return ["\t\t" + hex_blob[i : i + 32] for i in range(0, len(hex_blob), 32)]


def _xrandr(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _mon(
    name: str,
    *,
    serial: str | None = None,
    mode: str | None = "1920x1080+0+0",
    internal: bool = False,
) -> MonitorInfo:
    return MonitorInfo(
        name=name, connected=True, mode=mode, serial=serial, is_internal=internal
    )


def _names(monitors: list[MonitorInfo]) -> list[str]:
    return [monitor.name for monitor in monitors]


def _primary_of(command: list[str]) -> str:
    """Name of the output the ``--primary`` flag belongs to."""
    index = command.index("--primary")
    while command[index] != "--output":
        index -= 1
    return command[index + 1]


SERIAL_A = b"\x01\x02\x03\x04"  # little endian -> 67305985
SERIAL_B = b"\x0a\x00\x00\x00"  # little endian -> 10

LAPTOP_AND_HDMI = _xrandr(
    "Screen 0: minimum 8 x 8, current 3840 x 1080, maximum 32767 x 32767",
    "eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis"
    " y axis) 344mm x 194mm",
    "\tEDID: ",
    *_edid_lines(SERIAL_A),
    "\tnon-desktop: 0 ",
    "\tscaling mode: Full aspect ",
    "   1920x1080     60.00*+  59.97  ",
    "   1680x1050     59.88  ",
    "HDMI-0 connected 1920x1080+1920+0 (normal left inverted right x axis"
    " y axis) 527mm x 296mm",
    "\tEDID: ",
    *_edid_lines(SERIAL_B),
    "\tnon-desktop: 0 ",
    "   1920x1080     60.00*+  50.00    59.94  ",
    "DP-0 disconnected (normal left inverted right x axis y axis)",
    "DP-1 disconnected (normal left inverted right x axis y axis)",
)

# Real xrandr prints no EDID for a disconnected port, only connector properties.
DISCONNECTED_WITH_PROPERTIES = _xrandr(
    "Screen 0: minimum 8 x 8, current 1920 x 1080, maximum 32767 x 32767",
    "DP-0 disconnected (normal left inverted right x axis y axis)",
    "\tlink-status: Good ",
    "\tCONNECTOR_ID: 95 ",
    "\tnon-desktop: 0 ",
    "HDMI-0 connected primary 1920x1080+0+0 (normal left inverted right x axis"
    " y axis) 527mm x 296mm",
    "\tnon-desktop: 0 ",
    "   1920x1080     60.00*+  50.00  ",
)

# xrandr itself never prints this line; the parser accepts it as an explicit
# serial property, so the branch is pinned here on its own.
SERIAL_PROPERTY_ONLY = _xrandr(
    "Screen 0: minimum 8 x 8, current 1920 x 1080, maximum 32767 x 32767",
    "HDMI-0 connected 1920x1080+0+0 (normal left inverted right x axis y axis)",
    "\tserial number: SN12345 ",
    "\tnon-desktop: 0 ",
)

NO_GEOMETRY_AND_ZERO_SERIAL = _xrandr(
    "Screen 0: minimum 8 x 8, current 1920 x 1080, maximum 32767 x 32767",
    "HDMI-1 connected (normal left inverted right x axis y axis)",
    "\tnon-desktop: 0 ",
    "DP-2 connected 2560x1440+0+0 (normal left inverted right x axis y axis)"
    " 597mm x 336mm",
    "\tEDID: ",
    *_edid_lines(b"\x00\x00\x00\x00"),
    "\tnon-desktop: 0 ",
    "   2560x1440     59.95*+  ",
)

# The EDID block is the last thing before the next port header, so it is
# flushed by the header and not by a property line.
EDID_BEFORE_HEADER = _xrandr(
    "Screen 0: minimum 8 x 8, current 1920 x 1080, maximum 32767 x 32767",
    "DP-1 connected 1920x1080+0+0 (normal left inverted right x axis y axis)",
    "\tEDID: ",
    *_edid_lines(SERIAL_A),
    "DP-3 connected 1920x1080+1920+0 (normal left inverted right x axis y axis)",
)


# --- _parse_mode_width -------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (None, 1920),
        ("", 1920),
        ("2560x1440+0+0", 2560),
        ("abcx100+0+0", 1920),
        ("320x200+0+0", 640),
    ],
)
def test_parse_mode_width(mode, expected):
    assert _parse_mode_width(mode) == expected


# --- _serial_from_edid -------------------------------------------------------


def test_serial_from_edid_decodes_little_endian_serial():
    serial = _serial_from_edid(_edid_lines(SERIAL_A))

    assert serial == "67305985"
    assert serial == str(int.from_bytes(SERIAL_A, byteorder="little"))


def test_serial_from_edid_zero_serial_is_none():
    assert _serial_from_edid(_edid_lines(b"\x00\x00\x00\x00")) is None


def test_serial_from_edid_short_blob_is_none():
    assert _serial_from_edid(["00ffffffffffff00"]) is None


def test_serial_from_edid_non_hex_content_is_none():
    assert _serial_from_edid(["zz" * 16]) is None


def test_serial_from_edid_strips_tabs_and_spaces():
    lines = [f" \t{line.strip()}\t " for line in _edid_lines(SERIAL_A)]

    assert _serial_from_edid(lines) == "67305985"


# --- _read_lid_state ---------------------------------------------------------


@pytest.fixture
def proc_root(monkeypatch, tmp_path):
    """Redirect ``system.Path`` so absolute paths resolve under ``tmp_path``."""
    monkeypatch.setattr(system, "Path", lambda p: tmp_path / str(p).lstrip("/"))
    return tmp_path


def _write_lid(root, text: str, name: str = "LID0") -> None:
    lid = root / "proc/acpi/button/lid" / name
    lid.mkdir(parents=True)
    (lid / "state").write_text(text, encoding="utf-8")


@pytest.mark.usefixtures("proc_root")
def test_read_lid_state_without_lid_dir_is_none():
    assert _read_lid_state() is None


def test_read_lid_state_closed(proc_root):
    _write_lid(proc_root, "state:      closed\n")

    assert _read_lid_state() is True


def test_read_lid_state_open(proc_root):
    _write_lid(proc_root, "state:      open\n")

    assert _read_lid_state() is False


def test_read_lid_state_garbage_is_none(proc_root):
    _write_lid(proc_root, "no idea\n")

    assert _read_lid_state() is None


def test_read_lid_state_skips_unreadable_state_file(proc_root):
    # A directory named "state" exists but read_text() raises an OSError.
    (proc_root / "proc/acpi/button/lid/LID0/state").mkdir(parents=True)

    assert _read_lid_state() is None


# --- internal output helpers -------------------------------------------------


def test_internal_output_overrides_unset_is_empty():
    assert _internal_output_overrides() == set()


def test_internal_output_overrides_parses_and_strips(monkeypatch):
    monkeypatch.setenv("QTILE_INTERNAL_OUTPUTS", "eDP-1, DP-5,,")

    assert _internal_output_overrides() == {"eDP-1", "DP-5"}


@pytest.mark.parametrize("name", ["eDP-1", "LVDS-1", "DSI-1"])
def test_is_internal_output_matches_builtin_prefixes(name):
    assert _is_internal_output(name, set()) is True


def test_is_internal_output_external_port_is_false():
    assert _is_internal_output("DP-0", set()) is False


def test_is_internal_output_honours_override():
    assert _is_internal_output("DP-5", {"DP-5"}) is True


# --- _run_xrandr_props -------------------------------------------------------


def test_run_xrandr_props_invokes_xrandr_without_stderr(monkeypatch):
    calls = []

    def fake_check_output(argv, **kwargs):
        calls.append((argv, kwargs))
        return "xrandr output"

    monkeypatch.setattr(system.subprocess, "check_output", fake_check_output)

    assert _run_xrandr_props() == "xrandr output"
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ["xrandr", "--props"]
    assert kwargs["text"] is True
    assert kwargs["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(errno.ENOENT, "No such file or directory", "xrandr"),
        PermissionError(errno.EACCES, "Permission denied", "xrandr"),
        OSError(errno.ENOEXEC, "Exec format error", "xrandr"),
    ],
    ids=["missing", "not-executable", "bad-format"],
)
def test_run_xrandr_props_exec_failure_is_empty(monkeypatch, error):
    def fake_check_output(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(system.subprocess, "check_output", fake_check_output)

    assert _run_xrandr_props() == ""


def test_run_xrandr_props_failing_xrandr_is_empty(monkeypatch):
    def fake_check_output(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "xrandr")

    monkeypatch.setattr(system.subprocess, "check_output", fake_check_output)

    assert _run_xrandr_props() == ""


# --- detect_connected_monitors -----------------------------------------------


def _detect(monkeypatch, sample: str) -> list[MonitorInfo]:
    monkeypatch.setattr(system, "_run_xrandr_props", lambda: sample)
    return detect_connected_monitors()


def test_detect_connected_monitors_empty_output(monkeypatch):
    assert _detect(monkeypatch, "") == []


def test_detect_connected_monitors_returns_only_connected_in_xrandr_order(
    monkeypatch,
):
    monitors = _detect(monkeypatch, LAPTOP_AND_HDMI)

    assert _names(monitors) == ["eDP-1", "HDMI-0"]
    assert all(monitor.connected for monitor in monitors)


def test_detect_connected_monitors_parses_mode_and_primary(monkeypatch):
    edp, hdmi = _detect(monkeypatch, LAPTOP_AND_HDMI)

    assert edp.mode == "1920x1080+0+0"
    assert hdmi.mode == "1920x1080+1920+0"


def test_detect_connected_monitors_decodes_edid_serial(monkeypatch):
    edp, hdmi = _detect(monkeypatch, LAPTOP_AND_HDMI)

    assert edp.serial == "67305985"
    assert hdmi.serial == "10"


def test_detect_connected_monitors_skips_disconnected_port(monkeypatch):
    monitors = _detect(monkeypatch, DISCONNECTED_WITH_PROPERTIES)

    assert _names(monitors) == ["HDMI-0"]
    assert monitors[0].serial is None


def test_detect_connected_monitors_reads_serial_property_line(monkeypatch):
    (hdmi,) = _detect(monkeypatch, SERIAL_PROPERTY_ONLY)

    assert hdmi.serial == "SN12345"


_HEADER = "DP-1 connected 1920x1080+0+0 (normal left inverted right x axis y axis)"
_SERIAL_LINE = "\tserial number: SN12345 "
_EDID_BLOCK = ("\tEDID: ", *_edid_lines(SERIAL_A))
_PROPERTY = "\tnon-desktop: 0 "


@pytest.mark.parametrize(
    "block",
    [
        (_SERIAL_LINE, *_EDID_BLOCK, _PROPERTY),
        (_SERIAL_LINE, *_EDID_BLOCK),
        (*_EDID_BLOCK, _SERIAL_LINE, _PROPERTY),
        (*_EDID_BLOCK, _SERIAL_LINE),
        (*_EDID_BLOCK, _PROPERTY, _SERIAL_LINE),
    ],
    ids=[
        "serial-edid-property",
        "serial-edid-end",
        "edid-serial-property",
        "edid-serial-end",
        "edid-property-serial",
    ],
)
def test_detect_connected_monitors_explicit_serial_beats_edid(monkeypatch, block):
    # Which serial won used to depend on the line after the EDID block.
    (monitor,) = _detect(monkeypatch, _xrandr(_HEADER, *block))

    assert monitor.serial == "SN12345"


def test_detect_connected_monitors_without_geometry_has_no_mode(monkeypatch):
    hdmi, _ = _detect(monkeypatch, NO_GEOMETRY_AND_ZERO_SERIAL)

    assert hdmi.name == "HDMI-1"
    assert hdmi.mode is None


def test_detect_connected_monitors_zero_serial_edid_is_none(monkeypatch):
    _, dp = _detect(monkeypatch, NO_GEOMETRY_AND_ZERO_SERIAL)

    assert dp.name == "DP-2"
    assert dp.mode == "2560x1440+0+0"
    assert dp.serial is None


def test_detect_connected_monitors_decodes_serial_before_more_properties(
    monkeypatch,
):
    # Property lines follow the EDID block here; the serial must survive them.
    edp, _ = _detect(monkeypatch, LAPTOP_AND_HDMI)

    assert edp.serial == "67305985"


def test_detect_connected_monitors_port_header_flushes_pending_edid(monkeypatch):
    first, second = _detect(monkeypatch, EDID_BEFORE_HEADER)

    assert first.serial == "67305985"
    assert second.serial is None


def test_detect_connected_monitors_marks_internal_by_prefix(monkeypatch):
    edp, hdmi = _detect(monkeypatch, LAPTOP_AND_HDMI)

    assert edp.is_internal is True
    assert hdmi.is_internal is False


def test_detect_connected_monitors_marks_internal_by_override(monkeypatch):
    monkeypatch.setenv("QTILE_INTERNAL_OUTPUTS", "DP-2")

    _, dp = _detect(monkeypatch, NO_GEOMETRY_AND_ZERO_SERIAL)

    assert dp.is_internal is True


# --- priorities --------------------------------------------------------------


def test_serial_priority_unset_is_empty():
    assert _serial_priority() == []


def test_serial_priority_parses_and_strips(monkeypatch):
    monkeypatch.setenv("QTILE_SCREEN_SERIAL_ORDER", "AAA, BBB,,")

    assert _serial_priority() == ["AAA", "BBB"]


def test_port_priority_unset_uses_default():
    assert _port_priority() == ["DP-0", "HDMI-0", "DP-2"]


def test_port_priority_whitespace_only_uses_default(monkeypatch):
    monkeypatch.setenv("QTILE_SCREEN_PORT_ORDER", "   ")

    assert _port_priority() == ["DP-0", "HDMI-0", "DP-2"]


def test_port_priority_returns_a_fresh_list_each_call():
    first = _port_priority()
    first.append("MUTATED")

    assert _port_priority() == ["DP-0", "HDMI-0", "DP-2"]


def test_port_priority_reads_env(monkeypatch):
    monkeypatch.setenv("QTILE_SCREEN_PORT_ORDER", "DP-1,HDMI-1")

    assert _port_priority() == ["DP-1", "HDMI-1"]


# --- _monitor_sort_key -------------------------------------------------------


def test_monitor_sort_key_serial_rank_beats_port_rank():
    serial_index = {"S0": 0, "S1": 1}
    port_index = {"DP-0": 0, "DP-2": 1}
    by_port = _mon("DP-0", serial="S1")
    by_serial = _mon("DP-2", serial="S0")

    assert _monitor_sort_key(by_serial, serial_index, port_index) < _monitor_sort_key(
        by_port, serial_index, port_index
    )


def test_monitor_sort_key_unknown_serial_ranks_after_known():
    serial_index = {"S0": 0, "S1": 1}

    unknown = _monitor_sort_key(_mon("DP-0", serial="other"), serial_index, {})
    missing = _monitor_sort_key(_mon("DP-0", serial=None), serial_index, {})

    assert unknown[0] == len(serial_index)
    assert missing[0] == len(serial_index)


def test_monitor_sort_key_unknown_port_ranks_after_known():
    port_index = {"DP-0": 0, "HDMI-0": 1}

    key = _monitor_sort_key(_mon("DP-9"), {}, port_index)

    assert key[1] == len(port_index)


def test_monitor_sort_key_ties_fall_back_to_name():
    first = _monitor_sort_key(_mon("DP-7"), {}, {})
    second = _monitor_sort_key(_mon("DP-8"), {}, {})

    assert first[:2] == second[:2]
    assert first[2] == "DP-7"
    assert first < second


# --- select_layout_monitors --------------------------------------------------


def _lid(monkeypatch, state):
    monkeypatch.setattr(system, "_read_lid_state", lambda: state)


def test_select_layout_monitors_empty_input(monkeypatch):
    _lid(monkeypatch, True)

    assert select_layout_monitors([]) == []


def test_select_layout_monitors_closed_lid_drops_internal_when_external_present(
    monkeypatch,
):
    _lid(monkeypatch, True)
    monitors = [_mon("eDP-1", internal=True), _mon("HDMI-0")]

    assert _names(select_layout_monitors(monitors)) == ["HDMI-0"]


def test_select_layout_monitors_closed_lid_keeps_lone_internal(monkeypatch):
    _lid(monkeypatch, True)
    monitors = [_mon("eDP-1", internal=True)]

    assert _names(select_layout_monitors(monitors)) == ["eDP-1"]


@pytest.mark.parametrize("lid_state", [False, None])
def test_select_layout_monitors_open_or_unknown_lid_keeps_all(monkeypatch, lid_state):
    _lid(monkeypatch, lid_state)
    monitors = [_mon("eDP-1", internal=True), _mon("HDMI-0")]

    assert set(_names(select_layout_monitors(monitors))) == {"eDP-1", "HDMI-0"}


def test_select_layout_monitors_serial_order_beats_port_order(monkeypatch):
    _lid(monkeypatch, None)
    monkeypatch.setenv("QTILE_SCREEN_SERIAL_ORDER", "SER1")
    monitors = [_mon("DP-0"), _mon("DP-2", serial="SER1")]

    assert _names(select_layout_monitors(monitors)) == ["DP-2", "DP-0"]


def test_select_layout_monitors_default_port_order_then_alphabetical(monkeypatch):
    _lid(monkeypatch, None)
    monitors = [_mon(n) for n in ("DP-5", "DP-2", "HDMI-0", "DP-0", "DP-1")]

    assert _names(select_layout_monitors(monitors)) == [
        "DP-0",
        "HDMI-0",
        "DP-2",
        "DP-1",
        "DP-5",
    ]


# --- _build_dynamic_layout_command -------------------------------------------


def test_build_dynamic_layout_command_empty():
    assert _build_dynamic_layout_command([]) == []


def test_build_dynamic_layout_command_single_monitor():
    command = _build_dynamic_layout_command([_mon("DP-0")])

    assert command == [
        "xrandr",
        "--output",
        "DP-0",
        "--auto",
        "--pos",
        "0x0",
        "--primary",
    ]


def test_build_dynamic_layout_command_positions_follow_mode_widths():
    monitors = [
        _mon("DP-0", mode="1920x1080+0+0"),
        _mon("HDMI-0", mode="2560x1440+1920+0"),
        _mon("DP-2", mode=None),
    ]

    assert _build_dynamic_layout_command(monitors) == [
        "xrandr",
        "--output",
        "DP-0",
        "--auto",
        "--pos",
        "0x0",
        "--output",
        "HDMI-0",
        "--auto",
        "--pos",
        "1920x0",
        "--primary",
        "--output",
        "DP-2",
        "--auto",
        "--pos",
        "4480x0",
    ]


def test_build_dynamic_layout_command_primary_defaults_to_hdmi_0():
    monitors = [_mon("DP-0"), _mon("HDMI-0"), _mon("DP-2")]

    command = _build_dynamic_layout_command(monitors)

    assert command.count("--primary") == 1
    assert _primary_of(command) == "HDMI-0"


def test_build_dynamic_layout_command_primary_follows_env(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "DP-2")
    monitors = [_mon("DP-0"), _mon("HDMI-0"), _mon("DP-2")]

    command = _build_dynamic_layout_command(monitors)

    assert command.count("--primary") == 1
    assert _primary_of(command) == "DP-2"


@pytest.mark.parametrize("first", ["DP-3", "DP-1", "DP-0"])
def test_build_dynamic_layout_command_primary_falls_back_to_first_in_order(first):
    # No env override and neither HDMI-0 nor DP-2 present: the first monitor in
    # layout order must win. Every rotation of the same three names runs in one
    # process, so a set-ordered implementation can satisfy at most one of them.
    names = ["DP-3", "DP-1", "DP-0"]
    rotation = names[names.index(first) :] + names[: names.index(first)]

    command = _build_dynamic_layout_command([_mon(name) for name in rotation])

    assert command.count("--primary") == 1
    assert _primary_of(command) == first


def test_build_dynamic_layout_command_fourth_monitor_is_turned_off():
    monitors = [_mon("DP-0"), _mon("HDMI-0"), _mon("DP-2"), _mon("DP-1")]

    command = _build_dynamic_layout_command(monitors)

    assert command[-3:] == ["--output", "DP-1", "--off"]
    assert command.count("--off") == 1


def test_build_dynamic_layout_command_turns_off_unselected_connected_monitor():
    selected = [_mon("DP-0")]
    extra = _mon("eDP-1", internal=True)

    command = _build_dynamic_layout_command(selected, all_connected=[*selected, extra])

    assert command[-3:] == ["--output", "eDP-1", "--off"]


# --- _legacy_fallback_commands -----------------------------------------------


def test_legacy_fallback_commands_shape():
    commands = _legacy_fallback_commands()

    assert len(commands) == 3
    for command in commands:
        assert command[0] == "xrandr"
        assert command.count("--primary") == 1


def test_legacy_fallback_commands_returns_fresh_lists():
    first = _legacy_fallback_commands()
    second = _legacy_fallback_commands()

    assert first == second
    assert first is not second
    assert first[0] is not second[0]


# --- apply_best_effort_layout ------------------------------------------------


def _fake_run(returncodes, calls):
    """Fake ``subprocess.run``: pops return codes in order, then fails."""
    pending = list(returncodes)

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        code = pending.pop(0) if pending else 1
        return subprocess.CompletedProcess(argv, code, stdout="", stderr="")

    return fake_run


@pytest.fixture
def two_monitors(monkeypatch):
    monitors = [_mon("DP-0"), _mon("HDMI-0")]
    monkeypatch.setattr(system, "detect_connected_monitors", lambda: monitors)
    monkeypatch.setattr(system, "_read_lid_state", lambda: None)
    return monitors


def test_apply_best_effort_layout_dynamic_command_success(monkeypatch, two_monitors):
    calls = []
    monkeypatch.setattr(system.subprocess, "run", _fake_run([0], calls))

    ok, description = apply_best_effort_layout()

    assert len(calls) == 1
    argv, _ = calls[0]
    assert argv == _build_dynamic_layout_command(
        two_monitors, all_connected=two_monitors
    )
    assert (ok, description) == (True, " ".join(argv))


@pytest.mark.usefixtures("two_monitors")
def test_apply_best_effort_layout_without_xrandr_binary_reports_not_found(
    monkeypatch,
):
    calls = []

    def missing_binary(argv, **_kwargs):
        calls.append(argv)
        raise FileNotFoundError(2, "No such file or directory", "xrandr")

    monkeypatch.setattr(system.subprocess, "run", missing_binary)

    assert apply_best_effort_layout() == (False, "xrandr-not-found")
    # Every fallback would fail the same way, so only one attempt is made.
    assert len(calls) == 1


@pytest.mark.usefixtures("two_monitors")
def test_apply_best_effort_layout_falls_back_to_first_legacy(monkeypatch):
    calls = []
    monkeypatch.setattr(system.subprocess, "run", _fake_run([1, 0], calls))

    ok, description = apply_best_effort_layout()

    legacy = _legacy_fallback_commands()[0]
    assert len(calls) == 2
    assert calls[1][0] == legacy
    assert (ok, description) == (True, " ".join(legacy))


@pytest.mark.usefixtures("two_monitors")
def test_apply_best_effort_layout_all_commands_fail(monkeypatch):
    calls = []
    monkeypatch.setattr(system.subprocess, "run", _fake_run([], calls))

    assert apply_best_effort_layout() == (False, "all-layout-commands-failed")
    assert len(calls) == 4


def test_apply_best_effort_layout_without_monitors_tries_only_legacy(monkeypatch):
    monkeypatch.setattr(system, "detect_connected_monitors", lambda: [])
    monkeypatch.setattr(system, "_read_lid_state", lambda: None)
    calls = []
    monkeypatch.setattr(system.subprocess, "run", _fake_run([], calls))

    assert apply_best_effort_layout() == (False, "all-layout-commands-failed")
    assert [argv for argv, _ in calls] == _legacy_fallback_commands()


@pytest.mark.usefixtures("two_monitors")
def test_apply_best_effort_layout_runs_with_expected_kwargs(monkeypatch):
    calls = []
    monkeypatch.setattr(system.subprocess, "run", _fake_run([0], calls))

    apply_best_effort_layout()

    _, kwargs = calls[0]
    assert kwargs == {"capture_output": True, "text": True, "check": False}


# --- effective_monitor_count -------------------------------------------------


def test_effective_monitor_count_without_monitors(monkeypatch):
    monkeypatch.setattr(system, "detect_connected_monitors", lambda: [])

    assert effective_monitor_count() == (0, "xrandr --props")


def test_effective_monitor_count_counts_selected_monitors(monkeypatch):
    monkeypatch.setattr(
        system, "detect_connected_monitors", lambda: [_mon("DP-0"), _mon("HDMI-0")]
    )
    _lid(monkeypatch, None)

    assert effective_monitor_count() == (2, "xrandr --props + lid-aware")


def test_effective_monitor_count_closed_lid_ignores_internal(monkeypatch):
    monkeypatch.setattr(
        system,
        "detect_connected_monitors",
        lambda: [_mon("eDP-1", internal=True), _mon("HDMI-0")],
    )
    _lid(monkeypatch, True)

    assert effective_monitor_count() == (1, "xrandr --props + lid-aware")
