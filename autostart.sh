#! /usr/bin/zsh

##### Autostart applications #####

#picom &
#nitrogen --restore &
#urxvtd -q -o -f &

##### Set up the environment for gnome-keyring-daemon #####

dbus-update-activation-environment --all
gnome-keyring-daemon --start --components=secrets

##### Systray Icons #####

### Battery icon
# select battery id from power supply list '-d', for me is BAT1 
cbatticon -d -u 5 -r 3 -c "poweroff" -l 15 -o "brightnessctl set 20%" BAT1 &

### Volume icon
volumeicon &

### Disk manager
udiskie -t &

### Network manager
nm-applet &

### Bluetooth
blueman-applet &
