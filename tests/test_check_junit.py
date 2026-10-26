"""Unit tests for ``tools/check_junit.py``, the CI gate over pytest's JUnit XML.

The gate is the only thing that notices a test that silently stopped running
(``importorskip``, a deleted file), because pytest still exits 0 in that case.
A gate that always passes is the classic failure, so each test below feeds it a
report that must be rejected for one specific reason and asserts that reason.
"""

from pathlib import Path

import pytest
from tools.check_junit import Counts, main, summarize

FLOOR = 288


def _suite(tests: int, failures: int = 0, errors: int = 0, skipped: int = 0) -> str:
    """Return a ``<testsuite>`` element the way pytest writes it."""
    cases = "".join(
        f'<testcase classname="tests.test_x" name="test_{i}" time="0.001"/>'
        for i in range(tests - failures - errors - skipped)
    )
    cases += "".join(
        f'<testcase classname="tests.test_skipped" name="test_skipped_{i}">'
        '<skipped type="pytest.skip" message="unconditional skip"/></testcase>'
        for i in range(skipped)
    )
    cases += "".join(
        f'<testcase classname="tests.test_broken" name="test_failed_{i}">'
        '<failure message="assert False"/></testcase>'
        for i in range(failures)
    )
    cases += "".join(
        f'<testcase classname="tests.test_broken" name="test_errored_{i}">'
        '<error message="boom"/></testcase>'
        for i in range(errors)
    )
    return (
        f'<testsuite name="pytest" errors="{errors}" failures="{failures}" '
        f'skipped="{skipped}" tests="{tests}">{cases}</testsuite>'
    )


def _report(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pytest.xml"
    path.write_text(f'<?xml version="1.0" encoding="utf-8"?>{body}')
    return path


def _run(report: Path, floor: int = FLOOR) -> int:
    return main([str(report), "--min-tests", str(floor)])


def test_passes_when_the_passed_count_equals_the_floor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, f"<testsuites>{_suite(FLOOR)}</testsuites>")

    assert _run(report) == 0

    assert "288 tests, 0 skipped (floor 288)" in capsys.readouterr().out


def test_asks_to_raise_the_floor_when_there_are_more_tests_than_the_floor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, _suite(FLOOR + 5))

    assert _run(report) == 0

    out = capsys.readouterr().out
    assert "293 tests, 0 skipped (floor 288)" in out
    assert "MIN_TESTS" in out


def test_fails_when_a_test_disappeared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, _suite(FLOOR - 1))

    assert _run(report) == 1

    err = capsys.readouterr().err
    assert "287" in err
    assert "floor 288" in err


def test_fails_on_any_skip_and_names_the_skipped_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Headroom above the floor, so the skip itself is what fails the gate.
    report = _report(tmp_path, _suite(FLOOR + 10, skipped=1))

    assert _run(report) == 1

    err = capsys.readouterr().err
    assert "skipped" in err
    assert "tests.test_skipped.test_skipped_0" in err


@pytest.mark.parametrize(
    ("failures", "errors", "word"),
    [(1, 0, "failure"), (0, 1, "error")],
)
def test_fails_on_a_failure_or_an_error_even_with_headroom(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failures: int,
    errors: int,
    word: str,
) -> None:
    report = _report(tmp_path, _suite(FLOOR + 10, failures=failures, errors=errors))

    assert _run(report) == 1

    err = capsys.readouterr().err
    assert word in err
    assert ("error" if word == "failure" else "failure") not in err


def test_fails_when_the_report_has_no_testsuite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, "<testsuites></testsuites>")

    assert _run(report) == 1

    assert "no <testsuite>" in capsys.readouterr().err


def test_sums_every_suite_under_a_testsuites_root(tmp_path: Path) -> None:
    body = f"<testsuites>{_suite(200)}{_suite(88, skipped=3)}</testsuites>"

    assert summarize(_report(tmp_path, body)) == Counts(
        tests=288, failures=0, errors=0, skipped=3
    )


def test_reads_a_bare_testsuite_root(tmp_path: Path) -> None:
    assert summarize(_report(tmp_path, _suite(10, failures=2, errors=1))) == Counts(
        tests=10, failures=2, errors=1, skipped=0
    )
