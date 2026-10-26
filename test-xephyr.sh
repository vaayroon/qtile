#!/usr/bin/env bash
#
# Launch the qtile config in an isolated Xephyr window for safe testing.
# Validates the config with `qtile check` BEFORE starting, so a typo never
# costs you a black screen.
#
# Usage:
#   ./test-xephyr.sh                 # defaults: display :2, 1920x720
#   ./test-xephyr.sh :3              # custom display
#   ./test-xephyr.sh :3 2560x1080    # custom display + resolution
#   CHECK_ONLY=1 ./test-xephyr.sh    # only validate, do not launch
#
set -euo pipefail

# Anchor every path to the repo root (this script's directory), so it works
# regardless of the current working directory.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${ROOT}/src/config.py"
QTILE="${ROOT}/.venv/bin/qtile"

DISPLAY_NUM="${1:-:2}"
SCREEN="${2:-1920x720}"

# --- preconditions --------------------------------------------------------
[[ -x "${QTILE}" ]] || { echo "✗ qtile not found at ${QTILE} (is the venv set up?)"; exit 1; }
[[ -f "${CONFIG}" ]] || { echo "✗ config not found at ${CONFIG}"; exit 1; }
command -v Xephyr >/dev/null || { echo "✗ Xephyr not installed (sudo apt install xserver-xephyr)"; exit 1; }

# --- 1. validate the config ----------------------------------------------
echo "→ Validating ${CONFIG} ..."
"${QTILE}" check -c "${CONFIG}"
echo "✓ Config is valid."

[[ "${CHECK_ONLY:-0}" == "1" ]] && { echo "CHECK_ONLY set — not launching."; exit 0; }

# --- 2. launch Xephyr + qtile --------------------------------------------
echo "→ Starting Xephyr on ${DISPLAY_NUM} (${SCREEN}) ..."
Xephyr -br -ac -noreset -screen "${SCREEN}" "${DISPLAY_NUM}" &
XEPHYR_PID=$!

# Kill Xephyr when this script exits (Ctrl-C, qtile quit, error).
cleanup() { kill "${XEPHYR_PID}" 2>/dev/null || true; }
trap cleanup EXIT

# Give the X server a moment to come up before qtile connects.
for _ in {1..20}; do
  DISPLAY="${DISPLAY_NUM}" xset q >/dev/null 2>&1 && break
  sleep 0.1
done

echo "→ Starting qtile (config: ${CONFIG}) ..."
DISPLAY="${DISPLAY_NUM}" "${QTILE}" start -c "${CONFIG}"
