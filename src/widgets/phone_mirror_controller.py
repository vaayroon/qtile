"""One shared controller for every phone mirror widget and key binding.

qtile builds the widget once per screen, so the scrcpy process, the cached
device state and every subprocess call live here instead. All process spawning
goes through the allowlisted runner.
"""

import asyncio
import os
import shutil
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from enum import Enum
from typing import Any

from libqtile.log_utils import logger
from libqtile.utils import create_task, send_notification

from . import phone_mirror_runner as runner
from .phone_mirror_commands import (
    Device,
    MirrorOptions,
    build_connect_argv,
    build_devices_argv,
    build_disconnect_argv,
    build_keyevent_argv,
    build_rofi_argv,
    build_scrcpy_argv,
    build_zenity_argv,
    device_label,
    normalize_quality,
    parse_devices,
    parse_zenity_values,
    ready_device,
    ready_devices,
)
from .phone_mirror_reasons import Reason, map_exception, map_failure, message_for

REFRESH_TTL = 2.0
TAIL_LINES = 20
NOTIFY_TITLE = "Phone mirror"
NOTIFY_IDS = {"status": 7101, "error": 7102}

ENV_KEYS = {
    "adb_path": "QTILE_PHONE_MIRROR_ADB_PATH",
    "scrcpy_path": "QTILE_PHONE_MIRROR_SCRCPY_PATH",
    "wireless_target": "QTILE_PHONE_MIRROR_WIRELESS_TARGET",
    "device": "QTILE_PHONE_MIRROR_DEVICE",
    "turn_screen_off": "QTILE_PHONE_MIRROR_SCREEN_OFF",
    "show_device": "QTILE_PHONE_MIRROR_SHOW_DEVICE",
    "volume_step": "QTILE_PHONE_MIRROR_VOLUME_STEP",
    "quality": "QTILE_PHONE_MIRROR_QUALITY",
    "audio": "QTILE_PHONE_MIRROR_AUDIO",
    "restart_on_switch": "QTILE_PHONE_MIRROR_RESTART_ON_SWITCH",
}

DEFAULTS = {
    "adb_path": "adb",
    "scrcpy_path": "scrcpy",
    "wireless_target": "",
    "device": "",
    "turn_screen_off": "true",
    "show_device": "false",
    "volume_step": "5",
    "quality": "balanced",
    "audio": "false",
    "restart_on_switch": "true",
}

_TRUE = {"1", "true", "yes", "on"}
_USER_BLOCKED = {Reason.UNAUTHORIZED, Reason.OFFLINE}

RunFn = Callable[..., Awaitable[runner.Result]]
SpawnFn = Callable[[Sequence[str]], Awaitable[Any]]


class SelectionCancelled(Exception):
    """The user dismissed the device selector."""


class State(Enum):
    READY = "ready"
    MIRROR = "mirror"
    DISCONNECTED = "disconnected"
    ERROR = "error"


def to_bool(value: str) -> bool:
    return value.strip().lower() in _TRUE


