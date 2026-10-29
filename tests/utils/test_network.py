"""Unit tests for ``src/utils/network.py``.

The real ``ip`` binary is never spawned: ``network.subprocess.run`` is replaced
with a fake that records its argv and kwargs and returns a canned
``CompletedProcess``, or ``_run_ip_command`` itself is patched. ``/sys`` is
never read: the module's ``Path`` name is redirected into ``tmp_path`` and each
test builds the fake ``sys/class/net/<dev>/...`` tree it needs. Every test
passes identically on a CI runner with no network devices at all.
"""

import subprocess
from types import SimpleNamespace

import pytest
from src.utils import network
from src.utils.network import (
    _active_devices,
    _default_route_device,
    _device_icon,
    _is_device_active,
    _is_wireless,
    _read_sysfs,
    _run_ip_command,
    get_my_net_ip,
)

WIRELESS_ICON = "\U000f16bb "
WIRED_ICON = "\U000f0200 "


@pytest.fixture
def sysfs(monkeypatch, tmp_path):
    """Redirect ``network.Path`` so absolute paths resolve under ``tmp_path``."""
    monkeypatch.setattr(network, "Path", lambda p: tmp_path / str(p).lstrip("/"))
    return tmp_path


def _add_device(root, name, *, operstate=None, carrier=None, wireless=False):
    device = root / "sys/class/net" / name
    device.mkdir(parents=True)
    if operstate is not None:
        (device / "operstate").write_text(f"{operstate}\n", encoding="utf-8")
    if carrier is not None:
        (device / "carrier").write_text(f"{carrier}\n", encoding="utf-8")
    if wireless:
        (device / "wireless").mkdir()


def _no_ip_output(monkeypatch):
    monkeypatch.setattr(network, "_run_ip_command", lambda *_args: "")


# --- _run_ip_command ---------------------------------------------------------


def test_run_ip_command_builds_argv_and_strips_stdout(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="eth0\n", stderr="")

    monkeypatch.setattr(network.subprocess, "run", fake_run)

    assert _run_ip_command("-j", "route", "show", "default") == "eth0"
    assert calls == [
        (
            ["ip", "-j", "route", "show", "default"],
            {"capture_output": True, "text": True, "check": False},
        )
    ]


def test_run_ip_command_without_ip_binary_returns_empty(monkeypatch):
    def missing_binary(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "ip")

    monkeypatch.setattr(network.subprocess, "run", missing_binary)

    assert _run_ip_command("-j", "route", "show", "default") == ""


# --- _default_route_device ---------------------------------------------------


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("", ""),
        ("not json", ""),
        ('[{"dst":"default"}]', ""),
        ('[{"dst":"default","dev":"wlan0"}]', "wlan0"),
        ('[{"dst":"default"},{"dst":"default","dev":"eth0"}]', "eth0"),
        (
            '[{"dst":"default","dev":"eth0"},{"dst":"default","dev":"wlan0"}]',
            "eth0",
        ),
    ],
)
def test_default_route_device(monkeypatch, output, expected):
    monkeypatch.setattr(network, "_run_ip_command", lambda *_args: output)

    assert _default_route_device() == expected


def test_default_route_device_queries_ip_json(monkeypatch):
    seen = []

    def fake_ip(*args):
        seen.append(args)
        return ""

    monkeypatch.setattr(network, "_run_ip_command", fake_ip)

    _default_route_device()

    assert seen == [("-j", "route", "show", "default")]


# --- _read_sysfs -------------------------------------------------------------


@pytest.mark.usefixtures("sysfs")
def test_read_sysfs_missing_file_is_empty():
    assert _read_sysfs("/sys/class/net/eth0/operstate") == ""


def test_read_sysfs_strips_content(sysfs):
    _add_device(sysfs, "eth0", operstate="up")

    assert _read_sysfs("/sys/class/net/eth0/operstate") == "up"


def test_read_sysfs_unreadable_file_is_empty(sysfs):
    # A directory exists() but read_text() raises an OSError on it.
    (sysfs / "sys/class/net/eth0/operstate").mkdir(parents=True)

    assert _read_sysfs("/sys/class/net/eth0/operstate") == ""


# --- _is_device_active -------------------------------------------------------


def test_is_device_active_default_route_skips_sysfs(monkeypatch):
    seen = []

    def fake_ip(*args):
        seen.append(args)
        return "default via 10.0.0.1 dev eth0"

    def boom(_path):
        raise AssertionError("sysfs must not be read when a default route exists")

    monkeypatch.setattr(network, "_run_ip_command", fake_ip)
    monkeypatch.setattr(network, "_read_sysfs", boom)

    assert _is_device_active("eth0") is True
    assert seen == [("route", "show", "default", "dev", "eth0")]


def test_is_device_active_operstate_up(monkeypatch, sysfs):
    _no_ip_output(monkeypatch)
    _add_device(sysfs, "eth0", operstate="up")

    assert _is_device_active("eth0") is True


