"""
Qtile configuration modules.

This package contains the core modules for Qtile configuration.
"""

# Import key components to make them available at the module level
from .keys import init_keys
from .groups import init_groups
from .layouts import init_layouts
from .screens import init_screens
from .mouse import init_mouse
from .hooks import init_hooks
from .widgets import init_widgets_screen1, init_widgets_screen2, init_widgets_screen3

__all__ = [
    'init_keys',
    'init_groups',
    'init_layouts',
    'init_screens',
    'init_mouse',
    'init_hooks',
    'init_widgets_screen1',
    'init_widgets_screen2',
    'init_widgets_screen3',
]