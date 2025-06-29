from libqtile.config import Screen
from libqtile import bar
from .widgets import init_widgets_screen1, init_widgets_screen2, init_widgets_screen3

### Single monitor support
""" def init_screens():
        return [Screen(top=bar.Bar(widgets=init_widgets_screen1(), opacity=1.0, size=20))] """

### Dual Monitor Support
def init_screens():
    return [
        Screen(top=bar.Bar(widgets=init_widgets_screen1(), opacity=1.0, size=20)),
        Screen(top=bar.Bar(widgets=init_widgets_screen2(), opacity=1.0, size=20))
    ]

### Triple Monitor Support
""" def init_screens():
    return [
        Screen(top=bar.Bar(widgets=init_widgets_screen1(), opacity=1.0, size=20)),
        Screen(top=bar.Bar(widgets=init_widgets_screen2(), opacity=1.0, size=20)),
        Screen(top=bar.Bar(widgets=init_widgets_screen3(), opacity=1.0, size=20))
    ] """