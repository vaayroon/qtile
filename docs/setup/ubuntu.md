# Ubuntu 24.04 desktop setup

This guide covers the desktop around Qtile on Ubuntu 24.04: audio, screens,
notifications, GTK and Qt themes, and the display manager. It assumes the
config is already installed. For the shell and the terminal, see
[shell.md](shell.md).

## Quick path

1. Install Qtile with the [README quick start](../../README.md#quick-start):

   ```bash
   ./install.sh --system-packages --nerd-font
   ```

2. Install the desktop extras that [`packages/apt.txt`](../../packages/apt.txt)
   does not list:

   ```bash
   sudo apt install pavucontrol arandr notification-daemon libnotify-bin \
       qt5ct qt5-style-kvantum qt5-style-kvantum-themes xserver-xephyr
   ```

3. Register the notification daemon with D-Bus ([Notifications](#notifications)).
4. Install and select the themes ([GTK theme](#gtk-theme) and [Qt theme](#qt-theme)).
5. Log out, pick **Qtile (venv)** in GDM ([Display manager](#display-manager)),
   and check the result with the [checklist](#checklist).

## What install.sh already does

| Step | Where |
|---|---|
| Virtual environment, `.env`, X session entry, rofi launchers | `./install.sh` |
| System packages: keybinding targets, bar tools, tray applets | `./install.sh --system-packages` ([`packages/apt.txt`](../../packages/apt.txt)) |
| `CaskaydiaCove Nerd Font` for your user | `./install.sh --nerd-font` |
| Keyring and tray applets at login | [`autostart.sh`](../../autostart.sh) |
| Monitor layout at login | `.env`, see [Monitors](../../README.md#monitors) |

The sections below only cover what is left.

## Audio

Ubuntu 24.04 ships PipeWire as the sound server. `pipewire-pulse` provides the
PulseAudio API, so the PulseAudio tools work unchanged:

| Tool | Role | Package |
|---|---|---|
| `pamixer` | Volume keys (`XF86AudioRaise/Lower/Mute`) | `packages/apt.txt` |
| `playerctl` | Media keys | `packages/apt.txt` |
| `volumeicon` | Tray volume icon | `packages/apt.txt` |
| `pavucontrol` | Graphical mixer: outputs, inputs and per-app volume | Quick path step 2 |

Do not install the `pulseaudio` package. Ubuntu's `pipewire-audio` package
conflicts with it, so apt would remove PipeWire's audio set.

Check that the PulseAudio API is served by PipeWire:

```bash
pactl info | grep "Server Name"
# Server Name: PulseAudio (on PipeWire 1.0.5)
```

## Screens

Qtile sets the monitor layout once per login with `xrandr`, from the variables
in `.env` (see [Monitors](../../README.md#monitors)). Make lasting changes
there.

Use `arandr` to inspect the outputs or to try a layout during a session. A
layout saved from `arandr` is not applied at the next login unless you run its
script yourself.

```bash
xrandr --query     # connected outputs and their names, such as DP-0 or eDP-1
arandr
```

## Notifications

`notification-daemon` shows the pop-ups that `notify-send` and other apps
send. On Ubuntu 24.04 the package ships the binary but no D-Bus service file,
so nothing starts it on demand. Register it for your user (no `sudo` needed):

```bash
mkdir -p ~/.local/share/dbus-1/services
cat > ~/.local/share/dbus-1/services/org.freedesktop.Notifications.service <<'EOF'
[D-BUS Service]
Name=org.freedesktop.Notifications
Exec=/usr/lib/notification-daemon/notification-daemon
EOF
```

Log out and back in, then test it:

```bash
notify-send "Notification test"
```

> To register it for every user instead, write the same file to
> `/usr/share/dbus-1/services/` with `sudo`. No package owns that path, so
> apt never replaces it.

## GTK theme

The reference desktop uses the **Orchis-Light** GTK theme and the
**Tela-light** icons. Both come from their upstream install scripts:

```bash
git clone --depth=1 https://github.com/vinceliuice/Orchis-theme.git /tmp/Orchis-theme
sudo /tmp/Orchis-theme/install.sh -d /usr/share/themes

git clone --depth=1 https://github.com/vinceliuice/Tela-icon-theme.git /tmp/Tela-icon-theme
sudo /tmp/Tela-icon-theme/install.sh -d /usr/share/icons
```

> Without `sudo` and `-d`, the scripts install into your home instead
> (`~/.themes` and `~/.local/share/icons`).

Qtile does not run a settings daemon, so GTK apps read their theme from
`settings.ini`. Put these lines in both `~/.config/gtk-3.0/settings.ini` and
`~/.config/gtk-4.0/settings.ini`:

```ini
[Settings]
gtk-theme-name=Orchis-Light
gtk-icon-theme-name=Tela-light
gtk-application-prefer-dark-theme=0
```

Restart the GTK apps to apply it. libadwaita apps (most GTK 4 GNOME apps)
ignore `gtk-theme-name`. To theme them too, run the Orchis script with `-l`,
which links the theme into `~/.config/gtk-4.0`.

## Qt theme

Qt apps ignore the GTK theme. `qt5ct` lets you pick their style, and the
Kvantum style engine draws it.

1. Tell Qt to use `qt5ct`. Add this line to `~/.profile`, which GDM reads at
   login:

   ```bash
   export QT_QPA_PLATFORMTHEME=qt5ct
   ```

2. Log out and back in, run `qt5ct`, and set **Style** to `kvantum`.
3. Run `kvantummanager` and pick a theme. `KvAdapta` matches Orchis-Light.

Use either `qt5ct` or `QT_STYLE_OVERRIDE=kvantum`, not both. The
[legacy Kali guide](kali.md#qt-tuned-to-kde-and-lxqt) uses the override; it
forces Kvantum but leaves the fonts, icons and colors to each app.

## Display manager

Ubuntu 24.04 uses **GDM**. It lists every session in `/usr/share/xsessions/`,
where `install.sh` registers `qtile-venv.desktop`. No GDM configuration is
needed.

1. Log out.
2. Click your user.
3. Open the gear menu in the bottom-right corner and pick **Qtile (venv)**.
4. Enter your password.

GDM remembers the choice for the next login. If **Qtile (venv)** is missing,
rerun `./install.sh` without `--skip-xsession`.

## Checklist

- [ ] `pactl info` reports `PulseAudio (on PipeWire ...)`, and the volume keys work.
- [ ] `notify-send "Notification test"` shows a pop-up.
- [ ] GTK apps (such as Nautilus) use Orchis-Light and the Tela icons.
- [ ] Qt apps (such as `qt5ct` itself) use the Kvantum theme.
- [ ] The tray shows the volume, network and, on a laptop, battery icons.
- [ ] To test config changes without logging out, run `./test-xephyr.sh` ([Try it without logging out](../../README.md#try-it-without-logging-out)).

## Next step

Set up zsh, its plugins, Powerlevel10k and kitty with [shell.md](shell.md).
