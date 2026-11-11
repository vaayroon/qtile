"""Wireless pairing flow with a fake runner, QR window and clock (R2.3-R2.7, R3.x)."""

import asyncio
import logging
import re
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.widgets import phone_mirror_controller as ctl
from src.widgets import phone_mirror_qr as qr
from src.widgets import phone_mirror_runner as runner
from src.widgets.phone_mirror_controller import PhoneController, State

HOST = "192.168.1.134"
PAIR_PORT = 35715
CONNECT_PORT = 45135
DEVICE = "adb-56201FDCR0077W-I7p3gg"

PAIR_OK = f"Successfully paired to {HOST}:{PAIR_PORT} [guid=adb-56201FDCR0077W-I7p3gg]"
PAIR_WRONG = "Failed: Wrong password or invalid pairing code"
CONNECT_OK = f"connected to {HOST}:{CONNECT_PORT}"
MDNS_HEAD = "List of discovered mdns services\n"
NOTHING = MDNS_HEAD
CONNECT_LINE = f"{DEVICE}\t_adb-tls-connect._tcp\t{HOST}:{CONNECT_PORT}\n"
OTHER_PAIRING = f"{DEVICE}\t_adb-tls-pairing._tcp\t{HOST}:{PAIR_PORT}\n"
SECRET_RE = re.compile(r"P:([^;]+);;")
POLL = 0.001


def pairing_line(name: str, host: str = HOST, port: int = PAIR_PORT) -> str:
    return f"{name}\t_adb-tls-pairing._tcp\t{host}:{port}\n"


class FakeWindow:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.opened = True
        self.closes = 0

    def is_open(self) -> bool:
        return self.opened

    async def close(self) -> None:
        self.opened = False
        self.closes += 1


class Fake:
    """Scripted adb/zenity plus a clock that moves on every mdns query."""

    def __init__(self, clock: list[float]) -> None:
        self.clock = clock
        self.calls: list[list[str]] = []
        self.stdin: list[tuple[str, str | None]] = []
        self.mdns: list[str] = [NOTHING]
        self.mdns_check = "mdns daemon version [Openscreen discovery 0.0.0]"
        self.pair = runner.Result(0, PAIR_OK, "")
        self.connect = runner.Result(0, CONNECT_OK, "")
        self.zenity: runner.Result | Exception = runner.Result(1, "", "")
        self.tick = 2.0
        self.windows: list[FakeWindow] = []
        self.qr_error: Exception | None = None
        self.on_mdns: Any = None

    @property
    def name(self) -> str:
        return self._secret_part(r"S:([^;]+);")

    @property
    def password(self) -> str:
        return self._secret_part(SECRET_RE.pattern)

    def _secret_part(self, pattern: str) -> str:
        match = re.search(pattern, self.windows[0].payload)
        assert match is not None
        return match.group(1)

    async def open_qr(self, payload: str, **_kwargs: Any) -> FakeWindow:
        if self.qr_error is not None:
            raise self.qr_error
        window = FakeWindow(payload)
        self.windows.append(window)
        return window

    async def run(
        self,
        argv: Sequence[str],
        timeout: float = 10.0,  # noqa: ARG002
        input_text: str | None = None,
    ) -> runner.Result:
        argv = list(argv)
        runner.validate(argv)
        self.calls.append(argv)
        if argv[0] == "zenity":
            if isinstance(self.zenity, Exception):
                raise self.zenity
            return self.zenity
        sub = argv[1:]
        if sub == ["mdns", "check"]:
            return runner.Result(0, self.mdns_check, "")
        if sub == ["mdns", "services"]:
            self.clock[0] += self.tick
            if self.on_mdns is not None:
                self.on_mdns()
            text = self.mdns.pop(0) if len(self.mdns) > 1 else self.mdns[0]
            return runner.Result(0, text, "")
        if sub[0] == "pair":
            self.stdin.append((sub[1], input_text))
            return self.pair
        if sub[0] == "connect":
            return self.connect
        return runner.Result(0, "", "")

    def adb(self, sub: str) -> list[list[str]]:
        return [c for c in self.calls if c[0] == "adb" and c[1] == sub]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ctl.ENV_KEYS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ctl, "PAIR_POLL_INTERVAL", POLL)


