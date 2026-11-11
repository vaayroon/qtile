"""One shared controller for every phone mirror widget and key binding.

qtile builds the widget once per screen, so the scrcpy process, the cached
device state and every subprocess call live here instead. All process spawning
goes through the allowlisted runner.
"""

import asyncio
import contextlib
import math
import os
import shutil
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from libqtile.utils import create_task, send_notification

from . import phone_mirror_log as plog
from . import phone_mirror_qr as qr
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
from .phone_mirror_log import logger
from .phone_mirror_pairing import (
    DEFAULT_TTL,
    MdnsEntry,
    PairingSession,
    build_mdns_argv,
    build_pair_argv,
    build_zenity_pair_argv,
    connect_succeeded,
    find_connect,
    find_connect_by_instance,
    find_pairing,
    new_session,
    parse_mdns,
    parse_zenity_pair,
    redact,
)
from .phone_mirror_reasons import Reason, map_exception, map_failure, message_for
from .phone_mirror_state import (
    MAX_ATTEMPTS,
    RememberedDevice,
    backoff_delay,
    is_wireless_serial,
    load,
    save,
    serial_from_instance,
    state_path,
    transport_of,
    valid_identity,
)

REFRESH_TTL = 2.0
STOP_GRACE = 3.0  # seconds between SIGTERM and SIGKILL when stopping scrcpy
VOLUME_STEP_DEFAULT = 5
VOLUME_STEP_MIN = 1
VOLUME_STEP_MAX = 20
TAIL_LINES = 20
NOTIFY_TITLE = "Phone mirror"
NOTIFY_IDS = {"status": 7101, "error": 7102, "pair": 7103}
PAIR_POLL_INTERVAL = 2.0  # seconds between `adb mdns services` queries
PAIR_TTL_MIN = 120.0
PAIR_TTL_MAX = 300.0
PAIR_TIMEOUT = 20.0  # seconds allowed for `adb pair`
CONNECT_WAIT = 10.0  # seconds to wait for the phone's connect entry after pairing

ENV_KEYS = {
    "adb_path": "QTILE_PHONE_MIRROR_ADB_PATH",
    "scrcpy_path": "QTILE_PHONE_MIRROR_SCRCPY_PATH",
    "wireless_target": "QTILE_PHONE_MIRROR_WIRELESS_TARGET",
    "device": "QTILE_PHONE_MIRROR_DEVICE",
    "turn_screen_off": "QTILE_PHONE_MIRROR_SCREEN_OFF",
    "show_device": "QTILE_PHONE_MIRROR_SHOW_DEVICE",
    "volume_step": "QTILE_PHONE_MIRROR_VOLUME_STEP",
    "quality": "QTILE_PHONE_MIRROR_QUALITY",
    "wifi_quality": "QTILE_PHONE_MIRROR_WIFI_QUALITY",
    "audio": "QTILE_PHONE_MIRROR_AUDIO",
    "restart_on_switch": "QTILE_PHONE_MIRROR_RESTART_ON_SWITCH",
    "pair_ttl": "QTILE_PHONE_MIRROR_PAIR_TTL",
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
    "wifi_quality": "low",
    "audio": "false",
    "restart_on_switch": "true",
    "pair_ttl": "180",
}

_TRUE = {"1", "true", "yes", "on"}
_USER_BLOCKED = {Reason.UNAUTHORIZED, Reason.OFFLINE}

RunFn = Callable[..., Awaitable[runner.Result]]
SpawnFn = Callable[[Sequence[str]], Awaitable[Any]]
OpenQrFn = Callable[..., Awaitable[Any]]
SleepFn = Callable[[float], Awaitable[None]]

