"""Application-service safety behavior."""

from types import SimpleNamespace

import pytest
from helpers import settings

from findmy_backend.icloud import (
    AppleCommandOutcomeUnknown,
    AppleDeviceLookupFailed,
    DeviceSummary,
)
from findmy_backend.service import (
    CommandOutcomeUnknown,
    CooldownActive,
    FindMyController,
    InvalidIdempotencyKey,
)


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def _target() -> DeviceSummary:
    return DeviceSummary(
        id="opaque-device-id",
        name="Phone",
        device_class="iPhone",
        display_name="iPhone",
        model="model",
        sound_available=True,
    )


def test_command_requires_idempotency_key_before_apple_access():
    controller = FindMyController(settings())

    with pytest.raises(InvalidIdempotencyKey, match="required"):
        controller.play_sound(None)


def test_idempotency_replays_without_second_apple_call(monkeypatch):
    clock = Clock()
    apple_calls = []
    monkeypatch.setattr(
        "findmy_backend.service.load_authenticated_session",
        lambda _settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "findmy_backend.service.resolve_device",
        lambda _service, _device_id: (SimpleNamespace(), _target()),
    )
    monkeypatch.setattr(
        "findmy_backend.service.send_play_sound",
        lambda _device: apple_calls.append("sent"),
    )
    controller = FindMyController(settings(), clock=clock)

    first = controller.play_sound("request-1234")
    replay = controller.play_sound("request-1234")

    assert apple_calls == ["sent"]
    assert replay.request_id == first.request_id
    assert replay.replayed is True


def test_global_cooldown_blocks_different_request(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(
        "findmy_backend.service.load_authenticated_session",
        lambda _settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "findmy_backend.service.resolve_device",
        lambda _service, _device_id: (SimpleNamespace(), _target()),
    )
    monkeypatch.setattr("findmy_backend.service.send_play_sound", lambda _device: None)
    controller = FindMyController(settings(), clock=clock)
    controller.play_sound("request-1234")

    with pytest.raises(CooldownActive) as error:
        controller.play_sound("request-5678")

    assert error.value.retry_after == 30


def test_failed_lookup_is_retried_before_one_command_dispatch(monkeypatch):
    clock = Clock()
    calls = 0

    def fail_then_succeed(_service, _device_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AppleDeviceLookupFailed("Apple failed")
        return SimpleNamespace(), _target()

    monkeypatch.setattr(
        "findmy_backend.service.load_authenticated_session",
        lambda _settings: SimpleNamespace(),
    )
    monkeypatch.setattr("findmy_backend.service.resolve_device", fail_then_succeed)
    send = SimpleNamespace(calls=0)
    monkeypatch.setattr(
        "findmy_backend.service.send_play_sound",
        lambda _device: setattr(send, "calls", send.calls + 1),
    )
    controller = FindMyController(settings(), clock=clock)

    assert controller.play_sound("request-1234").replayed is False
    assert calls == 2
    assert send.calls == 1


def test_unknown_command_outcome_suppresses_same_idempotency_key(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(
        "findmy_backend.service.load_authenticated_session",
        lambda _settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "findmy_backend.service.resolve_device",
        lambda _service, _device_id: (SimpleNamespace(), _target()),
    )
    sends = 0

    def ambiguous(_device):
        nonlocal sends
        sends += 1
        raise AppleCommandOutcomeUnknown("unknown")

    monkeypatch.setattr("findmy_backend.service.send_play_sound", ambiguous)
    controller = FindMyController(settings(), clock=clock)

    with pytest.raises(CommandOutcomeUnknown) as first:
        controller.play_sound("request-1234")
    with pytest.raises(CommandOutcomeUnknown) as replay:
        controller.play_sound("request-1234")

    assert sends == 1
    assert replay.value.operation_id == first.value.operation_id
    assert replay.value.replayed is True


def test_status_retries_one_read_only_apple_failure(monkeypatch):
    services = [SimpleNamespace(), SimpleNamespace()]
    monkeypatch.setattr(
        "findmy_backend.service.load_authenticated_session",
        lambda _settings: services.pop(0),
    )
    attempts = 0

    def fail_then_succeed(_service, _device_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise AppleDeviceLookupFailed("transient")
        return SimpleNamespace(), _target()

    monkeypatch.setattr("findmy_backend.service.resolve_device", fail_then_succeed)

    result = FindMyController(settings(), sleeper=lambda _seconds: None).status()

    assert attempts == 2
    assert result.state == "ready"


def test_ready_status_primes_short_lived_target_cache_for_command(monkeypatch):
    clock = Clock()
    resolves = 0
    monkeypatch.setattr(
        "findmy_backend.service.load_authenticated_session",
        lambda _settings: SimpleNamespace(),
    )

    def resolve(_service, _device_id):
        nonlocal resolves
        resolves += 1
        return SimpleNamespace(), _target()

    monkeypatch.setattr("findmy_backend.service.resolve_device", resolve)
    monkeypatch.setattr("findmy_backend.service.send_play_sound", lambda _device: None)
    controller = FindMyController(settings(), clock=clock)

    assert controller.status().state == "ready"
    controller.play_sound("request-1234")

    assert resolves == 1
