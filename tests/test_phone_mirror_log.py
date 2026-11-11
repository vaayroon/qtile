"""The dedicated phone mirror log: its own file, INFO and up, rotated."""

import logging
import os
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from src.widgets import phone_mirror, phone_mirror_controller, phone_mirror_state
from src.widgets import phone_mirror_log as plog


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture()
def family() -> tuple[logging.Logger, logging.Logger, Capture]:
    """A throwaway parent (qtile's logger, at WARNING) and its phone child."""
    parent = logging.getLogger("test_phone_log_parent")
    parent.handlers.clear()
    parent.setLevel(logging.WARNING)
    parent.propagate = False
    seen = Capture()
    parent.addHandler(seen)
    child = logging.getLogger("test_phone_log_parent.phone")
    child.handlers.clear()
    child.setLevel(logging.NOTSET)
    child.propagate = True
    return parent, child, seen


def test_the_log_lives_in_the_state_directory() -> None:
    path = plog.log_path({"XDG_STATE_HOME": "/var/state"})
    assert path == Path("/var/state/qtile/phone_mirror.log")


def test_the_default_location_is_under_home_local_state() -> None:
    path = plog.log_path({"HOME": "/home/someone"})
    assert path == Path("/home/someone/.local/state/qtile/phone_mirror.log")


def test_the_feature_modules_share_one_logger() -> None:
    assert plog.logger.name == "libqtile.phone_mirror"
    assert phone_mirror_controller.logger is plog.logger
    assert phone_mirror.logger is plog.logger
    assert phone_mirror_state.logger is plog.logger


