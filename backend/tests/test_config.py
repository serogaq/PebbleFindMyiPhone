"""Configuration parsing tests."""

import pytest

from findmy_backend.config import ConfigurationError, Settings


def test_settings_require_apple_id(monkeypatch):
    monkeypatch.delenv("APPLE_ID", raising=False)
    with pytest.raises(ConfigurationError, match="APPLE_ID"):
        Settings.from_environment()


def test_settings_parse_session_only_defaults(monkeypatch):
    monkeypatch.setenv("APPLE_ID", "owner@example.com")
    monkeypatch.delenv("APPLE_REGION", raising=False)
    monkeypatch.delenv("ICLOUD_WITH_FAMILY", raising=False)
    monkeypatch.delenv("TARGET_DEVICE_ID", raising=False)

    settings = Settings.from_environment()

    assert settings.apple_id == "owner@example.com"
    assert settings.china_mainland is False
    assert settings.with_family is False
    assert settings.target_device_id is None
    assert settings.connect_timeout == 5.0
    assert settings.read_timeout == 20.0
    assert settings.bind_address == "0.0.0.0"
    assert settings.port == 8080
    assert settings.play_sound_cooldown == 30.0
    assert settings.device_cache_ttl == 60.0


def test_settings_reject_invalid_boolean(monkeypatch):
    monkeypatch.setenv("APPLE_ID", "owner@example.com")
    monkeypatch.setenv("ICLOUD_WITH_FAMILY", "sometimes")
    with pytest.raises(ConfigurationError, match="true or false"):
        Settings.from_environment()


def test_api_requires_target_and_strong_token(monkeypatch):
    monkeypatch.setenv("APPLE_ID", "owner@example.com")
    monkeypatch.delenv("TARGET_DEVICE_ID", raising=False)
    monkeypatch.setenv("API_TOKEN", "short")
    settings = Settings.from_environment()

    with pytest.raises(ConfigurationError, match="TARGET_DEVICE_ID"):
        settings.validate_api()

    monkeypatch.setenv("TARGET_DEVICE_ID", "opaque-id")
    settings = Settings.from_environment()
    with pytest.raises(ConfigurationError, match="at least 32"):
        settings.validate_api()


def test_api_token_can_be_loaded_from_docker_secret(monkeypatch, tmp_path):
    token_file = tmp_path / "api-token"
    token_file.write_text("t" * 32 + "\n", encoding="utf-8")
    monkeypatch.setenv("APPLE_ID", "owner@example.com")
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setenv("API_TOKEN_FILE", str(token_file))

    assert Settings.from_environment().api_token == "t" * 32


def test_api_token_rejects_ambiguous_value_and_file(monkeypatch, tmp_path):
    token_file = tmp_path / "api-token"
    token_file.write_text("t" * 32, encoding="utf-8")
    monkeypatch.setenv("APPLE_ID", "owner@example.com")
    monkeypatch.setenv("API_TOKEN", "e" * 32)
    monkeypatch.setenv("API_TOKEN_FILE", str(token_file))

    with pytest.raises(ConfigurationError, match="only one"):
        Settings.from_environment()
