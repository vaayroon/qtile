"""Unit tests for ``tools/check_junit.py``, the CI gate over pytest's JUnit XML.

The gate is the only thing that notices a test that silently stopped running
(``importorskip``, a deleted file), because pytest still exits 0 in that case.
A gate that always passes is the classic failure, so each test below feeds it a
report that must be rejected for one specific reason and asserts that reason.
Some reports come from a real ``pytest --junitxml`` run, so the gate is also
checked against what pytest actually writes and not only against hand-made XML.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from tools.check_junit import main, read_report

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = 288


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


def _run(report: Path, expected: int = EXPECTED) -> int:
    return main([str(report), "--expected-tests", str(expected)])


def _pytest_report(tmp_path: Path, source: str) -> Path:
    """Run a real ``pytest --junitxml`` over ``source`` and return the report."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pytest.ini").write_text("[pytest]\nxfail_strict = true\n")
    (project / "test_sample.py").write_text(source)
    report = tmp_path / "real.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        + [f"--junitxml={report}"],
        cwd=project,
        check=False,
        capture_output=True,
    )
    return report


def test_passes_when_the_passed_count_is_the_expected_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, f"<testsuites>{_suite(EXPECTED)}</testsuites>")

    assert _run(report) == 0

    assert "288 tests passed (expected 288)" in capsys.readouterr().out


def test_fails_when_a_test_disappeared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, _suite(EXPECTED - 1))

    assert _run(report) == 1

    err = capsys.readouterr().err
    assert "287 tests passed, expected 288" in err
    assert "deleted or stopped being collected" in err
    assert "EXPECTED_TESTS to 287 in .github/workflows/ci.yml" in err


def test_fails_when_tests_were_added_without_updating_the_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, _suite(EXPECTED + 5))

    assert _run(report) == 1

    err = capsys.readouterr().err
    assert "293 tests passed, expected 288" in err
    assert "EXPECTED_TESTS to 293 in .github/workflows/ci.yml" in err
    assert "same commit" in err
    assert "deleted" not in err


def test_fails_on_any_skip_and_names_the_skipped_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The count is right, so the skip itself is what fails the gate.
    report = _report(tmp_path, _suite(EXPECTED + 1, skipped=1))

    assert _run(report, EXPECTED) == 1

    err = capsys.readouterr().err
    assert "1 skipped: tests.test_skipped.test_skipped_0" in err


def test_reports_xfail_apart_from_skips(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        '<testsuite name="pytest" tests="3" skipped="2">'
        '<testcase classname="tests.t" name="test_ok"/>'
        '<testcase classname="tests.t" name="test_skip">'
        '<skipped type="pytest.skip" message="no"/></testcase>'
        '<testcase classname="tests.t" name="test_known_bug">'
        '<skipped type="pytest.xfail" message="known"/></testcase>'
        "</testsuite>"
    )

    assert _run(_report(tmp_path, body), 1) == 1

    err = capsys.readouterr().err
    assert "1 skipped: tests.t.test_skip" in err
    assert "1 xfailed: tests.t.test_known_bug" in err


def test_reports_a_strict_xpass_as_xpassed_not_as_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        '<testsuite name="pytest" tests="1" failures="1">'
        '<testcase classname="tests.t" name="test_fixed">'
        '<failure message="[XPASS(strict)] known">[XPASS(strict)] known</failure>'
        "</testcase></testsuite>"
    )

    assert _run(_report(tmp_path, body), 1) == 1

    err = capsys.readouterr().err
    assert "1 xpassed: tests.t.test_fixed" in err
    assert "failed" not in err


@pytest.mark.parametrize(
    ("failures", "errors", "expected_message", "absent"),
    [(1, 0, "1 failed", "errored"), (0, 1, "1 errored", "failed")],
)
def test_fails_on_a_failure_or_an_error_even_with_the_right_count(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failures: int,
    errors: int,
    expected_message: str,
    absent: str,
) -> None:
    report = _report(tmp_path, _suite(EXPECTED, failures=failures, errors=errors))

    assert _run(report) == 1

    err = capsys.readouterr().err
    assert expected_message in err
    assert absent not in err


