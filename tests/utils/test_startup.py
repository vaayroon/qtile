import ast
import logging
import subprocess
from pathlib import Path

import pytest
from src.utils import startup
from src.utils.startup import (
    DEFAULT_AUTOSTART,
    autostart_log_path,
    resolve_autostart_path,
    run_autostart,
    run_command,
    run_steps,
    set_root_background,
    spawn_detached,
)


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == level]


def _assert_exception_logged(
    caplog: pytest.LogCaptureFixture, exc_type: type[BaseException]
) -> logging.LogRecord:
    """Exactly one ERROR record, with the traceback of `exc_type` attached."""
    (record,) = _records(caplog, logging.ERROR)
    assert record.name == "libqtile"
    assert record.exc_info is not None
    assert record.exc_info[0] is exc_type
    return record


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


@pytest.mark.parametrize(
    ("returncode", "stderr"), [(1, ""), (3, "boom happened")], ids=["bare", "stderr"]
)
def test_run_command_nonzero_exit_warns_with_returncode_and_stderr(
    caplog, tmp_path, returncode, stderr
) -> None:
    script = tmp_path / "fail.sh"
    script.write_text(f"#!/bin/sh\necho '{stderr}' >&2\nexit {returncode}\n")
    script.chmod(0o755)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_command([str(script)], label="probe") is False
    (record,) = _records(caplog, logging.WARNING)
    assert record.name == "libqtile"
    assert "probe" in record.getMessage()
    assert f"returncode {returncode}" in record.getMessage()
    assert stderr in record.getMessage()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [(None, "not found"), (0o644, "could not run")],
    ids=["missing-binary", "non-executable-file"],
)
def test_run_command_unlaunchable_command_warns(
    caplog, tmp_path, mode, expected
) -> None:
    target = tmp_path / "program"
    if mode is not None:
        target.write_text("not a program\n")
        target.chmod(mode)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_command([str(target)], label="probe") is False
    (record,) = _records(caplog, logging.WARNING)
    assert "probe" in record.getMessage()
    assert expected in record.getMessage()
    assert str(target) in record.getMessage()
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
    _assert_exception_logged(caplog, RuntimeError)


