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
TOOLS = ("dirname", "cat", "rm", "cp", "mkdir", "chmod")

FAKE_UV = f"""#!{BASH}
printf '%s\\n' "$*" >> "$FAKEBIN_LOG/uv.args"
printf '%s\\n' "$UV_PROJECT_ENVIRONMENT" >> "$FAKEBIN_LOG/uv.env"
if [[ -n "$UV_PROJECT_ENVIRONMENT" ]]; then
    mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
    printf '#!{BASH}\\n' > "$UV_PROJECT_ENVIRONMENT/bin/qtile"
    chmod +x "$UV_PROJECT_ENVIRONMENT/bin/qtile"
fi
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
        self, *args: str, env_extra: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": str(self.fakebin),
            "HOME": str(self.home),
            "FAKEBIN_LOG": str(self.log),
        }
        env.update(env_extra or {})
        return subprocess.run(
            [BASH, str(self.repo / "install.sh"), "--skip-xsession", *args],
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
    for directory in (repo, fakebin, home, log):
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
        f"sync --locked --no-dev --project {sandbox.repo} --python python3.12"
    ]
    assert sandbox.uv_env() == [str(sandbox.venv)]
    assert (sandbox.venv / "bin" / "qtile").exists()
    assert not sandbox.curl_called


def test_dev_flag_drops_no_dev(sandbox: Sandbox) -> None:
    result = sandbox.run("--dev")
    assert result.returncode == 0, result.stderr
    assert sandbox.uv_calls() == [
        f"sync --locked --project {sandbox.repo} --python python3.12"
    ]


def test_python_env_var_selects_the_interpreter(sandbox: Sandbox) -> None:
    _write_executable(sandbox.fakebin / "python3.13", f"#!{BASH}\nexit 0\n")
    result = sandbox.run(env_extra={"PYTHON": "python3.13"})
    assert result.returncode == 0, result.stderr
    assert "--python python3.13" in sandbox.uv_calls()[0]


def test_force_removes_the_existing_venv_before_syncing(sandbox: Sandbox) -> None:
    sandbox.venv.mkdir()
    (sandbox.venv / "stale-marker").write_text("old")
    result = sandbox.run("--force")
    assert result.returncode == 0, result.stderr
    assert not (sandbox.venv / "stale-marker").exists()
    assert len(sandbox.uv_calls()) == 1


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


def test_xsession_entry_launches_the_venv_binary_never_uv() -> None:
    lines = INSTALL_SH.read_text().splitlines()
    session_execs = [line for line in lines if line.startswith("Exec=${QTILE_BIN}")]
    assert session_execs == ["Exec=${QTILE_BIN} start -c ${CONFIG_PY}"]
    assert 'QTILE_BIN="${VENV_DIR}/bin/qtile"' in lines
    assert 'VENV_DIR="${REPO_DIR}/.venv"' in lines
    assert not [line for line in lines if line.startswith("Exec=") and "uv" in line]


def test_usage_and_header_talk_about_uv_not_pip(sandbox: Sandbox) -> None:
    script = INSTALL_SH.read_text()
    header = "\n".join(script.splitlines()[:12])
    assert "uv" in header
    assert "pip" not in script.lower().replace("pipefail", "")

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
    assert "pip" not in result.stdout.lower()
