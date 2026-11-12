"""Hardware decoding setting and the one-shot software fallback.

The failure lines are the real output of scrcpy 5.0.1 when its default
`--hwdec=auto` picked the NVIDIA VA-API driver and the decoder failed mid-stream.
"""

import asyncio
from collections.abc import Callable, Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.widgets import phone_mirror_controller as ctl
from src.widgets import phone_mirror_runner as runner
from src.widgets.phone_mirror_commands import (
    MirrorOptions,
    build_scrcpy_argv,
    normalize_hwdec,
)
from src.widgets.phone_mirror_controller import PhoneController, State

from tests.test_phone_mirror_controller import FakeProcess, FakeRunner

HW_FAILURE = [
    "ERROR: [FFmpeg] Failed to end picture decode issue: 23 (internal decoding error).",
    "ERROR: [FFmpeg] hardware accelerator failed to decode picture",
    "ERROR: Decoder 'video': could not send video packet: Input/output error",
    "ERROR: Decoding (video) failed",
]
NOTICE = "Hardware video decoding failed; using software decoding"


def _flag(argv: Sequence[str], name: str) -> str | None:
    for item in argv:
        if item.startswith(f"{name}="):
            return item.split("=", 1)[1]
    return None


# --- the argv ------------------------------------------------------------------------


def test_the_default_is_hwdec_auto() -> None:
    assert _flag(build_scrcpy_argv("scrcpy", MirrorOptions()), "--hwdec") == "auto"


@pytest.mark.parametrize("mode", ["auto", "disabled", "vaapi"])
def test_each_mode_is_passed_to_scrcpy(mode: str) -> None:
    argv = build_scrcpy_argv("scrcpy", MirrorOptions(hwdec=mode))
    assert _flag(argv, "--hwdec") == mode
    runner.validate(argv)  # still allowed by the runner


@pytest.mark.parametrize(
    ("raw", "mode"),
    [
        ("auto", "auto"),
        (" DISABLED ", "disabled"),
        ("VaApi", "vaapi"),
        ("", "auto"),
        ("nvdec", "auto"),
        ("d3d11va", "auto"),  # a real scrcpy mode, but not offered here
        ("disabled --foo", "auto"),
    ],
)
def test_normalize_hwdec(raw: str, mode: str) -> None:
    assert normalize_hwdec(raw) == mode


# --- the controller ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ctl.ENV_KEYS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ctl, "STOP_GRACE", 0.05)


