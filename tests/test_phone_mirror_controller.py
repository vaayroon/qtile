"""PhoneController with a fake runner and fake processes (R1.1, R1.4, R1.6)."""

import asyncio
from collections.abc import Callable, Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.widgets import phone_mirror_controller as ctl
from src.widgets import phone_mirror_runner as runner
from src.widgets.phone_mirror_controller import PhoneController, State

DEVICE_OK = "List of devices attached\n192.168.1.10:5555\tdevice\n"
DEVICE_NONE = "List of devices attached\n\n"
DEVICE_UNAUTH = "List of devices attached\nABC123\tunauthorized\n"


class FakeProcess:
    def __init__(self, stderr: Sequence[str] = (), exit_rc: int | None = None) -> None:
        self.returncode: int | None = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self._done = asyncio.Event()
        self.terminate = MagicMock(side_effect=lambda: self.finish(-15))
        self.kill = MagicMock(side_effect=lambda: self.finish(-9))
        for line in stderr:
            self.stderr.feed_data(f"{line}\n".encode())
        if exit_rc is not None:
            self.finish(exit_rc)

    def finish(self, rc: int) -> None:
        if self.returncode is not None:
            return
        self.returncode = rc
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode


class FakeRunner:
    """Records `run` calls; answers per adb subcommand."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.devices: list[str] = [DEVICE_OK]
        self.connect_text = "connected to 192.168.1.20:5555"
        self.zenity: runner.Result | Exception = runner.Result(1, "", "")
        self.spawned: list[list[str]] = []
        self.process = FakeProcess()
        self.spawn_error: Exception | None = None

    async def run(
        self,
        argv: Sequence[str],
        timeout: float = 10.0,  # noqa: ARG002
    ) -> runner.Result:
        argv = list(argv)
        self.calls.append(argv)
        runner.validate(argv)
        if argv[0] == "zenity":
            if isinstance(self.zenity, Exception):
                raise self.zenity
            return self.zenity
        if "devices" in argv:
            text = self.devices.pop(0) if len(self.devices) > 1 else self.devices[0]
            return runner.Result(0, text, "")
        if "connect" in argv:
            return runner.Result(0, self.connect_text, "")
        return runner.Result(0, "", "")

    async def spawn(self, argv: Sequence[str]) -> Any:
        argv = list(argv)
        runner.validate(argv)
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawned.append(argv)
        return self.process


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ctl.ENV_KEYS.values():
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def notes(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(return_value=1)
    monkeypatch.setattr(ctl, "send_notification", mock)
    return mock


@pytest.fixture()
async def fake() -> FakeRunner:
    return FakeRunner()


@pytest.fixture()
def clock() -> list[float]:
    return [100.0]


@pytest.fixture()
def controller(fake: FakeRunner, clock: list[float]) -> PhoneController:
    return PhoneController(
        run=fake.run,
        spawn=fake.spawn,
        which=lambda name: f"/bin/{name}",
        clock=lambda: clock[0],
    )


def _bodies(notes: MagicMock) -> list[str]:
    return [call.args[1] for call in notes.call_args_list]


# --- toggle ------------------------------------------------------------------


async def test_toggle_starts_scrcpy_once(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    await controller.toggle()

    assert len(fake.spawned) == 1
    argv = fake.spawned[0]
    assert argv[0] == "scrcpy"
    assert argv[argv.index("-s") + 1] == "192.168.1.10:5555"
    assert controller.state is State.MIRROR
    assert controller.is_mirroring()
    assert any("started" in body.lower() for body in _bodies(notes))


async def test_toggle_again_stops_the_process(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    await controller.toggle()
    watcher = controller._watcher
    await controller.toggle()
    assert watcher is not None
    await watcher

    fake.process.terminate.assert_called_once()
    assert len(fake.spawned) == 1
    assert controller.state is State.READY
    assert not controller.is_mirroring()
    assert not any("exited" in body.lower() for body in _bodies(notes))


@pytest.mark.usefixtures("notes")
async def test_busy_click_is_ignored(
    controller: PhoneController, fake: FakeRunner
) -> None:
    await controller._lock.acquire()
    try:
        await controller.toggle()
    finally:
        controller._lock.release()

    assert fake.spawned == []
    assert fake.calls == []


async def test_toggle_is_a_coroutine_scheduled_not_awaited_by_callers() -> None:
    assert asyncio.iscoroutinefunction(PhoneController.toggle)


# --- output capture ------------------------------------------------------------


async def test_spawn_pipes_stderr_not_devnull(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_exec(*_argv: str, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "proc"

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    await runner.spawn(["scrcpy", "-S"])

    assert seen["stderr"] == asyncio.subprocess.PIPE
    assert seen["stdout"] == asyncio.subprocess.PIPE


@pytest.mark.usefixtures("notes")
async def test_scrcpy_output_lines_are_logged(
    controller: PhoneController,
    fake: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(ctl, "logger", logger)
    fake.process = FakeProcess(stderr=["INFO: first", "WARN: second"], exit_rc=0)

    await controller.toggle()
    assert controller._watcher is not None
    await controller._watcher

    logged = " ".join(str(call.args) for call in logger.info.call_args_list)
    assert "INFO: first" in logged
    assert "WARN: second" in logged


async def test_non_zero_exit_notifies_the_reason(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    fake.process = FakeProcess(stderr=["ERROR: device unauthorized"], exit_rc=1)

    await controller.toggle()
    assert controller._watcher is not None
    await controller._watcher

    assert any("unauthorized" in body.lower() for body in _bodies(notes))
    assert controller.state is State.READY


async def test_clean_exit_does_not_notify_a_failure(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    fake.process = FakeProcess(exit_rc=0)

    await controller.toggle()
    assert controller._watcher is not None
    await controller._watcher

    assert not any("stopped unexpectedly" in b.lower() for b in _bodies(notes))


# --- notifications ----------------------------------------------------------------


@pytest.mark.usefixtures("fake")
async def test_notification_failure_is_logged_only(
    controller: PhoneController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(ctl, "logger", logger)
    monkeypatch.setattr(
        ctl, "send_notification", MagicMock(side_effect=FileNotFoundError("dbus"))
    )

    await controller.toggle()  # must not raise

    assert controller.is_mirroring()
    assert logger.warning.called or logger.info.called


async def test_notifications_use_a_fixed_id_per_topic(
    controller: PhoneController, notes: MagicMock
) -> None:
    controller.notify("status", "Phone", "one")
    controller.notify("status", "Phone", "two")
    controller.notify("error", "Phone", "three")

    ids = [call.kwargs["id_"] for call in notes.call_args_list]
    assert ids[0] == ids[1]
    assert ids[2] != ids[0]


# --- failures before start ----------------------------------------------------------


async def test_unauthorized_device_notifies_and_does_not_start(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    fake.devices = [DEVICE_UNAUTH]

    await controller.toggle()

    assert fake.spawned == []
    assert not any(call[0] == "zenity" for call in fake.calls)
    assert any("unauthorized" in body.lower() for body in _bodies(notes))


async def test_missing_binaries_set_error_and_notify(
    fake: FakeRunner, clock: list[float], notes: MagicMock
) -> None:
    controller = PhoneController(
        run=fake.run, spawn=fake.spawn, which=lambda _n: None, clock=lambda: clock[0]
    )

    await controller.toggle()

    assert fake.spawned == []
    assert controller.state is State.ERROR
    assert any("not found" in body.lower() for body in _bodies(notes))


async def test_spawn_file_not_found_notifies_missing_binary(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    fake.spawn_error = FileNotFoundError("scrcpy")

    await controller.toggle()

    assert not controller.is_mirroring()
    assert any("not found" in body.lower() for body in _bodies(notes))


@pytest.mark.usefixtures("notes")
async def test_wireless_target_is_connected_when_no_device(
    controller: PhoneController,
    fake: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "192.168.1.20:5555")
    fake.devices = [DEVICE_NONE, DEVICE_OK]

    await controller.toggle()

    assert ["adb", "connect", "192.168.1.20:5555"] in fake.calls
    assert len(fake.spawned) == 1


async def test_failure_without_device_opens_the_english_prompt(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    fake.devices = [DEVICE_NONE]

    await controller.toggle()

    prompts = [call for call in fake.calls if call[0] == "zenity"]
    assert len(prompts) == 1
    assert fake.spawned == []
    assert any("no device" in body.lower() for body in _bodies(notes))


# --- refresh ------------------------------------------------------------------------


async def test_refresh_is_cached_for_two_seconds(
    controller: PhoneController, fake: FakeRunner, clock: list[float]
) -> None:
    assert await controller.refresh() is State.READY
    await controller.refresh()
    assert sum("devices" in call for call in fake.calls) == 1

    clock[0] += 2.5
    await controller.refresh()
    assert sum("devices" in call for call in fake.calls) == 2


async def test_refresh_reports_disconnected_and_error(
    fake: FakeRunner, clock: list[float]
) -> None:
    fake.devices = [DEVICE_NONE]
    controller = PhoneController(
        run=fake.run, spawn=fake.spawn, which=lambda n: n, clock=lambda: clock[0]
    )
    assert await controller.refresh() is State.DISCONNECTED

    missing = PhoneController(
        run=fake.run, spawn=fake.spawn, which=lambda _n: None, clock=lambda: clock[0]
    )
    assert await missing.refresh() is State.ERROR


async def test_refresh_survives_runner_errors(
    clock: list[float], fake: FakeRunner
) -> None:
    async def boom(
        _argv: Sequence[str],
        timeout: float = 10.0,  # noqa: ARG001
    ) -> runner.Result:
        raise OSError("nope")

    controller = PhoneController(
        run=boom, spawn=fake.spawn, which=lambda n: n, clock=lambda: clock[0]
    )
    assert await controller.refresh() is State.DISCONNECTED


# --- other actions ------------------------------------------------------------------


async def test_volume_sends_step_keyevents(
    controller: PhoneController, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QTILE_PHONE_MIRROR_VOLUME_STEP", "3")
    monkeypatch.setenv("QTILE_PHONE_MIRROR_DEVICE", "SER")

    await controller.volume(up=True)

    expected = ["adb", "-s", "SER", "shell", "input", "keyevent", "24"]
    assert fake.calls == [expected] * 3

    fake.calls.clear()
    await controller.volume(up=False)
    assert fake.calls[0][-1] == "25"


async def test_screen_off_toggle_flips_the_session_value(
    controller: PhoneController,
) -> None:
    assert controller.resolve("turn_screen_off") == "true"
    controller.toggle_screen_off()
    assert controller.resolve("turn_screen_off") == "false"
    controller.toggle_screen_off()
    assert controller.resolve("turn_screen_off") == "true"


@pytest.mark.usefixtures("notes")
async def test_screen_off_setting_reaches_the_scrcpy_argv(
    controller: PhoneController, fake: FakeRunner
) -> None:
    controller.toggle_screen_off()
    await controller.toggle()
    assert "-S" not in fake.spawned[0]
    assert "--no-audio" in fake.spawned[0]


@pytest.mark.usefixtures("notes")
async def test_reconnect_disconnects_then_connects(
    controller: PhoneController,
    fake: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "192.168.1.20:5555")

    await controller.reconnect()

    assert fake.calls[0] == ["adb", "disconnect", "192.168.1.20:5555"]
    assert fake.calls[1] == ["adb", "connect", "192.168.1.20:5555"]


@pytest.mark.usefixtures("notes")
async def test_shutdown_terminates_a_running_process(
    controller: PhoneController, fake: FakeRunner
) -> None:
    await controller.toggle()
    controller.shutdown()
    fake.process.terminate.assert_called_once()


@pytest.mark.usefixtures("notes")
async def test_listeners_are_notified_and_the_last_detach_shuts_down(
    controller: PhoneController, fake: FakeRunner
) -> None:
    seen: list[int] = []
    cb: Callable[[], None] = lambda: seen.append(1)  # noqa: E731
    controller.attach(cb)
    await controller.toggle()
    assert seen
    controller.detach(cb)
    fake.process.terminate.assert_called_once()


# --- singleton and key function -------------------------------------------------------


def test_get_controller_is_a_singleton() -> None:
    assert ctl.get_controller() is ctl.get_controller()


def test_phone_toggle_schedules_a_task_and_is_synchronous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[Any] = []

    def fake_create_task(coro: Any) -> None:
        scheduled.append(coro)
        coro.close()

    monkeypatch.setattr(ctl, "create_task", fake_create_task)

    assert not asyncio.iscoroutinefunction(ctl.phone_toggle)
    ctl.phone_toggle(None)
    assert len(scheduled) == 1
