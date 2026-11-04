"""Typed readers for ``QTILE_*`` environment variables.

``settings.py`` exports ``.env`` into ``os.environ`` at import time, so these
readers see values from ``.env`` and from the process environment alike. They
read the environment on every call; nothing is cached.

This module MUST NOT import ``libqtile``, so it stays testable without it.
"""

import logging
import os

# Same logger object qtile configures, without importing libqtile.
logger = logging.getLogger("libqtile")

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def env_flag(name: str, default: bool) -> bool:
    """Boolean value of the environment variable `name`.

    Matching is case-insensitive and ignores surrounding whitespace. An unset or
    empty variable returns `default`. An unrecognised value also returns
    `default` and logs a warning, so a typo never silently flips the flag.
    """
    raw = os.environ.get(name, "")
    value = raw.strip().lower()
    if not value:
        return default
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    logger.warning(
        "env: %s=%r is not a boolean (use one of %s); using the default %s",
        name,
        raw,
        "/".join(sorted(TRUE_VALUES | FALSE_VALUES)),
        "true" if default else "false",
    )
    return default
