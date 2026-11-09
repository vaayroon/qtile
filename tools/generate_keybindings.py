"""Generate the README "Keybindings" tables from each binding's ``desc``.

Imports the config's key modules, renders ``modules.keys.cheatsheet_sections``
with ``utils.cheatsheet.to_markdown`` and rewrites the block between the
``BEGIN``/``END GENERATED KEYBINDINGS`` markers in README.md. Only the shipped
``scratchpads.toml`` is read, so a personal ``scratchpads.local.toml`` never
leaks into the README.

Usage: ``.venv/bin/python tools/generate_keybindings.py [--check] [README]``

``--check`` writes nothing and exits 1 when the README is out of date (CI
runs it through ``tests/test_keybindings_doc.py``). Exit code 2 means the
markers are missing.
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
    """Point `load_scratchpads` at `scratchpads.toml` alone. Must run before
    `modules` is imported, since its modules bind the name on import."""
    import utils.scratchpads as scratchpads

    shipped = functools.cache(
        lambda: scratchpads.load_scratchpads_from(ROOT / "scratchpads.toml", None)
    )
    scratchpads.load_scratchpads = shipped


def render() -> str:
    _use_shipped_registry_only()
    from modules.keys import cheatsheet_sections
    from utils.cheatsheet import build_sections, to_markdown

    return to_markdown(build_sections(cheatsheet_sections()))


def replace_block(text: str, body: str) -> str:
    """`text` with everything between the markers replaced by `body`."""
    start = text.find(BEGIN)
    end = text.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"README markers not found: {BEGIN!r} ... {END!r}")
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