@pytest.fixture()
def notes(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(return_value=1)
    monkeypatch.setattr(ctl, "send_notification", mock)
    return mock


@pytest.fixture()
def clock() -> list[float]:
    return [1000.0]


@pytest.fixture()
def fake(clock: list[float]) -> Fake:
    return Fake(clock)


@pytest.fixture()
def controller(fake: Fake, clock: list[float]) -> PhoneController:
    return PhoneController(
        run=fake.run,
        spawn=MagicMock(),
        which=lambda name: f"/bin/{name}",
        clock=lambda: clock[0],
        open_qr=fake.open_qr,
    )


def _bodies(notes: MagicMock) -> str:
    return "\n".join(call.args[1] for call in notes.call_args_list)


def phone_appears(fake: Fake, *, after: int = 3, connect: str = CONNECT_LINE) -> None:
    """From the `after`-th mDNS poll on, the phone shows up under our name."""
    polls = {"n": 0}

    def on_mdns() -> None:
        polls["n"] += 1
        if polls["n"] >= after and fake.windows:
            fake.mdns = [MDNS_HEAD + pairing_line(fake.name) + connect]

    fake.on_mdns = on_mdns


# --- R2.3 / R2.4: discover, pair, connect --------------------------------------


async def test_qr_pairing_polls_pairs_then_connects_on_the_same_host(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    phone_appears(fake)

    await controller.pair()

    names = [(c[1], c[2] if len(c) > 2 else "") for c in fake.calls]
    assert names[0] == ("mdns", "check")
    assert names.count(("mdns", "services")) >= 3
    assert fake.adb("pair") == [["adb", "pair", f"{HOST}:{PAIR_PORT}"]]
    assert fake.adb("connect") == [["adb", "connect", f"{HOST}:{CONNECT_PORT}"]]
    order = [c[1] for c in fake.calls if c[0] == "adb"]
    assert order.index("pair") < order.index("connect")
    assert controller.state is State.READY
    assert "connected" in _bodies(notes).lower()


async def test_the_password_goes_through_stdin_never_through_argv(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    phone_appears(fake)

    await controller.pair()

    assert fake.stdin == [(f"{HOST}:{PAIR_PORT}", fake.password + "\n")]
    assert all(fake.password not in " ".join(call) for call in fake.calls)


async def test_a_pairing_entry_under_another_name_is_ignored(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    calls = {"n": 0}

    def on_mdns() -> None:
        calls["n"] += 1
        if calls["n"] == 1:  # someone else's pairing dialog, same host
            fake.mdns = [MDNS_HEAD + OTHER_PAIRING + CONNECT_LINE]
        if calls["n"] == 3:
            fake.mdns = [MDNS_HEAD + pairing_line(fake.name) + CONNECT_LINE]

    fake.on_mdns = on_mdns

    await controller.pair()

    assert fake.adb("pair") == [["adb", "pair", f"{HOST}:{PAIR_PORT}"]]
    assert calls["n"] >= 3


async def test_connect_ignores_entries_of_other_hosts(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    elsewhere = "adb-OTHER-xyz\t_adb-tls-connect._tcp\t10.9.9.9:4000\n"
    phone_appears(fake, connect=elsewhere + CONNECT_LINE)

    await controller.pair()

    assert fake.adb("connect") == [["adb", "connect", f"{HOST}:{CONNECT_PORT}"]]


async def test_the_qr_window_is_closed_once_the_phone_answered(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    phone_appears(fake)

    await controller.pair()

    assert fake.windows[0].closes == 1
    assert not fake.windows[0].opened


async def test_wrong_code_stops_before_connect_and_says_so(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    phone_appears(fake)
    fake.pair = runner.Result(1, PAIR_WRONG, "")

    await controller.pair()

    assert fake.adb("connect") == []
    assert "rejected" in _bodies(notes).lower()
    assert controller.state is State.DISCONNECTED


async def test_connect_entry_not_found_tells_the_user_and_does_not_connect(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    phone_appears(fake, connect="")

    await controller.pair()

    assert fake.adb("pair")
    assert fake.adb("connect") == []
    body = _bodies(notes).lower()
    assert "paired" in body
    assert "wireless debugging" in body


async def test_connect_failure_is_reported(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    phone_appears(fake)
    fake.connect = runner.Result(0, f"failed to connect to {HOST}:{CONNECT_PORT}", "")

    await controller.pair()

    assert "unreachable" in _bodies(notes).lower()
    assert controller.state is State.DISCONNECTED


async def test_a_secret_that_expired_between_match_and_pair_is_not_used(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:

    def late() -> None:
        fake.clock[0] += 200.0  # the answer arrives after the expiry
        fake.mdns = [MDNS_HEAD + pairing_line(fake.name)]

    fake.on_mdns = late

    await controller.pair()

    assert fake.adb("pair") == []
    assert "expired" in _bodies(notes).lower()


# --- R2.5: the secret is never exposed ------------------------------------------


async def test_the_password_never_reaches_logs_notifications_or_argv(
    controller: PhoneController,
    fake: Fake,
    notes: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    phone_appears(fake)
    secret_seen: list[str] = []
    original = fake.run

    async def echoing(argv: Sequence[str], **kwargs: Any) -> runner.Result:
        result = await original(argv, **kwargs)
        if list(argv)[1:2] == ["pair"]:
            secret_seen.append(fake.password)
            # a hostile adb that echoes the code back
            return runner.Result(1, f"Failed: bad code {fake.password}", "")
        return result

    controller._run = echoing

    await controller.pair()

    secret = secret_seen[0]
    assert secret
    assert secret not in caplog.text
    assert secret not in repr(notes.call_args_list)
    assert all(secret not in " ".join(call) for call in fake.calls)


async def test_the_manual_code_is_not_logged_or_notified(
    controller: PhoneController,
    fake: Fake,
    notes: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    fake.qr_error = qr.QrUnavailable("segno")
    fake.zenity = runner.Result(0, f"{HOST}:{PAIR_PORT}|246810\n", "")

    await controller.pair()

    assert "246810" not in caplog.text
    assert "246810" not in repr(notes.call_args_list)
    assert all("246810" not in " ".join(call) for call in fake.calls)


# --- R2.6: expiry, countdown, state ---------------------------------------------


async def test_state_is_pairing_with_a_countdown_while_it_waits(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    seen: list[tuple[State, str]] = []

    def on_mdns() -> None:
        if len(seen) < 3:
            seen.append((controller.state, controller.pairing_countdown()))
        if len(seen) == 3:
            fake.mdns = [MDNS_HEAD + pairing_line(fake.name) + CONNECT_LINE]

    fake.on_mdns = on_mdns

    await controller.pair()

    assert [s for s, _ in seen] == [State.PAIRING] * 3
    # the clock moves 2 s per poll: the countdown went down 03:00 -> 02:58 -> 02:56
    assert [t for _, t in seen] == ["02:58", "02:56", "02:54"]
    assert controller.pairing_countdown() == ""


async def test_listeners_are_told_on_every_poll_so_the_countdown_moves(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    ticks: list[int] = []
    controller.attach(lambda: ticks.append(1))
    phone_appears(fake, after=5)

    await controller.pair()

    assert len(ticks) >= 3


async def test_refresh_and_toggle_leave_a_pairing_alone(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    seen: dict[str, State] = {}
    tasks: list[asyncio.Future[None]] = []

    async def poke() -> None:
        seen["refresh"] = await controller.refresh()
        await controller.toggle()

    def on_mdns() -> None:
        if not tasks:
            tasks.append(asyncio.ensure_future(poke()))
        fake.tick = 200.0  # then let the code expire

    fake.on_mdns = on_mdns

    await controller.pair()
    await tasks[0]

    assert seen["refresh"] is State.PAIRING
    assert not fake.adb("devices")  # neither the probe nor the toggle ran adb


async def test_expiry_stops_polling_explains_and_offers_the_manual_form(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    await controller.pair()

    assert fake.adb("pair") == []
    assert fake.windows[0].closes == 1
    body = _bodies(notes).lower()
    for cause in ("different network", "isolation", "multicast", "vpn", "firewall"):
        assert cause in body
    assert any(c[0] == "zenity" for c in fake.calls)
    assert controller.state is State.DISCONNECTED


async def test_polling_is_bounded_by_the_expiry(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    await controller.pair()

    polls = len([c for c in fake.calls if c[1:] == ["mdns", "services"]])
    assert 85 <= polls <= 95  # 180 s at 2 s per poll


async def test_a_retry_after_expiry_uses_a_new_secret(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    await controller.pair()
    first = fake.windows[0].payload

    await controller.pair()

    assert fake.windows[1].payload != first


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("", 180.0), ("abc", 180.0), ("240", 240.0), ("60", 120.0), ("900", 300.0)],
)
async def test_the_expiry_is_configurable_and_clamped(
    controller: PhoneController,
    fake: Fake,
    notes: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    seconds: float,
) -> None:
    del notes
    monkeypatch.setenv("QTILE_PHONE_MIRROR_PAIR_TTL", raw)
    fake.tick = 10.0

    await controller.pair()

    polls = len([c for c in fake.calls if c[1:] == ["mdns", "services"]])
    assert polls == int(seconds / fake.tick)


# --- R2.5 / cancel ---------------------------------------------------------------


async def test_pressing_the_key_again_cancels_the_pairing(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    started = asyncio.ensure_future(controller.pair_toggle())
    for _ in range(50):
        await asyncio.sleep(0)
        if fake.windows:
            break
    assert fake.windows

    await controller.pair_toggle()
    await started

    assert fake.adb("pair") == []
    assert fake.windows[0].closes == 1
    assert not any(c[0] == "zenity" for c in fake.calls)
    assert "cancel" in _bodies(notes).lower()
    assert controller.state is State.DISCONNECTED
    assert controller.pairing_countdown() == ""


async def test_closing_the_qr_window_cancels_the_pairing(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes

    def on_mdns() -> None:
        fake.windows[0].opened = False  # the user closed the window

    fake.on_mdns = on_mdns

    await controller.pair()

    assert fake.adb("pair") == []
    assert not any(c[0] == "zenity" for c in fake.calls)
    assert controller.state is State.DISCONNECTED


def test_cancel_without_a_pairing_does_nothing(controller: PhoneController) -> None:
    assert controller.cancel_pairing() is False


# --- R2.2 / R2.7: fallbacks ----------------------------------------------------


@pytest.mark.parametrize(
    ("missing", "needle"),
    [("segno", "segno"), ("kitty", "kitty"), ("runtime", "xdg_runtime_dir")],
)
async def test_without_qr_support_the_user_is_told_and_gets_the_manual_form(
    controller: PhoneController,
    fake: Fake,
    notes: MagicMock,
    missing: str,
    needle: str,
) -> None:
    fake.qr_error = qr.QrUnavailable(missing)

    await controller.pair()

    assert needle in _bodies(notes).lower()
    assert [c[0] for c in fake.calls].count("zenity") == 1
    assert fake.adb("pair") == []


async def test_manual_pairing_runs_pair_then_connect(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    fake.qr_error = qr.QrUnavailable("segno")
    fake.zenity = runner.Result(0, f"{HOST}:{PAIR_PORT}|123456\n", "")
    fake.mdns = [MDNS_HEAD + CONNECT_LINE]

    await controller.pair()

    assert fake.adb("pair") == [["adb", "pair", f"{HOST}:{PAIR_PORT}"]]
    assert fake.stdin == [(f"{HOST}:{PAIR_PORT}", "123456\n")]
    assert fake.adb("connect") == [["adb", "connect", f"{HOST}:{CONNECT_PORT}"]]
    assert controller.state is State.READY
    assert "connected" in _bodies(notes).lower()


async def test_manual_prompt_cancel_runs_nothing(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    fake.qr_error = qr.QrUnavailable("kitty")
    fake.zenity = runner.Result(1, "", "")

    await controller.pair()

    assert fake.adb("pair") == []
    assert fake.adb("connect") == []


@pytest.mark.parametrize("answer", ["", "nope|123456", f"{HOST}:{PAIR_PORT}|12"])
async def test_malformed_manual_input_is_rejected_in_english(
    controller: PhoneController, fake: Fake, notes: MagicMock, answer: str
) -> None:
    fake.qr_error = qr.QrUnavailable("kitty")
    fake.zenity = runner.Result(0, answer, "")

    await controller.pair()

    assert fake.adb("pair") == []
    assert "host:port" in _bodies(notes)
    assert "6-digit" in _bodies(notes)


async def test_zenity_missing_is_reported_without_crashing(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    fake.qr_error = qr.QrUnavailable("kitty")
    fake.zenity = FileNotFoundError("zenity")

    await controller.pair()

    assert fake.adb("pair") == []
    assert "manual" in _bodies(notes).lower()


async def test_wrong_manual_code_stops_before_connect(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    fake.qr_error = qr.QrUnavailable("segno")
    fake.zenity = runner.Result(0, f"{HOST}:{PAIR_PORT}|123456", "")
    fake.pair = runner.Result(1, PAIR_WRONG, "")

    await controller.pair()

    assert fake.adb("connect") == []
    assert "rejected" in _bodies(notes).lower()


# --- R3.4 / R3.5: discovery is read-only, failures only explain -------------------


async def test_mdns_backend_unavailable_says_so_and_offers_the_manual_form(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    fake.mdns_check = "ERROR: mdns daemon unavailable"

    await controller.pair()

    assert "mdns" in _bodies(notes).lower()
    assert fake.windows == []
    assert [c[0] for c in fake.calls].count("zenity") == 1
    assert all(c[0] in ("adb", "zenity") for c in fake.calls)


async def test_missing_adb_stops_before_anything_else(
    fake: Fake, clock: list[float], notes: MagicMock
) -> None:
    controller = PhoneController(
        run=fake.run,
        spawn=MagicMock(),
        which=lambda _name: None,
        clock=lambda: clock[0],
        open_qr=fake.open_qr,
    )

    await controller.pair()

    assert fake.calls == []
    assert fake.windows == []
    assert "adb" in _bodies(notes).lower()
    assert controller.state is State.ERROR


@pytest.mark.parametrize("scenario", ["success", "expiry", "manual", "unavailable"])
async def test_every_flow_only_runs_allowlisted_tools_and_never_tcpip(
    controller: PhoneController,
    fake: Fake,
    notes: MagicMock,
    scenario: str,
) -> None:
    del notes
    if scenario == "success":
        phone_appears(fake, after=1)
    elif scenario == "manual":
        fake.qr_error = qr.QrUnavailable("segno")
        fake.zenity = runner.Result(0, f"{HOST}:{PAIR_PORT}|123456", "")
        fake.mdns = [MDNS_HEAD + CONNECT_LINE]
    elif scenario == "unavailable":
        fake.mdns_check = "ERROR: mdns daemon unavailable"

    await controller.pair()

    assert fake.calls
    assert {c[0] for c in fake.calls} <= {"adb", "zenity", "kitty"}
    assert all("tcpip" not in call for call in fake.calls)
    for call in fake.calls:
        if call[0] == "adb":
            assert call[1] in {"mdns", "pair", "connect"}
            if call[1] == "mdns":
                assert call[2:] in (["services"], ["check"])


# --- concurrency and entry points ----------------------------------------------


async def test_a_second_pairing_while_busy_is_ignored(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    first = asyncio.ensure_future(controller.pair())
    for _ in range(50):
        await asyncio.sleep(0)
        if fake.windows:
            break

    await controller.pair()
    controller.cancel_pairing()
    await first

    assert len(fake.windows) == 1


async def test_pair_toggle_starts_a_pairing_when_idle(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    phone_appears(fake, after=1)

    await controller.pair_toggle()

    assert len(fake.windows) == 1
    assert fake.adb("pair")


def test_phone_pair_toggle_is_synchronous_and_schedules_a_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Any] = []
    monkeypatch.setattr(ctl, "create_task", lambda coro: created.append(coro))
    monkeypatch.setattr(
        ctl, "get_controller", lambda: MagicMock(pair_toggle=MagicMock())
    )

    ctl.phone_pair_toggle()

    assert len(created) == 1
    assert not asyncio.iscoroutinefunction(ctl.phone_pair_toggle)


# --- R2.10: states along the pairing flow -----------------------------------------


async def test_qr_pairing_goes_pairing_connecting_ready(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    phone_appears(fake)

    await controller.pair()

    assert list(controller.history) == [State.PAIRING, State.CONNECTING, State.READY]


async def test_a_rejected_code_goes_pairing_connecting_disconnected(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    phone_appears(fake)
    fake.pair = runner.Result(1, PAIR_WRONG, "")

    await controller.pair()

    assert list(controller.history) == [
        State.PAIRING,
        State.CONNECTING,
        State.DISCONNECTED,
    ]


async def test_connecting_is_shown_while_adb_pair_runs(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    phone_appears(fake)
    real = fake.run
    seen: list[State] = []

    async def spy(argv: Any, **kwargs: Any) -> runner.Result:
        if list(argv)[1:2] in (["pair"], ["connect"]):
            seen.append(controller.state)
        return await real(argv, **kwargs)

    controller._run = spy

    await controller.pair()

    assert seen == [State.CONNECTING, State.CONNECTING]


async def test_manual_pairing_shows_connecting_then_ready(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    fake.qr_error = qr.QrUnavailable("segno")
    fake.zenity = runner.Result(0, f"{HOST}:{PAIR_PORT}|123456\n", "")
    fake.mdns = [MDNS_HEAD + CONNECT_LINE]

    await controller.pair()

    assert list(controller.history) == [State.CONNECTING, State.READY]


async def test_a_cancelled_pairing_goes_back_to_disconnected(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    task = asyncio.ensure_future(controller.pair())
    while not fake.windows:
        await asyncio.sleep(0)
    controller.cancel_pairing()
    await task

    assert list(controller.history) == [State.PAIRING, State.DISCONNECTED]


async def test_the_listeners_hear_about_connecting_after_a_match(
    controller: PhoneController, fake: Fake, notes: MagicMock
) -> None:
    del notes
    phone_appears(fake)
    heard: list[State] = []
    controller.attach(lambda: heard.append(controller.state))

    await controller.pair()

    assert State.CONNECTING in heard
