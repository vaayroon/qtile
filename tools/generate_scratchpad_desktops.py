"""Write the rofi launchers for the scratchpad registry.

Loads ``scratchpads.toml`` and ``scratchpads.local.toml`` the way Qtile does
and syncs one ``qtile-scratchpad-<name>.desktop`` per entry into the target
directory (see ``utils.desktop_entries``). ``install.sh`` runs it. Qtile
refreshes the launchers on every start and config reload when it runs from
the runtime clone; run this tool to refresh them without Qtile.

Usage: ``.venv/bin/python tools/generate_scratchpad_desktops.py [TARGET_DIR]``

``TARGET_DIR`` defaults to ``$XDG_DATA_HOME/applications``, or
``~/.local/share/applications`` when ``XDG_DATA_HOME`` is unset or relative.
"""

import argparse
import logging
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from utils.desktop_entries import (  # noqa: E402
    TOGGLE_SCRIPT,
    default_target_dir,
    sync_desktop_entries,
)
from utils.scratchpads import load_scratchpads  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target_dir", nargs="?", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.WARNING)

    target_dir = args.target_dir or default_target_dir()
    report = sync_desktop_entries(load_scratchpads(), target_dir, TOGGLE_SCRIPT)
    for label, names in (
        ("written", report.written),
        ("unchanged", report.unchanged),
        ("removed", report.removed),
        ("skipped", report.skipped),
    ):
        if names:
            print(f"{label}: {', '.join(names)}")
    print(f"rofi launchers in {target_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
