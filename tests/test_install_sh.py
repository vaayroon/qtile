"""Contract tests for ``install.sh`` (uv-based bootstrap).

``install.sh`` runs against a hermetic sandbox: a copy of the script inside a
temporary repo, ``PATH`` limited to a ``fakebin`` directory and ``HOME`` inside
the temp dir. ``uv`` is a fake that records its arguments and fabricates
``.venv/bin/qtile``, so no network, no real venv and no sudo are involved.
"""

import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT / "install.sh"
BASH = "/bin/bash"
UV_INSTALL_CMD = "curl -LsSf https://astral.sh/uv/install.sh | sh"

# External tools install.sh needs besides bash builtins (--skip-xsession path).
TOOLS = ("dirname", "cat", "rm", "mv", "cp", "mkdir", "chmod", "readlink")

# Fake uv: records its call and fabricates a venv the way a real sync would,
# including the pyvenv.cfg ``home`` of the interpreter it was told to use
# (FAKE_UV_HOME overrides it to emulate "uv picked another interpreter").
FAKE_UV = f"""#!{BASH}
printf '%s\\n' "$*" >> "$FAKEBIN_LOG/uv.args"
printf '%s\\n' "$UV_PROJECT_ENVIRONMENT" >> "$FAKEBIN_LOG/uv.env"
if [[ -e "$UV_PROJECT_ENVIRONMENT" ]]; then venv=present; else venv=absent; fi
if [[ -d "$UV_PROJECT_ENVIRONMENT.bak" ]]; then bak=present; else bak=absent; fi
printf 'venv=%s backup=%s\\n' "$venv" "$bak" >> "$FAKEBIN_LOG/uv.state"
if [[ -n "${{FAKE_UV_TERM:-}}" ]]; then  # emulate Ctrl-C/kill during the sync
    mkdir -p "$UV_PROJECT_ENVIRONMENT"
    : > "$UV_PROJECT_ENVIRONMENT/half-synced"
    kill -TERM "$PPID"
    exit 0
fi
if [[ -n "${{FAKE_UV_FAIL:-}}" ]]; then
    mkdir -p "$UV_PROJECT_ENVIRONMENT"
    : > "$UV_PROJECT_ENVIRONMENT/half-synced"
    exit 1
fi
python=""
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--python" ]]; then python="$2"; fi
    shift
done
if [[ -n "$UV_PROJECT_ENVIRONMENT" ]]; then
    mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
    printf '#!{BASH}\\n' > "$UV_PROJECT_ENVIRONMENT/bin/qtile"
    chmod +x "$UV_PROJECT_ENVIRONMENT/bin/qtile"
    python="$(command -v "$python")"
    printf 'home = %s\\n' "${{FAKE_UV_HOME:-$(dirname "$python")}}" \\
        > "$UV_PROJECT_ENVIRONMENT/pyvenv.cfg"
fi
"""

# Fake sudo: records the call and what was piped to it, never touches anything.
FAKE_SUDO = f"""#!{BASH}
printf '%s\\n' "$*" >> "$FAKEBIN_LOG/sudo.args"
cat > "$FAKEBIN_LOG/sudo.stdin"
"""

