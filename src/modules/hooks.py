from libqtile import hook
from libqtile.log_utils import logger

from utils.startup import run_autostart, run_steps, set_root_background
from utils.system import apply_best_effort_layout


def _apply_layout() -> None:
    applied, source = apply_best_effort_layout()
    logger.info("Display layout applied=%s source=%s", applied, source)


@hook.subscribe.startup_once
def start_once() -> None:
    # Each step is isolated: one failing never skips the others.
    run_steps(
        [
            ("layout", _apply_layout),
            ("root background", set_root_background),
            ("autostart", run_autostart),
        ]
    )
