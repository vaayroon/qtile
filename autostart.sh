#! /bin/bash
#picom &
#nitrogen --restore &
#urxvtd -q -o -f &

### Monitors Layout
#
#Laptop Layout (Main monitor on top and laptop on bottom)
xrandr --output HDMI-A-0 --mode 1920x1080 --pos 0x0 --rotate normal --output eDP --primary --mode 1920x1080 --pos 0x1080 --rotate normal --output DisplayPort-0 --off &

#Laptop Layout (Main monitor to the left and laptop to the right)
#xrandr --output HDMI-A-0 --mode 1920x1080 --pos 0x0 --rotate normal --output eDP --primary --mode 1920x1080 --pos 1920x526 --rotate normal --output DisplayPort-0 --off

#2 Monitors Layout (Main monitor on the left, secondary on the right)
#xrandr --output DVI-I-1 --mode 1920x1080 --pos 0x0 --rotate normal --output HDMI-1 --primary --mode 1920x1080      --pos 1920x0 --rotate normal --output VGA-1 --off --output DP-1-1 --off --output HDMI-1-2 --off --output DP-1-     2 --off --output HDMI-1-3 --off --output DP-1-3 --off --output HDMI-1-4 --off &


# systray battery icon
# select battery id from power supply list '-d', for me is BATT 
cbatticon -d -u 5 -r 3 -c "poweroff" -l 15 -o "brightnessctl set 5" BATT &

# systray volume
volumeicon &

# disk manager
udiskie -t &

#network manager
nm-applet &

#Bluetooth
blueman-applet &
