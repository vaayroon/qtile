import os
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

    _ENV_KEYS = {
        "adb_path": "QTILE_PHONE_MIRROR_ADB_PATH",
        "scrcpy_path": "QTILE_PHONE_MIRROR_SCRCPY_PATH",
        "wireless_target": "QTILE_PHONE_MIRROR_WIRELESS_TARGET",
        "device": "QTILE_PHONE_MIRROR_DEVICE",
        "turn_screen_off": "QTILE_PHONE_MIRROR_SCREEN_OFF",
        "show_device": "QTILE_PHONE_MIRROR_SHOW_DEVICE",
        "volume_step": "QTILE_PHONE_MIRROR_VOLUME_STEP",
    }

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        self.add_defaults(self.defaults)
        self._scrcpy_process: subprocess.Popen[str] | None = None
        self._session_values: dict[str, str] = {}
        self._fallback_values: dict[str, str] = {
            "adb_path": str(getattr(self, "adb_path", "adb")),
            "scrcpy_path": str(getattr(self, "scrcpy_path", "scrcpy")),
            "wireless_target": str(getattr(self, "wireless_target", "")),
            "device": str(getattr(self, "device", "")),
            "turn_screen_off": self._bool_to_string(
                bool(getattr(self, "turn_screen_off", True))
            ),
            "show_device": self._bool_to_string(
                bool(getattr(self, "show_device", False))
            ),
            "volume_step": str(getattr(self, "volume_step", 5)),
        }
        self.format_error: str = str(getattr(self, "format_error", "PHONE:ERR"))
        self.format_ready: str = str(getattr(self, "format_ready", "PHONE:READY"))
        self.format_disconnected: str = str(
            getattr(self, "format_disconnected", "PHONE:DISC")
        )
        self.format_mirroring: str = str(
            getattr(self, "format_mirroring", "PHONE:MIRROR")
        )

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
        resolved = self._resolve_settings()

        if not self._has_binary(resolved["adb_path"]) or not self._has_binary(
            resolved["scrcpy_path"]
        ):
            return str(self.format_error)

        if self._is_mirroring_running():
            return self._format_status(self.format_mirroring, resolved["device"])

        if self._has_connected_device(
            resolved["adb_path"],
            resolved["device"],
        ):
            return self._format_status(self.format_ready, resolved["device"])

        if resolved["wireless_target"]:
            self._adb_call(
                resolved["adb_path"],
                ["connect", resolved["wireless_target"]],
            )
            if self._has_connected_device(
                resolved["adb_path"],
                resolved["device"],
            ):
                return self._format_status(self.format_ready, resolved["device"])

        return self._format_status(self.format_disconnected, resolved["device"])

    def _format_status(self, base_text: str, device: str) -> str:
        if self._to_bool(self._resolve_value("show_device")) and device:
            return f"{base_text}:{device}"
        return base_text

    def _toggle_mirroring(self) -> None:
        if self._is_mirroring_running():
            self._stop_mirroring()
            self.tick()
            return

        if not self._ensure_ready_for_mirroring(triggered_by_user=True):
            self.tick()
            return

        self._start_mirroring()
        self.tick()

    def _toggle_turn_screen_off(self) -> None:
        current = self._to_bool(self._resolve_value("turn_screen_off"))
        self._session_values["turn_screen_off"] = self._bool_to_string(not current)
        self.tick()

    def _reconnect_wireless(self) -> None:
        resolved = self._resolve_settings()
        target = resolved["wireless_target"]
        device = resolved["device"]
        adb_path = resolved["adb_path"]

        if target:
            self._adb_call(adb_path, ["disconnect", target])
            self._adb_call(adb_path, ["connect", target])
        elif device:
            self._adb_call(adb_path, ["disconnect", device])
            self._adb_call(adb_path, ["connect", device])
        else:
            self._adb_call(adb_path, ["disconnect"])

        if not self._ensure_ready_for_mirroring(triggered_by_user=False):
            self._prompt_for_missing_or_failed_connection()
        self.tick()

    def _start_mirroring(self) -> None:
        resolved = self._resolve_settings()

        if (
            not self._has_connected_device(
                resolved["adb_path"],
                resolved["device"],
            )
            and resolved["wireless_target"]
        ):
            self._adb_call(
                resolved["adb_path"],
                ["connect", resolved["wireless_target"]],
            )

        command: list[str] = [resolved["scrcpy_path"]]
        if self._to_bool(resolved["turn_screen_off"]):
            command.append("-S")

        if resolved["device"]:
            command.extend(["-s", resolved["device"]])

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

    def _has_connected_device(self, adb_path: str, expected_device: str) -> bool:
        output = self._adb_call(adb_path, ["devices"])
        if output is None:
            return False

        for raw_line in output.splitlines()[1:]:
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith("\tdevice"):
                serial = line.split("\t", maxsplit=1)[0]
                if not expected_device or expected_device == serial:
                    return True

        return False

    def _adb_call(self, adb_path: str, args: Sequence[str]) -> str | None:
        command: list[str] = [adb_path, *args]
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
        resolved = self._resolve_settings()
        args: list[str] = ["shell", "input", "keyevent", str(keycode)]
        if resolved["device"]:
            args = ["-s", resolved["device"], *args]
        self._adb_call(resolved["adb_path"], args)

    def _volume_up(self) -> None:
        step = max(1, self._safe_int(self._resolve_value("volume_step"), 5))
        for _ in range(step):
            self._send_keyevent(24)

    def _volume_down(self) -> None:
        step = max(1, self._safe_int(self._resolve_value("volume_step"), 5))
        for _ in range(step):
            self._send_keyevent(25)

    def _resolve_value(self, key: str) -> str:
        # Priority: session runtime values -> .env -> widget config defaults.
        session_value = self._session_values.get(key, "").strip()
        if session_value:
            return session_value

        env_key = self._ENV_KEYS.get(key, "")
        env_value = os.getenv(env_key, "").strip() if env_key else ""
        if env_value:
            return env_value

        return self._fallback_values.get(key, "").strip()

    def _resolve_settings(self) -> dict[str, str]:
        return {
            "adb_path": self._resolve_value("adb_path"),
            "scrcpy_path": self._resolve_value("scrcpy_path"),
            "wireless_target": self._resolve_value("wireless_target"),
            "device": self._resolve_value("device"),
            "turn_screen_off": self._resolve_value("turn_screen_off"),
            "show_device": self._resolve_value("show_device"),
            "volume_step": self._resolve_value("volume_step"),
        }

    def _ensure_ready_for_mirroring(self, *, triggered_by_user: bool) -> bool:
        resolved = self._resolve_settings()

        if not self._has_binary(resolved["adb_path"]) or not self._has_binary(
            resolved["scrcpy_path"]
        ):
            if not triggered_by_user:
                return False
            if not self._prompt_for_missing_or_failed_connection():
                return False
            resolved = self._resolve_settings()

        connected = self._has_connected_device(
            resolved["adb_path"],
            resolved["device"],
        )
        if connected:
            return True

        if resolved["wireless_target"]:
            self._adb_call(
                resolved["adb_path"],
                ["connect", resolved["wireless_target"]],
            )
            if self._has_connected_device(
                resolved["adb_path"],
                resolved["device"],
            ):
                return True

        if not triggered_by_user:
            return False

        if not self._prompt_for_missing_or_failed_connection():
            return False

        resolved = self._resolve_settings()
        if resolved["wireless_target"]:
            self._adb_call(
                resolved["adb_path"],
                ["connect", resolved["wireless_target"]],
            )

        return self._has_connected_device(
            resolved["adb_path"],
            resolved["device"],
        )

    def _prompt_for_missing_or_failed_connection(self) -> bool:
        initial = self._resolve_settings()
        values = self._prompt_with_zenity(initial)
        if not values:
            values = self._prompt_with_tkinter(initial)
        if not values:
            return False

        self._session_values.update(values)
        return True

    def _prompt_with_zenity(self, initial: dict[str, str]) -> dict[str, str] | None:
        if shutil.which("zenity") is None:
            return None

        # Zenity forms cannot prefill defaults directly, so values are shown in labels.
        command = [
            "zenity",
            "--forms",
            "--title=Phone Mirror Setup",
            "--text=Ingresa solo lo minimo para conectar el telefono",
            "--separator=|",
            (
                "--add-entry=ADB host:port "
                f"({initial['wireless_target'] or '192.168.1.10:5555'})"
            ),
            f"--add-entry=Device serial opcional ({initial['device'] or 'auto'})",
            f"--add-entry=ADB path ({initial['adb_path']})",
            f"--add-entry=scrcpy path ({initial['scrcpy_path']})",
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if completed.returncode != 0:
            return None

        values = completed.stdout.strip().split("|")
        if len(values) < 4:
            return None

        target = values[0].strip() or initial["wireless_target"]
        device = values[1].strip() or initial["device"]
        adb_path = values[2].strip() or initial["adb_path"]
        scrcpy_path = values[3].strip() or initial["scrcpy_path"]

        return {
            "wireless_target": target,
            "device": device,
            "adb_path": adb_path,
            "scrcpy_path": scrcpy_path,
        }

    def _prompt_with_tkinter(self, initial: dict[str, str]) -> dict[str, str] | None:
        try:
            import tkinter as tk
        except ImportError:
            return None

        result: dict[str, str] = {}

        root = tk.Tk()
        root.title("Phone Mirror Setup")
        root.resizable(False, False)

        labels = [
            "ADB host:port",
            "Device serial (opcional)",
            "ADB path",
            "scrcpy path",
        ]
        keys = ["wireless_target", "device", "adb_path", "scrcpy_path"]
        entries: dict[str, tk.Entry] = {}

        for index, (label, key) in enumerate(zip(labels, keys, strict=True)):
            tk.Label(root, text=label).grid(
                row=index,
                column=0,
                padx=8,
                pady=4,
                sticky="w",
            )
            entry = tk.Entry(root, width=42)
            entry.insert(0, initial[key])
            entry.grid(row=index, column=1, padx=8, pady=4)
            entries[key] = entry

        def submit() -> None:
            for key in keys:
                result[key] = entries[key].get().strip()
            root.destroy()

        def cancel() -> None:
            result.clear()
            root.destroy()

        button_frame = tk.Frame(root)
        button_frame.grid(row=len(keys), column=0, columnspan=2, pady=8)
        tk.Button(button_frame, text="Conectar", command=submit).pack(
            side="left",
            padx=6,
        )
        tk.Button(button_frame, text="Cancelar", command=cancel).pack(
            side="left",
            padx=6,
        )

        root.mainloop()

        if not result:
            return None

        return {
            "wireless_target": result.get(
                "wireless_target",
                initial["wireless_target"],
            ),
            "device": result.get("device", initial["device"]),
            "adb_path": result.get("adb_path", initial["adb_path"]),
            "scrcpy_path": result.get("scrcpy_path", initial["scrcpy_path"]),
        }

    @staticmethod
    def _safe_int(value: str, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _bool_to_string(value: bool) -> str:
        return "true" if value else "false"

    @staticmethod
    def _has_binary(name_or_path: str) -> bool:
        return shutil.which(name_or_path) is not None