_QR_MISSING = {
    "segno": (
        "The QR library (segno) is not installed. Install it with "
        "'uv sync --extra phone'. Pairing manually instead."
    ),
    "kitty": "kitty is not available, so the QR cannot be shown. Pairing manually.",
    "runtime": (
        "XDG_RUNTIME_DIR is not set, so the QR cannot be shown. Pairing manually."
    ),
}
_DISCOVERY_FAILED = (
    "The phone was not found. Likely causes: it is on a different network than "
    "this computer, the router isolates Wi-Fi clients (AP isolation), a firewall "
    "blocks mDNS (multicast DNS), or a VPN is active. Nothing was changed on this "
    "computer. Enter the pairing details manually instead."
)
_MDNS_DOWN = (
    "Automatic discovery (mDNS) is not available. Enter the pairing details manually."
)
_MANUAL_INVALID = (
    "Invalid pairing details. Enter the host:port and the 6-digit code shown "
    "on the phone."
)
_GAVE_UP = (
    f"Could not reconnect to the phone after {MAX_ATTEMPTS} attempts. Left-click "
    "or right-click the widget, or press Mod+P, to try again."
)
_NO_CONNECT_ENTRY = (
    "Paired, but the phone's connect address was not found. Open Wireless "
    "debugging on the phone, then left-click the widget and enter the host:port "
    "shown there."
)


class SelectionCancelled(Exception):
    """The user dismissed the device selector."""


class State(Enum):
    READY = "ready"
    MIRROR = "mirror"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    PAIRING = "pairing"
    CONNECTING = "connecting"


