"""Keep the phone mirror tests away from the real state directory."""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _phone_state_isolation(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Phone tests get their own XDG_STATE_HOME and a clean feature logger."""
    if not request.module.__name__.rsplit(".", 1)[-1].startswith("test_phone"):
        yield
        return
    from src.widgets import phone_mirror_log as plog

    state = tmp_path_factory.mktemp("state")
    mp = pytest.MonkeyPatch()
    mp.setenv("XDG_STATE_HOME", str(state))
    saved = (list(plog.logger.handlers), plog.logger.level, plog.logger.propagate)
    try:
        yield
    finally:
        for handler in list(plog.logger.handlers):
            if handler not in saved[0]:
                plog.logger.removeHandler(handler)
                handler.close()
        plog.logger.setLevel(saved[1])
        plog.logger.propagate = saved[2]
        mp.undo()