def test_setup_attaches_a_rotating_handler_of_about_1_mb_and_3_backups(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    _parent, child, _seen = family
    where = tmp_path / "qtile" / "phone_mirror.log"

    assert plog.setup(child, where) == where

    handlers = [h for h in child.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 1_000_000
    assert handlers[0].backupCount == 3
    assert handlers[0].level == logging.INFO
    assert stat.S_IMODE(where.parent.stat().st_mode) == 0o700


def test_info_reaches_the_file_even_when_qtile_runs_at_warning(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    parent, child, _seen = family
    where = tmp_path / "phone_mirror.log"
    assert parent.getEffectiveLevel() == logging.WARNING
    plog.setup(child, where)

    child.info("scrcpy stderr: INFO: Renderer: opengl")
    child.debug("not recorded")

    text = where.read_text()
    assert "INFO scrcpy stderr: INFO: Renderer: opengl" in text
    assert "not recorded" not in text


def test_every_line_has_a_timestamp(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    _parent, child, _seen = family
    where = tmp_path / "phone_mirror.log"
    plog.setup(child, where)

    child.info("hello")

    assert where.read_text().startswith("20")  # asctime: YYYY-MM-DD HH:MM:SS,mmm


def test_setup_is_idempotent(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    _parent, child, _seen = family
    where = tmp_path / "phone_mirror.log"
    plog.setup(child, where)
    plog.setup(child, where)

    child.info("once")

    assert where.read_text().count("once") == 1
    assert len([h for h in child.handlers if isinstance(h, RotatingFileHandler)]) == 1


def test_warnings_still_go_to_the_qtile_handlers_but_info_does_not(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    _parent, child, seen = family
    plog.setup(child, tmp_path / "phone_mirror.log")

    child.info("chatty scrcpy line")
    child.warning("something is wrong")

    assert [r.getMessage() for r in seen.records] == ["something is wrong"]


def test_setup_touches_this_logger_only(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    parent, child, _seen = family
    root_handlers = list(logging.getLogger().handlers)
    root_level = logging.getLogger().level
    parent_level = parent.level

    plog.setup(child, tmp_path / "phone_mirror.log")

    assert logging.getLogger().handlers == root_handlers
    assert logging.getLogger().level == root_level
    assert parent.level == parent_level
    assert not any(isinstance(h, RotatingFileHandler) for h in parent.handlers)


def test_an_unwritable_location_is_not_fatal(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    _parent, child, seen = family
    blocker = tmp_path / "file"
    blocker.write_text("x")

    assert plog.setup(child, blocker / "sub" / "phone_mirror.log") is None

    assert not any(isinstance(h, RotatingFileHandler) for h in child.handlers)
    assert any("no dedicated log file" in r.getMessage() for r in seen.records)


def test_the_file_rotates_and_keeps_three_backups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: tuple[logging.Logger, logging.Logger, Capture],
) -> None:
    _parent, child, _seen = family
    monkeypatch.setattr(plog, "MAX_BYTES", 400)
    where = tmp_path / "phone_mirror.log"
    plog.setup(child, where)

    for index in range(100):
        child.info("line %03d %s", index, "x" * 40)

    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [
        "phone_mirror.log",
        "phone_mirror.log.1",
        "phone_mirror.log.2",
        "phone_mirror.log.3",
    ]


def test_the_controller_singleton_sets_the_log_up_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(plog, "setup", lambda *_a, **_k: calls.append(1))
    monkeypatch.setattr(phone_mirror_controller, "_controller", None)

    first = phone_mirror_controller.get_controller()
    second = phone_mirror_controller.get_controller()

    assert first is second
    assert calls == [1]


def test_the_tests_run_with_their_own_state_directory() -> None:
    home = Path.home() / ".local" / "state"
    assert not Path(os.environ["XDG_STATE_HOME"]).is_relative_to(home)
    assert plog.log_path().is_relative_to(Path(os.environ["XDG_STATE_HOME"]))


def test_a_real_setup_does_not_leak_into_the_next_test(
    tmp_path: Path,
) -> None:
    plog.setup(path=tmp_path / "phone_mirror.log")
    assert plog.logger.propagate is False


def test_the_previous_real_setup_was_undone() -> None:
    assert plog.logger.propagate is True
    assert not any(isinstance(h, RotatingFileHandler) for h in plog.logger.handlers)


# --- file mode (review fix) -----------------------------------------------------------


def test_the_log_file_is_private(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    _parent, child, _seen = family
    where = tmp_path / "phone_mirror.log"
    old_umask = os.umask(0o022)
    try:
        plog.setup(child, where)
        child.info("hello")
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(where.stat().st_mode) == 0o600


def test_an_older_log_with_loose_permissions_is_made_private(
    tmp_path: Path, family: tuple[logging.Logger, logging.Logger, Capture]
) -> None:
    _parent, child, _seen = family
    where = tmp_path / "phone_mirror.log"
    where.write_text("old line\n")
    where.chmod(0o644)

    plog.setup(child, where)
    child.info("new line")

    assert stat.S_IMODE(where.stat().st_mode) == 0o600
    assert where.read_text().startswith("old line\n")  # appended, not truncated


def test_rotated_files_are_private_too(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: tuple[logging.Logger, logging.Logger, Capture],
) -> None:
    _parent, child, _seen = family
    monkeypatch.setattr(plog, "MAX_BYTES", 400)
    where = tmp_path / "phone_mirror.log"
    old_umask = os.umask(0o022)
    try:
        plog.setup(child, where)
        for index in range(100):
            child.info("line %03d %s", index, "x" * 40)
    finally:
        os.umask(old_umask)

    files = sorted(tmp_path.glob("phone_mirror.log*"))
    assert len(files) == 4
    assert {stat.S_IMODE(f.stat().st_mode) for f in files} == {0o600}


# --- log injection (review fix) -----------------------------------------------------


def test_escape_codes_and_carriage_returns_are_made_visible() -> None:
    assert plog.sanitize("a\x1b[2Jb\rc") == "a\\x1b[2Jb\\rc"


def test_tab_is_kept_and_plain_text_is_untouched() -> None:
    assert plog.sanitize("a\tb plain: text") == "a\tb plain: text"


@pytest.mark.parametrize("char", ["\x00", "\x07", "\x08", "\x0b", "\x0c", "\x7f"])
def test_other_control_characters_are_escaped(char: str) -> None:
    cleaned = plog.sanitize(f"x{char}y")
    assert char not in cleaned
    assert cleaned == f"x\\x{ord(char):02x}y"


def test_a_newline_inside_a_message_cannot_forge_a_log_line() -> None:
    assert plog.sanitize("ok\nINFO forged") == "ok\\nINFO forged"


def test_sanitized_lines_gives_one_clean_line_per_line_of_output() -> None:
    text = "first\r\nsecond \x1b[31mred\x1b[0m\n\nthird\n"

    assert plog.sanitized_lines(text) == [
        "first",
        "second \\x1b[31mred\\x1b[0m",
        "third",
    ]


def test_sanitized_lines_of_nothing_is_empty() -> None:
    assert plog.sanitized_lines("  \n \r\n") == []
