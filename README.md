# Qtile — Personal Tiling Window Manager Config

A complete, batteries-included [Qtile](https://qtile.org/) configuration for X11: multi-monitor aware, Nerd Font powerline bar, media/brightness keys, and a custom widget to mirror and control an Android phone over wireless ADB + scrcpy.

> Built and tested on Ubuntu 24.04.4 LTS with Python 3.12 and Qtile 0.37.1.

![Session selector](.screenshots/select_manager.png)

---

## Features

- **Modular config** — keys, groups, layouts, screens, hooks, and widgets live in separate files under `src/modules/`.
- **Dynamic multi-monitor** — screens are detected at startup via `xrandr`; monitor order is configurable by serial or port.
- **11 layouts** — MonadTall, MonadWide, Max, Tile, Stack, TreeTab, Matrix, and more.
- **Powerline status bar** — system updates, crypto ticker, CPU/GPU temps, memory, network, clock, and a system tray.
- **Phone mirroring widget** — start/stop scrcpy, reconnect ADB, and control phone volume straight from the bar.
- **`.env`-driven** — runtime behavior (monitor ordering, phone mirror) is configured through environment variables, not hardcoded.
- **Reproducible deps** — managed and locked with [uv](https://docs.astral.sh/uv/) (`uv.lock`, exact installs); linted and type-checked with `ruff` and `mypy`.

---

## Requirements

- An **X11** session (this config targets the X backend, not Wayland).
- **Python 3.12+** from your distro (`/usr/bin/python3.12`). The venv backs your login session, so `install.sh` builds it on that exact interpreter (override with `PYTHON=/path/to/python3.12 ./install.sh`) and fails if `.venv/pyvenv.cfg` says otherwise; uv never downloads a Python. Merely having a Homebrew or pyenv Python earlier on your `PATH` does not change this.
- **[uv](https://docs.astral.sh/uv/)** — manages the virtual environment and dependencies. `install.sh` requires it but never installs it for you:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  Other installation methods are listed in the [uv docs](https://docs.astral.sh/uv/getting-started/installation/).
- A **Nerd Font** installed — the bar uses `CaskaydiaCove Nerd Font`. Grab it from [nerdfonts.com](https://www.nerdfonts.com/).
- A display manager that reads `/usr/share/xsessions/` (LightDM, GDM, SDDM, etc.).

---

## Quick start

This config is designed to live at `~/.config/qtile`.

```bash
git clone https://github.com/vaayroon/qtile.git ~/.config/qtile
cd ~/.config/qtile
./install.sh
```

`install.sh` syncs the virtual environment from `uv.lock`, sets up `.env` from
the template, and registers the X session entry (the X session step prompts for
`sudo`). Then **log out and pick "Qtile (venv)"** from your display manager.

Useful flags:

| Flag | Effect |
|---|---|
| `--dev` | Also install the dev tools (`ruff`, `mypy`, `pytest`, `pytest-asyncio`). Without it they are removed. |
| `--force` | Recreate the virtual environment. The old one is moved to `.venv.bak` while the new one is synced, restored if the sync fails, and deleted once it succeeds. |
| `--skip-xsession` | Don't touch `/usr/share/xsessions` (no `sudo`). |

> The script is re-runnable. `.env` is never overwritten, and `.venv` is
> converged to `uv.lock` on every run: missing packages are installed and
> unlocked ones are pruned (dev tools included, unless `--dev`). uv leaves the
> venv's seed packages (such as `pip`) alone, so they may still be present.
> Use `--force` to rebuild the venv from scratch. If the sync fails, the script
> exits non-zero before writing `.env` or any session entry.

### Manual setup

Prefer to do it by hand? The steps the script performs:

```bash
uv sync --locked --no-dev                    # 1. .venv + runtime dependencies from uv.lock
cp .env.example .env && $EDITOR .env         # 2. configure
```

Then register the session by creating `/usr/share/xsessions/qtile-venv.desktop`:

```ini
[Desktop Entry]
Name=Qtile (venv)
Comment=Qtile Session
Type=Application
Keywords=wm;tiling
Path=/home/YOUR_USER/.config/qtile
Exec=/home/YOUR_USER/.config/qtile/.venv/bin/qtile start -c /home/YOUR_USER/.config/qtile/src/config.py
```

> ⚠️ Replace `YOUR_USER` with your username. `Exec` and `Path` must be absolute —
> the display manager does not expand `~`. `Path` sets the working directory so
> `.env` is loaded; without it your configuration is silently ignored.

### Try it without logging out

Test the config in a nested X server with [Xephyr](https://wiki.archlinux.org/title/Xephyr):

```bash
sudo apt install xserver-xephyr
Xephyr -br -ac -noreset -screen 1280x720 :1 &
DISPLAY=:1 .venv/bin/qtile start -c src/config.py
```

### Upgrading from a pip-based install

If your clone's `.venv` was created by an older `install.sh` (pip and
the old requirements files), migrate it once. The session entry does not change, because
it still launches `.venv/bin/qtile`. Do it from a TTY, not from inside the Qtile
session:

1. Install uv and confirm it works: `uv --version`.
2. Log out of the Qtile session and switch to a TTY (for example `Ctrl+Alt+F3`).
3. Update the clone:

   ```bash
   cd ~/.config/qtile
   git switch main && git pull --ff-only
   ```

4. Keep the old environment as a backup and build the new one:

   ```bash
   mv .venv .venv.pip
   ./install.sh --skip-xsession
   ```

5. Check it: `.venv/bin/qtile --version` should print `0.37.1`, then validate the
   config with `.venv/bin/qtile check -c src/config.py` (it needs no X server)
   and log back in.
6. Once everything is stable, delete the backup: `rm -rf .venv.pip`.

**Rollback:** the backup only works under its original name, because the scripts
inside a venv embed absolute paths: `.venv.pip/bin/qtile` points at
`.venv/bin/python`, i.e. at the new environment. From a TTY, run
`rm -rf .venv && mv .venv.pip .venv`. The repository does not need to be reverted
for the old environment to start.

---

## Configuration

Runtime behavior is controlled through `.env` (loaded by `python-dotenv` at startup). Copy `.env.example` and adjust:

### Monitors

| Variable | Default | Purpose |
|---|---|---|
| `QTILE_SCREEN_SERIAL_ORDER` | _(empty)_ | Comma-separated monitor serials, highest priority for ordering. |
| `QTILE_SCREEN_PORT_ORDER` | `DP-0,HDMI-0,DP-2` | Port-name fallback order when serials are missing. |
| `QTILE_INTERNAL_OUTPUTS` | `eDP-1` | Outputs treated as the internal laptop panel. |
| `QTILE_PRIMARY_MONITOR` | _(empty)_ | Force a specific output to be `--primary`. |

### Phone mirroring

| Variable | Default | Purpose |
|---|---|---|
| `QTILE_PHONE_MIRROR_WIRELESS_TARGET` | _(empty)_ | ADB wireless target, e.g. `192.168.1.15:5555`. |
| `QTILE_PHONE_MIRROR_DEVICE` | _(empty)_ | Fixed ADB serial (empty = first device found). |
| `QTILE_PHONE_MIRROR_ADB_PATH` | `/opt/genymobile/adb` | Path to the `adb` binary. |
| `QTILE_PHONE_MIRROR_SCRCPY_PATH` | `scrcpy` | Path to the `scrcpy` binary. |
| `QTILE_PHONE_MIRROR_SCREEN_OFF` | `true` | Start scrcpy with the phone screen off (`-S`). |
| `QTILE_PHONE_MIRROR_SHOW_DEVICE` | `false` | Append the device serial to the bar status text. |
| `QTILE_PHONE_MIRROR_VOLUME_STEP` | `5` | ADB volume key-events sent per scroll tick. |

### Startup

| Variable | Default | Purpose |
|---|---|---|
| `QTILE_AUTOSTART_PATH` | _(empty)_ | Script run once per login (empty = [`autostart.sh`](autostart.sh) from this checkout). |

The script is started in the background; a missing or non-executable script only logs a warning. Its output is written to `$XDG_DATA_HOME/qtile/autostart.log` (default `~/.local/share/qtile/autostart.log`) and truncated each session.

### Appearance

Colors, borders, fonts, and the terminal are defined in [`src/settings.py`](src/settings.py):

- **Mod key**: `Super` (Windows key).
- **Borders**: 2px, focused `#117af0`, normal `#1D2330`, 6px gaps.
- **Bar font**: `CaskaydiaCove Nerd Font`, size 12.

---

## Keybindings

`mod` = `Super` (Windows key).

### Windows & layouts

| Keys | Action |
|---|---|
| `mod + Tab` | Cycle to next layout |
| `mod + j` / `mod + k` | Move focus up / down the stack |
| `mod + Shift + j` / `mod + Shift + k` | Shuffle window up / down |
| `mod + h` / `mod + l` | Grow / shrink window (or adjust master count) |
| `mod + n` | Normalize window sizes |
| `mod + m` | Toggle maximize |
| `mod + Shift + f` | Toggle floating |
| `mod + Shift + m` | Toggle fullscreen |
| `mod + space` | Switch focus between stack panes |
| `mod + Shift + space` | Flip the main pane side |
| `mod + Ctrl + Return` | Toggle split / unsplit |
| `mod + Shift + c` | Close window |
| `mod + Shift + r` | Reload config |
| `mod + Shift + q` | Quit Qtile |

### Groups (workspaces)

| Keys | Action |
|---|---|
| `mod + 1…7` | Switch to group |
| `mod + Shift + 1…7` | Move focused window to group |

### Monitors

| Keys | Action |
|---|---|
| `mod + w` / `mod + e` / `mod + r` | Focus monitor 1 / 2 / 3 |
| `mod + period` / `mod + comma` | Focus next / previous monitor |

### Launchers

| Keys | Action |
|---|---|
| `mod + Return` | Terminal (`kitty`) |
| `mod + Shift + Return` | `dmenu` run prompt |
| `Menu` | App launcher (`rofi`) |
| `mod + Alt + <key>` | Quick-launch apps (browser, files, editor, Spotify, screenshots…) |

### Media, audio & brightness

| Keys | Action |
|---|---|
| `XF86AudioRaise/Lower/Mute` | Volume via `pamixer` |
| `XF86AudioPlay/Next/Prev/Stop` | Playback via `playerctl` |
| `XF86MonBrightnessUp/Down` | Brightness via `brightnessctl` |
| `Ctrl + Alt + l` | Lock screen (`i3lock`) |

> The full, authoritative list lives in [`src/modules/keys.py`](src/modules/keys.py).

---

## The status bar

Left to right, the bar shows: group box → window name → available updates → BTC/EUR ticker → CPU & GPU temps → memory → network → **phone mirror** → clock → current layout → system tray (primary monitor only).

### Phone mirror widget

A custom widget ([`src/widgets/phone_mirror.py`](src/widgets/phone_mirror.py)) that controls scrcpy from the bar:

| Interaction | Action |
|---|---|
| **Left click** | Start / stop mirroring |
| **Right click** | Force wireless ADB reconnect |
| **Middle click** | Toggle "phone screen off" mode |
| **Scroll up / down** | Phone volume up / down |

Status text: `PHONE:READY` (connected, idle) · `PHONE:MIRROR` (running) · `PHONE:DISC` (no device) · `PHONE:ERR` (adb/scrcpy not found). If a binary is missing it opens a `zenity`/`tkinter` dialog to fix paths and targets on the fly.

---

## External tools

The config spawns external programs for keybindings, the bar, and widget click actions. Install the ones you use.

**Core (recommended):**

```bash
sudo apt install kitty rofi suckless-tools pamixer playerctl \
  brightnessctl i3lock flameshot x11-xserver-utils
```

**Status bar & autostart helpers:**

```bash
sudo apt install lm-sensors htop glances \
  cbatticon volumeicon-alsa udiskie network-manager-gnome blueman
```

**Phone mirroring:** [`adb`](https://developer.android.com/tools/adb) and [`scrcpy`](https://github.com/Genymobile/scrcpy) (the config expects them under `/opt/genymobile/`; override via `.env`).

Other optional integrations referenced in keybindings: `nautilus`, `pavucontrol`, `psensor`, `cointop`, `gnome-calendar`, `brave-browser`, `code-insiders`, `spotify`, and remote-desktop clients. None are required — unbound tools simply do nothing when their key is pressed.

---

## Full desktop setup

The sections above cover Qtile itself. To reproduce the rest of the desktop (audio, systray, notifications, themes, display manager, shell and terminal), follow the guide for your distro:

| Distro | Guide | Status |
|--------|-------|--------|
| Kali Linux | [docs/setup/kali.md](docs/setup/kali.md) | Legacy (2022), may be outdated |

---

## Development

Dependencies are declared in **`pyproject.toml`** (the single source of truth)
and locked to exact versions in **`uv.lock`**, which is generated: never edit it
by hand and always commit it together with the `pyproject.toml` change that
caused it. The dev tools (`ruff`, `mypy`, `pytest`, `pytest-asyncio`) live in the
`dev` dependency group.

```bash
uv sync --locked                 # runtime + dev tools, exactly as locked
                                 # (plain `uv sync` installs the dev group too)

# Lint, type-check, test
uv run --locked ruff check src tests
uv run --locked mypy src
uv run --locked pytest

# Format the files you changed
uv run --locked ruff format <files>
```

> `--locked` makes uv fail instead of silently re-locking when `uv.lock` is out
> of date with `pyproject.toml`.
>
> `ruff format --check .` currently reports `src/utils/scratchpads.py` and
> `tests/utils/test_scratchpads.py`. Both predate the uv migration and are
> reformatted separately, so format only the files you touch rather than the
> whole tree.

### Upgrading dependencies

Upgrades are manual and one package at a time, so each bump can be checked on its
own:

```bash
uv lock --upgrade-package <pkg>   # bump one package inside its allowed range
uv sync --locked                  # apply the new lock to .venv
uv lock --check                   # verify uv.lock still matches pyproject.toml
```

Run the lint, type-check and test commands above before committing the new
`uv.lock`.

Qtile itself is pinned exactly (`qtile==X.Y.Z`), because the config and the tests
rely on libqtile internals. To upgrade it, change the pin in `pyproject.toml`,
`project.version` (it mirrors the pin) and the version in the README banner
together, then run `uv lock --upgrade-package qtile` and `uv sync --locked`. The
contract tests fail if the pin, `project.version`, the README banner and
`uv.lock` disagree.

---

## Project structure

```
src/
├── config.py        # Qtile entry point — assembles everything
├── settings.py      # Mod key, terminal, colors, fonts, layout theme
├── modules/         # groups · hooks · keys · layouts · mouse · screens · widgets
├── widgets/         # Custom widgets (PhoneMirrorWidget)
└── utils/           # colors · network · startup · system helpers
pyproject.toml       # Project metadata + dependency declarations (source of truth)
uv.lock              # Generated uv lock file (exact versions of every package)
.python-version      # Python minor version uv uses (3.12)
.env.example         # Template for runtime configuration
install.sh           # Bootstrap script (uv sync, .env, X session)
docs/setup/          # Per-distro full desktop setup guides
.screenshots/        # README assets
```

---

## License

Personal configuration — use it, fork it, adapt it freely.
