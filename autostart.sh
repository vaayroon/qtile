#! /bin/bash
#picom &
#nitrogen --restore &
#urxvtd -q -o -f &

# Monitors 2 Layout
xrandr --output eDP-1 --off --output HDMI-1 --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --primary --mode 1920x1080 --pos 0x0 --rotate normal --output DP-4 --off

# Monitors Layout
#xrandr --output HDMI-A-0 --mode 1920x1080 --pos 0x0 --rotate normal --output eDP --primary --mode 1920x1080 --pos 0x1080 --rotate normal --output DisplayPort-0 --off &

#Laptop work Layout --> Main Monitor to the right and second to the left
#xrandr --output eDP-1 --off --output HDMI-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-2 --off --output DP-3 --off --output DP-4 --off

#Laptop work 2 Layout --> Main monitor to the bottom and second to the top
#xrandr --output eDP-1 --primary --mode 1920x1200 --pos 0x1080 --rotate normal --output HDMI-1 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off

# systray battery icon
# select battery id from power supply list '-d', for me is BATT 
#cbatticon -d -u 5 -r 3 -c "poweroff" -l 15 -o "xbacklight = 5" &
cbatticon -d -u 5 -r 3 -c "poweroff" -l 15 -o "xbacklight = 5" BAT0 &

# systray volume
volumeicon &

# disk manager
udiskie -t &

#network manager
nm-applet &

#bluetooth
blueman-applet &
