"""The single choke point for every subprocess the phone mirror code starts.

Only a small allowlist of executables may run, adb is limited to a fixed set
of subcommands, and any argv token naming a host-network or privilege tool is
rejected before a process is created. Nothing here ever uses a shell.
"""

import asyncio
import os
from collections.abc import Sequence
from dataclasses import dataclass

ALLOWED_EXECUTABLES: frozenset[str] = frozenset(
    {"adb", "scrcpy", "zenity", "kitty", "rofi"}
)

ALLOWED_ADB_SUBCOMMANDS: frozenset[str] = frozenset(
    {"devices", "connect", "disconnect", "pair", "mdns", "shell", "tcpip", "version"}
)
ALLOWED_MDNS_ACTIONS: frozenset[str] = frozenset({"services", "check"})

# Names that must never appear as an executable or as an argv token.
FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "nmcli",
        "networkmanager",
        "ufw",
        "iptables",
        "ip6tables",
        "nft",
        "nftables",
        "ip",
        "ifconfig",
        "iwconfig",
        "iw",
        "route",
        "netplan",
        "dhclient",
        "resolvectl",
        "resolvconf",
        "systemd-resolve",
        "systemd-resolved",
        "rfkill",
        "wpa_supplicant",
        "wpa_cli",
        "systemctl",
        "service",
        "kill",
        "pkill",
        "killall",
        "sudo",
        "su",
        "doas",
        "pkexec",
        "sh",
        "bash",
        "zsh",
        "dash",
        "fish",
        "env",
        "xargs",
    }
)

_KEYEVENT_SHELL = ("input", "keyevent")


class ForbiddenCommand(Exception):
    """Raised before execution when an argv violates the allowlist."""


@dataclass(frozen=True)
class Result:
    rc: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _base(token: str) -> str:
    return token.rsplit("/", 1)[-1].lower()


def _is_forbidden_token(token: str) -> bool:
    candidates = [token, *token.split("=")]
    for candidate in candidates:
        name = _base(candidate)
        if name in FORBIDDEN_NAMES or name.startswith("avahi"):
            return True
    return False


def _validate_adb(args: Sequence[str]) -> None:
    rest = list(args)
    if len(rest) >= 2 and rest[0] == "-s":
        rest = rest[2:]
    if not rest:
        raise ForbiddenCommand("adb needs a subcommand")
    sub, tail = rest[0], rest[1:]
    if sub not in ALLOWED_ADB_SUBCOMMANDS:
        raise ForbiddenCommand(f"adb subcommand not allowed: {sub}")
    if sub == "mdns" and (len(tail) != 1 or tail[0] not in ALLOWED_MDNS_ACTIONS):
        raise ForbiddenCommand("only 'adb mdns services|check' is allowed")
    if sub == "shell" and not (
        len(tail) == 3 and tuple(tail[:2]) == _KEYEVENT_SHELL and tail[2].isdigit()
    ):
        raise ForbiddenCommand("adb shell is limited to 'input keyevent N'")


def validate(argv: Sequence[str]) -> None:
    """Raise ForbiddenCommand unless argv is safe to execute."""
    if not argv:
        raise ForbiddenCommand("empty command")
    for token in argv:
        if _is_forbidden_token(token):
            raise ForbiddenCommand(f"forbidden token in command: {token}")
    exe = _base(argv[0])
    if exe not in ALLOWED_EXECUTABLES:
        raise ForbiddenCommand(f"executable not allowed: {argv[0]}")
    if exe == "adb":
        _validate_adb(argv[1:])


async def run(
    argv: Sequence[str], timeout: float = 10.0, input_text: str | None = None
) -> Result:
    """Run an allowlisted command to completion and capture its output."""
    validate(argv)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if input_text is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    data = input_text.encode() if input_text is not None else None
    try:
        out, err = await asyncio.wait_for(proc.communicate(input=data), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return Result(rc=-1, stdout="", stderr="", timed_out=True)
    return Result(
        rc=proc.returncode if proc.returncode is not None else -1,
        stdout=out.decode(errors="replace"),
        stderr=err.decode(errors="replace"),
    )


async def spawn(argv: Sequence[str]) -> asyncio.subprocess.Process:
    """Start an allowlisted long-running command with piped output."""
    validate(argv)
    return await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )
