from libqtile.config import Match
from libqtile import layout
from typing import List

# Import all modular components
from modules import init_keys, init_groups, init_layouts, init_screens, init_mouse, init_hooks
from settings import widget_defaults, extension_defaults

# Initialize all components
keys = init_keys()
groups = init_groups()
layouts = init_layouts()
screens = init_screens()
mouse = init_mouse()
init_hooks()  # Set up hooks

# Default widget settings
widget_defaults = widget_defaults
extension_defaults = extension_defaults

# Other global settings
dgroups_key_binder = None
dgroups_app_rules = []  # type: List
main = None
follow_mouse_focus = True
bring_front_click = False
cursor_warp = False

floating_layout = layout.Floating(float_rules=[
    *layout.Floating.default_float_rules,
    Match(wm_class='confirm'),
    Match(wm_class='wps'),
    Match(wm_class='dialog'),
    Match(wm_class='download'),
    Match(wm_class='error'),
    Match(wm_class='gnome-calculator'),
    Match(wm_class='file_progress'),
    Match(wm_class='notification'),
    Match(wm_class='splash'),
    Match(title='TeamViewer'),
    Match(wm_class='toolbar'),
    Match(wm_class='Thunar'),
    Match(wm_class='org.gnome.Nautilus'),
    Match(wm_class='Vmware-modconfig'),
    Match(wm_class='Blueman-manager'),
    Match(wm_class='fortitray'),
    Match(wm_class='Dnieremotewizard'),
    Match(wm_class='endeavour'),
    Match(wm_class='Nm-connection-editor'),
    Match(wm_class='Todoist'),
    Match(wm_class='gnome-todo'),
    Match(wm_class='Xfce4-appfinder'),
    Match(title='virtual-shell'),
    Match(func=lambda c: bool(c.is_transient_for())),
    Match(title='Calendar'),
    Match(title='Volume Control'),
    Match(wm_class='confirmreset'),  # gitk
    Match(wm_class='makebranch'),  # gitk
    Match(wm_class='maketag'),  # gitk
    Match(title='branchdialog'),  # gitk
    Match(title='pinentry'),  # GPG key password entry
    Match(wm_class='ssh-askpass'),  # ssh-askpass
])

auto_fullscreen = True
focus_on_window_activation = "smart"
wmname = "LG3D"