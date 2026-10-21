"""Never-raise helpers for Qtile startup side effects.

Blocking and detached subprocess helpers plus the thin startup steps built on
them (root background, autostart script). This module MUST NOT import
``libqtile``: Qtile wiring lives in ``modules.hooks``.

Never-crash contract: every public function catches every exception and logs
it, so a failing startup step can never take Qtile down or skip later steps.
"""

import logging
import os
import subprocess
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import IO

# Same logger object qtile configures, without importing libqtile.
logger = logging.getLogger("libqtile")

_REPO_ROOT = Path(__file__).resolve().parents[2]  # src/utils/startup.py -> repo
DEFAULT_AUTOSTART = _REPO_ROOT / "autostart.sh"
AUTOSTART_ENV = "QTILE_AUTOSTART_PATH"


def run_command(cmd: Sequence[str], *, label: str, timeout: float = 5.0) -> bool:
    """Run `cmd` to completion; True only on exit status 0. Never raises.

    Blocks the caller (Qtile's event loop), hence the timeout.
    """
    try:
        proc = subprocess.run(
            list(cmd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",  # stray non-UTF-8 output must not fail the step
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("startup: %s: command not found: %s", label, cmd[0])
        return False
    except subprocess.TimeoutExpired:
        logger.warning("startup: %s: timed out after %ss", label, timeout)
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("startup: %s: could not run %s: %s", label, cmd[0], exc)
        return False
    except Exception:
        logger.exception("startup: %s: unexpected error", label)
        return False
    if proc.returncode != 0:
        logger.warning(
            "startup: %s: exited with returncode %s: %s",
            label,
            proc.returncode,
            proc.stderr.strip(),
        )
        return False
    logger.debug("startup: %s: ok", label)
    return True


def spawn_detached(
    cmd: Sequence[str], *, log_path: Path | None, label: str
) -> subprocess.Popen[bytes] | None:
    """Start `cmd` without waiting for it; the Popen handle, or None on failure.

    The child gets its own session and, when `log_path` is usable, stdout and
    stderr are written to it (truncated first, so it holds one session). If the
    log cannot be opened (including an invalid path) the child inherits our
    stdio instead. Never raises.
    """
    log_file = None
    try:
        if log_path is not None:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = open(log_path, "wb")
            except (OSError, ValueError) as exc:  # ValueError: e.g. NUL in path
                logger.warning(
                    "startup: %s: cannot open log %s, inheriting stdio: %s",
                    label,
                    log_path,
                    exc,
                )
        return _popen(cmd, log_file, label)
    except Exception:
        logger.exception("startup: %s: unexpected error", label)
        return None
    finally:
        if log_file is not None:
            log_file.close()


def _popen(
    cmd: Sequence[str], log_file: IO[bytes] | None, label: str
) -> subprocess.Popen[bytes] | None:
    try:
        proc = subprocess.Popen(
            list(cmd),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT if log_file else None,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("startup: %s: could not start %s: %s", label, cmd[0], exc)
        return None
    except Exception:
        logger.exception("startup: %s: unexpected error", label)
        return None
    logger.debug("startup: %s: started pid %s", label, proc.pid)
    return proc


def resolve_autostart_path() -> Path:
    """Autostart script: `$QTILE_AUTOSTART_PATH` if set, else the repo's own.

    The environment is read at call time: `settings` copies `.env` into it
    during config import, which happens before the startup hook fires.
    """
    value = os.environ.get(AUTOSTART_ENV, "").strip()
    return Path(value).expanduser() if value else DEFAULT_AUTOSTART


def autostart_log_path() -> Path:
    """`$XDG_DATA_HOME/qtile/autostart.log`, defaulting to `~/.local/share`."""
    data_home = Path(os.environ.get("XDG_DATA_HOME", "").strip())
    # The XDG spec says relative values must be ignored.
    if not data_home.is_absolute():
        data_home = Path.home() / ".local" / "share"
    return data_home / "qtile" / "autostart.log"


def run_autostart() -> bool:
    """Spawn the autostart script, detached, with its output in a log file."""
    try:
        # Absolute so Popen never falls back to a PATH lookup for a bare name,
        # and so the checks below and the spawn refer to the same file.
        path = resolve_autostart_path().absolute()
        if not path.is_file():
            logger.warning("startup: autostart: script not found: %s", path)
            return False
        if not os.access(path, os.X_OK):
            logger.warning("startup: autostart: script not executable: %s", path)
            return False
        proc = spawn_detached(
            [str(path)], log_path=autostart_log_path(), label="autostart"
        )
        return proc is not None
    except Exception:
        logger.exception("startup: autostart: unexpected error")
        return False


def set_root_background() -> bool:
    """Paint the X root window black."""
    return run_command(["xsetroot", "-solid", "#000000"], label="root background")


def run_steps(steps: Iterable[tuple[str, Callable[[], object]]]) -> None:
    """Run labelled steps in order; one failing never skips the others."""
    for label, step in steps:
        try:
            step()
        except Exception:
            logger.exception("startup: step %r failed", label)
