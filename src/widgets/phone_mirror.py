"""Bar widget for wireless ADB + scrcpy phone mirroring.

A thin view: the shared controller owns the state and every child process, the
widget only renders it and forwards clicks. qtile never awaits mouse
callbacks, so they are plain functions that schedule the async work.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from libqtile.log_utils import logger
from libqtile.utils import create_task
from libqtile.widget import base

from .phone_mirror_controller import PhoneController, State, get_controller, to_bool


class PhoneMirrorWidget(base.BackgroundPoll):
    """Control wireless ADB + scrcpy mirroring directly from the Qtile bar.

    Mouse controls:
    - Left click: start/stop scrcpy mirroring
    - Middle click: toggle mirror mode (screen on/off)
    - Right click: reconnect / switch device (reopens mirroring if it was on)
    - Scroll up/down: phone volume up/down
    """

    defaults = [
        ("update_interval", 5, "Polling interval in seconds."),
        ("adb_path", "adb", "Path to adb binary."),
        ("scrcpy_path", "scrcpy", "Path to scrcpy binary."),
        (
            "device",
            "",
            (
                "Target device serial or host:port for adb/scrcpy; "
                "leave empty to use first device."
            ),
        ),
        (
            "wireless_target",
            "",
            (
                "Wireless adb target host:port for adb connect "
                "(example: 192.168.1.15:5555)."
            ),
        ),
        ("turn_screen_off", True, "Start scrcpy with phone display off (-S)."),
        ("quality", "balanced", "Video preset: low, balanced or high."),
        ("audio", False, "Forward the phone audio to the computer."),
        (
            "restart_on_switch",
            True,
            "Reopen mirroring after a right-click device switch if it was running.",
        ),
        ("show_device", False, "Show selected device in widget text."),
        ("format_ready", "PHONE:READY", "Text when a device is connected."),
        ("format_disconnected", "PHONE:DISC", "Text when no device is connected."),
        ("format_mirroring", "PHONE:MIRROR", "Text while scrcpy is running."),
        ("format_error", "PHONE:ERR", "Text when required binaries are missing."),
        ("volume_step", 5, "Phone media volume step used for scroll callbacks."),
    ]

    _SETTING_KEYS = (
        "adb_path",
        "scrcpy_path",
        "wireless_target",
        "device",
        "turn_screen_off",
        "quality",
        "audio",
        "restart_on_switch",
        "show_device",
        "volume_step",
    )

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        self.add_defaults(self.defaults)
        self._controller: PhoneController | None = None
        self._listener: Callable[[], None] | None = None
        self.controller.configure(
            {key: self._as_text(getattr(self, key)) for key in self._SETTING_KEYS}
        )
        self.add_callbacks(
            {
                "Button1": lambda: self._schedule(self.controller.toggle()),
                "Button2": lambda: self.controller.toggle_screen_off(),
                "Button3": lambda: self._schedule(self.controller.reconnect()),
                "Button4": lambda: self._schedule(self.controller.volume(up=True)),
                "Button5": lambda: self._schedule(self.controller.volume(up=False)),
            }
        )

    @property
    def controller(self) -> PhoneController:
        if self._controller is None:
            self._controller = get_controller()
        return self._controller

    @staticmethod
    def _as_text(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _schedule(coro: Coroutine[Any, Any, None]) -> None:
        create_task(coro)

    def _configure(self, qtile: Any, bar: Any) -> None:
        super()._configure(qtile, bar)
        if self._listener is None:
            self._listener = self.force_update
            self.controller.attach(self._listener)

    async def apoll(self) -> str:
        try:
            state = await self.controller.refresh()
        except Exception:
            logger.exception("PhoneMirrorWidget: refresh failed")
            state = State.ERROR
        return self._format_status(state)

    def _format_status(self, state: State) -> str:
        text = {
            State.READY: self.format_ready,
            State.MIRROR: self.format_mirroring,
            State.DISCONNECTED: self.format_disconnected,
            State.ERROR: self.format_error,
        }[state]
        device = self.controller.resolve("device")
        if state in (State.READY, State.MIRROR) and device:
            if to_bool(self.controller.resolve("show_device")):
                return f"{text}:{device}"
        return str(text)

    def finalize(self) -> None:
        if self._listener is not None:
            self.controller.detach(self._listener)
            self._listener = None
        super().finalize()
