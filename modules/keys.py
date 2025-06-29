from libqtile.config import Key
from libqtile.lazy import lazy
from settings import mod, myTerm

keys = [
    # The essentials
    Key([mod], "Return",
        lazy.spawn('kitty'),
        desc='Launches My Terminal'
        ),
    Key([mod, "mod1"], "Return",
        lazy.spawn("kitty --title virtual-shell"),
        desc='Launches Virtual Kitty'
        ),
    Key([mod, "shift"], "Return",
        lazy.spawn("dmenu_run -p 'Run: '"),
        desc='Dmenu Run Launcher'
        ),
    Key([mod], "Tab",
        lazy.next_layout(),
        desc='Toggle through layouts'
        ),
    Key([mod, "shift"], "c",
        lazy.window.kill(),
        desc='Kill active window'
        ),
    Key([mod, "shift"], "r",
        lazy.restart(),
        desc='Restart Qtile'
        ),
    Key([mod, "shift"], "q",
        lazy.shutdown(),
        desc='Shutdown Qtile'
        ),
    Key(["control", "shift"], "e",
        lazy.spawn(myTerm+" sudo -S ls -l"),
        desc='Doom Emacs'
        ),
    Key(["control", "mod1"], "l",
        lazy.spawn("i3lock -ufc 000000")
        ),
    # Switch focus to specific monitor (out of three)
    Key([mod], "w",
        lazy.to_screen(0),
        desc='Keyboard focus to primary monitor'
        ),
    Key([mod], "e",
        lazy.to_screen(1),
        desc='Keyboard focus to secondary monitor'
        ),
    Key([mod], "r",
        lazy.to_screen(2),
        desc='Keyboard focus to tertiary monitor'
        ),
    # Switch focus of monitors
    Key([mod], "period",
        lazy.next_screen(),
        desc='Move focus to next monitor'
        ),
    Key([mod], "comma",
        lazy.prev_screen(),
        desc='Move focus to prev monitor'
        ),
    # Treetab controls
    Key([mod, "control"], "j",
        lazy.layout.section_up(),
        desc='Move up a section in treetab'
        ),
    Key([mod, "control"], "k",
        lazy.layout.section_down(),
        desc='Move down a section in treetab'
        ),
    # Window controls
    Key([mod], "k",
        lazy.layout.down(),
        desc='Move focus down in current stack pane'
        ),
    Key([mod], "j",
        lazy.layout.up(),
        desc='Move focus up in current stack pane'
        ),
    Key([mod, "shift"], "k",
        lazy.layout.shuffle_down(),
        desc='Move windows down in current stack'
        ),
    Key([mod, "shift"], "j",
        lazy.layout.shuffle_up(),
        desc='Move windows up in current stack'
        ),
    Key([mod], "h",
        lazy.layout.grow(),
        lazy.layout.increase_nmaster(),
        desc='Expand window (MonadTall), increase number in master pane (Tile)'
        ),
    Key([mod], "l",
        lazy.layout.shrink(),
        lazy.layout.decrease_nmaster(),
        desc='Shrink window (MonadTall), decrease number in master pane (Tile)'
        ),
    Key([mod], "n",
        lazy.layout.normalize(),
        desc='normalize window size ratios'
        ),
    Key([mod], "m",
        lazy.layout.maximize(),
        desc='toggle window between minimum and maximum sizes'
        ),
    Key([mod, "shift"], "f",
        lazy.window.toggle_floating(),
        desc='toggle floating'
        ),
    Key([mod, "shift"], "m",
        lazy.window.toggle_fullscreen(),
        desc='toggle fullscreen'
        ),
    # Stack controls
    Key([mod, "shift"], "space",
        lazy.layout.rotate(),
        lazy.layout.flip(),
        desc='Switch which side main pane occupies (XmonadTall)'
        ),
    Key([mod], "space",
        lazy.layout.next(),
        desc='Switch window focus to other pane(s) of stack'
        ),
    Key([mod, "control"], "Return",
        lazy.layout.toggle_split(),
        desc='Toggle between split and unsplit sides of stack'
        ),
    # Dmenu scripts launched with ALT + CTRL + KEY
    Key(["mod1", "control"], "e",
        lazy.spawn("./.dmenu/dmenu-edit-configs.sh"),
        desc='Dmenu script for editing config files'
        ),
    Key(["mod1", "control"], "m",
        lazy.spawn("./.dmenu/dmenu-sysmon.sh"),
        desc='Dmenu system monitor script'
        ),
    Key(["mod1", "control"], "f",
        lazy.spawn("./.dmenu/dmenu-trading.sh"),
        desc='Dmenu trading programs script'
        ),
    Key(["mod1", "control"], "p",
        lazy.spawn("passmenu"),
        desc='Passmenu'
        ),
    Key(["mod1", "control"], "t",
        lazy.spawn("nautilus trash:///"),
        desc='Open Trash'
        ),
    # My applications launched with SUPER + ALT + KEY
    Key([mod, "mod1"], "b",
        lazy.spawn("brave-browser-stable --new-window --incognito --explicitly-allowed-ports=10080"),
        desc='Brave Incognito'
        ),
    Key([mod, "mod1"], "d",
        lazy.spawn("nautilus"),
        desc='File browser',
        ),
    Key([mod, "mod1"], "n",
        lazy.spawn("gnome-todo"),
        desc='Take Notes'
        ),
    Key([mod, "mod1"], "a",
        lazy.spawn("anydesk"),
        desc='AnyDesk Remote Desktop'
        ),
    Key([mod, "mod1"], "r",
        lazy.spawn("remmina"),
        desc='Remmina Remote Desktop Client'
        ),
    Key([mod, "mod1"], "t",
        lazy.spawn("rustdesk"),
        desc='RustDesk Remote Desktop'
        ),
    Key([mod, "mod1"], "e",
        lazy.spawn("spotify"),
        desc='Spotify Music Player'
        ),
    Key([mod, "mod1"], "m",
        lazy.spawn("microsoft-edge-dev"),
        desc='Microsfot Edge Developer'
        ),
    Key([mod, "mod1"], "f",
        lazy.spawn("flameshot"),
        desc='Flameshot Screenshot Tool'
        ),
    Key([mod, "mod1"], "p",
        lazy.spawn("pavucontrol"),
        desc='Volume Control Utility'
        ),
    Key([mod, "mod1"], "s",
        lazy.spawn("code-insiders"),
        desc='Visual Studio Code Insiders'
        ),
    Key([mod, "mod1"], "v",
        lazy.spawn("vmware"),
        desc='VMware Workstation Player'
        ),
    Key([mod, "mod1"], "w",
        lazy.spawn("wps"),
        desc='WPS Office Suite'
        ),

    # Application launchers
    Key([], "Menu", lazy.spawn("xfce4-appfinder"), desc='App Finder'),
    Key([], "XF86Favorites", lazy.spawn("xfce4-appfinder"), desc='App Finder'),
    Key([], "XF86HomePage", lazy.spawn("xfce4-appfinder"), desc='App Finder'),

    # Web browser shortcuts
    Key([], "XF86Explorer", lazy.spawn("brave-browser-stable --new-window --incognito"), desc="Private Firefox"),

    # Volume
    Key([], "XF86AudioMute", lazy.spawn("pamixer --toggle-mute"), desc="Toggle Mute"),
    Key([], "XF86AudioLowerVolume", lazy.spawn("pamixer --decrease 2"), desc="Lower Volume"),
    Key([], "XF86AudioRaiseVolume", lazy.spawn("pamixer --increase 2"), desc="Raise Volume"),

    # Audio
    Key([], "XF86AudioPlay", lazy.spawn("playerctl play-pause"), desc="Play/Pause"),
    Key([], "XF86AudioNext", lazy.spawn("playerctl next"), desc="Next Track"),
    Key([], "XF86AudioPrev", lazy.spawn("playerctl previous"), desc="Previous Track"),
    Key([], "XF86AudioStop", lazy.spawn("playerctl stop"), desc="Stop Playback"),

    #Laptop Screen Brightness
    Key([], "XF86MonBrightnessUp", lazy.spawn("brightnessctl set +10%"), desc="Increase Brightness"),
    Key([], "XF86MonBrightnessDown", lazy.spawn("brightnessctl set 10%-"), desc="Decrease Brightness"),

    # Extras
    Key([], "XF86Calculator", lazy.spawn("gnome-calculator"), desc="Open Calculator"),

    # Screen Shots
    Key(["shift", mod], "s", lazy.spawn("flameshot gui"), desc="Flameshot GUI"),
]

def init_keys():
    return keys