"""Host-network safety guards for the phone mirror code (R3.1, R3.2, R3.3, R3.6).

Every subprocess started by the phone mirror code must go through the
allowlisted runner. These tests fail if a guard is removed or weakened.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.widgets import phone_mirror_runner as runner

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
    import asyncio

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
        ["kitty", "--class", "phone-pair-qr", "--hold"],
    ],
)
async def test_allowlisted_calls_are_spawned(
    argv: list[str], exec_mock: AsyncMock
) -> None:
    await runner.run(argv)
    exec_mock.assert_awaited_once()


# --- allowlist shape and negative control ------------------------------------


def _assert_allowlist_is_safe(allowed: frozenset[str] | set[str]) -> None:
    leaked = {name for name in allowed if name in FORBIDDEN_EXECUTABLES}
    assert not leaked, f"forbidden executables in the allowlist: {leaked}"


def test_allowlist_is_exactly_the_expected_set() -> None:
    assert set(runner.ALLOWED_EXECUTABLES) == {"adb", "scrcpy", "zenity", "kitty"}
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


def test_no_forbidden_command_in_string_constants() -> None:
    offenders: list[str] = []
    for path in _phone_files():
        if path.name == RUNNER_FILE:  # the deny list itself lives there
            continue
        for text in _string_constants(path):
            tokens = text.split()
            if not tokens:
                continue
            first = tokens[0].rsplit("/", 1)[-1].lower()
            if first in runner.FORBIDDEN_NAMES or first.startswith("avahi"):
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


def test_subprocess_is_only_used_by_the_runner() -> None:
    offenders: list[str] = []
    for path in _phone_files():
        if path.name == RUNNER_FILE:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            else:
                continue
            if any(
                n.split(".")[0] == "subprocess" or n == "create_subprocess_exec"
                for n in names
            ):
                offenders.append(f"{path.name}:{node.lineno}")
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
