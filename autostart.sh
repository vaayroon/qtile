#! /bin/bash

##### Widgets are displayed on the primary monitor #####

#picom &
#nitrogen --restore &
#urxvtd -q -o -f &

### Laptop, just 2 external monitors (HDMI-1 as secondary to the right and DP-3 as primary to the left) --> OFICIAL WORK
#xrandr --output eDP-1 --off --output HDMI-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-4 --off

### 3 external monitors (DP-3 as thernary on left, HDMI-1 as primary on mid, DP-1 as secondary on right) -->> OFICIAL WORK 1
#xrandr --output eDP-1 --off --output HDMI-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --mode 1920x1080 --pos 3840x0 --rotate normal --output DP-2 --off --output DP-3 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-4 --off

### Laptop + 1 external monitor (HDMI-1(external) as primary on the left and eDP-1(laptop) as secondary on the right) --> OFICIAL HOME 0
#xrandr --output eDP-1 --mode 1920x1200 --pos 1920x0 --rotate normal --output HDMI-1 --primary --mode 1920x1080 --pos 0x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off

### Laptop + 2 external monitors (eDP-1(Laptop) as secondary to the left, HDMI-1(attached to laptop) as primary on mid, DP-3 from usc-c hub as thernary to the right) --> OFICIAL HOME 1
#xrandr --output eDP-1 --mode 1920x1200 --pos 0x0 --rotate normal --output HDMI-1 --mode 1920x1080 --pos 3840x0 --rotate normal --output DP-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-2 --off --output DP-3 --off --output DP-4 --off

### Laptop + 1 external monitor (DP-3-2 as primary on the left and eDP-1(laptop) as secondary on the right) --> OFICIAL HOME 1
#xrandr --output eDP-1 --mode 1920x1200 --pos 1600x0 --rotate normal --output HDMI-1 --off --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off --output DP-3-1 --off --output DP-3-2 --primary --mode 1600x900 --pos 0x0 --rotate normal --output DP-3-3 --off

### Laptop + 1 external monitor (HDMI-1 as primary on the right and eDP-1(laptop) as secondary on the left) --> OFICIAL HOME 2 (Sevilla)(1600x900)
#xrandr --output eDP-1 --mode 1920x1200 --pos 0x0 --rotate normal --output HDMI-1 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off

### Oficial Home ubuntu
xrandr --output HDMI-0 --off --output DP-0 --off --output DP-1 --off --output DP-2 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-3 --off --output DP-4 --primary --mode 1920x1080 --pos 1920x0 --rotate normal --output DP-5 --off

### Single Laptop Layout (eDP-1)
#xrandr --output eDP-1 --primary --mode 1920x1200 --pos 0x0 --rotate normal --output HDMI-1 --off --output DP-1 --off --output DP-2 --off --output DP-3 --off --output DP-4 --off

### Single Monitor VGA Output (VGA-1)
#xrandr --output DVI-I-1 --off --output HDMI-4 --off --output VGA-1 --mode 1920x1080 --pos 0x0 --rotate normal --output DP-1-1 --off --output HDMI-1-1 --off --output DP-1-2 --off --output HDMI-1-2 --off --output DP-1-3 --off --output HDMI-1-3 --off

##### Systray Icons #####

### Battery icon
# select battery id from power supply list '-d', for me is BATT 
cbatticon -d -u 5 -r 3 -c "poweroff" -l 15 -o "xbacklight = 5" BAT0 &

### Volume icon
volumeicon &

### Disk manager
udiskie -t &

### Network manager
nm-applet &

### Bluetooth
blueman-applet &
