"""Logger of this feature, with an optional dedicated rotating log file.

qtile usually runs at WARNING, so INFO lines (scrcpy output, mirror start and
stop) never reach `qtile.log`. `setup()` gives this feature's logger its own
file at INFO; warnings and errors are still forwarded to qtile's handlers.
"""

import logging
import os
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "libqtile.phone_mirror"
LOG_FILE = "phone_mirror.log"
MAX_BYTES = 1_000_000
BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)s %(message)s"

logger = logging.getLogger(LOGGER_NAME)

_FILE_MARK = "_phone_mirror_file"


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
        handler = RotatingFileHandler(
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
