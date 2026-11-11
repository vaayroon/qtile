"""Remembered device and auto-reconnect with backoff (R2.8, R2.9).

The runner, the clock and the sleep are fakes: nothing here touches adb, a phone
or the network, and no test waits for real time.
"""

import asyncio
import json
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.widgets import phone_mirror_controller as ctl
from src.widgets import phone_mirror_pairing as pairing
from src.widgets import phone_mirror_qr as qr
from src.widgets import phone_mirror_runner as runner
from src.widgets import phone_mirror_state as st
from src.widgets.phone_mirror_controller import PhoneController, State
from src.widgets.phone_mirror_state import RememberedDevice

INSTANCE = "adb-56201FDCR0077W-I7p3gg"  # real mDNS instance name
SERIAL = "56201FDCR0077W"
HOST = "192.168.1.134"
OLD_PORT = 45135
NEW_PORT = 38811  # the connect port changes over time
OLD = f"{HOST}:{OLD_PORT}"
NEW = f"{HOST}:{NEW_PORT}"
HEAD = "List of discovered mdns services\n"
NO_DEVICES = "List of devices attached\n\n"
PAIR_PORT = 35715
PAIR_OK = f"Successfully paired to {HOST}:{PAIR_PORT} [guid={INSTANCE}]"


def connect_line(port: int, instance: str = INSTANCE, host: str = HOST) -> str:
    return f"{instance}\t_adb-tls-connect._tcp\t{host}:{port}\n"


def listed(serial: str, extra: str = "") -> str:
    return f"List of devices attached\n{serial}\tdevice{extra}\n"


def remembered(**changes: str) -> RememberedDevice:
    fields = {
        "service_name": INSTANCE,
        "last_address": OLD,
        "serial": SERIAL,
        "paired_at": "2026-11-11T20:00:00+00:00",
    }
    fields.update(changes)
    return RememberedDevice(**fields)


class Fake:
    """Scripted adb: the device list, the mDNS table and the connect answers."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.devices = NO_DEVICES
        self.mdns = HEAD + connect_line(NEW_PORT)
        self.connect: list[runner.Result] = [
            runner.Result(0, f"failed to connect to {NEW}", "")
        ]
        self.on_connect: Any = None
        self.zenity: runner.Result = runner.Result(1, "", "")

    async def run(
        self,
        argv: Sequence[str],
        timeout: float = 10.0,  # noqa: ARG002
        input_text: str | None = None,  # noqa: ARG002
    ) -> runner.Result:
        argv = list(argv)
        runner.validate(argv)
        self.calls.append(argv)
        if argv[0] == "zenity":
            return self.zenity
        sub = argv[1:]
        if sub[:2] == ["mdns", "services"]:
            return runner.Result(0, self.mdns, "")
        if sub[:2] == ["mdns", "check"]:
            return runner.Result(0, "mdns daemon version [Openscreen]", "")
        if sub[0] == "devices":
            return runner.Result(0, self.devices, "")
        if sub[0] == "pair":
            return runner.Result(0, PAIR_OK, "")
        if sub[0] == "connect":
            if self.on_connect is not None:
                self.on_connect(sub[1])
            result = self.connect.pop(0) if len(self.connect) > 1 else self.connect[0]
            return result
        return runner.Result(0, "", "")

    def connects(self) -> list[str]:
        return [c[2] for c in self.calls if c[:2] == ["adb", "connect"]]


class Sleeper:
    """Replaces asyncio.sleep: records the delay, never waits for real time."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self.gate: asyncio.Event | None = None

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if self.gate is not None:
            await self.gate.wait()
            self.gate.clear()
        else:
            await asyncio.sleep(0)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ctl.ENV_KEYS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ctl, "PAIR_POLL_INTERVAL", 0.001)


