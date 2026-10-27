"""CI gate over pytest's JUnit XML: an exact test count and nothing skipped.

pytest exits 0 when a test is skipped or when a test file is deleted, so a
suite can silently shrink while the job stays green. This gate reads the report
written by ``pytest --junitxml`` and fails when:

* the report is missing, malformed or has no ``<testsuite>``;
* any test failed or errored;
* any test was skipped, xfailed or xpassed (they are listed by id);
* the number of passed tests differs from the expected one
  (``EXPECTED_TESTS`` in the CI workflow), in either direction.

Everything is counted from the ``<testcase>`` elements, never from the
``tests``/``skipped`` attributes of a suite. An unexpected pass is only visible
in the report when pytest runs with ``xfail_strict`` (otherwise it is written
as a plain pass), which ``pyproject.toml`` sets.

Standard library only, so it runs before and after ``uv sync`` alike.

Usage: ``python tools/check_junit.py REPORT.xml --expected-tests N``
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

XFAIL_TYPE = "pytest.xfail"
XPASS_PREFIX = "[XPASS(strict)]"


class ReportError(Exception):
    """The report cannot be used as evidence of a test run."""


class Report(NamedTuple):
    """What the ``<testcase>`` elements of a report say, one id per problem."""

    passed: int
    failures: list[str]
    errors: list[str]
    skipped: list[str]
    xfailed: list[str]
    xpassed: list[str]


def _case_id(case: ET.Element) -> str:
    """Return ``classname.name``, leaving out an empty classname (module level)."""
    return ".".join(p for p in (case.get("classname"), case.get("name")) if p)


def read_report(path: Path) -> Report:
    """Classify every ``<testcase>`` of the JUnit report at ``path``."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ReportError(f"cannot read {path}: {' '.join(str(exc).split())}") from exc
    if root.tag != "testsuite" and next(root.iter("testsuite"), None) is None:
        raise ReportError(f"no <testsuite> in {path}")

    passed = 0
    failures: list[str] = []
    errors: list[str] = []
    skipped: list[str] = []
    xfailed: list[str] = []
    xpassed: list[str] = []
    for case in root.iter("testcase"):
        ident = _case_id(case)
        clean = True
        for child in case:
            if child.tag == "skipped":
                (xfailed if child.get("type") == XFAIL_TYPE else skipped).append(ident)
            elif child.tag == "failure":
                is_xpass = child.get("message", "").startswith(XPASS_PREFIX)
                (xpassed if is_xpass else failures).append(ident)
            elif child.tag == "error":
                errors.append(ident)
            else:
                continue
            clean = False
        passed += clean
    return Report(passed, failures, errors, skipped, xfailed, xpassed)


def _problems(report: Report) -> list[str]:
    """Return one ``N label: ids`` entry per kind of problem the report has."""
    kinds = (
        ("failed", report.failures),
        ("errored", report.errors),
        ("skipped", report.skipped),
        ("xfailed", report.xfailed),
        ("xpassed", report.xpassed),
    )
    return [f"{len(ids)} {label}: {', '.join(ids)}" for label, ids in kinds if ids]


def _fail(reason: str) -> int:
    print(f"check_junit: FAIL: {reason}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("report", type=Path, help="JUnit XML written by pytest")
    parser.add_argument(
        "--expected-tests",
        type=int,
        required=True,
        help="exact number of tests that must pass",
    )
    args = parser.parse_args(argv)

    try:
        report = read_report(args.report)
    except ReportError as exc:
        return _fail(str(exc))

    problems = _problems(report)
    if problems:
        reason = "; ".join(problems)
        if report.skipped or report.xfailed or report.xpassed:
            reason += "; skips, xfails and xpasses are not allowed"
        return _fail(reason)

    passed, expected = report.passed, args.expected_tests
    if passed != expected:
        advice = (
            "a test was deleted or stopped being collected; if that is intended, "
            if passed < expected
            else "tests were added; "
        )
        return _fail(
            f"{passed} tests passed, expected {expected}; {advice}"
            f"set EXPECTED_TESTS to {passed} in .github/workflows/ci.yml "
            "in the same commit"
        )

    print(f"{passed} tests passed (expected {expected}), no skip, xfail or xpass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
