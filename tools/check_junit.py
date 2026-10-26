"""CI gate over pytest's JUnit XML: a test floor and zero skips.

pytest exits 0 when a test is skipped or when a test file is deleted, so a
suite can silently shrink while the job stays green. This gate reads the report
written by ``pytest --junitxml`` and fails when:

* the report has no ``<testsuite>``;
* any test failed or errored;
* any test was skipped (they are listed by id);
* fewer tests passed than the floor (``MIN_TESTS`` in the CI workflow).

Standard library only, so it runs before and after ``uv sync`` alike.

Usage: ``python tools/check_junit.py REPORT.xml --min-tests N``
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple


class Counts(NamedTuple):
    """Totals summed over every ``<testsuite>`` of a report."""

    tests: int
    failures: int
    errors: int
    skipped: int


def _suites(report: Path) -> list[ET.Element]:
    """Return every ``<testsuite>``; the root is a ``<testsuites>`` or a suite."""
    root = ET.parse(report).getroot()
    if root.tag == "testsuite":
        return [root]
    return list(root.iter("testsuite"))


def summarize(report: Path) -> Counts:
    """Sum the counters of every ``<testsuite>`` in ``report``."""
    totals = Counts(0, 0, 0, 0)
    for suite in _suites(report):
        totals = Counts(
            totals.tests + int(suite.get("tests", 0)),
            totals.failures + int(suite.get("failures", 0)),
            totals.errors + int(suite.get("errors", 0)),
            totals.skipped + int(suite.get("skipped", 0)),
        )
    return totals


def _skipped_ids(report: Path) -> list[str]:
    """Return ``classname.name`` of every testcase that carries ``<skipped>``."""
    return [
        f"{case.get('classname', '')}.{case.get('name', '')}"
        for suite in _suites(report)
        for case in suite.iter("testcase")
        if case.find("skipped") is not None
    ]


def _fail(reason: str) -> int:
    print(f"check_junit: FAIL: {reason}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="JUnit XML written by pytest")
    parser.add_argument(
        "--min-tests", type=int, required=True, help="floor for the passed count"
    )
    args = parser.parse_args(argv)

    if not _suites(args.report):
        return _fail(f"no <testsuite> in {args.report}")

    counts = summarize(args.report)
    if counts.failures or counts.errors:
        broken = [
            f"{count} {label}(s)"
            for count, label in ((counts.failures, "failure"), (counts.errors, "error"))
            if count
        ]
        return _fail(" and ".join(broken))
    if counts.skipped:
        ids = ", ".join(_skipped_ids(args.report))
        return _fail(f"{counts.skipped} skipped test(s) are not allowed: {ids}")

    passed = counts.tests
    if passed < args.min_tests:
        return _fail(
            f"{passed} tests passed, floor {args.min_tests}; "
            "a test was deleted or stopped being collected"
        )

    print(f"{passed} tests, 0 skipped (floor {args.min_tests})")
    if passed > args.min_tests:
        print(
            f"check_junit: raise MIN_TESTS to {passed} in the commit that added tests"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
