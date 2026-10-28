#!/usr/bin/env bash
#
# Toggle a Qtile scratchpad dropdown from outside Qtile (e.g. rofi).
#
# Usage: scratchpad-toggle.sh [NAME]   (NAME defaults to "term")
#
# Qtile exposes an IPC command interface via `qtile cmd-obj`. This reaches the
# running Qtile instance and toggles the NAME DropDown defined in the
# "scratchpad" group, the same action as its keybind. The default keeps a
# launcher written before NAME existed working.

set -euo pipefail

# Resolve the repo root from this script's location:
#   src/assets/scratchpad/scratchpad-toggle.sh  ->  <repo>
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Prefer the venv's qtile (matches the running instance); fall back to PATH.
QTILE="${REPO_DIR}/.venv/bin/qtile"
if [[ ! -x "$QTILE" ]]; then
    QTILE="$(command -v qtile)" || {
        echo "qtile binary not found" >&2
        exit 1
    }
fi

exec "$QTILE" cmd-obj -o group scratchpad -f dropdown_toggle -a "${1:-term}"