class PhoneController:
    def __init__(
        self,
        *,
        run: RunFn = runner.run,
        spawn: SpawnFn = runner.spawn,
        which: Callable[[str], str | None] = shutil.which,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._run = run
        self._spawn = spawn
        self._which = which
        self._clock = clock
        self.state = State.DISCONNECTED
        self._lock = asyncio.Lock()
        self._defaults: dict[str, str] = dict(DEFAULTS)
        self._session: dict[str, str] = {}
        self._process: Any = None
        self._stop_requested: Any = None
        self._watcher: asyncio.Task[None] | None = None
        self._tail: deque[str] = deque(maxlen=TAIL_LINES)
        self._labels: dict[str, str] = {}
        self._serial = ""  # device picked in the selector, kept for the session
        self._last_refresh: float | None = None
        self._listeners: list[Callable[[], None]] = []

    # -- settings ----------------------------------------------------------

    def configure(self, defaults: Mapping[str, str]) -> None:
        self._defaults.update({k: str(v) for k, v in defaults.items()})

    def resolve(self, key: str) -> str:
        """Priority: session values, then .env, then the widget defaults."""
        session = self._session.get(key, "").strip()
        if session:
            return session
        env_name = ENV_KEYS.get(key, "")
        env_value = os.getenv(env_name, "").strip() if env_name else ""
        if env_value:
            return env_value
        return self._defaults.get(key, "").strip()

    def _settings(self) -> dict[str, str]:
        return {key: self.resolve(key) for key in DEFAULTS}

    def _options(self, serial: str) -> MirrorOptions:
        return MirrorOptions(
            quality=normalize_quality(self.resolve("quality")),
            screen_off=to_bool(self.resolve("turn_screen_off")),
            audio=to_bool(self.resolve("audio")),
            serial=serial,
        )

    def toggle_screen_off(self) -> None:
        current = to_bool(self.resolve("turn_screen_off"))
        self._session["turn_screen_off"] = "false" if current else "true"
        if self.is_mirroring():
            wanted = "on" if current is False else "off"
            self.notify(
                "status",
                NOTIFY_TITLE,
                f"Screen-off mode is now {wanted}. It applies on the next start. "
                "To turn the phone screen off or on now, press Alt+O or "
                "Alt+Shift+O in the scrcpy window.",
            )

    # -- listeners ---------------------------------------------------------

    def attach(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def detach(self, listener: Callable[[], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)
        if not self._listeners:
            self.shutdown()

    def _changed(self) -> None:
        self._last_refresh = None
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                logger.exception("PhoneMirror: listener failed")

    # -- notifications -----------------------------------------------------

    def notify(
        self, topic: str, title: str, message: str, urgent: bool = False
    ) -> None:
        logger.info("PhoneMirror: %s: %s", title, message)
        try:
            send_notification(
                title, message, urgent=urgent, id_=NOTIFY_IDS.get(topic, 7100)
            )
        except Exception as exc:
            logger.warning("PhoneMirror: notification failed: %s", exc)

    def _fail(self, reason: Reason) -> None:
        self.notify("error", NOTIFY_TITLE, message_for(reason), urgent=True)

    # -- state -------------------------------------------------------------

    def is_mirroring(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _missing_binaries(self) -> bool:
        return self._which(self.resolve("adb_path")) is None or (
            self._which(self.resolve("scrcpy_path")) is None
        )

    async def _exec(self, argv: Sequence[str], timeout: float = 5.0) -> tuple[int, str]:
        """Run an allowlisted command; never raises, returns (rc, text)."""
        try:
            result = await self._run(argv, timeout=timeout)
        except FileNotFoundError:
            return 127, "command not found"
        except (OSError, runner.ForbiddenCommand) as exc:
            logger.warning("PhoneMirror: command failed: %s", exc)
            return 1, str(exc)
        if result.timed_out:
            return 1, "timed out"
        return result.rc, f"{result.stdout}\n{result.stderr}"

    async def _list_devices(self) -> tuple[list[Device], str]:
        _rc, text = await self._exec(
            build_devices_argv(self.resolve("adb_path"), long=True)
        )
        devices = parse_devices(text)
        self._labels = {d.serial: device_label(d) for d in devices}
        return devices, text

    async def _select_device(self, devices: Sequence[Device]) -> str:
        """Ask which device to use; raises SelectionCancelled on dismissal."""
        stdin = "\n".join(device_label(d) for d in devices)
        try:
            result = await self._run(
                build_rofi_argv("Phone"), timeout=120, input_text=stdin
            )
        except (OSError, runner.ForbiddenCommand) as exc:
            logger.warning("PhoneMirror: device selector unavailable: %s", exc)
            raise SelectionCancelled from exc
        try:
            index = int(result.stdout.strip())
        except ValueError:
            index = -1
        if result.rc != 0 or not 0 <= index < len(devices):
            raise SelectionCancelled
        return devices[index].serial

    async def _find_device(self, interactive: bool = True) -> tuple[str | None, str]:
        """Pick the target serial: env, remembered, the only one, or ask."""
        devices, text = await self._list_devices()
        expected = self.resolve("device")
        if expected:
            return ready_device(devices, expected), text
        ready = ready_devices(devices)
        if self._serial and self._serial not in {d.serial for d in ready}:
            logger.info("PhoneMirror: device %s is gone, resolving again", self._serial)
            self._serial = ""
        if self._serial:
            return self._serial, text
        if len(ready) <= 1:
            return (ready[0].serial if ready else None), text
        if not interactive:
            return ready[0].serial, text
        self._serial = await self._select_device(ready)
        return self._serial, text

    async def _connect(self) -> str:
        target = self.resolve("wireless_target")
        if not target:
            return ""
        _rc, text = await self._exec(
            build_connect_argv(self.resolve("adb_path"), target)
        )
        return text

    async def refresh(self) -> State:
        if self._lock.locked():
            return self.state
        now = self._clock()
        if self._last_refresh is not None and now - self._last_refresh < REFRESH_TTL:
            return self.state
        self._last_refresh = now
        try:
            self.state = await self._probe()
        except Exception:
            logger.exception("PhoneMirror: refresh failed")
            self.state = State.DISCONNECTED
        return self.state

    async def _probe(self) -> State:
        if self._missing_binaries():
            return State.ERROR
        if self.is_mirroring():
            return State.MIRROR
        serial, _text = await self._find_device(interactive=False)
        if serial is None and self.resolve("wireless_target"):
            await self._connect()
            serial, _text = await self._find_device(interactive=False)
        return State.READY if serial else State.DISCONNECTED

    # -- actions -----------------------------------------------------------

    async def toggle(self) -> None:
        if self._lock.locked():
            logger.info("PhoneMirror: busy, click ignored")
            return
        async with self._lock:
            try:
                if self.is_mirroring():
                    self._stop()
                    return
                serial = await self._ensure_ready()
                if serial is not None:
                    await self._start(serial)
            except Exception:
                logger.exception("PhoneMirror: toggle failed")
            finally:
                self._changed()

    async def stop(self) -> None:
        self._stop()
        self._changed()

    def _stop(self) -> None:
        proc = self._process
        if proc is None:
            return
        self._stop_requested = proc
        self._process = None
        self.state = State.READY
        try:
            if proc.returncode is None:
                proc.terminate()
        except ProcessLookupError:
            pass

    def shutdown(self) -> None:
        self._stop()

    async def reconnect(self) -> None:
        """Reconnect the wireless target, then pick the device again."""
        if self._lock.locked():
            logger.info("PhoneMirror: busy, click ignored")
            return
        async with self._lock:
            try:
                was_mirroring = self.is_mirroring()
                if was_mirroring:
                    logger.info("PhoneMirror: reconnect: stopping mirroring")
                    self._stop()
                self._serial = ""
                adb = self.resolve("adb_path")
                # Never a bare `adb disconnect`: it drops every wireless device.
                target = self.resolve("wireless_target")
                if not target and ":" in self.resolve("device"):
                    target = self.resolve("device")
                if target:
                    await self._exec(build_disconnect_argv(adb, target))
                    await self._connect()
                serial = await self._ensure_ready()
                if serial is not None:
                    restarted = False
                    if was_mirroring and to_bool(self.resolve("restart_on_switch")):
                        logger.info("PhoneMirror: restarting mirroring on %s", serial)
                        await self._start(serial)
                        restarted = self.is_mirroring()
                    elif was_mirroring:
                        logger.info("PhoneMirror: mirroring not restarted (disabled)")
                    self._announce(serial, restarted=restarted, was=was_mirroring)
            except Exception:
                logger.exception("PhoneMirror: reconnect failed")
            finally:
                self._changed()

    def _announce(self, serial: str, *, restarted: bool, was: bool) -> None:
        if self.resolve("device"):
            message = (
                f"Using {serial}: it is fixed by QTILE_PHONE_MIRROR_DEVICE, "
                "so the device selector is skipped."
            )
        else:
            message = f"Using {self._labels.get(serial, serial)}."
        if restarted:
            message += " Mirroring restarted."
        elif was:
            message += " Mirroring not restarted."
        self.notify("status", NOTIFY_TITLE, message)

    async def volume(self, *, up: bool, _retry: bool = True) -> None:
        try:
            step = max(1, int(self.resolve("volume_step") or "5"))
        except ValueError:
            step = 5
        serial = self.resolve("device") or self._serial
        if not serial:
            if self._lock.locked():
                logger.info("PhoneMirror: busy, volume ignored")
                return
            async with self._lock:
                try:
                    found, _text = await self._find_device()
                except SelectionCancelled:
                    logger.info("PhoneMirror: device selection cancelled")
                    return
            if not found:
                return
            serial = found
        argv = build_keyevent_argv(self.resolve("adb_path"), 24 if up else 25, serial)
        for index in range(step):
            rc, _text = await self._exec(argv)
            if rc != 0 and index == 0 and serial == self._serial and _retry:
                logger.info("PhoneMirror: device %s is gone, resolving again", serial)
                self._serial = ""
                await self.volume(up=up, _retry=False)
                return

    async def _prompt(self) -> bool:
        initial = self._settings()
        try:
            result = await self._run(build_zenity_argv(initial), timeout=120)
        except (OSError, runner.ForbiddenCommand):
            logger.warning("PhoneMirror: zenity unavailable; skipping setup prompt")
            return False
        if result.rc != 0:
            return False
        values = parse_zenity_values(result.stdout, initial)
        if values is None:
            return False
        self._session.update(values)
        return True

    async def _ensure_ready(self) -> str | None:
        """A usable serial, or None after notifying the reason."""
        try:
            return await self._ensure_ready_inner()
        except SelectionCancelled:
            logger.info("PhoneMirror: device selection cancelled")
            return None

    async def _ensure_ready_inner(self) -> str | None:
        if self._missing_binaries() and not (
            await self._prompt() and not self._missing_binaries()
        ):
            self.state = State.ERROR
            self._fail(Reason.MISSING_BINARY)
            return None

        serial, text = await self._find_device()
        if serial is None:
            text += await self._connect()
            serial, more = await self._find_device()
            text += more
        reason = map_failure(text)
        if serial is None and reason not in _USER_BLOCKED and await self._prompt():
            text += await self._connect()
            serial, more = await self._find_device()
            text += more
            reason = map_failure(text)
        if serial is not None:
            return serial

        self.state = State.DISCONNECTED
        self._fail(Reason.NO_DEVICE if reason is Reason.UNKNOWN else reason)
        return None

    async def _start(self, serial: str) -> None:
        argv = build_scrcpy_argv(self.resolve("scrcpy_path"), self._options(serial))
        try:
            proc = await self._spawn(argv)
        except (OSError, runner.ForbiddenCommand) as exc:
            self.state = State.DISCONNECTED
            self._fail(map_exception(exc))
            return
        self._process = proc
        self._tail.clear()
        self.state = State.MIRROR
        self._watcher = create_task(self._watch(proc))
        self.notify("status", NOTIFY_TITLE, "Mirroring started.")

    async def _pump(self, stream: Any, label: str) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode(errors="replace").rstrip()
            if text:
                logger.info("scrcpy %s: %s", label, text)
                self._tail.append(text)

    async def _watch(self, proc: Any) -> None:
        await asyncio.gather(
            self._pump(proc.stdout, "stdout"), self._pump(proc.stderr, "stderr")
        )
        rc = await proc.wait()
        if self._process is proc:
            self._process = None
            self.state = State.READY
        if rc != 0 and self._stop_requested is not proc:
            reason = map_failure("\n".join(self._tail), rc)
            self.notify(
                "error",
                NOTIFY_TITLE,
                f"Mirroring stopped unexpectedly. {message_for(reason)}",
                urgent=True,
            )
        self._changed()


_controller: PhoneController | None = None


def get_controller() -> PhoneController:
    global _controller
    if _controller is None:
        _controller = PhoneController()
    return _controller


def phone_toggle(qtile: Any = None) -> None:
    """`lazy.function` target: synchronous, schedules the async toggle."""
    del qtile
    create_task(get_controller().toggle())