@pytest.fixture()
def notes(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(return_value=1)
    monkeypatch.setattr(ctl, "send_notification", mock)
    return mock


@pytest.fixture()
async def fake() -> FakeRunner:
    return FakeRunner()


@pytest.fixture()
def controller(fake: FakeRunner) -> PhoneController:
    return PhoneController(
        run=fake.run, spawn=fake.spawn, which=lambda name: f"/bin/{name}"
    )


def sequence(
    controller: PhoneController, processes: list[FakeProcess]
) -> list[list[str]]:
    """Each spawn hands out the next process; returns the argv list it records."""
    argvs: list[list[str]] = []

    async def spawn(argv: Sequence[str]) -> Any:
        runner.validate(argv)
        argvs.append(list(argv))
        return processes.pop(0)

    controller._spawn = spawn
    return argvs


async def until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait for a condition instead of a fixed time: fast when it holds, bounded."""

    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout)


async def drained(process: FakeProcess) -> None:
    """Every line the process printed has been read and handled."""
    await until(lambda: not process.stderr._buffer)
    for _ in range(10):  # let anything a line triggered get scheduled
        await asyncio.sleep(0)


async def settled(controller: PhoneController) -> None:
    task = controller._hwdec_task
    if task is not None:
        await asyncio.wait_for(task, 5)


def _bodies(notes: MagicMock) -> list[str]:
    return [call.args[1] for call in notes.call_args_list]


async def test_scrcpy_gets_hwdec_auto_by_default(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    del notes
    await controller.toggle()

    assert _flag(fake.spawned[0], "--hwdec") == "auto"


async def test_the_setting_comes_from_the_environment(
    controller: PhoneController,
    fake: FakeRunner,
    notes: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del notes
    monkeypatch.setenv("QTILE_PHONE_MIRROR_HWDEC", "vaapi")

    await controller.toggle()

    assert _flag(fake.spawned[0], "--hwdec") == "vaapi"


async def test_an_invalid_value_becomes_auto_with_a_log_line(
    controller: PhoneController,
    fake: FakeRunner,
    notes: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    del notes
    monkeypatch.setenv("QTILE_PHONE_MIRROR_HWDEC", "nvdec")

    with caplog.at_level("INFO"):
        await controller.toggle()

    assert _flag(fake.spawned[0], "--hwdec") == "auto"
    assert "hwdec" in caplog.text
    assert "'nvdec'" in caplog.text


async def test_the_start_line_records_the_decoding_mode(
    controller: PhoneController,
    fake: FakeRunner,
    notes: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    del notes, fake
    with caplog.at_level("INFO"):
        await controller.toggle()

    assert "hwdec=auto" in caplog.text


# --- the fallback --------------------------------------------------------------------


async def test_a_hardware_decoding_failure_restarts_once_in_software(
    controller: PhoneController,
    notes: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = FakeProcess(stderr=HW_FAILURE)
    second = FakeProcess()
    argvs = sequence(controller, [first, second])

    with caplog.at_level("INFO"):
        await controller.toggle()
        await until(lambda: controller._hwdec_task is not None)
        await settled(controller)

    assert len(argvs) == 2
    assert _flag(argvs[0], "--hwdec") == "auto"
    assert _flag(argvs[1], "--hwdec") == "disabled"
    assert argvs[1][argvs[1].index("-s") + 1] == argvs[0][argvs[0].index("-s") + 1]
    first.terminate.assert_called_once()
    assert controller.is_mirroring()
    assert controller.state is State.MIRROR
    assert _bodies(notes).count(NOTICE) == 1
    assert "software decoding" in caplog.text
    assert not any("stopped unexpectedly" in b for b in _bodies(notes))


async def test_a_scrcpy_that_ignores_sigterm_is_killed_before_the_restart(
    controller: PhoneController, notes: MagicMock
) -> None:
    first = FakeProcess(stderr=HW_FAILURE, stubborn=True)  # as seen on real hardware
    second = FakeProcess()
    argvs = sequence(controller, [first, second])

    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await settled(controller)

    first.kill.assert_called_once()
    assert len(argvs) == 2
    assert _flag(argvs[1], "--hwdec") == "disabled"
    assert _bodies(notes).count(NOTICE) == 1


async def test_a_failure_that_also_ends_scrcpy_by_itself_still_restarts(
    controller: PhoneController, notes: MagicMock
) -> None:
    first = FakeProcess(stderr=HW_FAILURE, exit_rc=1)
    second = FakeProcess()
    argvs = sequence(controller, [first, second])

    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await settled(controller)

    assert len(argvs) == 2
    assert _flag(argvs[1], "--hwdec") == "disabled"
    assert _bodies(notes).count(NOTICE) == 1
    assert not any("stopped unexpectedly" in b for b in _bodies(notes))


async def test_the_accelerator_line_alone_triggers_the_fallback(
    controller: PhoneController, notes: MagicMock
) -> None:
    del notes
    line = "ERROR: [FFmpeg] hardware accelerator failed to decode picture"
    argvs = sequence(controller, [FakeProcess(stderr=[line]), FakeProcess()])

    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await settled(controller)

    assert [_flag(a, "--hwdec") for a in argvs] == ["auto", "disabled"]


@pytest.mark.parametrize(
    "lines",
    [
        ["ERROR: Decoding (video) failed"],
        [  # a corrupt packet on a flaky Wi-Fi link, no hardware involved
            "ERROR: [FFmpeg] Invalid data found when processing input",
            "ERROR: Decoder 'video': could not send video packet: Invalid data",
            "ERROR: Decoding (video) failed",
        ],
    ],
)
async def test_a_generic_decoding_failure_does_not_trigger_the_fallback(
    controller: PhoneController, notes: MagicMock, lines: list[str]
) -> None:
    first = FakeProcess(stderr=lines)
    argvs = sequence(controller, [first, FakeProcess()])

    await controller.toggle()
    await drained(first)

    assert len(argvs) == 1
    assert controller._hwdec_task is None
    assert controller._hwdec_override == ""
    assert NOTICE not in _bodies(notes)
    assert controller.is_mirroring()


async def test_it_never_loops_even_when_software_decoding_also_fails(
    controller: PhoneController, notes: MagicMock
) -> None:
    del notes
    second = FakeProcess(stderr=HW_FAILURE)
    argvs = sequence(controller, [FakeProcess(stderr=HW_FAILURE), second])

    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    task = controller._hwdec_task
    await settled(controller)
    await drained(second)

    assert len(argvs) == 2
    assert controller._hwdec_task is task


async def test_the_software_choice_lasts_for_the_session_and_is_not_repeated(
    controller: PhoneController, notes: MagicMock
) -> None:
    argvs = sequence(
        controller, [FakeProcess(stderr=HW_FAILURE), FakeProcess(), FakeProcess()]
    )
    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await settled(controller)
    await controller.toggle()  # stop
    await until(lambda: controller._stopping is None and not controller.is_mirroring())

    await controller.toggle()  # start again, later in the same session

    assert [_flag(a, "--hwdec") for a in argvs] == ["auto", "disabled", "disabled"]
    assert _bodies(notes).count(NOTICE) == 1


async def test_a_user_who_already_chose_disabled_gets_no_fallback(
    controller: PhoneController,
    notes: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QTILE_PHONE_MIRROR_HWDEC", "disabled")
    first = FakeProcess(stderr=HW_FAILURE, exit_rc=1)
    argvs = sequence(controller, [first])

    await controller.toggle()
    await until(lambda: controller._watcher.done())

    assert len(argvs) == 1
    assert controller._hwdec_task is None
    assert NOTICE not in _bodies(notes)


async def test_other_scrcpy_errors_do_not_trigger_the_fallback(
    controller: PhoneController, notes: MagicMock
) -> None:
    argvs = sequence(
        controller,
        [FakeProcess(stderr=["ERROR: Could not open video stream"], exit_rc=1)],
    )

    await controller.toggle()
    await until(lambda: controller._watcher.done())

    assert len(argvs) == 1
    assert NOTICE not in _bodies(notes)


async def test_a_manual_stop_before_the_failure_is_read_does_not_restart(
    controller: PhoneController, notes: MagicMock
) -> None:
    process = FakeProcess()
    argvs = sequence(controller, [process, FakeProcess()])
    await controller.toggle()
    for line in HW_FAILURE:
        process.stderr.feed_data(f"{line}\n".encode())

    await controller.toggle()  # the user stops it before the lines are read
    await until(lambda: controller._watcher.done())

    assert len(argvs) == 1
    assert NOTICE not in _bodies(notes)
    assert controller.state is State.READY


async def test_the_fallback_only_touches_the_same_serial(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    del notes
    argvs = sequence(controller, [FakeProcess(stderr=HW_FAILURE), FakeProcess()])

    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await settled(controller)

    assert {a[a.index("-s") + 1] for a in argvs} == {"192.168.1.10:5555"}
    assert {c[0] for c in fake.calls} <= {"adb"}  # no other tool was involved


# --- shutdown, and scrcpy that already ended ------------------------------------------


async def test_shutdown_while_the_restart_waits_does_not_start_a_second_scrcpy(
    controller: PhoneController,
    notes: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ctl, "STOP_GRACE", 0.2)
    first = FakeProcess(stderr=HW_FAILURE, stubborn=True)  # ignores SIGTERM
    second = FakeProcess()
    argvs = sequence(controller, [first, second])
    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await until(lambda: controller._stopping is first)  # the restart is in _settled()
    task = controller._hwdec_task

    controller.shutdown()
    await until(lambda: first.returncode is not None and controller._stopping is None)
    for _ in range(10):
        await asyncio.sleep(0)

    assert task is not None
    assert task.done()
    assert len(argvs) == 1
    assert not controller.is_mirroring()
    assert NOTICE not in _bodies(notes)


async def test_a_closed_controller_does_not_restart_even_if_the_task_is_not_cancelled(
    controller: PhoneController, notes: MagicMock
) -> None:
    first = FakeProcess(stderr=HW_FAILURE)
    argvs = sequence(controller, [first, FakeProcess()])
    await controller.toggle()
    await drained(first)
    await settled(controller)
    assert len(argvs) == 2  # the normal restart did happen

    controller.shutdown()
    await controller._hwdec_restart(first, "192.168.1.10:5555")  # a late call

    assert len(argvs) == 2
    assert NOTICE in _bodies(notes)
    assert not controller.is_mirroring()


async def test_attaching_again_after_a_shutdown_reopens_the_controller(
    controller: PhoneController,
) -> None:
    controller.shutdown()
    assert controller._closed

    controller.attach(lambda: None)

    assert not controller._closed


async def test_a_phone_that_dropped_after_the_accelerator_line_is_not_restarted(
    controller: PhoneController, notes: MagicMock
) -> None:
    # only the accelerator line, then scrcpy ends by itself (the phone went away)
    line = "ERROR: [FFmpeg] hardware accelerator failed to decode picture"
    first = FakeProcess(stderr=[line], exit_rc=1)
    argvs = sequence(controller, [first, FakeProcess()])

    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await settled(controller)
    await until(lambda: controller._watcher.done())

    assert len(argvs) == 1
    assert not controller.is_mirroring()
    assert NOTICE not in _bodies(notes)
    assert any("stopped unexpectedly" in b for b in _bodies(notes))


async def test_a_window_closed_by_the_user_after_the_accelerator_line_is_not_restarted(
    controller: PhoneController, notes: MagicMock
) -> None:
    line = "ERROR: [FFmpeg] hardware accelerator failed to decode picture"
    first = FakeProcess(stderr=[line], exit_rc=0)  # the user closed the window
    argvs = sequence(controller, [first, FakeProcess()])

    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await settled(controller)
    await until(lambda: controller._watcher.done())

    assert len(argvs) == 1
    assert not controller.is_mirroring()
    assert controller.state is State.READY
    assert NOTICE not in _bodies(notes)
    assert not any("stopped unexpectedly" in b for b in _bodies(notes))


async def test_scrcpy_that_ends_because_of_the_decoder_failure_still_restarts(
    controller: PhoneController, notes: MagicMock
) -> None:
    # the whole real sequence, then scrcpy exits on its own: the exit is the decoder's
    first = FakeProcess(stderr=HW_FAILURE, exit_rc=1)
    argvs = sequence(controller, [first, FakeProcess()])

    await controller.toggle()
    await until(lambda: controller._hwdec_task is not None)
    await settled(controller)

    assert [_flag(a, "--hwdec") for a in argvs] == ["auto", "disabled"]
    assert controller.is_mirroring()
    assert _bodies(notes).count(NOTICE) == 1
