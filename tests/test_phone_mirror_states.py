"""Widget states and their transitions (R2.10)."""

import itertools
from unittest.mock import MagicMock

import pytest
from src.widgets import phone_mirror_controller as ctl
from src.widgets.phone_mirror import PhoneMirrorWidget
from src.widgets.phone_mirror_controller import PhoneController, State

from tests.test_phone_mirror_controller import (
    DEVICE_NONE,
    DEVICE_OK,
    FakeRunner,
)

ALL = list(State)

ALLOWED = {
    (State.DISCONNECTED, State.READY),
    (State.DISCONNECTED, State.CONNECTING),
    (State.DISCONNECTED, State.PAIRING),
    (State.DISCONNECTED, State.ERROR),
    (State.CONNECTING, State.READY),
    (State.CONNECTING, State.DISCONNECTED),
    (State.CONNECTING, State.ERROR),
    (State.CONNECTING, State.PAIRING),
    (State.READY, State.MIRROR),
    (State.READY, State.DISCONNECTED),
    (State.READY, State.CONNECTING),
    (State.READY, State.PAIRING),
    (State.READY, State.ERROR),
    (State.MIRROR, State.READY),
    (State.MIRROR, State.DISCONNECTED),
    (State.MIRROR, State.ERROR),
    (State.PAIRING, State.CONNECTING),
    (State.PAIRING, State.DISCONNECTED),
    (State.PAIRING, State.ERROR),
    (State.ERROR, State.DISCONNECTED),
    (State.ERROR, State.READY),
    (State.ERROR, State.CONNECTING),
    (State.ERROR, State.PAIRING),
}
REJECTED = [pair for pair in itertools.permutations(ALL, 2) if pair not in ALLOWED]


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
def controller(fake: FakeRunner) -> PhoneController:
    return PhoneController(
        run=fake.run, spawn=fake.spawn, which=lambda name: f"/bin/{name}"
    )


# --- the table ------------------------------------------------------------------------


def test_there_are_six_states() -> None:
    assert {s.name for s in State} == {
        "PAIRING",
        "CONNECTING",
        "READY",
        "MIRROR",
        "DISCONNECTED",
        "ERROR",
    }


def test_the_table_covers_every_state() -> None:
    assert set(ctl.TRANSITIONS) == set(State)


@pytest.mark.parametrize(("old", "new"), sorted(ALLOWED, key=str))
def test_allowed_transitions_are_accepted(
    controller: PhoneController, old: State, new: State
) -> None:
    controller._state = old

    controller.state = new

    assert controller.state is new


@pytest.mark.parametrize(("old", "new"), REJECTED)
def test_invalid_transitions_are_rejected_and_logged(
    controller: PhoneController,
    old: State,
    new: State,
    caplog: pytest.LogCaptureFixture,
) -> None:
    controller._state = old

    with caplog.at_level("WARNING"):
        controller.state = new

    assert controller.state is old
    assert "invalid state change" in caplog.text


@pytest.mark.parametrize("state", ALL)
def test_staying_in_a_state_is_not_a_transition(
    controller: PhoneController, state: State, caplog: pytest.LogCaptureFixture
) -> None:
    controller._state = state

    with caplog.at_level("WARNING"):
        controller.state = state

    assert controller.state is state
    assert caplog.text == ""


def test_disc_to_mirror_is_the_documented_invalid_case(
    controller: PhoneController,
) -> None:
    assert controller.state is State.DISCONNECTED

    controller.state = State.MIRROR

    assert controller.state is State.DISCONNECTED


def test_an_accepted_transition_is_recorded(controller: PhoneController) -> None:
    controller.state = State.CONNECTING
    controller.state = State.READY

    assert list(controller.history)[-2:] == [State.CONNECTING, State.READY]


def test_a_rejected_transition_is_not_recorded(controller: PhoneController) -> None:
    controller.state = State.MIRROR

    assert list(controller.history) == []


# --- flows ----------------------------------------------------------------------------


@pytest.mark.usefixtures("notes")
async def test_toggle_goes_through_ready_before_mirror(
    controller: PhoneController,
) -> None:
    await controller.toggle()

    assert list(controller.history) == [State.READY, State.MIRROR]


