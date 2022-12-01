#! /bin/bash
#picom &
#nitrogen --restore &
#urxvtd -q -o -f &

# Monitors Layout
#xrandr --output HDMI-A-0 --mode 1920x1080 --pos 0x0 --rotate normal --output eDP --primary --mode 1920x1080 --pos 0x1080 --rotate normal --output DisplayPort-0 --off &

# systray battery icon
# select battery id from power supply list '-d', for me is BATT 
cbatticon -d -u 5 -r 3 -c "poweroff" -l 15 -o "xbacklight = 5" &

# systray volume
volumeicon &

# disk manager
udiskie -t &

#network manager
nm-applet &
