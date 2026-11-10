"""PhoneMirrorWidget is a thin view over the shared controller (R1.1, R1.7, R1.8).

The widget is built through the real constructor (no bar needed) and given a
fake controller, so nothing here touches adb, scrcpy or the network.
"""

import asyncio
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.widgets import phone_mirror
from src.widgets.phone_mirror import PhoneMirrorWidget
from src.widgets.phone_mirror_controller import State

SOURCE = Path(phone_mirror.__file__).read_text()

PREVIOUS_SPANISH_STRINGS = (
    "Ingresa solo lo minimo",
    "telefono",
    "opcional",
)


class FakeController:
    def __init__(self, state: State = State.READY) -> None:
        self.state = state
        self.configured: dict[str, str] = {}
        self.attached: list[Any] = []
        self.detached: list[Any] = []
        self.actions: list[str] = []
        self.settings = {"device": "SER", "show_device": "false"}
        self.countdown = "02:41"

    def configure(self, defaults: dict[str, str]) -> None:
        self.configured = dict(defaults)

    def resolve(self, key: str) -> str:
        return self.settings.get(key, "")

    async def refresh(self) -> State:
        return self.state

    async def toggle(self) -> None:
        self.actions.append("toggle")

    async def reconnect(self) -> None:
        self.actions.append("reconnect")

    async def volume(self, *, up: bool) -> None:
        self.actions.append("volume_up" if up else "volume_down")

    def toggle_screen_off(self) -> None:
        self.actions.append("screen_off")

    def pairing_countdown(self) -> str:
        return self.countdown

    def attach(self, listener: Any) -> None:
        self.attached.append(listener)

    def detach(self, listener: Any) -> None:
        self.detached.append(listener)


@pytest.fixture()
def fake() -> FakeController:
    return FakeController()


@pytest.fixture()
def widget(fake: FakeController) -> PhoneMirrorWidget:
    w = PhoneMirrorWidget()
    w._controller = fake  # type: ignore[assignment]
    return w


# --- R1.1: callbacks are synchronous ---------------------------------------------


def test_callbacks_are_not_coroutine_functions(widget: PhoneMirrorWidget) -> None:
    callbacks = widget.mouse_callbacks
    assert set(callbacks) >= {"Button1", "Button2", "Button3", "Button4", "Button5"}
    for name, callback in callbacks.items():
        assert not inspect.iscoroutinefunction(callback), name


async def test_left_click_schedules_the_toggle(
    widget: PhoneMirrorWidget, fake: FakeController, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks: list[asyncio.Future[Any]] = []

    def fake_create_task(coro: Any) -> None:
        tasks.append(asyncio.ensure_future(coro))

    monkeypatch.setattr(phone_mirror, "create_task", fake_create_task)

    widget.mouse_callbacks["Button1"]()
    widget.mouse_callbacks["Button3"]()
    widget.mouse_callbacks["Button4"]()
    widget.mouse_callbacks["Button5"]()
    await asyncio.gather(*tasks)

    assert fake.actions == ["toggle", "reconnect", "volume_up", "volume_down"]


def test_middle_click_flips_screen_off(
    widget: PhoneMirrorWidget, fake: FakeController
) -> None:
    widget.mouse_callbacks["Button2"]()
    assert fake.actions == ["screen_off"]


def test_sync_poll_is_gone() -> None:
    assert PhoneMirrorWidget.poll is phone_mirror.base.BackgroundPoll.poll
    assert inspect.iscoroutinefunction(PhoneMirrorWidget.apoll)


# --- R1.8: widget text -------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "text"),
    [
        (State.READY, "PHONE:READY"),
        (State.DISCONNECTED, "PHONE:DISC"),
        (State.MIRROR, "PHONE:MIRROR"),
        (State.ERROR, "PHONE:ERR"),
    ],
)
async def test_apoll_text_per_state(
    widget: PhoneMirrorWidget, fake: FakeController, state: State, text: str
) -> None:
    fake.state = state
    assert await widget.apoll() == text


async def test_apoll_shows_the_pairing_countdown(
    widget: PhoneMirrorWidget, fake: FakeController
) -> None:
    fake.state = State.PAIRING
    assert await widget.apoll() == "PHONE:PAIR 02:41"

    fake.countdown = "00:07"
    assert await widget.apoll() == "PHONE:PAIR 00:07"


async def test_a_broken_pairing_format_falls_back_to_the_raw_text(
    widget: PhoneMirrorWidget, fake: FakeController
) -> None:
    fake.state = State.PAIRING
    widget.format_pairing = "PAIR {oops}"
    assert await widget.apoll() == "PAIR {oops}"

    widget.format_pairing = "PAIR"
    assert await widget.apoll() == "PAIR"


async def test_apoll_appends_the_device_when_enabled(
    widget: PhoneMirrorWidget, fake: FakeController
) -> None:
    fake.settings["show_device"] = "true"
    assert await widget.apoll() == "PHONE:READY:SER"


async def test_apoll_survives_a_controller_error(
    widget: PhoneMirrorWidget, fake: FakeController
) -> None:
    async def boom() -> State:
        raise RuntimeError("x")

    fake.refresh = boom  # type: ignore[method-assign]
    assert await widget.apoll() == "PHONE:ERR"


# --- configuration and lifecycle -----------------------------------------------------


def test_constructor_hands_defaults_to_the_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeController()
    monkeypatch.setattr(phone_mirror, "get_controller", lambda: fake)
    PhoneMirrorWidget(adb_path="/opt/genymobile/adb", turn_screen_off=False)

    assert fake.configured["adb_path"] == "/opt/genymobile/adb"
    assert fake.configured["turn_screen_off"] == "false"
    assert fake.configured["quality"] == "balanced"
    assert fake.configured["pair_ttl"] == "180"


def test_finalize_detaches_from_the_controller(
    widget: PhoneMirrorWidget, fake: FakeController, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phone_mirror.base.BackgroundPoll, "finalize", MagicMock())
    listener = widget.force_update
    widget._listener = listener
    widget.finalize()
    assert fake.detached == [listener]
    assert widget._listener is None


def test_configuring_twice_attaches_the_listener_once(
    widget: PhoneMirrorWidget, fake: FakeController, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phone_mirror.base.BackgroundPoll, "_configure", MagicMock())

    widget._configure(MagicMock(), MagicMock())
    widget._configure(MagicMock(), MagicMock())

    assert len(fake.attached) == 1
    assert fake.attached[0] == widget.force_update


# --- R1.7: English only, no direct process handling ------------------------


@pytest.mark.parametrize("fragment", PREVIOUS_SPANISH_STRINGS)
def test_no_spanish_strings(fragment: str) -> None:
    assert fragment not in SOURCE


def test_source_contract() -> None:
    assert "import tkinter" not in SOURCE
    assert "self.tick()" not in SOURCE
    assert "subprocess" not in SOURCE
    assert "shell=True" not in SOURCE
