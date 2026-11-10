"""QR window: lazy segno, private PNG, allowlisted kitty (R2.2, R2.5)."""

import asyncio
import importlib
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.widgets import phone_mirror_qr as qr
from src.widgets import phone_mirror_runner as runner

PAYLOAD = "WIFI:T:ADB;S:qtile-abc;P:secretsecret1;;"


class FakeSegno:
    """Stands in for segno so the tests pass with or without it installed."""

    def __init__(self) -> None:
        self.made: list[tuple[str, dict[str, Any]]] = []

    def make(self, payload: str, **kwargs: Any) -> Any:
        self.made.append((payload, kwargs))
        outer = self

        class Code:
            def save(self, out: Any, **save_kwargs: Any) -> None:
                outer.saved = save_kwargs
                out.write(b"\x89PNG fake")

        return Code()

    saved: dict[str, Any]


class FakeKitty:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self._done = asyncio.Event()
        self.terminate = MagicMock(side_effect=lambda: self._finish(-15))
        self.kill = MagicMock(side_effect=lambda: self._finish(-9))

    def _finish(self, rc: int) -> None:
        if self.returncode is None:
            self.returncode = rc
        self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def segno(monkeypatch: pytest.MonkeyPatch) -> FakeSegno:
    fake = FakeSegno()
    monkeypatch.setitem(sys.modules, "segno", fake)
    return fake


class Spawner:
    def __init__(self) -> None:
        self.argvs: list[list[str]] = []
        self.process = FakeKitty()

    async def __call__(self, argv: Sequence[str]) -> FakeKitty:
        runner.validate(argv)  # the real allowlist, not a stub
        self.argvs.append(list(argv))
        return self.process


def _which(found: str | None = "/usr/bin/kitty") -> Any:
    return lambda _name: found


# --- R2.2: lazy, optional segno ------------------------------------------------


def test_importing_the_module_never_needs_segno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "segno", None)  # import segno -> ImportError
    monkeypatch.delitem(sys.modules, "src.widgets.phone_mirror_qr", raising=False)

    module = importlib.import_module("src.widgets.phone_mirror_qr")

    assert module.QrUnavailable is not None


@pytest.mark.usefixtures("runtime")
def test_render_without_segno_reports_it_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "segno", None)

    with pytest.raises(qr.QrUnavailable) as info:
        qr.render_png(PAYLOAD)

    assert info.value.missing == "segno"


@pytest.mark.usefixtures("segno")
def test_render_without_a_runtime_dir_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    with pytest.raises(qr.QrUnavailable) as info:
        qr.render_png(PAYLOAD)

    assert info.value.missing == "runtime"


# --- private PNG ---------------------------------------------------------------


def test_render_writes_the_png_where_the_runner_allows_it(
    runtime: Path, segno: FakeSegno
) -> None:
    path = qr.render_png(PAYLOAD)

    assert str(path) == runner.qr_image_path()
    assert path == runtime / "qtile" / "pair-qr.png"
    assert path.read_bytes() == b"\x89PNG fake"
    assert segno.made[0][0] == PAYLOAD
    assert segno.saved["kind"] == "png"


@pytest.mark.usefixtures("segno")
def test_png_is_private_to_the_user(runtime: Path) -> None:
    path = qr.render_png(PAYLOAD)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((runtime / "qtile").stat().st_mode) == 0o700


@pytest.mark.usefixtures("segno")
def test_an_old_png_with_loose_permissions_is_made_private(runtime: Path) -> None:
    target = runtime / "qtile"
    target.mkdir()
    old = target / "pair-qr.png"
    old.write_bytes(b"x" * 500)
    old.chmod(0o644)

    path = qr.render_png(PAYLOAD)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_bytes() == b"\x89PNG fake"  # truncated, not appended


def test_remove_png_deletes_it_and_tolerates_a_missing_file(
    runtime: Path, segno: FakeSegno
) -> None:
    del segno
    path = qr.render_png(PAYLOAD)

    qr.remove_png(path)
    qr.remove_png(path)

    assert not path.exists()
    assert (runtime / "qtile").is_dir()


# --- kitty window --------------------------------------------------------------


def test_kitty_argv_matches_the_allowlisted_template(runtime: Path) -> None:
    argv = qr.build_kitty_argv(runtime / "qtile" / "pair-qr.png")

    assert argv == [
        "kitty",
        "--class",
        "phone-pair-qr",
        "--title",
        "Pair phone",
        "kitty",
        "+kitten",
        "icat",
        "--hold",
        str(runtime / "qtile" / "pair-qr.png"),
    ]
    runner.validate(argv)


@pytest.mark.usefixtures("segno")
async def test_open_window_renders_then_spawns_kitty(runtime: Path) -> None:
    spawn = Spawner()

    window = await qr.open_window(PAYLOAD, spawn=spawn, which=_which())

    assert spawn.argvs == [qr.build_kitty_argv(runtime / "qtile" / "pair-qr.png")]
    assert window.is_open()
    assert window.path.exists()


@pytest.mark.usefixtures("runtime", "segno")
async def test_open_window_without_kitty_is_unavailable() -> None:
    spawn = Spawner()

    with pytest.raises(qr.QrUnavailable) as info:
        await qr.open_window(PAYLOAD, spawn=spawn, which=_which(None))

    assert info.value.missing == "kitty"
    assert spawn.argvs == []


async def test_open_window_without_segno_never_spawns(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "segno", None)
    spawn = Spawner()

    with pytest.raises(qr.QrUnavailable) as info:
        await qr.open_window(PAYLOAD, spawn=spawn, which=_which())

    assert info.value.missing == "segno"
    assert spawn.argvs == []
    assert not (runtime / "qtile" / "pair-qr.png").exists()


@pytest.mark.usefixtures("segno")
async def test_a_failed_spawn_removes_the_png(runtime: Path) -> None:
    async def broken(_argv: Sequence[str]) -> Any:
        raise FileNotFoundError("kitty")

    with pytest.raises(qr.QrUnavailable) as info:
        await qr.open_window(PAYLOAD, spawn=broken, which=_which())

    assert info.value.missing == "kitty"
    assert not (runtime / "qtile" / "pair-qr.png").exists()


@pytest.mark.usefixtures("runtime", "segno")
async def test_closing_the_window_terminates_kitty_and_deletes_the_png() -> None:
    spawn = Spawner()
    window = await qr.open_window(PAYLOAD, spawn=spawn, which=_which())

    await window.close()

    spawn.process.terminate.assert_called_once_with()
    spawn.process.kill.assert_not_called()
    assert not window.is_open()
    assert not window.path.exists()


@pytest.mark.usefixtures("runtime", "segno")
async def test_a_window_the_user_closed_is_not_open_and_leaves_no_png() -> None:
    spawn = Spawner()
    window = await qr.open_window(PAYLOAD, spawn=spawn, which=_which())

    spawn.process.returncode = 0  # the user closed it
    assert not window.is_open()
    await window.close()

    spawn.process.terminate.assert_not_called()
    assert not window.path.exists()


@pytest.mark.usefixtures("runtime", "segno")
async def test_a_stubborn_kitty_is_killed_after_the_grace_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(qr, "CLOSE_GRACE", 0.01)
    spawn = Spawner()
    spawn.process.terminate = MagicMock()  # ignores SIGTERM
    window = await qr.open_window(PAYLOAD, spawn=spawn, which=_which())

    await window.close()

    spawn.process.kill.assert_called_once_with()
    assert not window.path.exists()