@pytest.fixture()
def notes(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(return_value=1)
    monkeypatch.setattr(ctl, "send_notification", mock)
    return mock


@pytest.fixture()
def fake() -> Fake:
    return Fake()


@pytest.fixture()
def sleeper() -> Sleeper:
    return Sleeper()


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
async def controller(fake: Fake, sleeper: Sleeper, clock: Clock) -> PhoneController:
    ctrl = PhoneController(
        run=fake.run,
        spawn=MagicMock(),
        which=lambda name: f"/bin/{name}",
        clock=clock,
        sleep=sleeper,
    )
    return ctrl


def save(device: RememberedDevice) -> None:
    assert st.save(st.state_path(), device)


def stored() -> dict[str, Any]:
    return json.loads(st.state_path().read_text())  # type: ignore[no-any-return]


async def tick(controller: PhoneController, clock: Clock) -> State:
    """One widget poll: step past the refresh cache first."""
    clock.now += 10.0
    return await controller.refresh()


async def settle(controller: PhoneController) -> None:
    task = controller._reconnect_task
    if task is not None:
        await asyncio.wait_for(task, 5)


# --- pure helpers -------------------------------------------------------------------


def test_find_connect_by_instance_ignores_other_instances() -> None:
    entries = pairing.parse_mdns(
        HEAD
        + connect_line(1111, instance="adb-OTHER-xyz")
        + f"{INSTANCE}\t_adb-tls-pairing._tcp\t{HOST}:2222\n"
        + connect_line(NEW_PORT)
    )

    entry = pairing.find_connect_by_instance(entries, INSTANCE)

    assert entry is not None
    assert entry.address == NEW


def test_find_connect_by_instance_without_a_match() -> None:
    entries = pairing.parse_mdns(HEAD + connect_line(1111, instance="adb-OTHER-xyz"))
    assert pairing.find_connect_by_instance(entries, INSTANCE) is None


@pytest.mark.parametrize(
    ("rc", "text", "ok"),
    [
        (0, f"connected to {NEW}", True),
        (0, f"already connected to {NEW}", True),
        (0, f"failed to connect to {NEW}", False),  # rc 0 on adb 37
        (1, f"connected to {NEW}", False),
        (0, "", False),
        (0, "error: no route to host", False),
    ],
)
def test_connect_succeeded(rc: int, text: str, ok: bool) -> None:
    assert pairing.connect_succeeded(rc, text) is ok


# --- remembering --------------------------------------------------------------------


async def test_nothing_is_remembered_at_first(controller: PhoneController) -> None:
    assert controller.remembered is None
    assert not st.state_path().exists()


async def test_pairing_remembers_the_phone_by_its_service_identity(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    fake.connect = [runner.Result(0, f"connected to {OLD}", "")]
    fake.mdns = HEAD + connect_line(OLD_PORT)
    fake.zenity = runner.Result(0, f"{HOST}:{PAIR_PORT}|123456\n", "")
    controller._open_qr = _no_qr

    await controller.pair()

    assert controller.state is State.READY
    data = stored()
    assert data["service_name"] == INSTANCE
    assert data["serial"] == SERIAL
    assert data["last_address"] == OLD
    assert data["version"] == 1
    assert data["paired_at"]
    assert controller.remembered == RememberedDevice(
        INSTANCE, OLD, SERIAL, data["paired_at"]
    )


async def _no_qr(_payload: str, **_kw: Any) -> Any:
    raise qr.QrUnavailable("segno")


async def test_the_pairing_code_is_never_stored(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    fake.connect = [runner.Result(0, f"connected to {OLD}", "")]
    fake.mdns = HEAD + connect_line(OLD_PORT)
    fake.zenity = runner.Result(0, f"{HOST}:{PAIR_PORT}|123456\n", "")
    controller._open_qr = _no_qr

    await controller.pair()

    assert "123456" not in st.state_path().read_text()
    assert stat.S_IMODE(st.state_path().stat().st_mode) == 0o600


async def test_a_failed_pairing_remembers_nothing(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    fake.connect = [runner.Result(0, f"failed to connect to {OLD}", "")]
    fake.mdns = HEAD + connect_line(OLD_PORT)
    fake.zenity = runner.Result(0, f"{HOST}:{PAIR_PORT}|123456\n", "")
    controller._open_qr = _no_qr

    await controller.pair()

    assert controller.remembered is None
    assert not st.state_path().exists()


async def test_a_wireless_connect_remembers_the_phone(
    controller: PhoneController,
    fake: Fake,
    notes: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del notes
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", OLD)
    fake.connect = [runner.Result(0, f"connected to {OLD}", "")]
    fake.mdns = HEAD + connect_line(OLD_PORT)
    fake.devices = NO_DEVICES

    await controller.toggle()

    assert controller.remembered is not None
    assert controller.remembered.service_name == INSTANCE
    assert controller.remembered.last_address == OLD


async def test_a_wireless_connect_without_an_mdns_identity_is_not_remembered(
    controller: PhoneController,
    fake: Fake,
    notes: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del notes
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", OLD)
    fake.connect = [runner.Result(0, f"connected to {OLD}", "")]
    fake.mdns = HEAD

    await controller.toggle()

    assert controller.remembered is None


async def test_the_remembered_phone_is_loaded_from_the_file(
    fake: Fake, sleeper: Sleeper
) -> None:
    save(remembered())
    ctrl = PhoneController(run=fake.run, sleep=sleeper)

    assert ctrl.remembered == remembered()


async def test_a_corrupt_file_means_no_remembered_phone_and_no_reconnect(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    st.state_path().parent.mkdir(parents=True)
    st.state_path().write_text("{broken")

    state = await tick(controller, clock)

    assert state is State.DISCONNECTED
    assert controller.remembered is None
    assert controller._reconnect_task is None
    assert sleeper.delays == []
    assert fake.connects() == []


async def test_the_state_file_goes_under_xdg_state_home(
    controller: PhoneController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    controller._remember(INSTANCE, OLD)

    assert (tmp_path / "qtile" / "phone_mirror.json").exists()


# --- reconnect: when it starts ------------------------------------------------------


async def test_without_a_remembered_phone_nothing_is_attempted(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    await tick(controller, clock)
    await tick(controller, clock)

    assert controller._reconnect_task is None
    assert sleeper.delays == []
    assert fake.connects() == []


async def test_a_disconnected_remembered_phone_starts_one_timer(
    controller: PhoneController, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    sleeper.gate = asyncio.Event()

    await tick(controller, clock)
    first = controller._reconnect_task
    await asyncio.sleep(0)
    await tick(controller, clock)
    await tick(controller, clock)

    assert first is not None
    assert controller._reconnect_task is first  # one task at a time
    assert sleeper.delays == [8.0]
    controller.shutdown()


@pytest.mark.parametrize(
    "serial",
    [OLD, SERIAL, f"{INSTANCE}._adb-tls-connect._tcp"],
)
async def test_a_connected_remembered_phone_needs_no_reconnect(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper, serial: str
) -> None:
    save(remembered())
    fake.devices = listed(serial)

    state = await tick(controller, clock)

    assert state is State.READY
    assert controller._reconnect_task is None
    assert sleeper.delays == []


async def test_another_connected_device_does_not_hide_a_lost_remembered_one(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    fake.devices = listed("emulator-5554")
    sleeper.gate = asyncio.Event()

    await tick(controller, clock)
    await asyncio.sleep(0)

    assert controller._reconnect_task is not None
    assert sleeper.delays == [8.0]
    controller.shutdown()


async def test_no_reconnect_while_mirroring(
    controller: PhoneController, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    controller._process = MagicMock(returncode=None)

    await tick(controller, clock)

    assert controller._reconnect_task is None
    assert sleeper.delays == []


async def test_no_reconnect_when_adb_is_missing(
    fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    ctrl = PhoneController(
        run=fake.run, which=lambda _n: None, clock=clock, sleep=sleeper
    )

    assert await tick(ctrl, clock) is State.ERROR
    assert ctrl._reconnect_task is None


async def test_a_configured_wireless_target_keeps_the_old_behavior(
    controller: PhoneController,
    clock: Clock,
    sleeper: Sleeper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save(remembered())
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "10.0.0.2:5555")

    await tick(controller, clock)

    assert controller._reconnect_task is None
    assert sleeper.delays == []


# --- reconnect: backoff -------------------------------------------------------------


async def test_the_delays_are_8_16_32_64_128_300_and_then_it_stops(
    controller: PhoneController,
    fake: Fake,
    clock: Clock,
    sleeper: Sleeper,
    notes: MagicMock,
) -> None:
    save(remembered())

    await tick(controller, clock)
    await settle(controller)

    assert sleeper.delays == [8.0, 16.0, 32.0, 64.0, 128.0, 300.0]
    assert len(fake.connects()) == 6
    body = notes.call_args.args[1]
    assert "6 attempts" in body
    assert "right-click" in body.lower()
    assert controller.state is State.DISCONNECTED


async def test_after_the_last_attempt_it_waits_for_a_user_action(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    await tick(controller, clock)
    await settle(controller)
    calls = len(fake.calls)
    delays = len(sleeper.delays)

    for _ in range(5):
        await tick(controller, clock)

    assert controller._reconnect_task is None
    assert len(sleeper.delays) == delays
    assert [c for c in fake.calls[calls:] if c[1] == "connect"] == []


async def test_the_giving_up_notice_is_sent_once(
    controller: PhoneController, clock: Clock, notes: MagicMock
) -> None:
    save(remembered())
    await tick(controller, clock)
    await settle(controller)
    for _ in range(3):
        await tick(controller, clock)

    gave_up = [c for c in notes.call_args_list if "attempts" in c.args[1]]
    assert len(gave_up) == 1


async def test_every_attempt_waits_first_so_there_is_no_busy_loop(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    order: list[str] = []
    real_sleep = sleeper.__call__

    async def spy(delay: float) -> None:
        order.append("sleep")
        await real_sleep(delay)

    controller._sleep = spy
    fake.on_connect = lambda _addr: order.append("connect")

    await tick(controller, clock)
    await settle(controller)

    assert order == ["sleep", "connect"] * 6


async def test_success_on_the_third_attempt_ends_in_ready_and_stops(
    controller: PhoneController,
    fake: Fake,
    clock: Clock,
    sleeper: Sleeper,
    notes: MagicMock,
) -> None:
    save(remembered())
    fail = runner.Result(0, f"failed to connect to {NEW}", "")
    fake.connect = [fail, fail, runner.Result(0, f"connected to {NEW}", "")]

    await tick(controller, clock)
    await settle(controller)

    assert controller.state is State.READY
    assert sleeper.delays == [8.0, 16.0, 32.0]
    assert len(fake.connects()) == 3
    assert controller._reconnect_task is None
    assert any("reconnected" in c.args[1].lower() for c in notes.call_args_list)
    assert not any("attempts" in c.args[1] for c in notes.call_args_list)


async def test_the_budget_is_back_after_a_success(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    fake.connect = [runner.Result(0, f"connected to {NEW}", "")]
    await tick(controller, clock)
    await settle(controller)
    assert controller.state is State.READY

    # the phone drops again: a new episode starts from the first delay
    fake.connect = [runner.Result(0, f"failed to connect to {NEW}", "")]
    sleeper.delays.clear()
    await tick(controller, clock)
    await settle(controller)

    assert sleeper.delays == [8.0, 16.0, 32.0, 64.0, 128.0, 300.0]


async def test_a_phone_that_comes_back_resets_a_spent_budget(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    await tick(controller, clock)
    await settle(controller)
    assert controller._exhausted

    fake.devices = listed(SERIAL)  # the phone is back, over USB
    assert await tick(controller, clock) is State.READY
    assert not controller._exhausted

    fake.devices = NO_DEVICES
    sleeper.delays.clear()
    await tick(controller, clock)
    await settle(controller)
    assert sleeper.delays[0] == 8.0


# --- reconnect: the endpoint --------------------------------------------------------


async def test_the_current_port_comes_from_mdns_by_the_instance_name(
    controller: PhoneController, fake: Fake, clock: Clock
) -> None:
    save(remembered())  # last known port is the OLD one
    fake.mdns = HEAD + connect_line(NEW_PORT)

    await tick(controller, clock)
    await settle(controller)

    assert set(fake.connects()) == {NEW}


async def test_a_new_endpoint_is_stored_after_a_successful_reconnect(
    controller: PhoneController, fake: Fake, clock: Clock
) -> None:
    save(remembered())
    fake.connect = [runner.Result(0, f"connected to {NEW}", "")]

    await tick(controller, clock)
    await settle(controller)

    data = stored()
    assert data["last_address"] == NEW
    assert data["service_name"] == INSTANCE
    assert data["paired_at"] == "2026-11-11T20:00:00+00:00"  # identity kept


async def test_a_failed_reconnect_does_not_overwrite_the_stored_endpoint(
    controller: PhoneController, clock: Clock
) -> None:
    save(remembered())

    await tick(controller, clock)
    await settle(controller)

    assert stored()["last_address"] == OLD


async def test_without_an_mdns_entry_the_last_address_is_used(
    controller: PhoneController, fake: Fake, clock: Clock
) -> None:
    save(remembered())
    fake.mdns = HEAD

    await tick(controller, clock)
    await settle(controller)

    assert set(fake.connects()) == {OLD}


async def test_an_entry_of_another_phone_on_the_same_host_is_ignored(
    controller: PhoneController, fake: Fake, clock: Clock
) -> None:
    save(remembered())
    fake.mdns = HEAD + connect_line(9999, instance="adb-OTHERSERIAL-abc")

    await tick(controller, clock)
    await settle(controller)

    assert set(fake.connects()) == {OLD}


async def test_the_pairing_entry_is_never_used_to_connect(
    controller: PhoneController, fake: Fake, clock: Clock
) -> None:
    save(remembered())
    fake.mdns = HEAD + f"{INSTANCE}\t_adb-tls-pairing._tcp\t{HOST}:{PAIR_PORT}\n"

    await tick(controller, clock)
    await settle(controller)

    assert set(fake.connects()) == {OLD}


# --- reconnect: states and the lock -------------------------------------------------


async def test_each_attempt_shows_connecting_and_falls_back_to_disconnected(
    controller: PhoneController, fake: Fake, clock: Clock
) -> None:
    save(remembered())
    seen: list[State] = []
    fake.on_connect = lambda _addr: seen.append(controller.state)

    await tick(controller, clock)
    await settle(controller)

    assert seen == [State.CONNECTING] * 6
    assert controller.state is State.DISCONNECTED


async def test_the_listeners_hear_about_each_attempt(
    controller: PhoneController, clock: Clock
) -> None:
    save(remembered())
    heard: list[State] = []
    controller.attach(lambda: heard.append(controller.state))

    await tick(controller, clock)
    await settle(controller)

    assert State.CONNECTING in heard


async def test_an_attempt_is_skipped_while_another_action_holds_the_lock(
    controller: PhoneController, fake: Fake, sleeper: Sleeper
) -> None:
    save(remembered())
    await controller._lock.acquire()
    seen = {"sleeps": 0}
    real_sleep = sleeper.__call__

    async def sleep(delay: float) -> None:
        seen["sleeps"] += 1
        if seen["sleeps"] == 3:
            controller._lock.release()
        await real_sleep(delay)

    controller._sleep = sleep

    controller._schedule_reconnect()
    await settle(controller)

    # two timers fired with the lock held: no attempt was made or counted
    assert sleeper.delays == [8.0, 8.0, 8.0, 16.0, 32.0, 64.0, 128.0, 300.0]
    assert len(fake.connects()) == 6


async def test_a_state_change_during_an_attempt_is_not_overwritten(
    controller: PhoneController, fake: Fake, clock: Clock
) -> None:
    save(remembered())
    fake.connect = [runner.Result(0, f"connected to {NEW}", "")]
    fake.on_connect = lambda _addr: controller._touch()  # something else acted

    await tick(controller, clock)
    await settle(controller)

    assert controller.state is State.CONNECTING  # left alone: stale answer
    assert stored()["last_address"] == NEW  # but the endpoint is still saved


# --- user actions and shutdown ------------------------------------------------------


async def test_a_user_toggle_cancels_the_timer_and_resets_the_budget(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper, notes: Any
) -> None:
    del notes
    save(remembered())
    sleeper.gate = asyncio.Event()
    await tick(controller, clock)
    await asyncio.sleep(0)
    task = controller._reconnect_task
    assert task is not None

    fake.zenity = runner.Result(1, "", "")
    await controller.toggle()
    await asyncio.sleep(0)

    assert task.cancelled() or task.done()
    assert controller._reconnect_task is None
    assert controller._attempts == 0
    assert not controller._exhausted


async def test_a_toggle_after_giving_up_connects_to_the_remembered_phone(
    controller: PhoneController, fake: Fake, clock: Clock, notes: Any
) -> None:
    del notes
    save(remembered())
    await tick(controller, clock)
    await settle(controller)
    assert controller._exhausted
    before = len(fake.connects())
    fake.connect = [runner.Result(0, f"connected to {NEW}", "")]

    fake.on_connect = lambda _addr: setattr(fake, "devices", listed(NEW))
    controller._spawn = _spawn_ok

    await controller.toggle()

    assert len(fake.connects()) == before + 1
    assert fake.connects()[-1] == NEW
    assert not controller._exhausted
    assert controller._attempts == 0
    assert State.CONNECTING in controller.history


async def _spawn_ok(_argv: Sequence[str]) -> Any:
    proc = MagicMock(returncode=None)
    proc.stdout = None
    proc.stderr = None

    async def wait() -> int:
        await asyncio.sleep(3600)
        return 0

    proc.wait = wait
    return proc


async def test_the_right_click_reconnects_the_remembered_phone_too(
    controller: PhoneController, fake: Fake, notes: Any
) -> None:
    del notes
    save(remembered())
    fake.connect = [runner.Result(0, f"connected to {NEW}", "")]
    fake.on_connect = lambda _addr: setattr(fake, "devices", listed(NEW))

    await controller.reconnect()

    assert fake.connects() == [NEW]
    assert controller.state is State.READY


async def test_shutdown_cancels_the_timer(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    sleeper.gate = asyncio.Event()
    await tick(controller, clock)
    await asyncio.sleep(0)
    task = controller._reconnect_task
    assert task is not None

    controller.shutdown()
    await asyncio.sleep(0)

    assert task.cancelled()
    assert controller._reconnect_task is None
    assert fake.connects() == []


async def test_the_last_listener_detaching_cancels_the_timer(
    controller: PhoneController, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())
    sleeper.gate = asyncio.Event()
    listener = MagicMock()
    controller.attach(listener)
    await tick(controller, clock)
    await asyncio.sleep(0)
    task = controller._reconnect_task

    controller.detach(listener)
    await asyncio.sleep(0)

    assert task is not None
    assert task.cancelled()


async def test_a_crash_in_an_attempt_is_contained(
    controller: PhoneController, fake: Fake, clock: Clock, sleeper: Sleeper
) -> None:
    save(remembered())

    def boom(_addr: str) -> None:
        raise RuntimeError("boom")

    fake.on_connect = boom

    await tick(controller, clock)
    await settle(controller)

    assert sleeper.delays == [8.0, 16.0, 32.0, 64.0, 128.0, 300.0]
    assert controller.state is State.DISCONNECTED


# --- safety -------------------------------------------------------------------------


async def test_the_reconnect_only_runs_allowlisted_adb_calls_and_never_tcpip(
    controller: PhoneController, fake: Fake, clock: Clock
) -> None:
    save(remembered())

    await tick(controller, clock)
    await settle(controller)

    assert {c[0] for c in fake.calls} == {"adb"}
    assert {c[1] for c in fake.calls} <= {"devices", "mdns", "connect"}
    assert not any("tcpip" in c for c in fake.calls)
    assert not any("disconnect" in c for c in fake.calls)
