# backend/tests/test_config.py
import pytest
from config import Settings


def test_settings_loads_defaults():
    s = Settings(
        google_api_key="test-key",
        emergency_number="+381601234567",
    )
    assert s.redis_url == "redis://localhost:6379"
    assert s.triage_timeout_seconds == 10
    assert s.confidence_threshold == 0.85
    assert s.reconnect_max_attempts == 3


def test_settings_rejects_112():
    with pytest.raises(ValueError, match="real emergency"):
        Settings(google_api_key="k", emergency_number="112")


def test_settings_rejects_194():
    with pytest.raises(ValueError, match="real emergency"):
        Settings(google_api_key="k", emergency_number="194")


def test_settings_rejects_padded_112():
    with pytest.raises(ValueError, match="real emergency"):
        Settings(google_api_key="k", emergency_number=" 112 ")


def test_settings_rejects_plus_112():
    with pytest.raises(ValueError, match="real emergency"):
        Settings(google_api_key="k", emergency_number="+112")


def test_settings_livedemo_mode_defaults_to_off():
    s = Settings(google_api_key="k", emergency_number="+381601234567")
    assert s.livedemo_mode == "off"


def test_settings_livedemo_mode_full():
    s = Settings(google_api_key="k", emergency_number="+381601234567", livedemo_mode="full")
    assert s.livedemo_mode == "full"


def test_settings_livedemo_mode_lite():
    s = Settings(google_api_key="k", emergency_number="+381601234567", livedemo_mode="LITE")
    assert s.livedemo_mode == "lite"  # normalized to lowercase


def test_settings_livedemo_mode_invalid():
    with pytest.raises(ValueError, match="livedemo_mode"):
        Settings(google_api_key="k", emergency_number="+381601234567", livedemo_mode="banana")