# Where each state may go next. Staying in a state is always fine. Anything not
# listed is rejected, e.g. DISCONNECTED -> MIRROR: mirroring needs a READY device.
TRANSITIONS: dict[State, frozenset[State]] = {
    State.DISCONNECTED: frozenset(
        {State.READY, State.CONNECTING, State.PAIRING, State.ERROR}
    ),
    State.CONNECTING: frozenset(
        {State.READY, State.DISCONNECTED, State.PAIRING, State.ERROR}
    ),
    State.READY: frozenset(
        {
            State.MIRROR,
            State.DISCONNECTED,
            State.CONNECTING,
            State.PAIRING,
            State.ERROR,
        }
    ),
    State.MIRROR: frozenset({State.READY, State.DISCONNECTED, State.ERROR}),
    State.PAIRING: frozenset({State.CONNECTING, State.DISCONNECTED, State.ERROR}),
    State.ERROR: frozenset(
        {State.DISCONNECTED, State.READY, State.CONNECTING, State.PAIRING}
    ),
}
HISTORY = 32  # accepted transitions kept for debugging and tests


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
        open_qr: OpenQrFn = qr.open_window,
        sleep: SleepFn = asyncio.sleep,
        state_file: Path | None = None,
    ) -> None:
        self._sleep = sleep
        self._state_file = state_file
        self._remembered: RememberedDevice | None = None
        self._remembered_loaded = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._attempts = 0  # reconnect attempts used in this disconnect
        self._exhausted = False  # all attempts spent: wait for a user action
        # The backoff only starts for a phone that was ready in THIS session and
        # dropped; at startup there is a single silent attempt, nothing more.
        self._session_ready = False
        self._startup_tried = False
        self._startup_task: asyncio.Task[None] | None = None
        self._seen_ready: list[str] = []  # serials the last probe found usable
        self._open_qr = open_qr
        self._pairing: PairingSession | None = None
        self._qr_window: Any = None  # the QR window while a pairing waits
        self._pair_cancel = asyncio.Event()
        self._run = run
        self._spawn = spawn
        self._which = which
        self._clock = clock
        self._state = State.DISCONNECTED
        self.history: deque[State] = deque(maxlen=HISTORY)
        self._lock = asyncio.Lock()
        self._defaults: dict[str, str] = dict(DEFAULTS)
        self._session: dict[str, str] = {}
        self._process: Any = None
        self._stop_requested: Any = None
        self._watcher: asyncio.Task[None] | None = None
        self._stopping: Any = None  # a terminated scrcpy that has not exited yet
        self._reaper: asyncio.Task[None] | None = None
        self._mirror_serial = ""  # the device the running scrcpy is attached to
        self._generation = 0  # bumped by every action that changes the state
        self._labels: dict[str, str] = {}
        self._serial = ""  # device picked in the selector, kept for the session
        self._last_refresh: float | None = None
        self._listeners: list[Callable[[], None]] = []

    # -- state -------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @state.setter
    def state(self, new: State) -> None:
        old = self._state
        if new is old:
            return
        if new not in TRANSITIONS[old]:
            logger.warning(
                "PhoneMirror: invalid state change %s -> %s rejected",
                old.name,
                new.name,
            )
            return
        logger.info("PhoneMirror: state %s -> %s", old.name, new.name)
        self._state = new
        self.history.append(new)

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

    def _preset(self, serial: str) -> tuple[str, str]:
        """The preset for this device and why; Wi-Fi has its own, lighter one."""
        if is_wireless_serial(serial):
            wanted = normalize_quality(self.resolve("wifi_quality"), default="low")
            return wanted, "wifi transport, QTILE_PHONE_MIRROR_WIFI_QUALITY"
        wanted = normalize_quality(self.resolve("quality"))
        return wanted, "usb transport, QTILE_PHONE_MIRROR_QUALITY"

    def _options(self, serial: str) -> MirrorOptions:
        return MirrorOptions(
            quality=self._preset(serial)[0],
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
        if listener not in self._listeners:
            self._listeners.append(listener)

    def detach(self, listener: Callable[[], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)
        if not self._listeners:
            self.shutdown()

    def _touch(self) -> None:
        """Invalidate any probe that started before this state change."""
        self._generation += 1

    def _changed(self) -> None:
        self._touch()
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

    def _fail(self, reason: Reason, *, typed_code: bool = False) -> None:
        text = message_for(reason, typed_code=typed_code)
        self.notify("error", NOTIFY_TITLE, text, urgent=True)

    # -- state -------------------------------------------------------------

    def is_mirroring(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _missing_binaries(self) -> bool:
        return self._which(self.resolve("adb_path")) is None or (
            self._which(self.resolve("scrcpy_path")) is None
        )

    async def _exec(
        self,
        argv: Sequence[str],
        timeout: float = 5.0,
        input_text: str | None = None,
    ) -> tuple[int, str]:
        """Run an allowlisted command; never raises, returns (rc, text)."""
        extra = {} if input_text is None else {"input_text": input_text}
        try:
            result = await self._run(argv, timeout=timeout, **extra)
        except FileNotFoundError:
            return 127, "command not found"
        except (OSError, runner.ForbiddenCommand) as exc:
            logger.warning("PhoneMirror: command failed: %s", exc)
            return 1, str(exc)
        if result.timed_out:
            return 1, "timed out"
        return result.rc, f"{result.stdout}\n{result.stderr}"

    async def _list_devices(
        self, *, update_labels: bool = True
    ) -> tuple[list[Device], str, bool]:
        """Devices, the raw text, and whether adb actually answered."""
        rc, text = await self._exec(
            build_devices_argv(self.resolve("adb_path"), long=True)
        )
        devices = parse_devices(text)
        if update_labels:
            self._labels = {d.serial: device_label(d) for d in devices}
        return devices, text, rc == 0

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

    async def _find_device(self) -> tuple[str | None, str]:
        """Pick the target serial: env, remembered, the only one, or ask."""
        devices, text, answered = await self._list_devices()
        expected = self.resolve("device")
        if expected:
            return ready_device(devices, expected), text
        ready = ready_devices(devices)
        if self._serial and self._serial not in {d.serial for d in ready}:
            if not answered:
                # adb timed out or failed: that says nothing about the device.
                return self._serial, text
            logger.info("PhoneMirror: device %s is gone, resolving again", self._serial)
            self._serial = ""
        if self._serial:
            return self._serial, text
        if len(ready) <= 1:
            return (ready[0].serial if ready else None), text
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

    async def _connect_user(self) -> str:
        """Connect the wireless target for an action and show CONNECTING meanwhile."""
        target = self.resolve("wireless_target")
        if not target and self.remembered is None:
            return ""
        self.state = State.CONNECTING
        self._changed()
        if not target:
            _ok, text = await self._connect_remembered()
            return text
        text = await self._connect()
        await self._remember_target(target, text)
        return text

    async def refresh(self) -> State:
        if self._lock.locked():
            return self.state
        now = self._clock()
        if self._last_refresh is not None and now - self._last_refresh < REFRESH_TTL:
            return self.state
        self._last_refresh = now
        generation = self._generation
        try:
            state = await self._probe()
        except Exception:
            logger.exception("PhoneMirror: refresh failed")
            state = State.DISCONNECTED
        if generation != self._generation:
            return self.state  # an action ran meanwhile; this answer is stale
        self.state = state
        try:
            self._watch_remembered(state)
        except Exception:
            logger.exception("PhoneMirror: reconnect scheduling failed")
        return state

    async def _probe(self) -> State:
        """Read-only status check: it never changes the remembered device."""
        self._seen_ready = []
        if self._missing_binaries():
            return State.ERROR
        if self.is_mirroring():
            return State.MIRROR
        expected = self.resolve("device")
        devices, _text, _ok = await self._list_devices(update_labels=False)
        serial = ready_device(devices, expected)
        if serial is None and self.resolve("wireless_target"):
            await self._connect()
            devices, _text, _ok = await self._list_devices(update_labels=False)
            serial = ready_device(devices, expected)
        self._seen_ready = [d.serial for d in ready_devices(devices)]
        return State.READY if serial else State.DISCONNECTED

    # -- remembered device and reconnect -----------------------------------

    def _store_path(self) -> Path:
        return self._state_file if self._state_file is not None else state_path()

    @property
    def remembered(self) -> RememberedDevice | None:
        if not self._remembered_loaded:
            self._remembered_loaded = True
            self._remembered = load(self._store_path())
        return self._remembered

    def _remember(self, instance: str, address: str) -> None:
        """Keep the phone by its mDNS identity; the port is only the last one seen."""
        if not valid_identity(instance, address):
            logger.warning(
                "PhoneMirror: %r at %r is not a valid identity, not remembered",
                plog.sanitize(instance),
                plog.sanitize(address),
            )
            return
        previous = self.remembered
        paired_at = (
            previous.paired_at
            if previous is not None
            and previous.service_name == instance
            and previous.paired_at
            else datetime.now(UTC).isoformat(timespec="seconds")
        )
        device = RememberedDevice(
            instance, address, serial_from_instance(instance), paired_at
        )
        if device == previous:
            return
        self._remembered = device
        self._remembered_loaded = True
        save(self._store_path(), device)
        logger.info("PhoneMirror: remembered %s at %s", instance, address)

    async def _remember_target(self, target: str, text: str) -> None:
        """After a wireless connect, find the phone's mDNS identity and keep it."""
        if not connect_succeeded(0, text):
            return
        host = target.rpartition(":")[0].strip("[]")
        _rc, out = await self._exec(
            build_mdns_argv(self.resolve("adb_path"), "services")
        )
        entry = find_connect(parse_mdns(out), host)
        if entry is None:
            logger.info("PhoneMirror: %s has no mDNS identity, not remembered", target)
            return
        self._remember(entry.instance, target)

    async def _connect_remembered(self) -> tuple[bool, str]:
        """`adb connect` to the remembered phone's current endpoint (mDNS first)."""
        device = self.remembered
        if device is None:
            return False, ""
        adb = self.resolve("adb_path")
        _rc, out = await self._exec(build_mdns_argv(adb, "services"))
        entry = find_connect_by_instance(parse_mdns(out), device.service_name)
        address = entry.address if entry is not None else device.last_address
        logger.info(
            "PhoneMirror: connecting to %s at %s (%s)",
            device.service_name,
            address,
            "found by mDNS" if entry is not None else "last known address",
        )
        rc, text = await self._exec(build_connect_argv(adb, address))
        ok = connect_succeeded(rc, text)
        if ok:
            self._remember(device.service_name, address)
        else:
            logger.info("PhoneMirror: connect to %s failed: %s", address, text.strip())
        return ok, text

    def _reset_reconnect(self) -> None:
        """A user action or a connected phone: forget the spent attempts."""
        self._attempts = 0
        self._exhausted = False
        task = self._reconnect_task
        self._reconnect_task = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def _watch_remembered(self, state: State) -> None:
        """After a probe: reset on a ready phone, retry only after a real drop."""
        device = self.remembered
        if device is None or state is State.ERROR:
            return
        if any(device.matches(serial) for serial in self._seen_ready):
            came_back = self._attempts > 0
            self._session_ready = True
            self._startup_tried = True
            self._reset_reconnect()  # the only place a spent budget is refilled
            if came_back:
                self.notify("status", NOTIFY_TITLE, "Reconnected to the phone.")
            return
        if state is State.MIRROR or self.resolve("wireless_target"):
            return
        if self._session_ready:
            self._schedule_reconnect()
        elif not self._startup_tried:
            self._startup_tried = True
            self._startup_task = create_task(self._startup_attempt())

    async def _startup_attempt(self) -> None:
        """The one silent try at login: no timer, no notification, no new state."""
        if self._lock.locked():
            return
        async with self._lock:
            if self.remembered is None or self.is_mirroring():
                return
            logger.info("PhoneMirror: startup: one silent attempt to reach the phone")
            try:
                await self._connect_remembered()
            except Exception:
                logger.exception("PhoneMirror: startup attempt failed")
        self._changed()

    def _schedule_reconnect(self) -> None:
        """One reconnect timer at a time; none once the attempts are spent."""
        task = self._reconnect_task
        if self._exhausted or (task is not None and not task.done()):
            return
        self._reconnect_task = create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        try:
            while True:
                delay = backoff_delay(self._attempts)
                if delay is None:
                    self._give_up()
                    return
                await self._sleep(delay)
                if self._lock.locked():
                    logger.info("PhoneMirror: busy, reconnect attempt postponed")
                    continue
                if await self._reconnect_attempt():
                    return
        finally:
            if self._reconnect_task is asyncio.current_task():
                self._reconnect_task = None

    def _give_up(self) -> None:
        self._exhausted = True
        logger.info("PhoneMirror: reconnect gave up after %d attempts", self._attempts)
        self.notify("error", NOTIFY_TITLE, _GAVE_UP)

    async def _reconnect_attempt(self) -> bool:
        """One attempt under the lock; True when the loop should stop.

        It never stops on its own after a connect: only a probe that sees the
        device ready (`_watch_remembered`) or a user action ends the loop.
        """
        async with self._lock:
            if self.remembered is None or self.is_mirroring():
                return True
            self._attempts += 1
            before = self.state
            self.state = State.CONNECTING
            self._changed()
            generation = self._generation
            logger.info(
                "PhoneMirror: reconnect attempt %d of %d", self._attempts, MAX_ATTEMPTS
            )
            try:
                ok, _text = await self._connect_remembered()
            except Exception:
                logger.exception("PhoneMirror: reconnect attempt failed")
                ok = False
            if generation == self._generation:  # else an action ran: stale answer
                self.state = (
                    State.DISCONNECTED if before is State.CONNECTING else before
                )
            if ok:
                # `adb connect` printing "connected" proves nothing: the device can
                # still be offline or unauthorized. The next probe decides.
                logger.info("PhoneMirror: adb connected, waiting for the device")
            self._changed()
            return False

    # -- actions -----------------------------------------------------------

    def _is_stopping(self) -> bool:
        return self._stopping is not None and self._stopping.returncode is None

    async def toggle(self) -> None:
        if self._is_stopping():
            logger.info("PhoneMirror: previous scrcpy is still stopping, click ignored")
            return
        if self._lock.locked():
            logger.info("PhoneMirror: busy, click ignored")
            return
        async with self._lock:
            self._touch()
            self._reset_reconnect()
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
        self._touch()
        self._stop_requested = proc
        self._process = None
        self._mirror_serial = ""
        self.state = State.READY
        try:
            if proc.returncode is None:
                proc.terminate()
        except ProcessLookupError:
            return
        if proc.returncode is None:
            self._reap_later(proc)

    def _reap_later(self, proc: Any) -> None:
        """Give a terminated scrcpy a grace period, then kill it, off the loop."""
        self._stopping = proc
        coro = self._reap(proc)
        try:
            self._reaper = create_task(coro)
        except RuntimeError:  # no running loop (shutting down): nothing to wait on
            coro.close()
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            self._stopping = None

    async def _reap(self, proc: Any) -> None:
        try:
            await asyncio.wait_for(proc.wait(), STOP_GRACE)
        except TimeoutError:
            logger.warning("PhoneMirror: scrcpy ignored SIGTERM, killing it")
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
        finally:
            if self._stopping is proc:
                self._stopping = None

    async def _settled(self) -> None:
        """Wait until a process that is being stopped has really exited."""
        reaper = self._reaper
        if reaper is not None and not reaper.done():
            await asyncio.shield(reaper)

    def shutdown(self) -> None:
        self._reset_reconnect()
        self._abort_pairing()
        self._stop()

    def _abort_pairing(self) -> None:
        """Cancel a waiting pairing and drop its QR now (the secret must not linger)."""
        if self._pairing is not None:
            self._pair_cancel.set()
        window = self._qr_window
        if window is not None:
            self._qr_window = None
            window.abort()

    async def reconnect(self) -> None:
        """Reconnect the wireless target, then pick the device again."""
        if self._lock.locked():
            logger.info("PhoneMirror: busy, click ignored")
            return
        async with self._lock:
            self._touch()
            self._reset_reconnect()
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
                    await self._connect_user()
                serial = await self._ensure_ready()
                if serial is not None:
                    restarted = False
                    if was_mirroring and to_bool(self.resolve("restart_on_switch")):
                        logger.info("PhoneMirror: restarting mirroring on %s", serial)
                        await self._settled()
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

    # -- wireless pairing ---------------------------------------------------

    def pairing_countdown(self) -> str:
        """`mm:ss` left on the pairing code, or an empty string."""
        return self._pairing.countdown(self._clock()) if self._pairing else ""

    def cancel_pairing(self) -> bool:
        """Stop a pairing in its waiting phase; False if none is waiting."""
        if self._pairing is None:
            return False
        logger.info("PhoneMirror: pairing cancelled")
        self._pair_cancel.set()
        return True

    async def pair_toggle(self) -> None:
        """The key: cancel a waiting pairing, otherwise start one."""
        if not self.cancel_pairing():
            await self.pair()

    async def pair(self) -> None:
        """Pair over Wi-Fi with a QR code, or by hand when that is not possible."""
        if self.is_mirroring():
            self.notify("pair", NOTIFY_TITLE, "Stop mirroring before pairing a phone.")
            return
        if self._lock.locked():
            logger.info("PhoneMirror: busy, pairing ignored")
            return
        async with self._lock:
            self._touch()
            self._reset_reconnect()
            self._pair_cancel = asyncio.Event()
            try:
                await self._pair_flow()
            except Exception:
                logger.exception("PhoneMirror: pairing failed")
                self.state = State.DISCONNECTED
                self._fail(Reason.UNKNOWN)
            finally:
                self._pairing = None
                if self.state in (State.PAIRING, State.CONNECTING):
                    # cancelled mid-way (task cancelled, shutdown): leave no half state
                    self.state = State.DISCONNECTED
                self._changed()

    def _pair_ttl(self) -> float:
        raw = self.resolve("pair_ttl")
        try:
            wanted = float(raw)
        except ValueError:
            wanted = math.nan
        if not math.isfinite(wanted):  # "nan" and "inf" parse as floats
            logger.warning("PhoneMirror: bad pairing expiry %r, using the default", raw)
            return DEFAULT_TTL
        ttl = min(max(wanted, PAIR_TTL_MIN), PAIR_TTL_MAX)
        if ttl != wanted:
            logger.info(
                "PhoneMirror: pairing expiry %.0f s clamped to %.0f", wanted, ttl
            )
        return ttl

    async def _pair_flow(self) -> None:
        adb = self.resolve("adb_path")
        if self._which(adb) is None:
            self.state = State.ERROR
            self._fail(Reason.MISSING_BINARY)
            return
        _rc, text = await self._exec(build_mdns_argv(adb, "check"))
        if map_failure(text) is Reason.MDNS_UNAVAILABLE:
            self.notify("pair", NOTIFY_TITLE, _MDNS_DOWN)
            await self._manual_pair()
            return
        session = new_session(self._clock(), self._pair_ttl())
        try:
            window = await self._open_qr(
                session.payload, spawn=self._spawn, which=self._which
            )
        except qr.QrUnavailable as exc:
            logger.info("PhoneMirror: QR unavailable (%s)", exc.missing)
            self.notify("pair", NOTIFY_TITLE, _QR_MISSING.get(exc.missing, str(exc)))
            await self._manual_pair()
            return
        self._pairing = session
        self._qr_window = window
        self.state = State.PAIRING
        self._changed()
        left = session.countdown(self._clock())
        self.notify(
            "pair",
            NOTIFY_TITLE,
            "Scan the QR with the phone: Developer options, Wireless debugging, "
            f"Pair device with QR code. It expires in {left}. "
            "Press the same key again to cancel.",
        )
        try:
            entry, outcome = await self._await_pairing(session, window)
        finally:
            self._qr_window = None
            await window.close()
            self._pairing = None
        if outcome == "cancelled":
            self.state = State.DISCONNECTED
            self.notify("pair", NOTIFY_TITLE, "Pairing cancelled.")
        elif entry is None:
            self.state = State.DISCONNECTED
            self.notify("error", NOTIFY_TITLE, _DISCOVERY_FAILED, urgent=True)
            await self._manual_pair()
        elif not session.consume(self._clock()):
            self.state = State.DISCONNECTED
            self._fail(Reason.EXPIRED)
        else:
            await self._pair_and_connect(entry.address, session.password)

    async def _pause(self, seconds: float) -> None:
        """Sleep, waking early when the pairing is cancelled."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._pair_cancel.wait(), seconds)

    async def _await_pairing(
        self, session: PairingSession, window: Any
    ) -> tuple[MdnsEntry | None, str]:
        """Poll mDNS until the phone shows up under our name, or give up."""
        adb = self.resolve("adb_path")
        while True:
            if self._pair_cancel.is_set() or not window.is_open():
                return None, "cancelled"
            if session.expired(self._clock()):
                return None, "expired"
            _rc, text = await self._exec(build_mdns_argv(adb, "services"))
            entry = find_pairing(parse_mdns(text), session.name)
            if entry is not None:
                return entry, "found"
            self._changed()  # moves the countdown in the bar
            await self._pause(PAIR_POLL_INTERVAL)

    async def _manual_pair(self) -> None:
        """Ask for the phone's pairing address and code, then pair."""
        try:
            result = await self._run(build_zenity_pair_argv(), timeout=120)
        except (OSError, runner.ForbiddenCommand):
            logger.warning("PhoneMirror: zenity unavailable for manual pairing")
            self.notify(
                "error",
                NOTIFY_TITLE,
                "The manual pairing prompt (zenity) is not available.",
                urgent=True,
            )
            return
        if result.rc != 0:
            logger.info("PhoneMirror: manual pairing cancelled")
            return
        parsed = parse_zenity_pair(result.stdout)
        if parsed is None:
            self.notify("error", NOTIFY_TITLE, _MANUAL_INVALID, urgent=True)
            return
        endpoint, code = parsed
        await self._pair_and_connect(endpoint, code, typed_code=True)

    async def _pair_and_connect(
        self, endpoint: str, secret: str, *, typed_code: bool = False
    ) -> None:
        adb = self.resolve("adb_path")
        self.state = State.CONNECTING
        self._changed()
        # The code goes through stdin so it never shows up in argv or `ps`.
        rc, text = await self._exec(
            build_pair_argv(adb, endpoint),
            timeout=PAIR_TIMEOUT,
            input_text=f"{secret}\n",
        )
        text = redact(text, secret)
        for line in plog.sanitized_lines(text):
            logger.info("PhoneMirror: adb pair %s: %s", endpoint, line)
        if rc != 0 or "successfully paired" not in text.lower():
            reason = map_failure(text)
            if reason is Reason.UNREACHABLE:  # a timeout while pairing
                reason = Reason.PAIR_CONNECTION_LOST
            elif reason is Reason.UNKNOWN:
                reason = Reason.PAIR_REJECTED
            self.state = State.DISCONNECTED
            self._fail(reason, typed_code=typed_code)
            return
        host = endpoint.rpartition(":")[0].strip("[]")
        found = await self._find_connect_entry(host)
        address = found.address if found is not None else None
        if found is None or address is None:
            self.state = State.DISCONNECTED
            self.notify("error", NOTIFY_TITLE, _NO_CONNECT_ENTRY, urgent=True)
            return
        rc, text = await self._exec(build_connect_argv(adb, address))
        if connect_succeeded(rc, text):
            self._remember(found.instance, address)
            self._session_ready = True
            self.state = State.READY
            self.notify("pair", NOTIFY_TITLE, f"Paired and connected to {address}.")
            return
        self.state = State.DISCONNECTED
        self._fail(map_failure(text))

    async def _find_connect_entry(self, host: str) -> MdnsEntry | None:
        """The phone's connect entry: same host, whatever the instance name."""
        adb = self.resolve("adb_path")
        deadline = self._clock() + CONNECT_WAIT
        while True:
            _rc, text = await self._exec(build_mdns_argv(adb, "services"))
            entry = find_connect(parse_mdns(text), host)
            if entry is not None:
                return entry
            if self._clock() >= deadline:
                return None
            await asyncio.sleep(PAIR_POLL_INTERVAL)

    def _volume_step(self) -> int:
        raw = self.resolve("volume_step") or str(VOLUME_STEP_DEFAULT)
        try:
            wanted = int(raw)
        except ValueError:
            logger.warning("PhoneMirror: bad volume step %r, using the default", raw)
            return VOLUME_STEP_DEFAULT
        step = min(max(wanted, VOLUME_STEP_MIN), VOLUME_STEP_MAX)
        if step != wanted:
            logger.info("PhoneMirror: volume step %d clamped to %d", wanted, step)
        return step

    async def _serial_is_gone(self, serial: str) -> bool:
        """True only when adb answered and the device is really not listed."""
        devices, _text, answered = await self._list_devices()
        return answered and serial not in {d.serial for d in ready_devices(devices)}

    async def volume(self, *, up: bool, _retry: bool = True) -> None:
        step = self._volume_step()
        mirrored = self._mirror_serial if self.is_mirroring() else ""
        serial = self.resolve("device") or mirrored or self._serial
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
            if rc == 0:
                continue
            if (
                index == 0
                and _retry
                and serial == self._serial
                and await self._serial_is_gone(serial)
            ):
                logger.info("PhoneMirror: device %s is gone, resolving again", serial)
                self._serial = ""
                await self.volume(up=up, _retry=False)
            return  # a failing command would only fail again

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
            text += await self._connect_user()
            serial, more = await self._find_device()
            text += more
        reason = map_failure(text)
        if serial is None and reason not in _USER_BLOCKED and await self._prompt():
            text += await self._connect_user()
            serial, more = await self._find_device()
            text += more
            reason = map_failure(text)
        if serial is not None:
            self.state = State.READY
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
        tail: deque[str] = deque(maxlen=TAIL_LINES)  # this process only
        self._process = proc
        self._mirror_serial = serial
        self.state = State.MIRROR
        self._touch()
        known = self.remembered
        if known is not None and known.matches(serial):
            self._session_ready = True
        preset, why = self._preset(serial)
        logger.info(
            "PhoneMirror: mirror start serial=%s transport=%s preset=%s (%s)",
            serial,
            transport_of(serial),
            preset,
            why,
        )
        self._watcher = create_task(self._watch(proc, tail, serial))
        self.notify("status", NOTIFY_TITLE, "Mirroring started.")

    async def _pump(self, stream: Any, label: str, tail: deque[str]) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            text = plog.sanitize(line.decode(errors="replace").rstrip())
            if text:
                logger.info("scrcpy %s: %s", label, text)
                tail.append(text)

    async def _watch(self, proc: Any, tail: deque[str], serial: str) -> None:
        await asyncio.gather(
            self._pump(proc.stdout, "stdout", tail),
            self._pump(proc.stderr, "stderr", tail),
        )
        rc = await proc.wait()
        requested = self._stop_requested is proc
        logger.info(
            "PhoneMirror: mirror stop serial=%s transport=%s rc=%s (%s)",
            serial,
            transport_of(serial),
            rc,
            "requested" if requested else "unexpected" if rc != 0 else "ended",
        )
        if self._process is proc:
            self._process = None
            self._mirror_serial = ""
            self.state = State.READY
        if rc != 0 and self._stop_requested is not proc:
            reason = map_failure("\n".join(tail), rc)
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
        plog.setup()
        qr.remove_stale_png()  # a crash can leave the one-time QR behind
        _controller = PhoneController()
    return _controller


def phone_pair_toggle(qtile: Any = None) -> None:
    """`lazy.function` target: start a pairing, or cancel the one in progress."""
    del qtile
    create_task(get_controller().pair_toggle())


def phone_toggle(qtile: Any = None) -> None:
    """`lazy.function` target: synchronous, schedules the async toggle."""
    del qtile
    create_task(get_controller().toggle())
