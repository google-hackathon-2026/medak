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
