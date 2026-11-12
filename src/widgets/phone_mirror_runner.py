"""The single choke point for every subprocess the phone mirror code starts.

Only a small allowlist of executables may run, adb is limited to a fixed set
of subcommands, and any argv token naming a host-network or privilege tool is
rejected before a process is created. Nothing here ever uses a shell.
"""

import asyncio
import contextlib
import os
from collections.abc import Sequence
from dataclasses import dataclass

ALLOWED_EXECUTABLES: frozenset[str] = frozenset(
    {"adb", "scrcpy", "zenity", "rofi", "kitty"}
)

ALLOWED_ADB_SUBCOMMANDS: frozenset[str] = frozenset(
    {"devices", "connect", "disconnect", "pair", "mdns", "shell", "version"}
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

# Exactly the flags the code builds. rofi: flag -> accepted values (None = any
# single value, () = takes no value). zenity: the `--name=` prefixes of a form.
ROFI_FLAGS: dict[str, frozenset[str] | None] = {
    "-dmenu": frozenset(),
    "-i": frozenset(),
    "-p": None,
    "-format": frozenset({"i"}),
}
ZENITY_PREFIXES: tuple[str, ...] = (
    "--title=",
    "--text=",
    "--separator=",
    "--add-entry=",
)

# kitty is allowed for exactly one command: showing the pairing QR image.
#   kitty --class phone-pair-qr --title <title> kitty +kitten icat --hold <png>
KITTY_QR_CLASS = "phone-pair-qr"
KITTY_QR_TITLE = "Pair phone"
KITTY_QR_IMAGE = ("qtile", "pair-qr.png")  # relative to $XDG_RUNTIME_DIR
_KITTY_QR_HEAD = ("--class", KITTY_QR_CLASS, "--title", KITTY_QR_TITLE)
_KITTY_QR_BODY = ("kitty", "+kitten", "icat", "--hold")


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
    """True if the token, or any word or `=` part inside it, names a banned tool."""
    candidates = [token]
    for word in token.split():
        candidates += [word, *word.split("=")]
    candidates += token.split("=")
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


def _validate_rofi(args: Sequence[str]) -> None:
    seen: set[str] = set()
    index = 0
    while index < len(args):
        flag = args[index]
        if flag not in ROFI_FLAGS:
            raise ForbiddenCommand(f"rofi flag not allowed: {flag}")
        seen.add(flag)
        accepted = ROFI_FLAGS[flag]
        index += 1
        if accepted == frozenset():
            continue
        if index >= len(args):
            raise ForbiddenCommand(f"rofi flag needs a value: {flag}")
        if accepted is not None and args[index] not in accepted:
            raise ForbiddenCommand(f"rofi value not allowed for {flag}")
        index += 1
    if "-dmenu" not in seen:
        raise ForbiddenCommand("rofi is limited to -dmenu mode")


def _validate_zenity(args: Sequence[str]) -> None:
    if "--forms" not in args:
        raise ForbiddenCommand("zenity is limited to --forms")
    for arg in args:
        if arg != "--forms" and not arg.startswith(ZENITY_PREFIXES):
            raise ForbiddenCommand(f"zenity argument not allowed: {arg}")


def qr_image_path() -> str | None:
    """The only image kitty may show, or None without a runtime directory."""
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if not runtime.startswith("/"):
        return None
    return os.path.join(runtime.rstrip("/"), *KITTY_QR_IMAGE)


def _validate_kitty(args: Sequence[str]) -> None:
    expected = qr_image_path()
    if (
        expected is None
        or len(args) != len(_KITTY_QR_HEAD) + len(_KITTY_QR_BODY) + 1
        or tuple(args[:4]) != _KITTY_QR_HEAD
        or tuple(args[4:8]) != _KITTY_QR_BODY
        or args[8] != expected
    ):
        raise ForbiddenCommand("kitty is limited to showing the pairing QR image")


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
    elif exe == "rofi":
        _validate_rofi(argv[1:])
    elif exe == "zenity":
        _validate_zenity(argv[1:])
    elif exe == "kitty":
        _validate_kitty(argv[1:])


async def _kill(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    await proc.wait()


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
        await _kill(proc)
        return Result(rc=-1, stdout="", stderr="", timed_out=True)
    except BaseException:
        # Cancellation included: never leave an orphaned child behind.
        await _kill(proc)
        raise
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
