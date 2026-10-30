"""Check the relative links in the README and the docs.

A renamed file or heading silently breaks the links that point at it. These
tests resolve every relative link in ``README.md`` and ``docs/**/*.md``: the
target file must exist, and a ``#fragment`` must match a heading of the target
Markdown file, slugged the way GitHub does. External (``scheme:``) links and
anything inside code are skipped.
"""

import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]

# A backtick fence cannot have a backtick after it on the same line (CommonMark),
# so ```cmd``` on one line is inline code, not the start of a block.
FENCE = re.compile(r"^\s*(`{3,}(?=[^`]*$)|~{3,})")
INLINE_CODE = re.compile(r"(`+).+?\1")
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
LINK_TEXT = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
HEADING = re.compile(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _outside_fences(text: str) -> list[str]:
    """Return the lines of ``text`` that are not inside a fenced code block."""
    lines = []
    fence = ""
    for line in text.splitlines():
        match = FENCE.match(line)
        marker = match.group(1) if match else ""
        if fence:
            # Only a run of the same character, at least as long, closes it.
            if marker[:1] == fence[0] and len(marker) >= len(fence):
                fence = ""
        elif marker:
            fence = marker
        else:
            lines.append(line)
    return lines


def _slug(heading: str) -> str:
    """Return GitHub's anchor for a heading text (without the duplicate suffix)."""
    text = LINK_TEXT.sub(r"\1", heading).replace("`", "").lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    """Return every heading anchor of a Markdown file, duplicates suffixed."""
    seen: Counter[str] = Counter()
    anchors = set()
    for line in _outside_fences(path.read_text(encoding="utf-8")):
        heading = HEADING.match(line)
        if heading:
            slug = _slug(heading.group(1))
            anchors.add(f"{slug}-{seen[slug]}" if seen[slug] else slug)
            seen[slug] += 1
    return anchors


def _broken_links(path: Path) -> list[str]:
    """Return the relative links of ``path`` whose file or anchor is missing."""
    broken = []
    for line in _outside_fences(path.read_text(encoding="utf-8")):
        for target in LINK.findall(INLINE_CODE.sub("", line)):
            if SCHEME.match(target):
                continue
            file_part, _, fragment = target.partition("#")
            resolved = (path.parent / file_part).resolve() if file_part else path
            if not resolved.exists():
                broken.append(f"{target}: no such file")
            elif (
                fragment
                and resolved.suffix == ".md"
                and fragment not in _anchors(resolved)
            ):
                broken.append(f"{target}: no such heading")
    return broken


def test_the_slug_follows_github_rules() -> None:
    assert _slug("Qtile — Personal Tiling Window Manager Config") == (
        "qtile--personal-tiling-window-manager-config"
    )
    assert _slug("Media, audio & brightness") == "media-audio--brightness"
    assert _slug("Qt, tuned to KDE and LXQt") == "qt-tuned-to-kde-and-lxqt"
    assert _slug("The `mod + s` chord") == "the-mod--s-chord"
    assert _slug("See [the README](README.md)") == "see-the-readme"


def test_duplicate_headings_get_a_numbered_anchor(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("# Monitors\n\n## Monitors\n\n### Monitors\n", encoding="utf-8")

    assert _anchors(doc) == {"monitors", "monitors-1", "monitors-2"}


def test_headings_inside_code_blocks_are_not_anchors(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("# Real\n\n```toml\n# not a heading\n```\n", encoding="utf-8")

    assert _anchors(doc) == {"real"}


def test_triple_backtick_inline_code_does_not_open_a_block(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("```touch a && touch b```\n\n# After\n", encoding="utf-8")

    assert _anchors(doc) == {"after"}


def test_broken_files_and_anchors_are_reported(tmp_path: Path) -> None:
    (tmp_path / "other.md").write_text("# Present\n", encoding="utf-8")
    doc = tmp_path / "doc.md"
    doc.write_text(
        "# Top\n\n"
        "[ok](other.md#present) [ok](#top) [ok](other.md)\n"
        "[bad](missing.md) [bad](other.md#absent) [bad](#nowhere)\n",
        encoding="utf-8",
    )

    assert _broken_links(doc) == [
        "missing.md: no such file",
        "other.md#absent: no such heading",
        "#nowhere: no such heading",
    ]


def test_external_links_and_code_are_skipped(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "[web](https://example.com/missing.md) [mail](mailto:a@b.c)\n"
        "`[inline](missing.md)`\n\n"
        "```md\n[fenced](missing.md)\n```\n",
        encoding="utf-8",
    )

    assert _broken_links(doc) == []


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_resolves(path: Path) -> None:
    assert _broken_links(path) == []
