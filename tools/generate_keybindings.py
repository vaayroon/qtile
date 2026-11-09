"""Generate the README "Keybindings" tables from each binding's ``desc``.

Imports the config's key modules, renders ``modules.keys.cheatsheet_sections``
with ``utils.cheatsheet.to_markdown`` and rewrites the block between the
``BEGIN``/``END GENERATED KEYBINDINGS`` markers in README.md. Only the shipped
``scratchpads.toml`` and ``launchers.toml`` are read, so a personal
``scratchpads.local.toml`` or ``launchers.local.toml`` never leaks into the
README.

Usage: ``.venv/bin/python tools/generate_keybindings.py [--check] [README]``

``--check`` writes nothing and exits 1 when the README is out of date (CI
runs it through ``tests/test_keybindings_doc.py``). Exit code 2 means the
markers are missing or duplicated.
"""

import argparse
import functools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

BEGIN = "<!-- BEGIN GENERATED KEYBINDINGS: tools/generate_keybindings.py -->"
END = "<!-- END GENERATED KEYBINDINGS -->"


def _use_shipped_registry_only() -> None:
    """Point `load_scratchpads` and `load_launchers` at the shipped
    `scratchpads.toml` and `launchers.toml` alone. Must run before `modules`
    is imported, since its modules bind the names on import."""
    import utils.launchers as launchers
    import utils.scratchpads as scratchpads

    scratchpads.load_scratchpads = functools.cache(
        lambda: scratchpads.load_scratchpads_from(ROOT / "scratchpads.toml", None)
    )
    launchers.load_launchers = functools.cache(
        lambda mod: launchers.load_launchers_from(
            ROOT / "launchers.toml", None, mod=mod
        )
    )


def render() -> str:
    _use_shipped_registry_only()
    from modules.keys import cheatsheet_sections
    from utils.cheatsheet import build_sections, to_markdown

    return to_markdown(build_sections(cheatsheet_sections()))


def replace_block(text: str, body: str) -> str:
    """`text` with everything between the markers replaced by `body`.
    Exactly one marker pair is required, BEGIN first."""
    start = text.find(BEGIN)
    end = text.find(END, start + len(BEGIN)) if start != -1 else -1
    if start == -1 or end == -1:
        raise ValueError(f"README markers not found: {BEGIN!r} ... {END!r}")
    if text.count(BEGIN) > 1 or text.count(END) > 1:
        raise ValueError(f"README markers appear more than once: {BEGIN!r}")
    head = text[: start + len(BEGIN)]
    return f"{head}\n\n{body}\n{text[end:]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if out of date")
    parser.add_argument("readme", nargs="?", type=Path, default=ROOT / "README.md")
    args = parser.parse_args(argv)

    current = args.readme.read_text(encoding="utf-8")
    try:
        updated = replace_block(current, render())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if updated == current:
        print(f"{args.readme}: keybindings up to date")
        return 0
    if args.check:
        print(
            f"{args.readme}: keybindings out of date; run "
            "`.venv/bin/python tools/generate_keybindings.py`",
            file=sys.stderr,
        )
        return 1
    args.readme.write_text(updated, encoding="utf-8")
    print(f"{args.readme}: keybindings updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
