"""Shared test factories."""

from findmy_backend.config import Settings


def settings(**overrides) -> Settings:
    values = {
        "apple_id": "owner@example.invalid",
        "session_dir": "/tmp/test-session",
        "china_mainland": False,
        "with_family": False,
        "target_device_id": "opaque-device-id",
        "connect_timeout": 1.0,
        "read_timeout": 1.0,
        "api_token": "a" * 32,
        "bind_address": "127.0.0.1",
        "port": 8080,
        "play_sound_cooldown": 30.0,
        "idempotency_ttl": 300.0,
        "device_cache_ttl": 60.0,
        "log_level": "INFO",
    }
    values.update(overrides)
    return Settings(**values)
