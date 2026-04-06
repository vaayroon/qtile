"""
Qtile configuration modules.

This package contains the core modules for Qtile configuration.
"""

# Import key components to make them available at the module level
from .groups import init_groups
from .hooks import init_hooks
from .keys import init_keys
from .layouts import init_layouts
from .mouse import init_mouse
from .screens import generate_screens_module, init_screens
from .widgets import init_widgets_screen1, init_widgets_screen2, init_widgets_screen3

__all__ = [
    "init_keys",
    "init_groups",
    "init_layouts",
    "generate_screens_module",
    "init_screens",
    "init_mouse",
    "init_hooks",
    "init_widgets_screen1",
    "init_widgets_screen2",
    "init_widgets_screen3",
]
