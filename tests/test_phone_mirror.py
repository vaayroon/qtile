"""Unit tests for PhoneMirrorWidget.

These tests do not require a running Qtile session. The widget is constructed
by bypassing the full Qtile widget __init__ chain (which requires a bar/qtile
object) and setting the required attributes directly.
"""

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Widget source path helpers (static checks)
# ---------------------------------------------------------------------------

_WIDGET_SOURCE = (
    Path(__file__).parent.parent / "src" / "widgets" / "phone_mirror.py"
).read_text()


# ---------------------------------------------------------------------------
# Fixture: widget instance without a live Qtile bar
# ---------------------------------------------------------------------------


@pytest.fixture()
def widget():
    """Return a PhoneMirrorWidget instance with Qtile init bypassed."""
    from src.widgets.phone_mirror import PhoneMirrorWidget

    w = object.__new__(PhoneMirrorWidget)
    # Minimal attributes the widget logic depends on
    w._scrcpy_process = None
    w._session_values = {}
    w._fallback_values = {
        "adb_path": "adb",
        "scrcpy_path": "scrcpy",
        "wireless_target": "",
        "device": "",
        "turn_screen_off": "true",
        "show_device": "false",
        "volume_step": "5",
    }
    w.format_error = "PHONE:ERR"
    w.format_ready = "PHONE:READY"
    w.format_disconnected = "PHONE:DISC"
    w.format_mirroring = "PHONE:MIRROR"
    return w


# ---------------------------------------------------------------------------
# Phase 4 static checks (R4-B, R2-B)
# ---------------------------------------------------------------------------


def test_no_tkinter_import():
    """R4-B: tkinter must not be imported anywhere in the widget source."""
    assert "import tkinter" not in _WIDGET_SOURCE
    assert "tkinter.Tk" not in _WIDGET_SOURCE


def test_no_tick_call():
    """R2-B: self.tick() must not appear anywhere in the widget source."""
    assert "self.tick()" not in _WIDGET_SOURCE


# ---------------------------------------------------------------------------
# Phase 6: settings resolution (R6-A, R6-B)
# ---------------------------------------------------------------------------


def test_resolve_value_env_priority(widget, monkeypatch):
    """R6-A: env var is used when no session override exists."""
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "10.0.0.1:5555")
    widget._session_values.pop("wireless_target", None)

    assert widget._resolve_value("wireless_target") == "10.0.0.1:5555"


def test_resolve_value_session_priority(widget, monkeypatch):
    """R6-B: session value takes priority over env var."""
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "10.0.0.1:5555")
    widget._session_values["wireless_target"] = "192.168.1.99:5555"

    assert widget._resolve_value("wireless_target") == "192.168.1.99:5555"


def test_resolve_value_fallback(widget, monkeypatch):
    """Fallback value is used when session and env are both absent."""
    monkeypatch.delenv("QTILE_PHONE_MIRROR_ADB_PATH", raising=False)
    widget._session_values.pop("adb_path", None)

    assert widget._resolve_value("adb_path") == "adb"


# ---------------------------------------------------------------------------
# Phase 2: _adb_call_async (R3-B)
# ---------------------------------------------------------------------------


async def test_adb_call_async_success(widget):
    """R3-B: rc=0 stdout is returned decoded."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"List of devices attached\n", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await widget._adb_call_async("adb", ["devices"])

    assert result == "List of devices attached\n"


async def test_adb_call_async_nonzero(widget):
    """R3-B: non-zero returncode returns None."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await widget._adb_call_async("adb", ["devices"])

    assert result is None


async def test_adb_call_async_timeout(widget):
    """R3-B: TimeoutError returns None and kills the process."""
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await widget._adb_call_async("adb", ["devices"])

    assert result is None
    mock_proc.kill.assert_called_once()
    mock_proc.wait.assert_awaited_once()


async def test_adb_call_async_oserror(widget):
    """OSError from create_subprocess_exec returns None."""
    with patch("asyncio.create_subprocess_exec", side_effect=OSError("no binary")):
        result = await widget._adb_call_async("adb", ["devices"])

    assert result is None


# ---------------------------------------------------------------------------
# Phase 2: _has_connected_device_async parsing (R6)
# ---------------------------------------------------------------------------


async def test_has_connected_device_async_parses_output_found(widget):
    """Device found in adb devices output returns True."""
    adb_output = "List of devices attached\n192.168.1.10:5555\tdevice\n"

    async def fake_adb(_adb_path, _args):
        return adb_output

    widget._adb_call_async = fake_adb  # type: ignore[method-assign]
    result = await widget._has_connected_device_async("adb", "")
    assert result is True


