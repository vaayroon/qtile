"""Contract tests for ``autostart.sh``.

The script runs under dash (the strictest common ``/bin/sh``) with ``PATH``
limited to a ``fakebin`` directory of recording fakes and ``POWER_SUPPLY_DIR``
pointing at a fake sysfs, so no real applet is started. The fakes run in the
background, but ``capture_output`` only returns once every process holding the
output pipe has exited, so their logs are complete when ``run`` returns.
"""

import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AUTOSTART_SH = ROOT / "autostart.sh"
SH = shutil.which("dash") or "/bin/sh"

PROGRAMS = (
    "dbus-update-activation-environment",
    "gnome-keyring-daemon",
    "cbatticon",
    "volumeicon",
    "udiskie",
    "nm-applet",
    "blueman-applet",
)

FAKE_PROGRAM = """#!/bin/sh
printf '%s\\n' "$*" > "$FAKEBIN_LOG/${0##*/}.args"
"""


@dataclass
class Sandbox:
    fakebin: Path
    power: Path
    log: Path

    def add_supply(self, name: str, supply_type: str, newline: bool = True) -> None:
        supply = self.power / name
        supply.mkdir()
        (supply / "type").write_text(supply_type + ("\n" if newline else ""))

    def remove_program(self, name: str) -> None:
        (self.fakebin / name).unlink()

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [SH, str(AUTOSTART_SH)],
            env={
                "PATH": str(self.fakebin),
                "FAKEBIN_LOG": str(self.log),
                "POWER_SUPPLY_DIR": str(self.power),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def args(self, program: str) -> str | None:
        path = self.log / f"{program}.args"
        return path.read_text().rstrip("\n") if path.exists() else None


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    fakebin = tmp_path / "fakebin"
    power = tmp_path / "power_supply"
    log = tmp_path / "log"
    for directory in (fakebin, power, log):
        directory.mkdir()
    for program in PROGRAMS:
        path = fakebin / program
        path.write_text(FAKE_PROGRAM)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return Sandbox(fakebin, power, log)


def _cbatticon_args(battery: str) -> str:
    return f"-d -u 5 -r 3 -c poweroff -l 15 -o brightnessctl set 20% {battery}"


# --- Script text --------------------------------------------------------------


def test_shebang_is_posix_sh() -> None:
    assert AUTOSTART_SH.read_text().splitlines()[0] == "#!/bin/sh"


def test_script_is_executable() -> None:
    assert AUTOSTART_SH.stat().st_mode & stat.S_IXUSR


def test_script_parses_under_dash() -> None:
    result = subprocess.run(
        [SH, "-n", str(AUTOSTART_SH)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("machine_specific", ["zsh", "BAT1"])
def test_script_has_no_machine_specific_values(machine_specific: str) -> None:
    code = [
        line
        for line in AUTOSTART_SH.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert not [line for line in code if machine_specific in line]


# --- Behavior -----------------------------------------------------------------


def test_every_program_starts_with_its_arguments(sandbox: Sandbox) -> None:
    sandbox.add_supply("BAT0", "Battery")
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.args("dbus-update-activation-environment") == "--all"
    assert sandbox.args("gnome-keyring-daemon") == "--start --components=secrets"
    assert sandbox.args("cbatticon") == _cbatticon_args("BAT0")
    assert sandbox.args("volumeicon") == ""
    assert sandbox.args("udiskie") == "-t"
    assert sandbox.args("nm-applet") == ""
    assert sandbox.args("blueman-applet") == ""
    assert result.stdout == ""


def test_battery_is_the_first_supply_of_type_battery(sandbox: Sandbox) -> None:
    sandbox.add_supply("ACAD", "Mains")
    sandbox.add_supply("BAT1", "Battery")
    sandbox.add_supply("BAT2", "Battery")
    sandbox.add_supply("ucsi-source-psy-USBC000:001", "USB")
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.args("cbatticon") == _cbatticon_args("BAT1")


def test_battery_type_without_a_trailing_newline_is_still_read(
    sandbox: Sandbox,
) -> None:
    sandbox.add_supply("BAT0", "Battery", newline=False)
    sandbox.run()
    assert sandbox.args("cbatticon") == _cbatticon_args("BAT0")


@pytest.mark.parametrize(
    "supplies",
    [[], [("AC", "Mains")], [("AC", "Mains"), ("usb", "USB")]],
    ids=["no-supplies", "mains-only", "mains-and-usb"],
)
def test_no_battery_skips_cbatticon_and_starts_the_rest(
    sandbox: Sandbox, supplies: list[tuple[str, str]]
) -> None:
    for name, supply_type in supplies:
        sandbox.add_supply(name, supply_type)
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.args("cbatticon") is None
    assert "no battery" in result.stdout
    assert sandbox.args("nm-applet") == ""


def test_missing_power_supply_dir_skips_cbatticon(sandbox: Sandbox) -> None:
    sandbox.power.rmdir()
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.args("cbatticon") is None
    assert "no battery" in result.stdout


@pytest.mark.parametrize("missing", ["gnome-keyring-daemon", "cbatticon", "udiskie"])
def test_missing_program_is_reported_and_the_rest_still_start(
    sandbox: Sandbox, missing: str
) -> None:
    sandbox.add_supply("BAT0", "Battery")
    sandbox.remove_program(missing)
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"autostart: {missing} not found, skipping\n"
    for program in PROGRAMS:
        if program != missing:
            assert sandbox.args(program) is not None, program
