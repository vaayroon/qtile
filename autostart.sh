#!/bin/sh
#
# autostart.sh — Start the session helpers and tray applets once per login.
#
# Qtile runs this script in the background at the start of each session. Its
# output goes to $XDG_DATA_HOME/qtile/autostart.log. It is plain POSIX sh, so
# it needs neither zsh nor bash. Every program is optional: a missing one is
# reported in the log and skipped, and the rest still start.

# POWER_SUPPLY_DIR only exists so the tests can point at a fake sysfs.
POWER_SUPPLY_DIR="${POWER_SUPPLY_DIR:-/sys/class/power_supply}"

# Start a program in the background, or report it as missing.
start() {
    if command -v "$1" >/dev/null 2>&1; then
        "$@" &
    else
        echo "autostart: $1 not found, skipping"
    fi
}

# Print the name of the first power supply (in name order) whose type is
# Battery. AC adapters (Mains), USB supplies and the batteries of peripherals
# such as wireless mice (scope Device) are skipped.
first_battery() {
    for supply in "$POWER_SUPPLY_DIR"/*; do
        [ -r "$supply/type" ] || continue
        # No "|| continue": read fails on a last line without a newline, but
        # it still sets the variable.
        read -r supply_type < "$supply/type"
        supply_scope=
        if [ -r "$supply/scope" ]; then
            read -r supply_scope < "$supply/scope"
        fi
        if [ "$supply_type" = Battery ] && [ "$supply_scope" != Device ]; then
            echo "${supply##*/}"
            return 0
        fi
    done
    return 1
}

##### Environment for gnome-keyring-daemon #####

start dbus-update-activation-environment --all
start gnome-keyring-daemon --start --components=secrets

##### Systray icons #####

### Battery icon (skipped on machines without a battery)
battery="$(first_battery)"
if [ -n "$battery" ]; then
    start cbatticon -d -u 5 -r 3 -c "poweroff" -l 15 -o "brightnessctl set 20%" "$battery"
else
    echo "autostart: no battery in ${POWER_SUPPLY_DIR}, skipping cbatticon"
fi

### Volume icon
start volumeicon

### Disk manager
start udiskie -t

### Network manager
start nm-applet

### Bluetooth
start blueman-applet