async def test_has_connected_device_async_parses_output_not_found(widget):
    """No connected device returns False."""
    adb_output = "List of devices attached\n"

    async def fake_adb(_adb_path, _args):
        return adb_output

    widget._adb_call_async = fake_adb  # type: ignore[method-assign]
    result = await widget._has_connected_device_async("adb", "")
    assert result is False


async def test_has_connected_device_async_none_output(widget):
    """None output from _adb_call_async returns False."""

    async def fake_adb(_adb_path, _args):
        return None

    widget._adb_call_async = fake_adb  # type: ignore[method-assign]
    result = await widget._has_connected_device_async("adb", "")
    assert result is False


async def test_has_connected_device_async_device_filter(widget):
    """When expected_device is set, only matching serial returns True."""
    adb_output = (
        "List of devices attached\n"
        "192.168.1.10:5555\tdevice\n"
        "192.168.1.20:5555\tdevice\n"
    )

    async def fake_adb(_adb_path, _args):
        return adb_output

    widget._adb_call_async = fake_adb  # type: ignore[method-assign]
    assert await widget._has_connected_device_async("adb", "192.168.1.10:5555") is True
    assert await widget._has_connected_device_async("adb", "192.168.1.99:5555") is False


# ---------------------------------------------------------------------------
# Phase 4: _prompt_with_zenity_async graceful degrade (R4-A)
# ---------------------------------------------------------------------------


async def test_prompt_with_zenity_async_absent_degrades(widget):
    """R4-A: when zenity is not installed, the prompt returns None without
    spawning a subprocess, so the event loop is never blocked."""
    initial = {
        "wireless_target": "",
        "device": "",
        "adb_path": "adb",
        "scrcpy_path": "scrcpy",
    }
    spawn = MagicMock()

    with (
        patch("shutil.which", return_value=None),
        patch("asyncio.create_subprocess_exec", spawn),
    ):
        result = await widget._prompt_with_zenity_async(initial)

    assert result is None
    spawn.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 5: finalize (R5-A, R5-B)
# ---------------------------------------------------------------------------


def test_finalize_terminates_scrcpy(widget):
    """R5-A: finalize calls terminate() on a running scrcpy process."""
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None  # process is alive
    widget._scrcpy_process = mock_proc

    with patch.object(type(widget).__mro__[1], "finalize", create=True) as mock_super:
        widget.finalize()

    mock_proc.terminate.assert_called_once()
    mock_super.assert_called_once()


def test_finalize_no_process(widget):
    """R5-B: finalize does not raise when _scrcpy_process is None."""
    widget._scrcpy_process = None

    with patch.object(type(widget).__mro__[1], "finalize", create=True):
        # Must not raise
        widget.finalize()


# ---------------------------------------------------------------------------
# Phase 3: poll() status format (R6-C)
# ---------------------------------------------------------------------------


def test_poll_status_format_connected(widget):
    """R6-C: poll() returns format_ready when a device is connected."""

    def fake_adb_call(_adb_path, args):
        if args == ["devices"]:
            return "List of devices attached\n192.168.1.10:5555\tdevice\n"
        return None

    widget._adb_call = fake_adb_call  # type: ignore[method-assign]
    widget._fallback_values["adb_path"] = "adb"
    widget._fallback_values["scrcpy_path"] = "scrcpy"

    with (
        patch("shutil.which", return_value="/usr/bin/adb"),
    ):
        result = widget.poll()

    assert result == "PHONE:READY"


def test_poll_status_format_disconnected(widget):
    """poll() returns format_disconnected when no device is connected."""

    def fake_adb_call(_adb_path, _args):
        return "List of devices attached\n"

    widget._adb_call = fake_adb_call  # type: ignore[method-assign]
    widget._fallback_values["wireless_target"] = ""

    with patch("shutil.which", return_value="/usr/bin/adb"):
        result = widget.poll()

    assert result == "PHONE:DISC"


def test_poll_status_format_error(widget):
    """poll() returns format_error when required binaries are missing."""
    with patch("shutil.which", return_value=None):
        result = widget.poll()

    assert result == "PHONE:ERR"


def test_poll_status_format_mirroring(widget):
    """poll() returns format_mirroring when scrcpy is running."""
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None  # process alive
    widget._scrcpy_process = mock_proc

    with patch("shutil.which", return_value="/usr/bin/adb"):
        result = widget.poll()

    assert result == "PHONE:MIRROR"
