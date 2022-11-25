# qtile-windown-manager
My own modified tiling window manage

## Kali Installation
Installation guide:

Install dependencies:
  ```
  sudo apt install xorg python3-xcffib python3-pip python3-cairocffi libcairo2 lightdm python3-psutil
  ```
  
Install some Fonts from (https://www.nerdfonts.com/):
```
wget https://github.com/ryanoasis/nerd-fonts/releases/download/v2.2.2/UbuntuMono.zip
wget https://github.com/ryanoasis/nerd-fonts/releases/download/v2.2.2/Hack.zip
```
```
unzip UbuntuMono.zip -d UbuntuMono
unzip Hack.zip -d HackNerFont
```
```
mv UbuntuMono /usr/share/fonts
mv HackNerdFont /usr/share/fonts
```

  Install the terminal you are gonna use(My default will be kitty).
  
  ```
  sudo apt install -y kitty qterminal
  ```

Clone repository:
  ```
  cd ~/.config
  ```
  ```
  git clone git://github.com/vaayroon/qtile.git
  ```

  Change default terminal:
  Edit config file
  ```
  nano ~/.config/qtile/config.py
  ```
  and replace "myTerm = "/usr/bin/kitty" by your terminal, fo example: "/usr/bin/qterminal"

Install qtile (http://docs.qtile.org/en/latest/manual/install/):
  I use to install qtile as following:
  ```
  pip install qtile
  ```
Running without sudo will install qtile inside your home local bin folder ("/home/vaayroon/.local/bin")

Test it with Xephyr (```apt-get install xserver-xephyr```):
  ```
  Xephyr -br -ac -noreset -screen 1280x720 :1 & DISPLAY=:1 /home/vaayroon/.local/bin/qtile start
  ```

Create xsession:
  ```
  sudo nano /usr/share/xsessions/qtile-venv.desktop
  ```
  And copy the following:
```php

[Desktop Entry]
Name=Qtile(venv)
Comment=Qtile Session
Exec=/home/vaayroon/.local/bin/qtile start
Type=Application
Keywords=wm;tiling

```
Select windows manager and login:

![Qtile](https://github.com/vaayroon/qtile/blob/main/.screenshots/select_manager.png)

## Optional widget tools

In some widgets there is defined some tools to be launched when clicked. The tools are optional but in order for them to work you need to install the following packages:
``` 
sudo apt install i3lock htop glances gnome-calendar xfce4-sensors-plugin xfce4-settings apt-show-versions
```

Another Optial tool is **[cointop](https://docs.cointop.sh/)**. A good application for tracking and monitoring cryptocurrency coin stats in real-time
Before installing it we will need **[go](https://go.dev/)** in order to be able to install cointop.

To install go there are 2 ways:

- The simple way is to install throught apt.
```
sudo apt install golang
```
- The other way is to install from **[source](https://go.dev/dl/)**.
  - Remove any previuos Go installation:
    ```
    sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go1.19.3.linux-amd64.tar.gz
    ```
  - Add $HOME/go/bin to the PATH environment variable:
    ```
    export PATH=$PATH:$HOME/go/bin
    ``` 
  - Verify that you've installed Go:
    ```
    go version
    ```    
Now we can install cointop(as non root user):
```
go install github.com/cointop-sh/cointop@latest
```
By default he cointop executable will be under your $HOME/go/bin/ path, so you will need to add that path to the $PATH enviroment variable if not already.
```
export PATH=$PATH:$HOME/go/bin
$HOME/go/bin/cointop
```

## Audio

For Audio we need
**[pulseaudio](https://wiki.archlinux.org/index.php/PulseAudio)**,
and a graphical program to control audio like
**[pavucontrol](https://www.archlinux.org/packages/extra/x86_64/pavucontrol/)**,
because we don't have keybindings for that yet:

```bash
sudo apt install -y pulseaudio pavucontrol
```

For a better CLI experience and easy to control our volume throught keybinds we will need
**[pamixer](https://github.com/cdemoulins/pamixer)**

```bash
sudo apt install -y pamixer
```

Now you can set up keybindings for pulseaudio, open Qtile's config.py and add these keys if not already or uncomment:
```python
# Audio
Key([], "XF86AudioMute", lazy.spawn("amixer -q set Master toggle")),
Key([], "XF86AudioLowerVolume", lazy.spawn("amixer -c 2 sset Master 1- unmute")),
Key([], "XF86AudioRaiseVolume", lazy.spawn("amixer -c 2 sset Master 1+ unmute")),
```

Now you can control your volume and toggle between mute/unmute,
but you would probably also like to control the media player like play/pause, next/previous song, etc. So we need
**[playerctl](https://github.com/altdesktop/playerctl)**.

```bash
sudo apt install -y playerctl
```


## Screens

If we have multiple monitors, you surely wants to use them, so need
**[xrandr](https://xorg.freedesktop.org/wiki/)**. To install run:
```bash
sudo apt install -y x11-xserver-utils
```

By default the configuration of multiple monitor if  0x0, so we need to specify the position for each output.
If we wanna do graphically we need
**[arandr](https://christian.amsuess.com/tools/arandr/)**
```bash
sudo apt install -y arandr
```

If you're on a laptop, you might also want to control the brightness of your screen, so you need to install
**[brightnessctl](https://github.com/Hummer12007/brightnessctl)**
```bash
sudo apt install -y brightnessctl
```
Now you can set up keybindings to control the brightness of your laptop screen.
Open the Qtile config file and add or uncomment if already set:
```python
#Laptop Screen Brightness
Key([], "XF86MonBrightnessUp", lazy.spawn("brightnessctl set +10%")),
Key([], "XF86MonBrightnessDown", lazy.spawn("brightnessctl set 10%-")),
```

## Systray

By default Qtile have a system tray, but at this point there should be nothing running on it.
You can run the following to check systray:
```bash
udiskie -t &
nm-applet &
volumeicon &
cbatticon &
```
**[udiskie](https://github.com/coldfix/udiskie)** is a front-end that allows to manage removable media such as CDs or flash drives from userspace.
**[nm-applet](https://gitlab.gnome.org/GNOME/network-manager-applet)** is a front-end Tray applet and an advanced network connection editor.
**[volumeicon](https://github.com/Maato/volumeicon)** is a lightweight volume control applet with support for global keybindings.
**[cbatticon](https://github.com/valr/cbatticon)** is a lightweight and fast battery icon that sits in your system tray.

To install them:
```bash
sudo apt install cbatticon volumeicon-alsa udiskie network-manager-gnome -y
```
To run when start Qtile, add the commands to the Qtile autostart.sh ```vim ~/.config/qtile/autostart.sh```

## Notifications
If you wanna have Desktop notifications, you need to install
**[libnotify](https://salsa.debian.org/gnome-team/libnotify)**
**[notification-daemon](https://salsa.debian.org/gnome-team/notification-daemon)**:
```bash
sudo apt install libnotify-bin notification-daemon -y
```

We need to create a new
**[D-Bus](https://wiki.archlinux.org/title/D-Bus)** service:
```bash
sudo nano /usr/share/dbus-1/services/org.freedesktop.Notifications.service
```
And add this lines to the file:
```bash
[D-BUS Service]
Name=org.freedesktop.Notifications
Exec=/usr/lib/notification-daemon-1.0/notification-daemon
```

You can test it:
```bash
notify-send "Notification Test"
```


## Themes

Currently I am using
**[Material-Black-Blueberry](https://www.gnome-look.org/p/1316887/)** ad default theme and
**[Material-Black-Blueberry-Suru](https://www.pling.com/p/1333360/)** as default icons.

You can find other GTK themes on this
**[page](https://www.gnome-look.org/browse/cat/135/)**.

After Downloads the .zip files this is what you have to do:
```bash
cd ~/Downloads
mkdir -p Material-Black-Blueberry
unzip Material-Black-Blueberry-4.0_2.0.zip
mv Material-Black-Blueberry-4.0/* Material-Black-Blueberry
unzip Material-Black-Blueberry-Suru_1.9.3.zip
```
Then move the unzipped files to make the theme and icons available
```bash
cd ~/Downloads
sudo mv Material-Black-Blueberry /usr/share/themes
sudo mv Material-Black-Blueberry-Suru /usr/share/icons
```

Now edit ~/.config/gtk-3.0/settings.ini and ~/.config/gtk-3.0/settings.ini
```touch ~/.config/gtk-3.0/settings.ini && ~/.config/gtk-4.0/settings.ini```
by adding these lines:
```bash
gtk-theme-name = "Material-Black-Blueberry"
gtk-icon-theme-name = "Material-Black-Blueberry-Suru"
```

You need to log in again for the changes to take effect.

In development
