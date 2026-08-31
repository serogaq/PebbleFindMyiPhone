"""Thread-safe application service for status and Play Sound commands."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from .config import Settings
from .icloud import (
    AppleCommandOutcomeUnknown,
    AppleDeviceLookupFailed,
    AuthenticationRequired,
    DeviceSummary,
    load_authenticated_session,
    resolve_device,
    send_play_sound,
)

LOGGER = logging.getLogger(__name__)
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class InvalidIdempotencyKey(ValueError):
    """An idempotency key is unsafe or ambiguous."""


class CooldownActive(RuntimeError):
    """A recent command dispatch is still inside the cooldown window."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Play Sound cooldown is active")
        self.retry_after = retry_after


class CommandOutcomeUnknown(RuntimeError):
    """A command may have reached Apple, so automatic retry is unsafe."""

    def __init__(self, operation_id: str, *, replayed: bool = False) -> None:
        super().__init__("Play Sound command outcome is unknown")
        self.operation_id = operation_id
        self.replayed = replayed


@dataclass(frozen=True)
class PlaySoundResult:
    request_id: str
    submitted_at: str
    target_id_suffix: str
    replayed: bool = False


@dataclass(frozen=True)
class UnknownCommandResult:
    operation_id: str


@dataclass(frozen=True)
class BackendStatus:
    state: str
    target_configured: bool
    target_available: bool
    target_id_suffix: str | None
    error_code: str | None = None


class FindMyController:
    """Serialize commands and suppress accidental duplicate alerts."""

    def __init__(
        self,
        settings: Settings,
        *,
        clock=time.monotonic,
        wall_clock=lambda: datetime.now(timezone.utc),
        sleeper=time.sleep,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleeper = sleeper
        self._lock = RLock()
        self._last_dispatch: float | None = None
        self._cached_target: tuple[float, object, DeviceSummary] | None = None
        self._idempotency: dict[
            str, tuple[float, PlaySoundResult | UnknownCommandResult]
        ] = {}

    def _resolve_target(self, *, allow_cached: bool):
        """Cache briefly and retry only failures before command dispatch."""

        now = self._clock()
        if allow_cached and self._cached_target is not None:
            cached_at, device, summary = self._cached_target
            if now - cached_at < self.settings.device_cache_ttl:
                return device, summary

        last_failure: AppleDeviceLookupFailed | None = None
        for attempt in range(3):
            service = load_authenticated_session(self.settings)
            try:
                device, summary = resolve_device(
                    service, self.settings.target_device_id
                )
                self._cached_target = (self._clock(), device, summary)
                return device, summary
            except AppleDeviceLookupFailed as exc:
                last_failure = exc
                if attempt < 2:
                    self._sleeper(0.5 * (2**attempt))
        if last_failure is not None:
            raise last_failure
        raise AppleDeviceLookupFailed("Apple device lookup failed before dispatch")

    def status(self) -> BackendStatus:
        """Validate the stored session and exact target without requesting location."""

        if not self.settings.target_device_id:
            return BackendStatus(
                "not_ready", False, False, None, "target.not_configured"
            )

        with self._lock:
            _device, summary = self._resolve_target(allow_cached=False)

        LOGGER.info(
            "Persisted Apple session and target validated",
            extra={"event": "icloud.ready"},
        )
        return BackendStatus("ready", True, True, summary.id[-6:] or None)

    def play_sound(self, idempotency_key: str | None) -> PlaySoundResult:
        """Submit one command, enforcing idempotency and a global cooldown."""

        if not idempotency_key or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise InvalidIdempotencyKey(
                "Idempotency-Key is required and must be 8-128 ASCII letters, "
                "digits, '.', '_', ':', or '-'"
            )
        if not self.settings.target_device_id:
            raise AuthenticationRequired("No target device is configured")

        with self._lock:
            now = self._clock()
            self._expire_idempotency(now)
            if idempotency_key in self._idempotency:
                cached = self._idempotency[idempotency_key][1]
                if isinstance(cached, UnknownCommandResult):
                    raise CommandOutcomeUnknown(cached.operation_id, replayed=True)
                return PlaySoundResult(
                    request_id=cached.request_id,
                    submitted_at=cached.submitted_at,
                    target_id_suffix=cached.target_id_suffix,
                    replayed=True,
                )

            if self._last_dispatch is not None:
                remaining = self.settings.play_sound_cooldown - (
                    now - self._last_dispatch
                )
                if remaining > 0:
                    raise CooldownActive(max(1, int(remaining + 0.999)))

            device, target = self._resolve_target(allow_cached=True)
            target: DeviceSummary
            operation_id = str(uuid4())
            try:
                send_play_sound(device)
            except AppleCommandOutcomeUnknown as exc:
                self._last_dispatch = self._clock()
                self._idempotency[idempotency_key] = (
                    self._last_dispatch,
                    UnknownCommandResult(operation_id),
                )
                LOGGER.warning(
                    "Play Sound command outcome is unknown; retry suppressed",
                    extra={"event": "findmy.command_outcome_unknown"},
                )
                raise CommandOutcomeUnknown(operation_id) from exc

            result = PlaySoundResult(
                request_id=operation_id,
                submitted_at=self._wall_clock().isoformat(),
                target_id_suffix=target.id[-6:],
            )
            self._last_dispatch = self._clock()
            self._idempotency[idempotency_key] = (self._last_dispatch, result)
            LOGGER.info(
                "Apple accepted Play Sound",
                extra={"event": "findmy.play_sound_submitted"},
            )
            return result

    def _expire_idempotency(self, now: float) -> None:
        expired = [
            key
            for key, (created, _result) in self._idempotency.items()
            if now - created >= self.settings.idempotency_ttl
        ]
        for key in expired:
            del self._idempotency[key]
