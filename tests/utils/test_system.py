from src.utils.system import _primary_output_name


def test_primary_output_name_single_monitor_ignores_env(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "HDMI-0")

    assert _primary_output_name(["DP-2"]) == "DP-2"


def test_primary_output_name_multi_monitor_returns_env_match(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "DP-1")

    assert _primary_output_name(["DP-1", "HDMI-1"]) == "DP-1"


def test_primary_output_name_multi_monitor_env_not_set_uses_heuristic(monkeypatch):
    monkeypatch.delenv("QTILE_PRIMARY_MONITOR", raising=False)

    assert _primary_output_name(["DP-1", "HDMI-0"]) == "HDMI-0"


def test_primary_output_name_multi_monitor_empty_env_uses_heuristic(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "")

    assert _primary_output_name(["DP-1", "HDMI-0"]) == "HDMI-0"


def test_primary_output_name_multi_monitor_whitespace_env_uses_heuristic(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "   ")

    assert _primary_output_name(["DP-1", "HDMI-0"]) == "HDMI-0"


def test_primary_output_name_multi_monitor_invalid_env_uses_heuristic(monkeypatch):
    monkeypatch.setenv("QTILE_PRIMARY_MONITOR", "FAKE-99")

    assert _primary_output_name(["DP-1", "HDMI-0"]) == "HDMI-0"
