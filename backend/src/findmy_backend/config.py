"""Environment-backed configuration for the Find My backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when required configuration is missing or invalid."""


# Uvicorn listens on the container network; Compose controls whether the host
# publishes it on loopback, a LAN address, or behind a reverse proxy.
DEFAULT_CONTAINER_BIND = "0.0.0.0"  # nosec B104


def _parse_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _parse_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _parse_port(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not 1 <= value <= 65535:
        raise ConfigurationError(f"{name} must be between 1 and 65535")
    return value


def _read_secret(name: str) -> str | None:
    """Read one secret from an environment value or Docker-style *_FILE."""

    value = os.getenv(name, "")
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if value and file_name:
        raise ConfigurationError(f"Set only one of {name} or {name}_FILE")
    if file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationError(f"Unable to read {name}_FILE") from exc
    return value.strip() or None


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared by all administrative commands."""

    apple_id: str
    session_dir: str
    china_mainland: bool
    with_family: bool
    target_device_id: str | None
    connect_timeout: float
    read_timeout: float
    api_token: str | None
    bind_address: str
    port: int
    play_sound_cooldown: float
    idempotency_ttl: float
    device_cache_ttl: float
    log_level: str

    def validate_api(self) -> None:
        """Validate settings needed only by the long-running HTTP server."""

        if not self.target_device_id:
            raise ConfigurationError("TARGET_DEVICE_ID is required for the HTTP API")
        if not self.api_token or len(self.api_token) < 32:
            raise ConfigurationError("API_TOKEN must contain at least 32 characters")

    @classmethod
    def from_environment(cls) -> Settings:
        apple_id = os.getenv("APPLE_ID", "").strip()
        if not apple_id:
            raise ConfigurationError("APPLE_ID is required")

        region = os.getenv("APPLE_REGION", "global").strip().lower()
        if region not in {"global", "china"}:
            raise ConfigurationError("APPLE_REGION must be global or china")

        target = os.getenv("TARGET_DEVICE_ID", "").strip() or None
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError(
                "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
            )

        return cls(
            apple_id=apple_id,
            session_dir=os.getenv("ICLOUD_SESSION_DIR", "/var/lib/find-my/session"),
            china_mainland=region == "china",
            with_family=_parse_bool("ICLOUD_WITH_FAMILY"),
            target_device_id=target,
            connect_timeout=_parse_positive_float(
                "ICLOUD_CONNECT_TIMEOUT_SECONDS", 5.0
            ),
            read_timeout=_parse_positive_float("ICLOUD_READ_TIMEOUT_SECONDS", 20.0),
            api_token=_read_secret("API_TOKEN"),
            bind_address=os.getenv("BIND_ADDRESS", DEFAULT_CONTAINER_BIND).strip()
            or DEFAULT_CONTAINER_BIND,
            port=_parse_port("PORT", 8080),
            play_sound_cooldown=_parse_positive_float(
                "PLAY_SOUND_COOLDOWN_SECONDS", 30.0
            ),
            idempotency_ttl=_parse_positive_float("IDEMPOTENCY_TTL_SECONDS", 300.0),
            device_cache_ttl=_parse_positive_float("DEVICE_CACHE_TTL_SECONDS", 60.0),
            log_level=log_level,
        )
