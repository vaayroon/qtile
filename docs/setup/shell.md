# Shell and terminal setup

This guide sets up the shell that goes with this desktop: zsh with
Powerlevel10k (no oh-my-zsh), a few plugins, `lsd`, `bat` and `fzf`, and the
kitty terminal. It does not depend on Qtile, so it works on any desktop. The
package names below are the Ubuntu 24.04 ones.

The configs live in the public [vaayroon/config](https://github.com/vaayroon/config)
repo, under `linux/`.

## Quick path

1. Install the packages:

   ```bash
   sudo apt install zsh zsh-syntax-highlighting zsh-autosuggestions \
       fzf lsd bat scrub xclip git curl
   ```

2. Install the sudo plugin, the personal zsh modules and Powerlevel10k
   ([Plugins](#plugins) and [Powerlevel10k](#powerlevel10k)).
3. Download the zshrc and the kitty config ([zshrc](#zshrc) and [kitty](#kitty)).
4. Make zsh your login shell, log out and back in, and run `p10k configure`.
5. Optional: give root the same shell ([Root shell](#root-shell)).

## Packages

| Package | Used by the zshrc for |
|---|---|
| `zsh` | The shell itself |
| `zsh-syntax-highlighting` | Colors commands while you type |
| `zsh-autosuggestions` | Suggests commands from history and completions |
| `fzf` | `Ctrl+R` history search, `Ctrl+T` file picker and the `fzf-lovely` preview function |
| `lsd` | The `ls`, `l`, `ll`, `la` and `lla` aliases |
| `bat` | The `cat` alias. On Ubuntu the binary is `batcat`; `catnormal` runs the real `cat` |
| `scrub` | The `rmk` function, which scrubs and then shreds files |
| `xclip` | The VClip module (clipboard commands) |

All of them are in the Ubuntu 24.04 archive; `lsd` no longer needs a `.deb`
from GitHub.

The icons in `lsd` and in the prompt need a Nerd Font in the terminal. The
kitty config uses `CaskaydiaCove Nerd Font`, the same font as the bar.
`./install.sh --nerd-font` in this repo installs it.

## Plugins

The zshrc sources each plugin from a fixed path under `/usr/share`. apt
installs syntax highlighting, autosuggestions and the fzf key bindings there.
Install the other two by hand.

**sudo plugin.** Press `Esc` twice to put `sudo` in front of the current
command. It comes from oh-my-zsh, but works without the rest of it:

```bash
sudo mkdir -p /usr/share/zsh-sudo
sudo curl -fsSL -o /usr/share/zsh-sudo/sudo.plugin.zsh \
    https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/plugins/sudo/sudo.plugin.zsh
```

**Personal modules.** VGitAliases (git aliases in the style of oh-my-zsh) and
VClip (clipboard commands) live in the config repo:

```bash
git clone --depth=1 https://github.com/vaayroon/config.git /tmp/vaayroon-config
sudo mkdir -p /usr/share/zsh-vaayroon
sudo cp -r /tmp/vaayroon-config/linux/Modules/VGitAliases \
    /tmp/vaayroon-config/linux/Modules/VClip /usr/share/zsh-vaayroon/
```

| Path the zshrc sources | Comes from |
|---|---|
| `/usr/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh` | apt |
| `/usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh` | apt |
| `/usr/share/doc/fzf/examples/key-bindings.zsh` and `completion.zsh` | apt (`fzf`) |
| `/usr/share/zsh-sudo/sudo.plugin.zsh` | oh-my-zsh, by hand |
| `/usr/share/zsh-vaayroon/{VGitAliases,VClip}/*.zsh` | vaayroon/config, by hand |

## Powerlevel10k

[Powerlevel10k](https://github.com/romkatv/powerlevel10k) is the prompt theme.
Clone it into your home; the zshrc already sources it from there:

```bash
git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ~/.powerlevel10k
```

Do not append a `source` line to `~/.zshrc` as the Powerlevel10k README says.
The zshrc already has it, and a second one loads the theme twice.

## zshrc

```bash
curl -fsSL -o ~/.zshrc \
    https://raw.githubusercontent.com/vaayroon/config/main/linux/.zshrc
```

> The zshrc is a personal file. Besides the shell setup above, it also
> configures gpg-agent as the SSH agent and adds tools such as dotnet, fnm,
> pnpm, cargo and Go to `PATH`. Read it before you use it, and remove what you
> do not need.

Make zsh your login shell, then log out and back in:

```bash
chsh -s /usr/bin/zsh
```

## Prompt

The first zsh start runs the Powerlevel10k wizard. Run it again at any time
with `p10k configure`. It writes `~/.p10k.zsh`, which the zshrc sources.

| Wizard question | Choice |
|---|---|
| Prompt style | Classic |
| Character set | Unicode |
| Prompt color | Dark |
| Show current time | No |
| Prompt separators | Angled |
| Prompt heads | Sharp |
| Prompt tails | Slanted |
| Prompt height | One line |
| Prompt spacing | Sparse |
| Icons | Many icons |
| Prompt flow | Fluent |
| Transient prompt | Yes |
| Instant prompt mode | Verbose |

Then edit `~/.p10k.zsh`:

1. Add `command_execution_time` and `context` to `POWERLEVEL9K_LEFT_PROMPT_ELEMENTS`.
2. Comment out every element of `POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS`, so
   nothing shows on the right.
3. Comment out `POWERLEVEL9K_CONTEXT_PREFIX`, which prints `with` before the
   user name.

## kitty

kitty is the terminal that `mod + Return` opens. `packages/apt.txt` installs
it. Download the config and its color file:

```bash
mkdir -p ~/.config/kitty
curl -fsSL -o ~/.config/kitty/kitty.conf \
    https://raw.githubusercontent.com/vaayroon/config/main/linux/kitty/kitty.conf
curl -fsSL -o ~/.config/kitty/color.ini \
    https://raw.githubusercontent.com/vaayroon/config/main/linux/kitty/color.ini
```

`kitty.conf` includes `color.ini`, uses `CaskaydiaCove Nerd Font` and starts
`zsh`. Press `Ctrl+Shift+F5` in kitty to reload it.

## Root shell

`sudo -i` opens a root shell with root's own config, which is empty. To give
root the same setup:

```bash
sudo ln -sf "$HOME/.zshrc" /root/.zshrc
sudo git clone --depth=1 https://github.com/romkatv/powerlevel10k.git /root/.powerlevel10k
sudo chsh -s /usr/bin/zsh root
```

The symlink keeps one zshrc for both users. Root still gets its own
`~/.p10k.zsh`: run `p10k configure` once as root.

To see at a glance that you are root, set the root template in root's
`/root/.p10k.zsh` to an icon, such as `nf-dev-codeigniter` from the
[Nerd Fonts cheat sheet](https://www.nerdfonts.com/cheat-sheet):

```zsh
typeset -g POWERLEVEL9K_CONTEXT_ROOT_TEMPLATE='<icon>'
```

## Editor

The legacy guide installed [NvChad](https://nvchad.com/) for Neovim. That
setup is out of scope here; follow the
[NvChad install guide](https://nvchad.com/docs/quickstart/install). It needs a
Nerd Font, which the kitty config already uses, and `ripgrep`.

## Checklist

- [ ] `echo $SHELL` prints `/usr/bin/zsh` after a new login.
- [ ] The prompt shows Powerlevel10k icons, not empty boxes.
- [ ] `ls` shows `lsd` icons, and `cat` highlights syntax.
- [ ] `Ctrl+R` opens the fzf history search.
- [ ] Pressing `Esc` twice puts `sudo` in front of the command.
- [ ] A new zsh prints no `no such file or directory` errors.
