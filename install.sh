#!/usr/bin/env bash
#
# install.sh — Bootstrap this Qtile configuration.
#
# Syncs the virtual environment from uv.lock (it installs exactly what the lock
# pins and prunes unlocked packages, except the seed tools uv leaves in place),
# sets up the .env file, and registers an X session entry so your display
# manager can launch Qtile from this repo's venv. With --system-packages it
# first installs the apt packages listed in packages/apt.txt.
#
# Requires uv (https://docs.astral.sh/uv/). It is never installed from here.
# Re-runnable: .env is preserved and the venv is converged to uv.lock on every
# run. --force rebuilds the venv: the old one is moved to .venv.bak first and
# restored if the new sync fails, so you are never left without a venv.

set -euo pipefail

# --- Paths --------------------------------------------------------------------
# Resolve the repo root from this script's location so the generated paths are
# always absolute and correct, regardless of where the script is invoked from.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${REPO_DIR}/.venv"
CONFIG_PY="${REPO_DIR}/src/config.py"
QTILE_BIN="${VENV_DIR}/bin/qtile"
BACKUP_DIR="${VENV_DIR}.bak"
APT_PACKAGES_FILE="${REPO_DIR}/packages/apt.txt"
# QTILE_XSESSION_FILE only exists so the tests can write the session entry to a
# temp dir; real users never need to set it.
XSESSION_FILE="${QTILE_XSESSION_FILE:-/usr/share/xsessions/qtile-venv.desktop}"

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
SYSTEM_PACKAGES=false

usage() {
    cat <<EOF
Usage: ./install.sh [options]

Options:
  --system-packages  First install the apt packages in packages/apt.txt (needs sudo,
                     Debian/Ubuntu only)
  --dev              Also install dev tools (ruff, mypy, pytest, pre-commit); without it they are removed
  --force            Recreate the virtual environment (the old one is kept as .venv.bak
                     during the sync and restored if it fails)
  --skip-xsession    Do not write the /usr/share/xsessions entry (needs sudo)
  -h, --help         Show this help

Environment:
  PYTHON             Python interpreter uv uses for the venv (default: ${DEFAULT_PYTHON})
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --system-packages) SYSTEM_PACKAGES=true ;;
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

BACKUP_MADE=false

# Abort the venv step. When --force moved the old venv aside, put it back first
# so a failed sync never leaves the login session without a working venv.
rollback_and_die() {
    local msg="$1"
    if [[ "$BACKUP_MADE" == true ]]; then
        rm -rf "$VENV_DIR"
        mv "$BACKUP_DIR" "$VENV_DIR"
        BACKUP_MADE=false
        msg+=$'\nThe previous virtual environment was restored.'
    fi
    die "$msg"
}

