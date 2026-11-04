import ast
import logging
from pathlib import Path

import pytest
from src.utils import env
from src.utils.env import env_flag

NAME = "QTILE_TEST_FLAG"


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NAME, raising=False)


def test_module_has_no_libqtile_import() -> None:
    tree = ast.parse(Path(env.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "libqtile" not in roots


@pytest.mark.parametrize("default", [True, False])
def test_unset_returns_default(default: bool) -> None:
    assert env_flag(NAME, default) is default


@pytest.mark.parametrize("raw", ["", "   "])
@pytest.mark.parametrize("default", [True, False])
def test_empty_returns_default(
    monkeypatch: pytest.MonkeyPatch, raw: str, default: bool
) -> None:
    monkeypatch.setenv(NAME, raw)

    assert env_flag(NAME, default) is default


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on", " true "])
def test_true_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(NAME, raw)

    assert env_flag(NAME, False) is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "No", "off", " off "])
def test_false_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(NAME, raw)

    assert env_flag(NAME, True) is False


@pytest.mark.parametrize("default", [True, False])
def test_unknown_value_returns_default_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    default: bool,
) -> None:
    monkeypatch.setenv(NAME, "flase")

    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert env_flag(NAME, default) is default

    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert record.name == "libqtile"
    message = record.getMessage()
    assert NAME in message
    assert "'flase'" in message
    assert message.endswith(f"using the default {'true' if default else 'false'}")


@pytest.mark.parametrize("raw", ["", "true", "off"])
def test_known_values_do_not_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    monkeypatch.setenv(NAME, raw)

    with caplog.at_level(logging.WARNING, logger="libqtile"):
        env_flag(NAME, True)

    assert caplog.records == []
