"""Host-network safety guards for the phone mirror code (R3.1, R3.2, R3.3, R3.6).

Every subprocess started by the phone mirror code must go through the
allowlisted runner. These tests fail if a guard is removed or weakened.
"""

import ast
import asyncio
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.widgets import phone_mirror_runner as runner
from src.widgets.phone_mirror_commands import build_rofi_argv, build_zenity_argv

SRC = Path(__file__).resolve().parent.parent / "src"
RUNNER_FILE = "phone_mirror_runner.py"

FORBIDDEN_EXECUTABLES = [
    "nmcli",
    "ip",
    "ifconfig",
    "iptables",
    "nft",
    "ufw",
    "systemctl",
    "resolvectl",
    "avahi-daemon",
    "avahi-browse",
    "sh",
    "bash",
    "sudo",
    "pkexec",
]


@pytest.fixture()
def exec_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace the only process-spawning primitive and record its calls."""
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"out", b"err"))
    mock = AsyncMock(return_value=proc)
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", mock)
    return mock


# --- R3.1: allowlisted executables -----------------------------------------


@pytest.mark.parametrize("name", FORBIDDEN_EXECUTABLES)
async def test_run_rejects_forbidden_executable(
    name: str, exec_mock: AsyncMock
) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run([name, "networking", "off"])
    exec_mock.assert_not_called()


@pytest.mark.parametrize("name", FORBIDDEN_EXECUTABLES)
def test_spawn_rejects_forbidden_executable(name: str, exec_mock: AsyncMock) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        asyncio.run(runner.spawn([name, "x"]))
    exec_mock.assert_not_called()


async def test_run_spawns_allowed_command(exec_mock: AsyncMock) -> None:
    result = await runner.run(["adb", "devices"])

    exec_mock.assert_awaited_once()
    assert exec_mock.await_args.args == ("adb", "devices")
    assert result.rc == 0
    assert result.stdout == "out"
    assert result.stderr == "err"


async def test_rofi_is_allowed_and_receives_stdin(exec_mock: AsyncMock) -> None:
    proc = exec_mock.return_value
    await runner.run(["rofi", "-dmenu", "-p", "Phone"], input_text="a\nb")

    exec_mock.assert_awaited_once()
    assert exec_mock.await_args.args[0] == "rofi"
    proc.communicate.assert_awaited_once_with(input=b"a\nb")


@pytest.mark.parametrize("name", FORBIDDEN_EXECUTABLES)
async def test_rofi_does_not_open_the_door_to_forbidden_tools(
    name: str, exec_mock: AsyncMock
) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run([name, "-dmenu"], input_text="x")
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(["rofi", "-dmenu", "-p", name])
    exec_mock.assert_not_called()


async def test_basename_of_a_path_is_resolved(exec_mock: AsyncMock) -> None:
    await runner.run(["/opt/genymobile/adb", "devices"])
    exec_mock.assert_awaited_once()


async def test_forbidden_path_is_rejected(exec_mock: AsyncMock) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(["/usr/sbin/ip", "addr"])
    exec_mock.assert_not_called()


async def test_empty_argv_is_rejected(exec_mock: AsyncMock) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run([])
    exec_mock.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        ["kitty", "-e", "nmcli", "networking", "off"],
        ["kitty", "--hold", "/usr/bin/sudo", "ip", "link"],
        ["zenity", "--info", "systemctl"],
        ["scrcpy", "--tcpip=x", "iptables"],
        ["kitty", "--override=shell=bash"],
        # a forbidden tool hidden inside one whitespace-separated argument
        ["rofi", "-dmenu", "-run-command", "nmcli networking off"],
        ["adb", "connect", "10.0.0.2:5555 iptables -F"],
        ["scrcpy", "--window-title", "Phone /usr/sbin/ip link"],
        ["zenity", "--forms", "--text=ok; sudo reboot"],
    ],
)
async def test_wrapped_forbidden_tokens_are_rejected(
    argv: list[str], exec_mock: AsyncMock
) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(argv)
    exec_mock.assert_not_called()


# --- adb subcommands ---------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["adb", "install", "app.apk"],
        ["adb", "push", "a", "/sdcard/a"],
        ["adb", "reverse", "tcp:1", "tcp:2"],
        ["adb", "forward", "tcp:1", "tcp:2"],
        ["adb", "reboot"],
        ["adb", "-s", "SER", "uninstall", "x"],
        ["adb", "shell", "rm", "-rf", "/sdcard"],
        ["adb", "shell", "svc", "wifi", "disable"],
        ["adb", "shell", "input", "text", "hello"],
        ["adb", "shell", "input", "keyevent", "abc"],
        ["adb", "shell"],
        ["adb", "mdns", "enable"],
        ["adb", "mdns"],
        ["adb"],
        ["adb", "-s"],
    ],
)
async def test_non_allowlisted_adb_calls_are_rejected(
    argv: list[str], exec_mock: AsyncMock
) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(argv)
    exec_mock.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        ["adb", "devices"],
        ["adb", "version"],
        ["adb", "connect", "192.168.1.20:5555"],
        ["adb", "disconnect"],
        ["adb", "pair", "192.168.1.20:37000", "123456"],
        ["adb", "mdns", "services"],
        ["adb", "mdns", "check"],
        ["adb", "tcpip", "5555"],
        ["adb", "-s", "SER", "shell", "input", "keyevent", "24"],
        ["adb", "shell", "input", "keyevent", "25"],
        ["scrcpy", "-S", "--no-audio", "--window-title=Phone"],
        ["zenity", "--forms", "--title=Phone"],
        ["rofi", "-dmenu", "-p", "Phone"],
    ],
)
async def test_allowlisted_calls_are_spawned(
    argv: list[str], exec_mock: AsyncMock
) -> None:
    await runner.run(argv)
    exec_mock.assert_awaited_once()


# --- strict rofi / zenity templates ------------------------------------------


RUNTIME = "/run/user/1000"
QR_PNG = f"{RUNTIME}/qtile/pair-qr.png"
QR_ARGV = [
    "kitty",
    "--class",
    "phone-pair-qr",
    "--title",
    "Pair phone",
    "kitty",
    "+kitten",
    "icat",
    "--hold",
    QR_PNG,
]


@pytest.fixture()
def runtime_dir(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("XDG_RUNTIME_DIR", RUNTIME)
    return RUNTIME


@pytest.mark.usefixtures("runtime_dir")
async def test_kitty_runs_the_exact_qr_template(exec_mock: AsyncMock) -> None:
    await runner.run(QR_ARGV)

    exec_mock.assert_awaited_once()
    assert exec_mock.await_args.args == tuple(QR_ARGV)


@pytest.mark.usefixtures("runtime_dir")
async def test_kitty_by_path_is_still_the_same_template(exec_mock: AsyncMock) -> None:
    await runner.run(["/usr/bin/kitty", *QR_ARGV[1:]])

    exec_mock.assert_awaited_once()


@pytest.mark.parametrize(
    "argv",
    [
        ["kitty"],
        ["kitty", "--hold"],
        ["/usr/bin/kitty", "--class", "phone-pair-qr"],
        # anything but the exact template
        [*QR_ARGV[:-1]],  # no png
        [*QR_ARGV, "extra"],
        ["kitty", "-e", "true"],
        ["kitty", "--class", "other", *QR_ARGV[3:]],
        ["kitty", "--class", "phone-pair-qr", "--title", "Other", *QR_ARGV[5:]],
        ["kitty", "--title", "Pair phone", "--class", "phone-pair-qr", *QR_ARGV[5:]],
        [*QR_ARGV[:5], "kitty", "+kitten", "ssh", "--hold", QR_PNG],
        [*QR_ARGV[:5], "kitty", "+kitten", "icat", QR_PNG],
        [*QR_ARGV[:5], "kitty", "+kitten", "icat", "--hold", "--engine=magick", QR_PNG],
        [*QR_ARGV[:5], "kitty", "+kitten", "icat", "--hold", "-n", QR_PNG],
        [*QR_ARGV[:5], "sh", "+kitten", "icat", "--hold", QR_PNG],
        [*QR_ARGV[:5], "python3", "-c", "x", "--hold", QR_PNG],
        ["kitty", "--class", "phone-pair-qr", "--title", "Pair phone", "-o", "x=y"],
        ["kitty", "--detach", *QR_ARGV[1:]],
        ["kitty", "+kitten", "icat", "--hold", QR_PNG],
        ["kitty", "@", "launch", "true"],
        # the image must be the one file the code writes
        [*QR_ARGV[:-1], "/etc/passwd"],
        [*QR_ARGV[:-1], "/tmp/pair-qr.png"],
        [*QR_ARGV[:-1], f"{RUNTIME}/qtile/other.png"],
        [*QR_ARGV[:-1], f"{RUNTIME}/other/pair-qr.png"],
        [*QR_ARGV[:-1], f"{RUNTIME}/qtile/../pair-qr.png"],
        [*QR_ARGV[:-1], f"{RUNTIME}/qtile/sub/pair-qr.png"],
        [*QR_ARGV[:-1], "qtile/pair-qr.png"],
        [*QR_ARGV[:-1], f"{RUNTIME}-evil/qtile/pair-qr.png"],
        [*QR_ARGV[:-1], f"{RUNTIME}/qtile/pair-qr.png.sh"],
        [*QR_ARGV[:-1], "http://example.com/x.png"],
    ],
)
@pytest.mark.usefixtures("runtime_dir")
async def test_kitty_rejects_anything_but_the_qr_template(
    argv: list[str], exec_mock: AsyncMock
) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(argv)
    with pytest.raises(runner.ForbiddenCommand):
        await runner.spawn(argv)
    exec_mock.assert_not_called()


async def test_kitty_needs_a_runtime_dir(
    monkeypatch: pytest.MonkeyPatch, exec_mock: AsyncMock
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(QR_ARGV)
    exec_mock.assert_not_called()


@pytest.mark.usefixtures("runtime_dir")
async def test_kitty_cannot_wrap_a_forbidden_tool(exec_mock: AsyncMock) -> None:
    for name in FORBIDDEN_EXECUTABLES:
        with pytest.raises(runner.ForbiddenCommand):
            await runner.run([*QR_ARGV[:5], name, "+kitten", "icat", "--hold", QR_PNG])
    exec_mock.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        ["rofi", "-dmenu", "-run-command", "true"],
        ["rofi", "-modi", "drun", "-show", "drun"],
        ["rofi", "-show", "run"],
        ["rofi", "-run"],
        ["rofi", "-dmenu", "-p"],
        ["rofi", "-p", "Phone"],
        ["rofi", "-dmenu", "-format", "f"],
        ["rofi", "-dmenu", "-p", "Phone", "extra"],
        ["rofi"],
    ],
)
async def test_rofi_only_accepts_the_flags_the_code_builds(
    argv: list[str], exec_mock: AsyncMock
) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(argv)
    exec_mock.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        ["zenity", "--info", "--text=hi"],
        ["zenity", "--file-selection"],
        ["zenity", "--forms", "--list"],
        ["zenity", "--forms", "--ok-label=x"],
        ["zenity", "--forms", "--add-entry"],
        ["zenity", "--forms", "--title=x", "extra"],
        ["zenity", "--add-entry=x"],
        ["zenity"],
    ],
)
async def test_zenity_only_accepts_the_forms_the_code_builds(
    argv: list[str], exec_mock: AsyncMock
) -> None:
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(argv)
    exec_mock.assert_not_called()


def test_the_argv_the_code_builds_passes_validation() -> None:
    initial = {
        "wireless_target": "",
        "device": "",
        "adb_path": "adb",
        "scrcpy_path": "scrcpy",
    }
    runner.validate(build_zenity_argv(initial))
    runner.validate(build_rofi_argv("Phone"))


# --- run(): timeout, cancellation and spawn ------------------------------------


def _hanging_proc() -> MagicMock:
    """A child whose communicate() never returns until it is killed."""
    proc = MagicMock()
    proc.returncode = None

    async def communicate(**_kwargs: Any) -> tuple[bytes, bytes]:
        await asyncio.Event().wait()
        return b"", b""

    proc.communicate = communicate
    proc.kill = MagicMock(side_effect=lambda: setattr(proc, "returncode", -9))
    proc.wait = AsyncMock(return_value=-9)
    return proc


async def test_run_kills_and_reaps_the_child_on_timeout(
    exec_mock: AsyncMock,
) -> None:
    proc = _hanging_proc()
    exec_mock.return_value = proc

    result = await runner.run(["adb", "devices"], timeout=0.05)

    assert result.timed_out is True
    assert result.rc == -1
    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


async def test_run_kills_and_reaps_the_child_on_cancellation(
    exec_mock: AsyncMock,
) -> None:
    proc = _hanging_proc()
    exec_mock.return_value = proc

    task = asyncio.ensure_future(runner.run(["adb", "devices"], timeout=30))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


async def test_run_kills_the_child_on_an_unexpected_error(
    exec_mock: AsyncMock,
) -> None:
    proc = _hanging_proc()
    proc.communicate = AsyncMock(side_effect=RuntimeError("boom"))
    exec_mock.return_value = proc

    with pytest.raises(RuntimeError):
        await runner.run(["adb", "devices"])

    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


async def test_spawn_returns_the_process_with_a_copied_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = object()
    mock = AsyncMock(return_value=child)
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", mock)
    monkeypatch.setenv("PHONE_RUNNER_TEST", "1")

    proc = await runner.spawn(["scrcpy", "-S"])

    assert proc is child
    assert mock.await_args.args == ("scrcpy", "-S")
    env = mock.await_args.kwargs["env"]
    assert env is not os.environ
    assert env["PHONE_RUNNER_TEST"] == "1"
    assert "shell" not in mock.await_args.kwargs


# --- allowlist shape and negative control ------------------------------------


def _assert_allowlist_is_safe(allowed: frozenset[str] | set[str]) -> None:
    leaked = {name for name in allowed if name in FORBIDDEN_EXECUTABLES}
    assert not leaked, f"forbidden executables in the allowlist: {leaked}"


def test_allowlist_is_exactly_the_expected_set() -> None:
    assert set(runner.ALLOWED_EXECUTABLES) == {
        "adb",
        "scrcpy",
        "zenity",
        "rofi",
        "kitty",
    }
    _assert_allowlist_is_safe(runner.ALLOWED_EXECUTABLES)


def test_negative_control_guard_detects_a_mutated_allowlist() -> None:
    """The allowlist guard must fail when `nmcli` sneaks into the allowlist."""
    with pytest.raises(AssertionError):
        _assert_allowlist_is_safe({*runner.ALLOWED_EXECUTABLES, "nmcli"})


async def test_runner_blocks_nmcli_even_if_the_allowlist_is_mutated(
    monkeypatch: pytest.MonkeyPatch, exec_mock: AsyncMock
) -> None:
    monkeypatch.setattr(
        runner, "ALLOWED_EXECUTABLES", frozenset({*runner.ALLOWED_EXECUTABLES, "nmcli"})
    )
    with pytest.raises(runner.ForbiddenCommand):
        await runner.run(["nmcli", "networking", "off"])
    exec_mock.assert_not_called()


# --- R3.2 / R3.3: static scan of every phone_mirror*.py ----------------------


def _phone_files() -> list[Path]:
    return sorted(SRC.rglob("phone_mirror*.py"))


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    skip = _docstring_nodes(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
    ]


def test_scan_covers_the_runner_and_new_files() -> None:
    names = {p.name for p in _phone_files()}
    assert RUNNER_FILE in names
    assert "phone_mirror.py" in names


# adb error text that the failure mapper matches on; it is never executed.
_KNOWN_PROSE = {"no route to host"}


def _forbidden_words(text: str) -> list[str]:
    """Every whitespace-separated word of `text` that names a forbidden tool."""
    if text in _KNOWN_PROSE:
        return []
    found: list[str] = []
    for word in text.split():
        for part in (word, *word.split("=")):
            name = part.strip(".,;:()[]{}'\"").rsplit("/", 1)[-1].lower()
            if name in runner.FORBIDDEN_NAMES or name.startswith("avahi"):
                found.append(word)
                break
    return found


@pytest.mark.parametrize(
    "text",
    [
        "nmcli networking off",
        "echo hi && /usr/sbin/ip link",
        "do this; sudo reboot",
        "--opt=iptables",
        "Mirroring started. (systemctl restart x)",
    ],
)
def test_negative_control_word_scan_finds_hidden_tools(text: str) -> None:
    assert _forbidden_words(text)


@pytest.mark.parametrize(
    "text", ["Mirroring started.", "Phone Mirror Setup", "--window-title", ""]
)
def test_word_scan_ignores_plain_text(text: str) -> None:
    assert _forbidden_words(text) == []


def test_no_forbidden_command_in_string_constants() -> None:
    offenders: list[str] = []
    for path in _phone_files():
        if path.name == RUNNER_FILE:  # the deny list itself lives there
            continue
        for text in _string_constants(path):
            if _forbidden_words(text):
                offenders.append(f"{path.name}: {text!r}")
    assert not offenders, offenders


def test_no_network_config_paths_or_discovery_stacks() -> None:
    banned = ("resolv.conf", "5353", "zeroconf", "avahi", "NetworkManager")
    offenders: list[str] = []
    for path in _phone_files():
        if path.name == RUNNER_FILE:
            continue
        for text in _string_constants(path):
            offenders.extend(
                f"{path.name}: {text!r}" for word in banned if word in text
            )
    assert not offenders, offenders


def test_runner_never_touches_network_config() -> None:
    source = (SRC / "widgets" / RUNNER_FILE).read_text()
    for word in ("resolv.conf", "5353", "zeroconf"):
        assert word not in source


_SHELL_SPAWNERS = {"create_subprocess_shell"}
_EXEC_PRIMITIVES = {"create_subprocess_exec", "subprocess"}
_OS_BANNED_NAMES = {"system", "popen"}


def _os_banned(name: str) -> bool:
    return name in _OS_BANNED_NAMES or name.startswith(("exec", "spawn")) or name == "*"


def _process_offenders(source: str, *, is_runner: bool = False) -> list[str]:
    """Process-spawning primitives in `source`; the runner may use exec only."""
    tree = ast.parse(source)
    os_aliases = {"os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            os_aliases |= {a.asname for a in node.names if a.name == "os" and a.asname}
    found: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            found += [
                f"{line}: import {a.name}"
                for a in node.names
                if a.name.split(".")[0] == "subprocess" and not is_runner
            ]
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module == "subprocess" and not is_runner:
                found.append(f"{line}: from subprocess import")
            for alias in node.names:
                if alias.name in _SHELL_SPAWNERS:
                    found.append(f"{line}: from-import {alias.name}")
                elif alias.name in _EXEC_PRIMITIVES and not is_runner:
                    found.append(f"{line}: from-import {alias.name}")
                elif module == "os" and _os_banned(alias.name):
                    found.append(f"{line}: from os import {alias.name}")
        elif isinstance(node, ast.Attribute):
            if node.attr in _SHELL_SPAWNERS:
                found.append(f"{line}: .{node.attr}")
            elif node.attr in _EXEC_PRIMITIVES and not is_runner:
                found.append(f"{line}: .{node.attr}")
            elif (
                isinstance(node.value, ast.Name)
                and node.value.id in os_aliases
                and _os_banned(node.attr)
            ):
                found.append(f"{line}: os.{node.attr}")
    return found


@pytest.mark.parametrize(
    "source",
    [
        "from asyncio import create_subprocess_exec",
        "from asyncio import create_subprocess_exec as spawn_it",
        "from subprocess import Popen",
        "from subprocess import *",
        "import subprocess",
        "import subprocess as sp",
        "import asyncio\nasyncio.create_subprocess_exec('x')",
        "import asyncio\nasyncio.subprocess.PIPE",
        "import asyncio\nasyncio.create_subprocess_shell('x')",
        "from asyncio import create_subprocess_shell",
        "import os\nos.system('x')",
        "import os\nos.popen('x')",
        "import os\nos.execv('/bin/x', [])",
        "import os\nos.execvp('x', [])",
        "import os\nos.spawnl(0, 'x')",
        "import os as o\no.system('x')",
        "from os import system",
        "from os import execv",
        "from os import popen as p",
        "from os import *",
    ],
)
def test_negative_control_scan_finds_process_primitives(source: str) -> None:
    assert _process_offenders(source)


@pytest.mark.parametrize(
    "source",
    [
        "from asyncio import create_subprocess_shell",
        "import asyncio\nasyncio.create_subprocess_shell('x')",
        "import os\nos.system('x')",
        "from os import popen",
        "import os\nos.execv('/bin/x', [])",
    ],
)
def test_runner_gets_no_exemption_for_shells_and_os_primitives(source: str) -> None:
    assert _process_offenders(source, is_runner=True)


def test_runner_may_use_exec_and_plain_os_helpers() -> None:
    source = (
        "import asyncio, os\n"
        "asyncio.create_subprocess_exec('x', stdout=asyncio.subprocess.PIPE)\n"
        "os.environ.copy()\nos.getenv('X')\n"
    )
    assert _process_offenders(source, is_runner=True) == []
    assert _process_offenders(source)  # anywhere else it is an offender


def test_plain_helpers_are_not_flagged() -> None:
    source = "import os\nfrom asyncio import create_task\nos.getenv('X')\n"
    assert _process_offenders(source) == []


def test_process_primitives_are_banned_in_phone_code() -> None:
    offenders = [
        f"{path.name}:{hit}"
        for path in _phone_files()
        for hit in _process_offenders(
            path.read_text(), is_runner=path.name == RUNNER_FILE
        )
    ]
    assert not offenders, offenders


def test_no_shell_true_anywhere_in_phone_code() -> None:
    for path in _phone_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                value = node.value
                assert not (isinstance(value, ast.Constant) and value.value), (
                    f"{path.name}: shell=True"
                )
