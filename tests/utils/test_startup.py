import ast
import logging
import subprocess
from pathlib import Path

import pytest
from src.utils import startup
from src.utils.startup import run_command, spawn_detached


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == level]


def test_module_has_no_libqtile_import() -> None:
    tree = ast.parse(Path(startup.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "libqtile" not in roots
    assert "libqtile" not in startup.__dict__


def test_logger_is_the_libqtile_logger() -> None:
    assert startup.logger is logging.getLogger("libqtile")
    assert startup.logger.name == "libqtile"


# --- run_command -------------------------------------------------------------


def test_run_command_success_returns_true_and_logs_debug(caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_command(["true"], label="probe") is True
    (record,) = _records(caplog, logging.DEBUG)
    assert record.name == "libqtile"
    assert "probe" in record.getMessage()
    assert not _records(caplog, logging.WARNING)


def test_run_command_nonzero_exit_warns_with_returncode(caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_command(["false"], label="probe") is False
    (record,) = _records(caplog, logging.WARNING)
    assert record.name == "libqtile"
    assert "probe" in record.getMessage()
    assert "returncode 1" in record.getMessage()


def test_run_command_includes_stripped_stderr_in_warning(caplog, tmp_path) -> None:
    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/sh\necho 'boom happened' >&2\nexit 3\n")
    script.chmod(0o755)
    with caplog.at_level(logging.WARNING, logger="libqtile"):
        assert run_command([str(script)], label="probe") is False
    (record,) = _records(caplog, logging.WARNING)
    assert "returncode 3" in record.getMessage()
    assert "boom happened" in record.getMessage()


def test_run_command_missing_binary_warns_not_found(caplog, tmp_path) -> None:
    missing = str(tmp_path / "no-such-binary")
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_command([missing], label="probe") is False
    (record,) = _records(caplog, logging.WARNING)
    assert "not found" in record.getMessage()
    assert missing in record.getMessage()


def test_run_command_non_executable_file_warns(caplog, tmp_path) -> None:
    script = tmp_path / "plain.txt"
    script.write_text("not a program\n")
    script.chmod(0o644)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_command([str(script)], label="probe") is False
    (record,) = _records(caplog, logging.WARNING)
    assert "probe" in record.getMessage()
    assert not _records(caplog, logging.ERROR)


def test_run_command_timeout_warns(caplog, monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="slow", timeout=5.0)

    monkeypatch.setattr(startup.subprocess, "run", fake_run)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_command(["slow"], label="probe") is False
    (record,) = _records(caplog, logging.WARNING)
    assert "probe" in record.getMessage()


def test_run_command_unexpected_exception_is_logged_not_raised(
    caplog, monkeypatch
) -> None:
    def fake_run(*_args, **_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(startup.subprocess, "run", fake_run)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_command(["x"], label="probe") is False
    (record,) = _records(caplog, logging.ERROR)
    assert record.name == "libqtile"
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


def test_run_command_passes_timeout_and_closed_stdin(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(startup.subprocess, "run", fake_run)
    assert run_command(["a", "b"], label="probe", timeout=2.5) is True
    assert seen["cmd"] == ["a", "b"]
    assert seen["timeout"] == 2.5
    assert seen["stdin"] == subprocess.DEVNULL
    assert seen["check"] is False
    assert seen["capture_output"] is True
    assert seen["text"] is True


def test_run_command_default_timeout_is_five_seconds(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(startup.subprocess, "run", fake_run)
    assert run_command(["a"], label="probe") is True
    assert seen["timeout"] == 5.0


# --- spawn_detached ----------------------------------------------------------


def _script(tmp_path: Path, body: str, name: str = "job.sh") -> Path:
    script = tmp_path / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return script


class _FakePopen:
    """Records Popen kwargs; stands in for the child handle."""

    calls: list[dict[str, object]] = []
    pid = 4242

    def __init__(self, cmd, **kwargs) -> None:
        self.cmd = cmd
        self.kwargs = kwargs
        self.stdout_closed_at_call = getattr(kwargs.get("stdout"), "closed", None)
        type(self).calls.append({"cmd": cmd, **kwargs})


@pytest.fixture
def fake_popen(monkeypatch):
    _FakePopen.calls = []
    monkeypatch.setattr(startup.subprocess, "Popen", _FakePopen)
    return _FakePopen


def test_spawn_detached_captures_stdout_and_stderr_in_log(tmp_path) -> None:
    script = _script(tmp_path, "echo to-stdout\necho to-stderr >&2")
    log = tmp_path / "out.log"
    proc = spawn_detached([str(script)], log_path=log, label="job")
    assert proc is not None
    assert proc.wait(timeout=5) == 0
    lines = log.read_text().splitlines()
    assert "to-stdout" in lines
    assert "to-stderr" in lines


def test_spawn_detached_creates_missing_parent_directories(tmp_path) -> None:
    script = _script(tmp_path, "echo hello")
    log = tmp_path / "a" / "b" / "autostart.log"
    proc = spawn_detached([str(script)], log_path=log, label="job")
    assert proc is not None
    proc.wait(timeout=5)
    assert log.read_text() == "hello\n"


def test_spawn_detached_truncates_previous_log(tmp_path) -> None:
    script = _script(tmp_path, "echo fresh")
    log = tmp_path / "out.log"
    log.write_text("stale line from the previous session\n")
    proc = spawn_detached([str(script)], log_path=log, label="job")
    assert proc is not None
    proc.wait(timeout=5)
    assert log.read_text() == "fresh\n"


def test_spawn_detached_does_not_wait_for_the_child(tmp_path) -> None:
    script = _script(tmp_path, "sleep 30")
    log = tmp_path / "out.log"
    proc = spawn_detached([str(script)], log_path=log, label="job")
    assert proc is not None
    try:
        assert proc.poll() is None  # returned while the child is still running
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_spawn_detached_popen_kwargs_and_handle_closed(tmp_path, fake_popen) -> None:
    log = tmp_path / "out.log"
    result = spawn_detached(["prog", "arg"], log_path=log, label="job")
    assert isinstance(result, _FakePopen)
    (call,) = fake_popen.calls
    assert call["cmd"] == ["prog", "arg"]
    assert call["start_new_session"] is True
    assert call["stdin"] == subprocess.DEVNULL
    assert call["stderr"] == subprocess.STDOUT
    stdout = call["stdout"]
    assert stdout is not None
    assert stdout.name == str(log)
    assert result.stdout_closed_at_call is False
    assert stdout.closed is True  # the parent's copy is closed after spawning


def test_spawn_detached_without_log_path_inherits_stdio(fake_popen) -> None:
    result = spawn_detached(["prog"], log_path=None, label="job")
    assert result is not None
    (call,) = fake_popen.calls
    assert call["stdout"] is None
    assert call["stderr"] is None
    assert call["start_new_session"] is True


def test_spawn_detached_mkdir_failure_falls_back_to_inherited_stdio(
    tmp_path, fake_popen, caplog
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    log = blocker / "qtile" / "autostart.log"
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        result = spawn_detached(["prog"], log_path=log, label="job")
    assert result is not None
    (call,) = fake_popen.calls
    assert call["stdout"] is None
    assert call["stderr"] is None
    (record,) = _records(caplog, logging.WARNING)
    assert record.name == "libqtile"
    assert str(log) in record.getMessage()


def test_spawn_detached_open_failure_falls_back_to_inherited_stdio(
    tmp_path, fake_popen, caplog
) -> None:
    log = tmp_path / "is-a-directory"
    log.mkdir()
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        result = spawn_detached(["prog"], log_path=log, label="job")
    assert result is not None
    (call,) = fake_popen.calls
    assert call["stdout"] is None
    assert call["stderr"] is None
    assert len(_records(caplog, logging.WARNING)) == 1


def test_spawn_detached_popen_oserror_returns_none_and_warns(
    tmp_path, monkeypatch, caplog
) -> None:
    seen: dict[str, object] = {}

    def fake_popen(_cmd, **kwargs):
        seen.update(kwargs)
        raise FileNotFoundError("zsh")

    monkeypatch.setattr(startup.subprocess, "Popen", fake_popen)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        result = spawn_detached(["prog"], log_path=tmp_path / "out.log", label="job")
    assert result is None
    (record,) = _records(caplog, logging.WARNING)
    assert "job" in record.getMessage()
    assert seen["stdout"].closed is True  # no leaked handle on failure


def test_spawn_detached_unexpected_exception_is_logged_not_raised(
    tmp_path, monkeypatch, caplog
) -> None:
    def fake_popen(_cmd, **_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(startup.subprocess, "Popen", fake_popen)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        result = spawn_detached(["prog"], log_path=tmp_path / "out.log", label="job")
    assert result is None
    (record,) = _records(caplog, logging.ERROR)
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