# Fail unless the venv was built from the interpreter we asked for: pyvenv.cfg
# records the directory of the interpreter as "home = <dir>". A symlinked
# interpreter (Homebrew, pyenv) may be recorded as its resolved directory.
verify_venv_interpreter() {
    local cfg="${VENV_DIR}/pyvenv.cfg" line home="" python_path
    [[ -f "$cfg" ]] || rollback_and_die "uv sync finished but ${cfg} is missing."
    while IFS= read -r line; do
        if [[ "$line" =~ ^home[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            home="${BASH_REMATCH[1]}"
            break
        fi
    done < "$cfg"
    python_path="$(command -v "$PYTHON")"
    if [[ "$home" != "$(dirname "$python_path")" \
        && "$home" != "$(dirname "$(readlink -f "$python_path")")" ]]; then
        rollback_and_die "${cfg} says the venv was built from '${home}', not from ${PYTHON} (${python_path}). Fix PYTHON= or your PATH, then re-run with --force."
    fi
}

# Print the package names in packages/apt.txt, one per line: everything after
# a `#` is a comment and blank lines are skipped.
read_package_list() {
    local line words
    while IFS= read -r line || [[ -n "$line" ]]; do
        read -ra words <<< "${line%%#*}"
        if (( ${#words[@]} )); then
            printf '%s\n' "${words[@]}"
        fi
    done < "$APT_PACKAGES_FILE"
}

# --- 0. System packages (opt-in) ----------------------------------------------
# Runs before the preconditions so it can provide the interpreter they check.
# Without --system-packages, apt is never touched.
if [[ "$SYSTEM_PACKAGES" == true ]]; then
    command -v apt-get >/dev/null 2>&1 \
        || die "--system-packages needs apt-get (Debian/Ubuntu). Install the packages in ${APT_PACKAGES_FILE} with your package manager, then re-run without it."
    [[ -f "$APT_PACKAGES_FILE" ]] \
        || die "${APT_PACKAGES_FILE} not found. Restore it with: git checkout -- packages/apt.txt"
    mapfile -t packages < <(read_package_list)
    (( ${#packages[@]} )) || die "${APT_PACKAGES_FILE} lists no packages."

    log "Installing ${#packages[@]} system packages from packages/apt.txt (needs sudo)"
    sudo apt-get update \
        || die "apt-get update failed; nothing else was changed."
    sudo apt-get install "${packages[@]}" \
        || die "apt-get install failed; nothing else was changed."
fi

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
# uv sync is exact for the lock: it installs what uv.lock pins and prunes other
# packages (dev tools included, unless --dev is passed). It leaves the seed
# tools of the venv (pip, setuptools) alone.
#
# --force moves the old venv aside instead of deleting it. Do NOT sync into a
# temp dir and rename it afterwards: venv scripts embed absolute shebangs.
if [[ "$FORCE" == true && -d "$VENV_DIR" ]]; then
    [[ ! -e "$BACKUP_DIR" ]] \
        || die "${BACKUP_DIR} already exists (left over from an interrupted --force?). Inspect or remove it, then re-run."
    log "Moving the existing virtual environment to ${BACKUP_DIR} (--force)"
    mv "$VENV_DIR" "$BACKUP_DIR"
    BACKUP_MADE=true
    trap 'rollback_and_die "Interrupted."' INT TERM
fi

sync_args=(sync --locked)
if [[ "$INSTALL_DEV" == true ]]; then
    log "Syncing ${VENV_DIR} from uv.lock (runtime + dev)"
else
    sync_args+=(--no-dev)
    log "Syncing ${VENV_DIR} from uv.lock (runtime only)"
fi
sync_args+=(--project "$REPO_DIR" --python "$PYTHON")
if ! UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv "${sync_args[@]}"; then
    rollback_and_die "uv sync failed; .env and the session entries were not touched."
fi

[[ -x "$QTILE_BIN" ]] || rollback_and_die "uv sync finished but ${QTILE_BIN} is missing."
verify_venv_interpreter

if [[ "$BACKUP_MADE" == true ]]; then
    trap - INT TERM
    rm -rf "$BACKUP_DIR"
    BACKUP_MADE=false
fi

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

    # Path= sets a sane working directory for the session (the display manager
    # would otherwise launch from $HOME). settings.py resolves .env from its own
    # location, so the working directory does not affect configuration loading.
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

# --- 4. Rofi launcher entries -------------------------------------------------
# One .desktop file per scratchpad entry with desktop_entry = true, so each can
# be toggled from `rofi -show drun`. The generator also removes the launchers
# it wrote for entries that are gone. A failure only warns: the window manager
# works without them, and the command can be re-run on its own.
SCRATCHPAD_TOGGLE="${REPO_DIR}/src/assets/scratchpad/scratchpad-toggle.sh"
DESKTOP_GENERATOR="${REPO_DIR}/tools/generate_scratchpad_desktops.py"

log "Registering rofi launcher entries for the scratchpads"
chmod +x "$SCRATCHPAD_TOGGLE" 2>/dev/null || true
"${VENV_DIR}/bin/python" "$DESKTOP_GENERATOR" \
    || warn "Could not write the rofi launchers. Re-run: ${VENV_DIR}/bin/python ${DESKTOP_GENERATOR}"

# --- Done ---------------------------------------------------------------------
log "Done."
echo
echo "Next steps:"
echo "  1. Review your settings:  \$EDITOR ${REPO_DIR}/.env"
echo "  2. Log out and pick 'Qtile (venv)' from your display manager."
echo
echo "Or test it now without logging out (requires xserver-xephyr):"
echo "  ${REPO_DIR}/test-xephyr.sh"