def test_a_suite_without_the_skipped_attribute_still_reports_its_skips(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Counters come from the testcases, never from attributes that a report
    # may leave out or get wrong.
    body = (
        '<testsuite name="pytest"><testcase classname="tests.t" name="test_a"/>'
        '<testcase classname="tests.t" name="test_b"><skipped message="x"/>'
        "</testcase></testsuite>"
    )

    assert _run(_report(tmp_path, body), 1) == 1

    assert "1 skipped: tests.t.test_b" in capsys.readouterr().err


def test_a_module_level_skip_is_named_without_a_leading_dot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        '<testsuite name="pytest"><testcase classname="" name="test_probe">'
        '<skipped message="collection skipped"/></testcase></testsuite>'
    )

    assert _run(_report(tmp_path, body), 1) == 1

    err = capsys.readouterr().err
    assert "1 skipped: test_probe" in err


def test_fails_when_the_report_has_no_testsuite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, "<testsuites></testsuites>")

    assert _run(report) == 1

    assert "no <testsuite>" in capsys.readouterr().err


def test_a_missing_report_is_a_one_line_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path / "absent.xml") == 1

    err = capsys.readouterr().err
    assert err.startswith("check_junit: FAIL: cannot read")
    assert "absent.xml" in err
    assert len(err.splitlines()) == 1


def test_a_malformed_report_is_a_one_line_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(tmp_path, "<testsuite><testcase")

    assert _run(report) == 1

    err = capsys.readouterr().err
    assert err.startswith("check_junit: FAIL: cannot read")
    assert "Traceback" not in err
    assert len(err.splitlines()) == 1


def test_sums_every_suite_under_a_testsuites_root(tmp_path: Path) -> None:
    body = f"<testsuites>{_suite(200)}{_suite(88, skipped=3)}</testsuites>"

    report = read_report(_report(tmp_path, body))

    assert report.passed == 285
    assert len(report.skipped) == 3


def test_reads_a_bare_testsuite_root(tmp_path: Path) -> None:
    report = read_report(_report(tmp_path, _suite(10, failures=2, errors=1)))

    assert (report.passed, len(report.failures), len(report.errors)) == (7, 2, 1)


# --- Against what pytest really writes -------------------------------------------


def test_passes_a_real_pytest_report_with_only_passing_tests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _pytest_report(tmp_path, "def test_a(): pass\ndef test_b(): pass\n")

    assert _run(report, 2) == 0
    assert "2 tests passed (expected 2)" in capsys.readouterr().out

    assert _run(report, 3) == 1
    assert "2 tests passed, expected 3" in capsys.readouterr().err


def test_rejects_a_real_pytest_report_with_a_skip_and_an_xfail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = (
        "import pytest\n"
        "def test_pass(): pass\n"
        "@pytest.mark.skip(reason='later')\n"
        "def test_skip(): pass\n"
        "@pytest.mark.xfail(reason='known')\n"
        "def test_xfail(): assert False\n"
    )

    # The passed count (1) matches, so only the skip and the xfail can fail it.
    assert _run(_pytest_report(tmp_path, source), 1) == 1

    err = capsys.readouterr().err
    assert "1 skipped: test_sample.test_skip" in err
    assert "1 xfailed: test_sample.test_xfail" in err


def test_rejects_a_real_pytest_report_with_a_module_level_importorskip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # pytest exits 0 here and reports "1 skipped": the case the gate exists for.
    source = (
        "import pytest\n"
        "pytest.importorskip('a_module_that_is_not_installed')\n"
        "def test_never_collected(): pass\n"
    )

    assert _run(_pytest_report(tmp_path, source), 1) == 1

    assert "1 skipped: test_sample" in capsys.readouterr().err


def test_rejects_a_real_pytest_report_with_an_unexpected_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = (
        "import pytest\n"
        "@pytest.mark.xfail(reason='fixed since')\n"
        "def test_fixed(): pass\n"
    )

    assert _run(_pytest_report(tmp_path, source), 1) == 1

    assert "1 xpassed: test_sample.test_fixed" in capsys.readouterr().err


def test_the_suite_turns_an_unexpected_pass_into_a_failure() -> None:
    # Without xfail_strict an xpass is written as a plain pass, so the gate
    # could not tell it from a green test.
    with (ROOT / "pyproject.toml").open("rb") as fh:
        options = tomllib.load(fh)["tool"]["pytest"]["ini_options"]

    assert options["xfail_strict"] is True
