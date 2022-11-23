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
## Screens
## Notifications
## Themes

In development