@pytest.mark.usefixtures("notes")
async def test_the_connect_step_shows_connecting(
    controller: PhoneController,
    fake: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "192.168.1.20:5555")
    fake.devices = [DEVICE_NONE, DEVICE_OK]
    seen: list[State] = []
    real = fake.run

    async def spy(argv, **kwargs):  # type: ignore[no-untyped-def]
        if "connect" in argv:
            seen.append(controller.state)
        return await real(argv, **kwargs)

    controller._run = spy

    await controller.toggle()

    assert seen == [State.CONNECTING]
    assert list(controller.history) == [State.CONNECTING, State.READY, State.MIRROR]


@pytest.mark.usefixtures("notes")
async def test_a_failed_connect_ends_disconnected(
    controller: PhoneController,
    fake: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "192.168.1.20:5555")
    fake.devices = [DEVICE_NONE]

    await controller.toggle()

    assert controller.state is State.DISCONNECTED
    assert State.CONNECTING in controller.history


@pytest.mark.usefixtures("notes")
async def test_the_listeners_hear_about_connecting(
    controller: PhoneController,
    fake: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "192.168.1.20:5555")
    fake.devices = [DEVICE_NONE, DEVICE_OK]
    heard: list[State] = []
    controller.attach(lambda: heard.append(controller.state))

    await controller.toggle()

    assert State.CONNECTING in heard


@pytest.mark.usefixtures("notes")
async def test_right_click_shows_connecting_while_it_reconnects(
    controller: PhoneController,
    fake: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QTILE_PHONE_MIRROR_WIRELESS_TARGET", "192.168.1.20:5555")
    fake.devices = [DEVICE_OK]

    await controller.reconnect()

    assert State.CONNECTING in controller.history
    assert controller.state is State.READY


async def test_pairing_is_refused_while_mirroring(
    controller: PhoneController, fake: FakeRunner, notes: MagicMock
) -> None:
    await controller.toggle()
    assert controller.state is State.MIRROR
    fake.calls.clear()

    await controller.pair()

    assert controller.state is State.MIRROR
    assert fake.calls == []
    assert "stop mirroring" in notes.call_args.args[1].lower()


async def test_stopping_goes_back_to_ready(controller: PhoneController) -> None:
    await controller.toggle()
    watcher = controller._watcher
    await controller.toggle()
    assert watcher is not None
    await watcher

    assert controller.state is State.READY


async def test_missing_binaries_end_in_error_from_any_state(
    fake: FakeRunner, notes: MagicMock
) -> None:
    del notes
    ctrl = PhoneController(run=fake.run, spawn=fake.spawn, which=lambda _n: None)
    ctrl._state = State.READY

    assert await ctrl.refresh() is State.ERROR


# --- widget text ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "text"),
    [
        (State.READY, "PHONE:READY"),
        (State.DISCONNECTED, "PHONE:DISC"),
        (State.MIRROR, "PHONE:MIRROR"),
        (State.ERROR, "PHONE:ERR"),
        (State.CONNECTING, "PHONE:CONN"),
    ],
)
def test_every_state_has_its_own_text(state: State, text: str) -> None:
    widget = PhoneMirrorWidget()
    widget._controller = MagicMock(
        resolve=lambda _k: "", pairing_countdown=lambda: "02:00"
    )

    assert widget._format_status(state) == text


def test_all_state_texts_are_distinct_and_english() -> None:
    widget = PhoneMirrorWidget()
    widget._controller = MagicMock(
        resolve=lambda _k: "", pairing_countdown=lambda: "02:00"
    )

    texts = [widget._format_status(state) for state in State]

    assert len(set(texts)) == len(State)
    assert all(t.startswith("PHONE:") and t.isascii() for t in texts)


def test_the_connecting_text_is_configurable() -> None:
    widget = PhoneMirrorWidget(format_connecting="LINKING")
    widget._controller = MagicMock(resolve=lambda _k: "")

    assert widget._format_status(State.CONNECTING) == "LINKING"
