# qtile-windown-manager
My own modified tiling window manage

Installation guide:

Install dependencies:
  ```
  sudo apt install xorg python3-xcffib python3-pip python3-cairocffi libcairo2 lightdm python3-psutil
  ```
  
Install ubuntu nerd font:
```
wget https://github.com/ryanoasis/nerd-fonts/releases/download/v2.1.0/UbuntuMono.zip
unzip UbuntuMono.zip -d UbuntuMono
mv UbuntuMono /usr/share/fonts
```

  Install the terminal you are gonna use.

Clone repository:
  ```
  cd ~/.config
  git clone git://github.com/vaayroon/qtile.git
  ```

  Change default terminal:
  Edit config file
    ```
    nano ~/.config/qtile/config.py
    ```
  and replace "myTerm = "/usr/bin/qterminal" by your terminal, fo example: "/usr/bin/gnome-terminal"

Install qtile (http://docs.qtile.org/en/latest/manual/install/):
  I use to install qtile as following:
    ```
    pip install qtile
    ```
    
Test it with Xephyr ($ apt-get install xserver-xephyr):
  ```
  Xephyr -br -ac -noreset -screen 1280x720 :1 & DISPLAY=:1 /usr/local/bin/qtile start
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
Exec=/usr/local/bin/qtile start
Type=Application
Keywords=wm;tiling

```
Select windows manager and login:

![Qtile](https://github.com/vaayroon/qtile/blob/main/.screenshots/select_manager.png)
