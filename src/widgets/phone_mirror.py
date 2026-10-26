import asyncio
import os
import shutil
import subprocess
from collections.abc import Sequence
from typing import Any

from libqtile.log_utils import logger
from libqtile.widget import base


class PhoneMirrorWidget(base.BackgroundPoll):
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

    # -------------------------------------------------------------------------
    # Poll (sync — runs in executor thread via BackgroundPoll)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Async button callbacks
    # -------------------------------------------------------------------------

    async def _toggle_mirroring(self) -> None:
        try:
            if self._is_mirroring_running():
                self._stop_mirroring()
                self.force_update()
                return

            if not await self._ensure_ready_for_mirroring_async(triggered_by_user=True):
                self.force_update()
                return

            await self._start_mirroring_async()
            self.force_update()
        except Exception:
            logger.exception("PhoneMirrorWidget: error in _toggle_mirroring")
            self.force_update()

    async def _toggle_turn_screen_off(self) -> None:
        current = self._to_bool(self._resolve_value("turn_screen_off"))
        self._session_values["turn_screen_off"] = self._bool_to_string(not current)
        self.force_update()

    async def _reconnect_wireless(self) -> None:
        try:
            resolved = self._resolve_settings()
            target = resolved["wireless_target"]
            device = resolved["device"]
            adb_path = resolved["adb_path"]

            if target:
                await self._adb_call_async(adb_path, ["disconnect", target])
                await self._adb_call_async(adb_path, ["connect", target])
            elif device:
                await self._adb_call_async(adb_path, ["disconnect", device])
                await self._adb_call_async(adb_path, ["connect", device])
            else:
                await self._adb_call_async(adb_path, ["disconnect"])

            ready = await self._ensure_ready_for_mirroring_async(
                triggered_by_user=False
            )
            if not ready:
                await self._prompt_for_missing_or_failed_connection_async()

            self.force_update()
        except Exception:
            logger.exception("PhoneMirrorWidget: error in _reconnect_wireless")
            self.force_update()

    async def _volume_up(self) -> None:
        try:
            step = max(1, self._safe_int(self._resolve_value("volume_step"), 5))
            for _ in range(step):
                await self._send_keyevent_async(24)
        except Exception:
            logger.exception("PhoneMirrorWidget: error in _volume_up")

    async def _volume_down(self) -> None:
        try:
            step = max(1, self._safe_int(self._resolve_value("volume_step"), 5))
            for _ in range(step):
                await self._send_keyevent_async(25)
        except Exception:
            logger.exception("PhoneMirrorWidget: error in _volume_down")

    # -------------------------------------------------------------------------
    # Async adb infrastructure
    # -------------------------------------------------------------------------

    async def _adb_call_async(self, adb_path: str, args: Sequence[str]) -> str | None:
        command = [adb_path, *args]
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        except TimeoutError:
            if proc is not None:
                proc.kill()
                await proc.wait()
            logger.debug("PhoneMirrorWidget: adb command timed out: %s", command)
            return None
        except OSError:
            logger.debug("PhoneMirrorWidget: OSError running adb command: %s", command)
            return None

        if proc.returncode != 0:
            return None

        return stdout.decode(errors="replace")

    async def _has_connected_device_async(
        self, adb_path: str, expected_device: str
    ) -> bool:
        output = await self._adb_call_async(adb_path, ["devices"])
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

    async def _send_keyevent_async(self, keycode: int) -> None:
        resolved = self._resolve_settings()
        args: list[str] = ["shell", "input", "keyevent", str(keycode)]
        if resolved["device"]:
            args = ["-s", resolved["device"], *args]
        await self._adb_call_async(resolved["adb_path"], args)

    async def _ensure_ready_for_mirroring_async(
        self, *, triggered_by_user: bool
    ) -> bool:
        resolved = self._resolve_settings()

        if not self._has_binary(resolved["adb_path"]) or not self._has_binary(
            resolved["scrcpy_path"]
        ):
            if not triggered_by_user:
                return False
            if not await self._prompt_for_missing_or_failed_connection_async():
                return False
            resolved = self._resolve_settings()

        connected = await self._has_connected_device_async(
            resolved["adb_path"],
            resolved["device"],
        )
        if connected:
            return True

        if resolved["wireless_target"]:
            await self._adb_call_async(
                resolved["adb_path"],
                ["connect", resolved["wireless_target"]],
            )
            if await self._has_connected_device_async(
                resolved["adb_path"],
                resolved["device"],
            ):
                return True

        if not triggered_by_user:
            return False

        if not await self._prompt_for_missing_or_failed_connection_async():
            return False

        resolved = self._resolve_settings()
        if resolved["wireless_target"]:
            await self._adb_call_async(
                resolved["adb_path"],
                ["connect", resolved["wireless_target"]],
            )

        return await self._has_connected_device_async(
            resolved["adb_path"],
            resolved["device"],
        )

    async def _start_mirroring_async(self) -> None:
        resolved = self._resolve_settings()

        if (
            not await self._has_connected_device_async(
                resolved["adb_path"],
                resolved["device"],
            )
            and resolved["wireless_target"]
        ):
            await self._adb_call_async(
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

    # -------------------------------------------------------------------------
    # Async zenity prompt
    # -------------------------------------------------------------------------

    async def _prompt_for_missing_or_failed_connection_async(self) -> bool:
        initial = self._resolve_settings()
        values = await self._prompt_with_zenity_async(initial)
        if not values:
            return False

        self._session_values.update(values)
        return True

    async def _prompt_with_zenity_async(
        self, initial: dict[str, str]
    ) -> dict[str, str] | None:
        if shutil.which("zenity") is None:
            logger.warning("PhoneMirrorWidget: zenity not found; skipping setup prompt")
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

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            if proc is not None:
                proc.kill()
                await proc.wait()
            return None
        except OSError:
            return None

        if proc.returncode != 0:
            return None

        values = stdout.decode(errors="replace").strip().split("|")
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

    # -------------------------------------------------------------------------
    # Sync adb infrastructure (poll path — runs in executor thread)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def finalize(self) -> None:
        self._stop_mirroring()
        super().finalize()

    # -------------------------------------------------------------------------
    # Settings resolution (unchanged)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Static helpers (unchanged)
    # -------------------------------------------------------------------------

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