@pytest.mark.parametrize(
    ("kwargs", "expected_timeout"),
    [({"timeout": 2.5}, 2.5), ({}, 5.0)],
    ids=["explicit", "default"],
)
def test_run_command_passes_timeout_and_closed_stdin(
    monkeypatch, kwargs, expected_timeout
) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd, **run_kwargs):
        seen["cmd"] = cmd
        seen.update(run_kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(startup.subprocess, "run", fake_run)
    assert run_command(["a", "b"], label="probe", **kwargs) is True
    assert seen["cmd"] == ["a", "b"]
    assert seen["timeout"] == expected_timeout
    assert seen["stdin"] == subprocess.DEVNULL
    assert seen["check"] is False
    assert seen["capture_output"] is True
    assert seen["text"] is True


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


def _blocked_parent(tmp_path: Path) -> Path:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    return blocker / "qtile" / "autostart.log"  # mkdir fails: NotADirectoryError


def _directory_as_file(tmp_path: Path) -> Path:
    log = tmp_path / "is-a-directory"
    log.mkdir()
    return log  # open() fails: IsADirectoryError


def _nul_byte_path(tmp_path: Path) -> Path:
    return tmp_path / "bad\0name" / "autostart.log"  # ValueError, not OSError


@pytest.mark.parametrize(
    "make_log",
    [_blocked_parent, _directory_as_file, _nul_byte_path],
    ids=["mkdir-failure", "open-failure", "nul-byte-path"],
)
def test_spawn_detached_unusable_log_falls_back_to_inherited_stdio(
    tmp_path, fake_popen, caplog, make_log
) -> None:
    log = make_log(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        result = spawn_detached(["prog"], log_path=log, label="job")
    assert result is not None
    (call,) = fake_popen.calls
    assert call["stdout"] is None
    assert call["stderr"] is None
    assert call["start_new_session"] is True
    (record,) = _records(caplog, logging.WARNING)
    assert record.name == "libqtile"
    assert "job" in record.getMessage()
    assert str(log) in record.getMessage()


def test_spawn_detached_without_log_path_inherits_stdio_quietly(
    fake_popen, caplog
) -> None:
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        result = spawn_detached(["prog"], log_path=None, label="job")
    assert result is not None
    (call,) = fake_popen.calls
    assert call["stdout"] is None
    assert call["stderr"] is None
    assert call["start_new_session"] is True
    assert not _records(caplog, logging.WARNING)  # no log requested: nothing to warn


def test_spawn_detached_unexpected_log_setup_error_is_logged_not_raised(
    tmp_path, fake_popen, monkeypatch, caplog
) -> None:
    def boom(*_args, **_kwargs) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(Path, "mkdir", boom)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        result = spawn_detached(["prog"], log_path=tmp_path / "out.log", label="job")
    assert result is None
    assert fake_popen.calls == []  # nothing was started
    _assert_exception_logged(caplog, RuntimeError)


@pytest.mark.parametrize(
    ("raised", "level", "traceback_of"),
    [
        (FileNotFoundError("zsh"), logging.WARNING, None),
        (RuntimeError("kaboom"), logging.ERROR, RuntimeError),
    ],
    ids=["oserror-warns", "unexpected-logs-exception"],
)
def test_spawn_detached_popen_failure_returns_none_and_logs(
    tmp_path, monkeypatch, caplog, raised, level, traceback_of
) -> None:
    seen: dict[str, object] = {}

    def fake_popen(_cmd, **kwargs):
        seen.update(kwargs)
        raise raised

    monkeypatch.setattr(startup.subprocess, "Popen", fake_popen)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        result = spawn_detached(["prog"], log_path=tmp_path / "out.log", label="job")
    assert result is None
    (record,) = _records(caplog, level)
    assert record.name == "libqtile"
    assert "job" in record.getMessage()
    assert (record.exc_info[0] if record.exc_info else None) is traceback_of
    assert seen["stdout"].closed is True  # no leaked handle on failure


# --- resolve_autostart_path --------------------------------------------------


def test_default_autostart_is_the_repo_script() -> None:
    repo_root = Path(startup.__file__).resolve().parents[2]
    assert DEFAULT_AUTOSTART == repo_root / "autostart.sh"
    assert DEFAULT_AUTOSTART.is_absolute()
    assert DEFAULT_AUTOSTART.is_file()


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_resolve_autostart_path_falls_back_to_default(monkeypatch, value) -> None:
    if value is None:
        monkeypatch.delenv("QTILE_AUTOSTART_PATH", raising=False)
    else:
        monkeypatch.setenv("QTILE_AUTOSTART_PATH", value)
    assert resolve_autostart_path() == DEFAULT_AUTOSTART


@pytest.mark.parametrize(
    ("raw", "relative"),
    [
        ("{home}/custom-autostart.sh", "custom-autostart.sh"),
        ("  ~/bin/start.sh  ", "bin/start.sh"),
    ],
    ids=["override", "strip-and-expanduser"],
)
def test_resolve_autostart_path_uses_env_value(
    monkeypatch, tmp_path, raw, relative
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", raw.format(home=tmp_path))
    assert resolve_autostart_path() == tmp_path / relative


def test_resolve_autostart_path_reads_env_at_call_time(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("QTILE_AUTOSTART_PATH", raising=False)
    assert resolve_autostart_path() == DEFAULT_AUTOSTART
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", str(tmp_path / "later.sh"))
    assert resolve_autostart_path() == tmp_path / "later.sh"


# --- autostart_log_path ------------------------------------------------------


def test_autostart_log_path_uses_xdg_data_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert autostart_log_path() == tmp_path / "qtile" / "autostart.log"


@pytest.mark.parametrize("value", [None, "", "relative/data"])
def test_autostart_log_path_falls_back_to_home(monkeypatch, tmp_path, value) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    if value is None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", value)
    expected = tmp_path / ".local" / "share" / "qtile" / "autostart.log"
    assert autostart_log_path() == expected


# --- run_autostart -----------------------------------------------------------


@pytest.fixture
def spawn_calls(monkeypatch) -> list[tuple[list[str], Path | None, str]]:
    calls: list[tuple[list[str], Path | None, str]] = []

    def fake_spawn(cmd, *, log_path, label):
        calls.append((list(cmd), log_path, label))
        return _FakePopen(cmd)

    monkeypatch.setattr(startup, "spawn_detached", fake_spawn)
    return calls


def test_run_autostart_missing_script_warns_and_does_not_spawn(
    monkeypatch, tmp_path, caplog, spawn_calls
) -> None:
    missing = tmp_path / "nope.sh"
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", str(missing))
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_autostart() is False
    (record,) = _records(caplog, logging.WARNING)
    assert record.name == "libqtile"
    assert "not found" in record.getMessage()
    assert str(missing) in record.getMessage()
    assert spawn_calls == []


def test_run_autostart_directory_counts_as_missing(
    monkeypatch, tmp_path, caplog, spawn_calls
) -> None:
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", str(tmp_path))
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_autostart() is False
    assert "not found" in _records(caplog, logging.WARNING)[0].getMessage()
    assert spawn_calls == []


def test_run_autostart_non_executable_script_warns_and_does_not_spawn(
    monkeypatch, tmp_path, caplog, spawn_calls
) -> None:
    script = tmp_path / "autostart.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", str(script))
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_autostart() is False
    (record,) = _records(caplog, logging.WARNING)
    assert "not executable" in record.getMessage()
    assert spawn_calls == []


def test_run_autostart_spawns_executable_script_with_log_path(
    monkeypatch, tmp_path, spawn_calls
) -> None:
    script = _script(tmp_path, "true", name="autostart.sh")
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", str(script))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert run_autostart() is True
    assert spawn_calls == [
        ([str(script)], tmp_path / "data" / "qtile" / "autostart.log", "autostart")
    ]


def test_run_autostart_spawns_relative_override_by_absolute_path(
    monkeypatch, tmp_path, spawn_calls
) -> None:
    # A bare name would make Popen do a PATH lookup instead of using the file
    # that passed the is_file()/X_OK checks against the cwd.
    script = _script(tmp_path, "true", name="autostart.sh")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", "autostart.sh")
    assert run_autostart() is True
    ((cmd, _log_path, _label),) = spawn_calls
    assert cmd == [str(script)]
    assert Path(cmd[0]).is_absolute()


def test_run_autostart_returns_false_when_spawn_fails(monkeypatch, tmp_path) -> None:
    script = _script(tmp_path, "true", name="autostart.sh")
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", str(script))
    monkeypatch.setattr(startup, "spawn_detached", lambda *_a, **_k: None)
    assert run_autostart() is False


def test_run_autostart_unexpected_exception_is_logged_not_raised(
    monkeypatch, caplog
) -> None:
    def boom() -> Path:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(startup, "resolve_autostart_path", boom)
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        assert run_autostart() is False
    _assert_exception_logged(caplog, RuntimeError)


def test_run_autostart_end_to_end_writes_script_output_to_log(
    monkeypatch, tmp_path
) -> None:
    script = _script(tmp_path, "echo started-by-autostart", name="autostart.sh")
    monkeypatch.setenv("QTILE_AUTOSTART_PATH", str(script))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    spawned: list[subprocess.Popen[bytes] | None] = []
    real_spawn = startup.spawn_detached

    def recording_spawn(cmd, *, log_path, label):
        proc = real_spawn(cmd, log_path=log_path, label=label)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(startup, "spawn_detached", recording_spawn)
    assert run_autostart() is True
    (proc,) = spawned
    assert proc is not None
    assert proc.wait(timeout=5) == 0
    log = tmp_path / "data" / "qtile" / "autostart.log"
    assert log.read_text() == "started-by-autostart\n"


# --- set_root_background -----------------------------------------------------


@pytest.mark.parametrize("outcome", [True, False])
def test_set_root_background_runs_exact_xsetroot_command(monkeypatch, outcome) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run(cmd, *, label, **_kwargs):
        calls.append((list(cmd), label))
        return outcome

    monkeypatch.setattr(startup, "run_command", fake_run)
    assert set_root_background() is outcome
    assert calls == [(["xsetroot", "-solid", "#000000"], "root background")]


# --- run_steps ---------------------------------------------------------------


def test_run_steps_runs_every_step_once_in_order() -> None:
    ran: list[str] = []
    run_steps(
        [
            ("layout", lambda: ran.append("layout")),
            ("background", lambda: ran.append("background")),
            ("autostart", lambda: ran.append("autostart")),
        ]
    )
    assert ran == ["layout", "background", "autostart"]


@pytest.mark.parametrize("failing", ["layout", "background", "autostart"])
def test_run_steps_isolates_a_raising_step(failing, caplog) -> None:
    ran: list[str] = []

    def make(name: str):
        def step() -> None:
            ran.append(name)
            if name == failing:
                raise RuntimeError(f"{name} exploded")

        return step

    names = ["layout", "background", "autostart"]
    with caplog.at_level(logging.DEBUG, logger="libqtile"):
        run_steps([(name, make(name)) for name in names])
    assert ran == names  # later steps still ran, the failing one included
    assert failing in _assert_exception_logged(caplog, RuntimeError).getMessage()


def test_run_steps_accepts_a_generator_and_ignores_return_values() -> None:
    ran: list[int] = []

    def steps():
        for i in range(3):
            yield (f"step-{i}", lambda i=i: ran.append(i) or "ignored")

    run_steps(steps())
    assert ran == [0, 1, 2]
