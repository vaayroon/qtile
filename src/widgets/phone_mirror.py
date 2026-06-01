import shutil
import subprocess
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:

    class ThreadPoolTextBase:
        def __init__(self, text: str = "", **config: Any) -> None: ...

        def add_defaults(self, defaults: list[tuple[str, Any, str]]) -> None: ...

        def add_callbacks(self, callbacks: dict[str, Any]) -> None: ...

        def tick(self) -> None: ...

else:
    from libqtile.widget.base import InLoopPollText as ThreadPoolTextBase


class PhoneMirrorWidget(ThreadPoolTextBase):
    """Control wireless ADB + scrcpy mirroring directly from the Qtile bar.

    Mouse controls:
    - Left click: start/stop scrcpy mirroring
    - Middle click: toggle mirror mode (screen on/off)
    - Right click: force wireless reconnect with ADB
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
        ("show_device", False, "Show selected device in widget text."),
        ("format_ready", "PHONE:READY", "Text when a device is connected."),
        ("format_disconnected", "PHONE:DISC", "Text when no device is connected."),
        ("format_mirroring", "PHONE:MIRROR", "Text while scrcpy is running."),
        ("format_error", "PHONE:ERR", "Text when required binaries are missing."),
        ("volume_step", 5, "Phone media volume step used for scroll callbacks."),
    ]

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        self.add_defaults(self.defaults)
        self._scrcpy_process: subprocess.Popen[str] | None = None
        self.turn_screen_off: bool = bool(getattr(self, "turn_screen_off", True))
        self.device: str = str(getattr(self, "device", ""))
        self.wireless_target: str = str(getattr(self, "wireless_target", ""))
        self.show_device: bool = bool(getattr(self, "show_device", False))
        self.volume_step: int = int(getattr(self, "volume_step", 5))
        self.format_error: str = str(getattr(self, "format_error", "PHONE:ERR"))
        self.format_ready: str = str(getattr(self, "format_ready", "PHONE:READY"))
        self.format_disconnected: str = str(
            getattr(self, "format_disconnected", "PHONE:DISC")
        )
        self.format_mirroring: str = str(
            getattr(self, "format_mirroring", "PHONE:MIRROR")
        )
        self.adb_path: str = str(getattr(self, "adb_path", "adb"))
        self.scrcpy_path: str = str(getattr(self, "scrcpy_path", "scrcpy"))

        self.add_callbacks(
            {
                "Button1": self._toggle_mirroring,
                "Button2": self._toggle_turn_screen_off,
                "Button3": self._reconnect_wireless,
                "Button4": self._volume_up,
                "Button5": self._volume_down,
            }
        )

    def poll(self) -> str:
        if not self._has_binary(self.adb_path) or not self._has_binary(
            self.scrcpy_path
        ):
            return str(self.format_error)

        if self._is_mirroring_running():
            return self._format_status(self.format_mirroring)

        if self._has_connected_device():
            return self._format_status(self.format_ready)

        if self.wireless_target:
            self._adb_call(["connect", self.wireless_target])
            if self._has_connected_device():
                return self._format_status(self.format_ready)

        return self._format_status(self.format_disconnected)

    def _format_status(self, base_text: str) -> str:
        if self.show_device and self.device:
            return f"{base_text}:{self.device}"
        return base_text

    def _toggle_mirroring(self) -> None:
        if self._is_mirroring_running():
            self._stop_mirroring()
            self.tick()
            return

        self._start_mirroring()
        self.tick()

    def _toggle_turn_screen_off(self) -> None:
        self.turn_screen_off = not self.turn_screen_off
        self.tick()

    def _reconnect_wireless(self) -> None:
        if self.wireless_target:
            self._adb_call(["disconnect", self.wireless_target])
            self._adb_call(["connect", self.wireless_target])
        elif self.device:
            self._adb_call(["disconnect", self.device])
            self._adb_call(["connect", self.device])
        else:
            self._adb_call(["disconnect"])
        self.tick()

    def _start_mirroring(self) -> None:
        if not self._has_connected_device() and self.wireless_target:
            self._adb_call(["connect", self.wireless_target])

        command: list[str] = [self.scrcpy_path]
        if self.turn_screen_off:
            command.append("-S")

        if self.device:
            command.extend(["-s", self.device])

        self._scrcpy_process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def _stop_mirroring(self) -> None:
        if self._scrcpy_process is None:
            return

        if self._scrcpy_process.poll() is None:
            self._scrcpy_process.terminate()

        self._scrcpy_process = None

    def _is_mirroring_running(self) -> bool:
        if self._scrcpy_process is None:
            return False

        if self._scrcpy_process.poll() is not None:
            self._scrcpy_process = None
            return False

        return True

    def _has_connected_device(self) -> bool:
        output = self._adb_call(["devices"])
        if output is None:
            return False

        for raw_line in output.splitlines()[1:]:
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith("\tdevice"):
                serial = line.split("\t", maxsplit=1)[0]
                if not self.device or self.device == serial:
                    return True

        return False

    def _adb_call(self, args: Sequence[str]) -> str | None:
        command: list[str] = [self.adb_path, *args]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if completed.returncode != 0:
            return None

        return completed.stdout

    def _send_keyevent(self, keycode: int) -> None:
        args: list[str] = ["shell", "input", "keyevent", str(keycode)]
        if self.device:
            args = ["-s", self.device, *args]
        self._adb_call(args)

    def _volume_up(self) -> None:
        for _ in range(max(1, int(self.volume_step))):
            self._send_keyevent(24)

    def _volume_down(self) -> None:
        for _ in range(max(1, int(self.volume_step))):
            self._send_keyevent(25)

    @staticmethod
    def _has_binary(name_or_path: str) -> bool:
        return shutil.which(name_or_path) is not None
