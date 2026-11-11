"""Show the pairing QR in a floating kitty window.

segno is a runtime dependency, but it is still imported lazily so this module
imports fine if it is missing; the pairing flow then falls back to manual
entry. The PNG lives in a private directory under $XDG_RUNTIME_DIR, is readable
only by the user and is deleted as soon as the window closes. kitty is started
through the allowlisted runner with one exact argv template, so the secret is
never in a command line.
"""

import asyncio
import contextlib
import importlib
import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from . import phone_mirror_runner as runner

CLOSE_GRACE = 3.0  # seconds between SIGTERM and SIGKILL for the QR window
QR_SCALE = 8
QR_BORDER = 4

SpawnFn = Callable[[Sequence[str]], Awaitable[Any]]
WhichFn = Callable[[str], str | None]


class QrUnavailable(Exception):
    """The QR cannot be shown; `missing` says what is lacking."""

    def __init__(self, missing: str) -> None:
        super().__init__(f"QR unavailable: {missing}")
        self.missing = missing  # "segno", "kitty" or "runtime"


def _load_segno() -> Any:
    try:
        return importlib.import_module("segno")
    except ImportError as exc:
        raise QrUnavailable("segno") from exc


def render_png(payload: str) -> Path:
    """Write the QR as a private PNG and return its path."""
    segno = _load_segno()
    target = runner.qr_image_path()
    if target is None:
        raise QrUnavailable("runtime")
    path = Path(target)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        code = segno.make(payload, error="m")
        # Create it private from the start: never write first and chmod later.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o600)  # an older, looser file keeps its mode
            code.save(out, kind="png", scale=QR_SCALE, border=QR_BORDER)
    except BaseException:
        remove_png(path)  # never leave a partial file that holds the secret
        raise
    return path


def remove_png(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def remove_stale_png() -> bool:
    """Delete a QR left by a crash: the phone does not enforce our expiry."""
    target = runner.qr_image_path()
    if target is None:
        return False
    path = Path(target)
    existed = path.exists()
    remove_png(path)
    return existed


def build_kitty_argv(png: Path) -> list[str]:
    return [
        "kitty",
        "--class",
        runner.KITTY_QR_CLASS,
        "--title",
        runner.KITTY_QR_TITLE,
        "kitty",
        "+kitten",
        "icat",
        "--hold",
        str(png),
    ]


class QrWindow:
    """The running kitty window and the PNG it shows."""

    def __init__(self, process: Any, path: Path) -> None:
        self._process = process
        self.path = path

    def is_open(self) -> bool:
        return bool(self._process.returncode is None)

    async def close(self) -> None:
        """End the window if it is still up, and always delete the PNG."""
        try:
            if self.is_open():
                with contextlib.suppress(ProcessLookupError):
                    self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), CLOSE_GRACE)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        self._process.kill()
                    await self._process.wait()
        finally:
            remove_png(self.path)


async def open_window(payload: str, *, spawn: SpawnFn, which: WhichFn) -> QrWindow:
    """Render the payload and show it; raises QrUnavailable when it cannot."""
    _load_segno()  # fail before anything touches the disk
    if which("kitty") is None:
        raise QrUnavailable("kitty")
    path = render_png(payload)
    try:
        process = await spawn(build_kitty_argv(path))
    except (OSError, runner.ForbiddenCommand) as exc:
        remove_png(path)
        raise QrUnavailable("kitty") from exc
    except BaseException:
        remove_png(path)
        raise
    return QrWindow(process, path)