FAKE_CURL = f"""#!{BASH}
printf 'curl was called\\n' >> "$FAKEBIN_LOG/curl.called"
exit 0
"""


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@dataclass
class Sandbox:
    root: Path
    repo: Path
    home: Path
    fakebin: Path
    log: Path

    def run(
        self,
        *args: str,
        env_extra: dict[str, str] | None = None,
        default_python: bool = False,
        xsession: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run install.sh in the sandbox.

        PYTHON points at a fake unless default_python is set. The X session
        entry is skipped unless xsession is set, in which case it is written
        to ``self.xsession_file`` (a temp path, so no sudo is involved).
        """
        env = {
            "PATH": str(self.fakebin),
            "HOME": str(self.home),
            "FAKEBIN_LOG": str(self.log),
            "QTILE_XSESSION_FILE": str(self.xsession_file),
        }
        if not default_python:
            env["PYTHON"] = str(self.fakebin / "python3.12")
        env.update(env_extra or {})
        flags = [] if xsession else ["--skip-xsession"]
        return subprocess.run(
            [BASH, str(self.repo / "install.sh"), *flags, *args],
            env=env,
            capture_output=True,
            text=True,
            cwd=self.root,  # not the repo: install.sh must not rely on cwd
            timeout=30,
            check=False,
        )

    def uv_calls(self) -> list[str]:
        path = self.log / "uv.args"
        return path.read_text().splitlines() if path.exists() else []

    def uv_env(self) -> list[str]:
        path = self.log / "uv.env"
        return path.read_text().splitlines() if path.exists() else []

    def uv_states(self) -> list[str]:
        path = self.log / "uv.state"
        return path.read_text().splitlines() if path.exists() else []

    @property
    def xsession_file(self) -> Path:
        return self.root / "xsessions" / "qtile-venv.desktop"

    @property
    def backup(self) -> Path:
        return self.repo / ".venv.bak"

    @property
    def sudo_called(self) -> bool:
        return (self.log / "sudo.args").exists()

    @property
    def python(self) -> Path:
        return self.fakebin / "python3.12"

    @property
    def venv(self) -> Path:
        return self.repo / ".venv"

    @property
    def curl_called(self) -> bool:
        return (self.log / "curl.called").exists()


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    repo = tmp_path / "repo"
    fakebin = tmp_path / "fakebin"
    home = tmp_path / "home"
    log = tmp_path / "log"
    for directory in (repo, fakebin, home, log, tmp_path / "xsessions"):
        directory.mkdir()

    shutil.copy(INSTALL_SH, repo / "install.sh")
    (repo / "uv.lock").write_text("version = 1\n")
    (repo / ".env.example").write_text("MONITOR_ORDER=example\n")
    (repo / "src" / "assets" / "scratchpad").mkdir(parents=True)
    (repo / "src" / "config.py").write_text("")
    (repo / "src" / "assets" / "scratchpad" / "scratchpad-toggle.sh").write_text("")

    for tool in TOOLS:
        found = shutil.which(tool)
        assert found, f"{tool} not found on the host"
        (fakebin / tool).symlink_to(found)
    _write_executable(fakebin / "python3.12", f"#!{BASH}\nexit 0\n")
    _write_executable(fakebin / "uv", FAKE_UV)
    _write_executable(fakebin / "curl", FAKE_CURL)  # must never be called
    _write_executable(fakebin / "sudo", FAKE_SUDO)

    return Sandbox(tmp_path, repo, home, fakebin, log)


# --- Preconditions ------------------------------------------------------------


def test_missing_uv_fails_with_the_official_install_command(sandbox: Sandbox) -> None:
    (sandbox.fakebin / "uv").unlink()
    result = sandbox.run()
    assert result.returncode != 0
    assert "uv not found" in result.stderr
    assert UV_INSTALL_CMD in result.stderr


def test_missing_uv_has_no_side_effects_and_never_runs_curl(sandbox: Sandbox) -> None:
    (sandbox.fakebin / "uv").unlink()
    sandbox.run()
    assert not sandbox.venv.exists()
    assert not (sandbox.repo / ".env").exists()
    assert not (sandbox.home / ".local").exists()
    assert not sandbox.curl_called


def test_missing_uv_lock_fails_naming_the_file(sandbox: Sandbox) -> None:
    (sandbox.repo / "uv.lock").unlink()
    result = sandbox.run()
    assert result.returncode != 0
    assert "uv.lock" in result.stderr
    assert sandbox.uv_calls() == []


SYSTEM_PYTHON = Path("/usr/bin/python3.12")


@pytest.mark.skipif(not SYSTEM_PYTHON.exists(), reason="needs /usr/bin/python3.12")
def test_default_interpreter_is_the_system_python_not_whatever_is_on_path(
    sandbox: Sandbox,
) -> None:
    # fakebin/python3.12 plays the Homebrew/pyenv Python that sits early on PATH.
    result = sandbox.run(default_python=True)
    assert result.returncode == 0, result.stderr
    assert sandbox.uv_calls() == [
        f"sync --locked --no-dev --project {sandbox.repo} --python {SYSTEM_PYTHON}"
    ]


def test_sync_that_used_another_interpreter_fails_before_writing_anything(
    sandbox: Sandbox,
) -> None:
    result = sandbox.run(env_extra={"FAKE_UV_HOME": "/home/linuxbrew/.linuxbrew/bin"})
    assert result.returncode != 0
    assert "pyvenv.cfg" in result.stderr
    assert "/home/linuxbrew/.linuxbrew/bin" in result.stderr
    assert str(sandbox.fakebin) in result.stderr  # the interpreter it expected
    assert not (sandbox.repo / ".env").exists()
    assert not (sandbox.home / ".local").exists()


def test_venv_home_may_be_the_resolved_dir_of_a_symlinked_interpreter(
    sandbox: Sandbox,
) -> None:
    real_dir = sandbox.root / "cellar"
    real_dir.mkdir()
    _write_executable(real_dir / "python3.12", f"#!{BASH}\nexit 0\n")
    link = sandbox.fakebin / "python-brew"
    link.symlink_to(real_dir / "python3.12")
    result = sandbox.run(env_extra={"PYTHON": str(link), "FAKE_UV_HOME": str(real_dir)})
    assert result.returncode == 0, result.stderr


def test_missing_python_interpreter_fails(sandbox: Sandbox) -> None:
    result = sandbox.run(env_extra={"PYTHON": "python-does-not-exist"})
    assert result.returncode != 0
    assert "python-does-not-exist not found" in result.stderr
    assert sandbox.uv_calls() == []


# --- uv sync ------------------------------------------------------------------


def test_default_run_syncs_runtime_only_from_the_lock(sandbox: Sandbox) -> None:
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.uv_calls() == [
        f"sync --locked --no-dev --project {sandbox.repo} --python {sandbox.python}"
    ]
    assert sandbox.uv_env() == [str(sandbox.venv)]
    assert (sandbox.venv / "bin" / "qtile").exists()
    assert not sandbox.curl_called


def test_dev_flag_drops_no_dev(sandbox: Sandbox) -> None:
    result = sandbox.run("--dev")
    assert result.returncode == 0, result.stderr
    assert sandbox.uv_calls() == [
        f"sync --locked --project {sandbox.repo} --python {sandbox.python}"
    ]


def test_python_env_var_selects_the_interpreter(sandbox: Sandbox) -> None:
    _write_executable(sandbox.fakebin / "python3.13", f"#!{BASH}\nexit 0\n")
    result = sandbox.run(env_extra={"PYTHON": "python3.13"})
    assert result.returncode == 0, result.stderr
    assert "--python python3.13" in sandbox.uv_calls()[0]


def test_force_moves_the_venv_aside_then_drops_the_backup_on_success(
    sandbox: Sandbox,
) -> None:
    sandbox.venv.mkdir()
    (sandbox.venv / "stale-marker").write_text("old")
    result = sandbox.run("--force")
    assert result.returncode == 0, result.stderr
    # uv saw no venv (it builds a new one) and the old one safe next to it.
    assert sandbox.uv_states() == ["venv=absent backup=present"]
    assert not (sandbox.venv / "stale-marker").exists()
    assert (sandbox.venv / "bin" / "qtile").exists()
    assert not sandbox.backup.exists()


def test_force_without_an_existing_venv_just_syncs(sandbox: Sandbox) -> None:
    result = sandbox.run("--force")
    assert result.returncode == 0, result.stderr
    assert sandbox.uv_states() == ["venv=absent backup=absent"]
    assert not sandbox.backup.exists()


def _old_venv(sandbox: Sandbox) -> None:
    sandbox.venv.mkdir()
    (sandbox.venv / "stale-marker").write_text("old")


def _assert_old_venv_restored(sandbox: Sandbox) -> None:
    assert (sandbox.venv / "stale-marker").read_text() == "old"
    assert not (sandbox.venv / "half-synced").exists()
    assert not sandbox.backup.exists()


def test_force_restores_the_old_venv_when_uv_sync_fails(sandbox: Sandbox) -> None:
    _old_venv(sandbox)
    result = sandbox.run("--force", env_extra={"FAKE_UV_FAIL": "1"})
    assert result.returncode != 0
    assert "restored" in result.stderr
    _assert_old_venv_restored(sandbox)
    assert not (sandbox.repo / ".env").exists()


def test_force_restores_the_old_venv_when_interrupted_mid_sync(
    sandbox: Sandbox,
) -> None:
    _old_venv(sandbox)
    result = sandbox.run("--force", env_extra={"FAKE_UV_TERM": "1"})
    assert result.returncode != 0
    assert "Interrupted" in result.stderr
    _assert_old_venv_restored(sandbox)


def test_force_restores_the_old_venv_when_sync_leaves_no_qtile(
    sandbox: Sandbox,
) -> None:
    _old_venv(sandbox)
    _write_executable(sandbox.fakebin / "uv", f"#!{BASH}\nexit 0\n")
    result = sandbox.run("--force")
    assert result.returncode != 0
    _assert_old_venv_restored(sandbox)


def test_force_restores_the_old_venv_when_the_interpreter_is_wrong(
    sandbox: Sandbox,
) -> None:
    _old_venv(sandbox)
    result = sandbox.run("--force", env_extra={"FAKE_UV_HOME": "/elsewhere/bin"})
    assert result.returncode != 0
    assert "pyvenv.cfg" in result.stderr
    _assert_old_venv_restored(sandbox)


def test_force_refuses_to_overwrite_an_existing_backup(sandbox: Sandbox) -> None:
    _old_venv(sandbox)
    sandbox.backup.mkdir()
    (sandbox.backup / "precious").write_text("mine")
    result = sandbox.run("--force")
    assert result.returncode != 0
    assert ".venv.bak" in result.stderr
    assert (sandbox.venv / "stale-marker").read_text() == "old"
    assert (sandbox.backup / "precious").read_text() == "mine"
    assert sandbox.uv_calls() == []


def test_failed_sync_without_force_exits_before_writing_anything(
    sandbox: Sandbox,
) -> None:
    result = sandbox.run(xsession=True, env_extra={"FAKE_UV_FAIL": "1"})
    assert result.returncode != 0
    assert len(sandbox.uv_calls()) == 1
    assert not (sandbox.repo / ".env").exists()
    assert not sandbox.xsession_file.exists()
    assert not (sandbox.home / ".local").exists()


def test_rerun_without_force_keeps_the_venv_and_resyncs(sandbox: Sandbox) -> None:
    sandbox.venv.mkdir()
    (sandbox.venv / "marker").write_text("kept")
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert (sandbox.venv / "marker").exists()
    assert len(sandbox.uv_calls()) == 1  # uv sync is what converges it


def test_fails_when_uv_sync_leaves_no_qtile_binary(sandbox: Sandbox) -> None:
    _write_executable(sandbox.fakebin / "uv", f"#!{BASH}\nexit 0\n")
    result = sandbox.run()
    assert result.returncode != 0
    assert "qtile" in result.stderr


# --- Behavior kept from the pip-based script ----------------------------------


def test_env_file_is_created_from_the_example_when_absent(sandbox: Sandbox) -> None:
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert (sandbox.repo / ".env").read_text() == "MONITOR_ORDER=example\n"


def test_existing_env_file_is_left_untouched(sandbox: Sandbox) -> None:
    (sandbox.repo / ".env").write_text("MONITOR_ORDER=mine\n")
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert (sandbox.repo / ".env").read_text() == "MONITOR_ORDER=mine\n"


def test_xsession_entry_launches_the_venv_binary_from_the_repo(
    sandbox: Sandbox,
) -> None:
    result = sandbox.run(xsession=True)
    assert result.returncode == 0, result.stderr
    assert sandbox.xsession_file.read_text().splitlines() == [
        "[Desktop Entry]",
        "Name=Qtile (venv)",
        "Comment=Qtile Session",
        "Type=Application",
        "Keywords=wm;tiling",
        f"Path={sandbox.repo}",
        f"Exec={sandbox.venv}/bin/qtile start -c {sandbox.repo}/src/config.py",
    ]
    assert not sandbox.sudo_called  # the directory is writable


def test_xsession_entry_uses_sudo_when_the_directory_is_not_writable(
    sandbox: Sandbox,
) -> None:
    sandbox.xsession_file.parent.chmod(0o555)
    try:
        result = sandbox.run(xsession=True)
    finally:
        sandbox.xsession_file.parent.chmod(0o755)
    assert result.returncode == 0, result.stderr
    assert (sandbox.log / "sudo.args").read_text().split() == [
        "tee",
        str(sandbox.xsession_file),
    ]
    assert (
        f"Exec={sandbox.venv}/bin/qtile start"
        in (sandbox.log / "sudo.stdin").read_text()
    )


def test_skip_xsession_writes_no_session_entry_and_never_calls_sudo(
    sandbox: Sandbox,
) -> None:
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert not sandbox.xsession_file.exists()
    assert not sandbox.sudo_called


def test_rofi_scratchpad_entry_is_still_written(sandbox: Sandbox) -> None:
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    entry = sandbox.home / ".local/share/applications/qtile-scratchpad.desktop"
    assert "Name=Scratchpad Terminal" in entry.read_text()


def test_unknown_flag_is_rejected_before_touching_anything(sandbox: Sandbox) -> None:
    result = sandbox.run("--bogus")
    assert result.returncode != 0
    assert "Unknown option: --bogus" in result.stderr
    assert sandbox.uv_calls() == []
    assert not sandbox.venv.exists()


# --- Script text --------------------------------------------------------------


def _leading_comment_block(script: str) -> str:
    lines = script.splitlines()[1:]  # skip the shebang
    block = []
    for line in lines:
        if not line.startswith("#"):
            break
        block.append(line)
    return "\n".join(block)


def test_header_documents_the_uv_lock_sync_and_the_backup() -> None:
    header = _leading_comment_block(INSTALL_SH.read_text())
    assert "uv.lock" in header
    assert ".venv.bak" in header


@pytest.mark.parametrize("legacy", ["pip install", "pip-sync", "pip-compile"])
def test_script_has_no_pip_tooling_left(legacy: str) -> None:
    assert legacy not in INSTALL_SH.read_text()


def test_script_does_not_reference_the_removed_requirements_files() -> None:
    assert "requirements" not in INSTALL_SH.read_text()


def test_usage_documents_uv_force_backup_and_the_default_interpreter(
    sandbox: Sandbox,
) -> None:
    result = subprocess.run(
        [BASH, str(sandbox.repo / "install.sh"), "--help"],
        env={"PATH": str(sandbox.fakebin), "HOME": str(sandbox.home)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "uv" in result.stdout
    assert "--force" in result.stdout and ".venv.bak" in result.stdout
    assert f"default: {SYSTEM_PYTHON}" in result.stdout
    assert "pip" not in result.stdout.lower()