def test_is_device_active_carrier_one(monkeypatch, sysfs):
    _no_ip_output(monkeypatch)
    _add_device(sysfs, "eth0", operstate="down", carrier=1)

    assert _is_device_active("eth0") is True


def test_is_device_active_down_without_carrier(monkeypatch, sysfs):
    _no_ip_output(monkeypatch)
    _add_device(sysfs, "eth0", operstate="down", carrier=0)

    assert _is_device_active("eth0") is False


# --- _is_wireless ------------------------------------------------------------


def test_is_wireless_true_with_wireless_dir(sysfs):
    _add_device(sysfs, "wlan0", wireless=True)

    assert _is_wireless("wlan0") is True


def test_is_wireless_false_without_wireless_dir(sysfs):
    _add_device(sysfs, "eth0")

    assert _is_wireless("eth0") is False


# --- _active_devices ---------------------------------------------------------


@pytest.mark.usefixtures("sysfs")
def test_active_devices_without_net_dir_is_empty():
    assert _active_devices() == []


def test_active_devices_skips_loopback_and_inactive(monkeypatch, sysfs):
    _no_ip_output(monkeypatch)
    _add_device(sysfs, "lo", operstate="up", carrier=1)
    _add_device(sysfs, "eth0", operstate="up")
    _add_device(sysfs, "eth1", operstate="down", carrier=0)
    _add_device(sysfs, "wlan0", operstate="down", carrier=1, wireless=True)

    assert _active_devices() == ["eth0", "wlan0"]


class _FakeNetDir:
    """A ``/sys/class/net`` stand-in whose ``iterdir()`` order is fixed."""

    def __init__(self, names):
        self._names = names

    def exists(self):
        return True

    def iterdir(self):
        return iter(SimpleNamespace(name=name) for name in self._names)


@pytest.mark.parametrize(
    "listing",
    [
        ["wlan0", "eth0", "enp3s0"],
        ["eth0", "enp3s0", "wlan0"],
        ["enp3s0", "wlan0", "eth0"],
    ],
)
def test_active_devices_are_sorted_whatever_the_iterdir_order(monkeypatch, listing):
    # Every rotation of the same names must give one result; an implementation
    # that keeps iterdir() order can pass at most one of these cases.
    monkeypatch.setattr(network, "Path", lambda _p: _FakeNetDir(listing))
    monkeypatch.setattr(network, "_is_device_active", lambda _device: True)

    assert _active_devices() == ["enp3s0", "eth0", "wlan0"]


# --- _device_icon ------------------------------------------------------------


def test_device_icon_wireless(sysfs):
    _add_device(sysfs, "wlan0", wireless=True)

    assert _device_icon("wlan0") == WIRELESS_ICON


def test_device_icon_wired(sysfs):
    _add_device(sysfs, "eth0")

    assert _device_icon("eth0") == WIRED_ICON


# --- get_my_net_ip -----------------------------------------------------------


def test_get_my_net_ip_prefers_active_default_route_device(monkeypatch, sysfs):
    _add_device(sysfs, "wlan0", wireless=True)
    monkeypatch.setattr(network, "_default_route_device", lambda: "wlan0")
    monkeypatch.setattr(network, "_is_device_active", lambda _device: True)

    assert get_my_net_ip() == ("wlan0", WIRELESS_ICON)


def test_get_my_net_ip_inactive_default_device_falls_through(monkeypatch, sysfs):
    _add_device(sysfs, "wlan0", wireless=True)
    _add_device(sysfs, "eth0")
    monkeypatch.setattr(network, "_default_route_device", lambda: "wlan0")
    monkeypatch.setattr(network, "_is_device_active", lambda device: device == "eth0")
    monkeypatch.setattr(network, "_active_devices", lambda: ["eth0"])

    assert get_my_net_ip() == ("eth0", WIRED_ICON)


def test_get_my_net_ip_without_default_route_uses_active_device(monkeypatch, sysfs):
    _no_ip_output(monkeypatch)
    _add_device(sysfs, "lo", operstate="up")
    _add_device(sysfs, "eth0", operstate="up")

    assert get_my_net_ip() == ("eth0", WIRED_ICON)


def test_get_my_net_ip_without_ip_binary_falls_back_to_sysfs(monkeypatch, sysfs):
    def missing_binary(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "ip")

    monkeypatch.setattr(network.subprocess, "run", missing_binary)
    _add_device(sysfs, "wlan0", operstate="up", wireless=True)

    assert get_my_net_ip() == ("wlan0", WIRELESS_ICON)


def test_get_my_net_ip_without_any_connection(monkeypatch, sysfs):
    _no_ip_output(monkeypatch)
    _add_device(sysfs, "eth0", operstate="down", carrier=0)

    assert get_my_net_ip() == ("", " ")
