"""Logger of this feature, with an optional dedicated rotating log file.

qtile usually runs at WARNING, so INFO lines (scrcpy output, mirror start and
stop) never reach `qtile.log`. `setup()` gives this feature's logger its own
file at INFO; warnings and errors are still forwarded to qtile's handlers.
"""

import logging
import os
import re
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOGGER_NAME = "libqtile.phone_mirror"
LOG_FILE = "phone_mirror.log"
MAX_BYTES = 1_000_000
BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)s %(message)s"

logger = logging.getLogger(LOGGER_NAME)

# Output of adb and scrcpy is data from outside: it must not carry terminal
# escape codes or fake log lines into the file.
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_ESCAPES = {"\r": "\\r", "\n": "\\n"}


def sanitize(text: str) -> str:
    """Make control characters visible (tab is kept): `\\x1b`, `\\r`, `\\n`."""
    return _CONTROL.sub(
        lambda match: _ESCAPES.get(match.group(), f"\\x{ord(match.group()):02x}"),
        text,
    )


def sanitized_lines(text: str) -> list[str]:
    """The non-empty lines of some output, each one sanitized."""
    return [sanitize(line) for line in text.splitlines() if line.strip()]


_FILE_MARK = "_phone_mirror_file"


class _PrivateRotatingHandler(RotatingFileHandler):
    """A rotating log that is only readable by the user, rotated files included.

    Rotation renames the live file (keeping its mode) and reopens a fresh one
    through `_open`, so creating every file 0600 here covers all of them.
    """

    def _open(self) -> Any:
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.fchmod(fd, 0o600)  # an older, looser file keeps its mode otherwise
        return os.fdopen(fd, self.mode, encoding=self.encoding, errors=self.errors)


class _Forward(logging.Handler):
    """Pass WARNING and above on to the handlers qtile set up."""

    def __init__(self, target: logging.Logger) -> None:
        super().__init__(level=logging.WARNING)
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        self._target.callHandlers(record)


def log_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_STATE_HOME", "").strip()
    if not base or not os.path.isabs(base):
        home = env.get("HOME", "").strip() or str(Path.home())
        base = os.path.join(home, ".local", "state")
    return Path(base) / "qtile" / LOG_FILE


def setup(
    target: logging.Logger | None = None, path: Path | None = None
) -> Path | None:
    """Attach the rotating file handler once; None if the file cannot be opened."""
    log = logger if target is None else target
    for handler in log.handlers:
        if getattr(handler, _FILE_MARK, False):
            return Path(getattr(handler, "baseFilename", "")) or None
    where = log_path() if path is None else path
    try:
        where.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        handler = _PrivateRotatingHandler(
            where, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
    except OSError as exc:
        log.warning("PhoneMirror: no dedicated log file (%s)", exc)
        return None
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(FORMAT))
    setattr(handler, _FILE_MARK, True)
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    if log.parent is not None and log.propagate:
        log.addHandler(_Forward(log.parent))
        log.propagate = False
    return where
