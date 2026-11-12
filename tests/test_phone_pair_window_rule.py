"""The pairing QR window must float, matched by the class kitty is given."""

from pathlib import Path

from src.widgets import phone_mirror_runner as runner

CONFIG = Path(__file__).resolve().parent.parent / "src" / "config.py"


def test_the_qr_window_class_has_a_float_rule() -> None:
    source = CONFIG.read_text()

    assert f'Match(wm_class="{runner.KITTY_QR_CLASS}")' in source


def test_a_window_with_another_class_is_not_covered_by_the_qr_rule() -> None:
    source = CONFIG.read_text()

    assert 'Match(wm_class="kitty")' not in source
