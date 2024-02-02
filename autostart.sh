#! /bin/bash
#picom &
#nitrogen --restore &
#urxvtd -q -o -f &
##Widgets are displayed on the secondary monitor
#2 Monitors (HDMI-1 as primary on the left and DP-3 as secondary on the right)
#xrandr --output eDP-1 --off --output HDMI-1 --primary --mode 1920x1080 --pos 0x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-4 --off

#2 Monitors (HDMI-1 as primary to the right and DP-3 as secondary to the left)
#xrandr --output eDP-1 --off --output HDMI-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-4 --off

#2 Monitors (HDMI-1 as secondary to the right and DP-3 as primary to the left) OFICIAL WORK
xrandr --output eDP-1 --off --output HDMI-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-4 --off

# Monitors Layout
#xrandr --output HDMI-A-0 --mode 1920x1080 --pos 0x0 --rotate normal --output eDP --primary --mode 1920x1080 --pos 0x1080 --rotate normal --output DisplayPort-0 --off &

#Laptop work Layout --> Main Monitor to the right and second to the left
#xrandr --output eDP-1 --off --output HDMI-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-2 --off --output DP-3 --off --output DP-4 --off

#Laptop work 2 Layout --> Main monitor to the bottom and second to the top
#xrandr --output eDP-1 --primary --mode 1920x1200 --pos 0x1080 --rotate normal --output HDMI-1 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off

#Laptop work 3 Layout --> Main monitor to the bottom(laptop display) and DP monitor to the top
#xrandr --output eDP-1 --primary --mode 1920x1200 --pos 0x1080 --rotate normal --output HDMI-1 --off --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off --output DP-1-1 --off --output DP-1-2 --off --output DP-1-3 --mode 1920x1080 --pos 0x0 --rotate normal

#Laptop work Bizarre --> eDP-1 (primary, bottom), DP-1 (top)
#xrandr --output eDP-1 --primary --mode 1920x1200 --pos 732x1080 --rotate normal --output HDMI-1 --off --output DP-1 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-2 --off --output DP-3 --off --output DP-4 --off

#Laptop work Bizarre (HDMI-1 as primary on the left and eDP-1 as secondary on the right) --> OFICIAL HOME
#xrandr --output eDP-1 --mode 1920x1200 --pos 1920x0 --rotate normal --output HDMI-1 --primary --mode 1920x1080 --pos 0x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off

#Laptop Home2 (DP-3-2 as primary on the left and eDP-1 as secondary on the right) --> OFICIAL HOME 2
#xrandr --output eDP-1 --mode 1920x1200 --pos 1600x0 --rotate normal --scale 0.75x0.75 --output HDMI-1 --off --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off --output DP-3-1 --off --output DP-3-2 --primary --mode 1600x900 --pos 0x0 --rotate normal --output DP-3-3 --off

#Laptop Home3 (HDMI-1 as primary on the right and eDP-1 as secondary on the left) --> OFICIAL HOME3
#xrandr --output eDP-1 --mode 1920x1200 --pos 0x0 --rotate normal --output HDMI-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off

#Single Laptop Layout
#xrandr --output eDP-1 --primary --mode 1920x1200 --pos 0x0 --rotate normal --output HDMI-1 --off --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off

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
