#!/usr/bin/env bash
#
# install.sh — Bootstrap this Qtile configuration.
#
# Syncs the virtual environment from uv.lock (exact: it installs what the lock
# pins and removes everything else), sets up the .env file, and registers an X
# session entry so your display manager can launch Qtile from this repo's venv.
#
# Requires uv (https://docs.astral.sh/uv/). It is never installed from here.
# Re-runnable: .env is preserved, and the venv is converged to uv.lock on every
# run. Pass --force to recreate the venv from scratch.

set -euo pipefail

# --- Paths --------------------------------------------------------------------
# Resolve the repo root from this script's location so the generated paths are
# always absolute and correct, regardless of where the script is invoked from.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${REPO_DIR}/.venv"
CONFIG_PY="${REPO_DIR}/src/config.py"
QTILE_BIN="${VENV_DIR}/bin/qtile"
XSESSION_FILE="/usr/share/xsessions/qtile-venv.desktop"

# The login session runs from this venv, so it must be built on the distro
# interpreter. uv's python-preference = "only-system" still accepts ANY non-uv
# Python found on PATH (Homebrew, pyenv shims...), so name the interpreter
# explicitly instead of relying on PATH.
DEFAULT_PYTHON="/usr/bin/python3.12"
PYTHON="${PYTHON:-$DEFAULT_PYTHON}"

# --- Options ------------------------------------------------------------------
INSTALL_DEV=false
FORCE=false
SKIP_XSESSION=false

usage() {
    cat <<EOF
Usage: ./install.sh [options]

Options:
  --dev            Also install dev tools (ruff, mypy, pytest); without it they are removed
  --force          Recreate the virtual environment from scratch
  --skip-xsession  Do not write the /usr/share/xsessions entry (needs sudo)
  -h, --help       Show this help

Environment:
  PYTHON           Python interpreter uv uses for the venv (default: ${DEFAULT_PYTHON})
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dev) INSTALL_DEV=true ;;
        --force) FORCE=true ;;
        --skip-xsession) SKIP_XSESSION=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
    shift
done

# --- Helpers ------------------------------------------------------------------
log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# Fail unless the venv was built from the interpreter we asked for: pyvenv.cfg
# records the directory of the interpreter as "home = <dir>". A symlinked
# interpreter (Homebrew, pyenv) may be recorded as its resolved directory.
verify_venv_interpreter() {
    local cfg="${VENV_DIR}/pyvenv.cfg" line home="" python_path
    [[ -f "$cfg" ]] || die "uv sync finished but ${cfg} is missing."
    while IFS= read -r line; do
        if [[ "$line" =~ ^home[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            home="${BASH_REMATCH[1]}"
            break
        fi
    done < "$cfg"
    python_path="$(command -v "$PYTHON")"
    if [[ "$home" != "$(dirname "$python_path")" \
        && "$home" != "$(dirname "$(readlink -f "$python_path")")" ]]; then
        die "${cfg} says the venv was built from '${home}', not from ${PYTHON} (${python_path}). Fix PYTHON= or your PATH, then re-run with --force."
    fi
}

# --- Preconditions ------------------------------------------------------------
command -v uv >/dev/null 2>&1 \
    || die "uv not found. Install it, open a new shell, then re-run ./install.sh:
    curl -LsSf https://astral.sh/uv/install.sh | sh
Other methods: https://docs.astral.sh/uv/getting-started/installation/"

command -v "$PYTHON" >/dev/null 2>&1 \
    || die "$PYTHON not found. Install Python 3.12+ or set PYTHON=<interpreter>."

[[ -f "${REPO_DIR}/uv.lock" ]] \
    || die "uv.lock not found in ${REPO_DIR}. Restore it with: git checkout -- uv.lock"

# --- 1. Virtual environment and dependencies ----------------------------------
# uv sync is exact: it installs what uv.lock pins and REMOVES everything else
# (dev tools included, unless --dev is passed).
if [[ "$FORCE" == true && -d "$VENV_DIR" ]]; then
    log "Removing existing virtual environment (--force)"
    rm -rf "$VENV_DIR"
fi

sync_args=(sync --locked)
if [[ "$INSTALL_DEV" == true ]]; then
    log "Syncing ${VENV_DIR} from uv.lock (runtime + dev)"
else
    sync_args+=(--no-dev)
    log "Syncing ${VENV_DIR} from uv.lock (runtime only)"
fi
sync_args+=(--project "$REPO_DIR" --python "$PYTHON")
UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv "${sync_args[@]}"

[[ -x "$QTILE_BIN" ]] || die "uv sync finished but ${QTILE_BIN} is missing."
verify_venv_interpreter

# --- 2. Environment file ------------------------------------------------------
if [[ -f "${REPO_DIR}/.env" ]]; then
    log ".env already exists — leaving it untouched"
else
    log "Creating .env from .env.example"
    cp "${REPO_DIR}/.env.example" "${REPO_DIR}/.env"
    warn "Edit .env to set your monitor order and phone mirror paths."
fi

# --- 3. X session entry -------------------------------------------------------
if [[ "$SKIP_XSESSION" == true ]]; then
    log "Skipping X session entry (--skip-xsession)"
else
    log "Registering X session entry at ${XSESSION_FILE}"

    # Path= sets the working directory so settings.py's dotenv_values() finds
    # .env, which it loads relative to the CWD (the display manager would
    # otherwise launch from $HOME and silently skip your configuration).
    desktop_entry="$(cat <<EOF
[Desktop Entry]
Name=Qtile (venv)
Comment=Qtile Session
Type=Application
Keywords=wm;tiling
Path=${REPO_DIR}
Exec=${QTILE_BIN} start -c ${CONFIG_PY}
EOF
)"

    if [[ -w "$(dirname "$XSESSION_FILE")" ]]; then
        printf '%s\n' "$desktop_entry" > "$XSESSION_FILE"
    else
        warn "Writing ${XSESSION_FILE} requires sudo."
        printf '%s\n' "$desktop_entry" | sudo tee "$XSESSION_FILE" >/dev/null
    fi
fi

# --- 4. Rofi launcher entry ---------------------------------------------------
# Write a .desktop file so the scratchpad terminal can be toggled from
# `rofi -show drun` (in addition to the Super+masculine (º) keybind).
SCRATCHPAD_TOGGLE="${REPO_DIR}/src/assets/scratchpad/scratchpad-toggle.sh"
DESKTOP_DIR="${HOME}/.local/share/applications"
SCRATCHPAD_DESKTOP="${DESKTOP_DIR}/qtile-scratchpad.desktop"

log "Registering rofi launcher entry at ${SCRATCHPAD_DESKTOP}"
mkdir -p "$DESKTOP_DIR"
chmod +x "$SCRATCHPAD_TOGGLE" 2>/dev/null || true
cat > "$SCRATCHPAD_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Scratchpad Terminal
Comment=Toggle the floating dropdown terminal
Exec=${SCRATCHPAD_TOGGLE}
Icon=utilities-terminal
Terminal=false
Categories=System;TerminalEmulator;
Keywords=scratchpad;dropdown;quake;terminal;
EOF

# --- Done ---------------------------------------------------------------------
log "Done."
echo
echo "Next steps:"
echo "  1. Review your settings:  \$EDITOR ${REPO_DIR}/.env"
echo "  2. Log out and pick 'Qtile (venv)' from your display manager."
echo
echo "Or test it now without logging out (requires xserver-xephyr):"
echo "  Xephyr -br -ac -noreset -screen 1280x720 :1 &"
echo "  DISPLAY=:1 ${QTILE_BIN} start -c ${CONFIG_PY}"
