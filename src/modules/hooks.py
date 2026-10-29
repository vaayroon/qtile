from libqtile import hook
from libqtile.log_utils import logger

from utils.desktop_entries import refresh_desktop_entries
from utils.scratchpads import load_scratchpads
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


def _refresh_launchers() -> None:
    report = refresh_desktop_entries(load_scratchpads())
    if report is not None and (report.written or report.removed):
        logger.info(
            "Rofi launchers written=%s removed=%s", report.written, report.removed
        )


@hook.subscribe.startup
def on_startup() -> None:
    # `startup` fires on start, restart and every config reload, so an edited
    # registry reaches rofi without rerunning the generator tool.
    run_steps([("rofi launchers", _refresh_launchers)])
