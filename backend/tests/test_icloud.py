"""Tests for exact device selection and real-command preparation."""

import json
import logging
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pyicloud.exceptions import (
    PyiCloudAPIResponseException,
    PyiCloudAuthRequiredException,
)

from findmy_backend.icloud import (
    AppleCommandOutcomeUnknown,
    AuthenticationRequired,
    SoundUnavailable,
    TargetDeviceNotFound,
    authenticate,
    complete_interactive_mfa,
    list_devices,
    load_authenticated_session,
    play_sound,
    read_auth_status,
)
from findmy_backend.logging_config import JsonFormatter


class FakeSession:
    def __init__(self, *, persisted=True):
        self.data = {"session_token": "token"} if persisted else {}
        self.cookies = {"X-APPLE-WEBAUTH-TOKEN": "cookie"} if persisted else {}


def _device(device_id="opaque-id", device_class="iPhone", sound=True):
    data = {
        "id": device_id,
        "name": "Owner iPhone",
        "deviceClass": device_class,
        "deviceDisplayName": "iPhone 17 Pro",
        "deviceModel": "iPhone18,1",
        "features": {"SND": sound},
        "location": {"latitude": 55.0, "longitude": 37.0},
    }
    return SimpleNamespace(data=data, play_sound=Mock())


class FakeDevices:
    def __init__(self, devices):
        self._devices = {device.data["id"]: device for device in devices}

    def __iter__(self):
        return iter(self._devices.values())

    def __getitem__(self, key):
        return self._devices[key]


def test_explicit_login_forces_credential_refresh(monkeypatch):
    service = SimpleNamespace(authenticate=Mock())
    create_service = Mock(return_value=service)
    monkeypatch.setattr("findmy_backend.icloud.create_service", create_service)
    settings = Mock()

    assert authenticate(settings, "not-stored-password") is service

    create_service.assert_called_once_with(settings, password="not-stored-password")
    service.authenticate.assert_called_once_with(force_refresh=True)


def test_list_devices_never_returns_location():
    service = SimpleNamespace(devices=FakeDevices([_device()]))
    summary = list_devices(service)[0]
    assert not hasattr(summary, "location")
    assert summary.id == "opaque-id"


def test_play_sound_uses_exact_id():
    target = _device()
    other = _device("other-id")
    service = SimpleNamespace(devices=FakeDevices([other, target]))

    summary = play_sound(service, "opaque-id")

    assert summary.id == "opaque-id"
    target.play_sound.assert_called_once_with()
    other.play_sound.assert_not_called()


def test_play_sound_rejects_name_instead_of_id():
    service = SimpleNamespace(devices=FakeDevices([_device()]))
    with pytest.raises(TargetDeviceNotFound):
        play_sound(service, "Owner iPhone")


def test_play_sound_requires_iphone():
    service = SimpleNamespace(devices=FakeDevices([_device(device_class="Watch")]))
    with pytest.raises(TargetDeviceNotFound, match="not an iPhone"):
        play_sound(service, "opaque-id")


def test_play_sound_requires_sound_capability():
    service = SimpleNamespace(devices=FakeDevices([_device(sound=False)]))
    with pytest.raises(SoundUnavailable):
        play_sound(service, "opaque-id")


def test_play_sound_maps_expired_session_without_leaking_apple_error():
    target = _device()
    target.play_sound.side_effect = PyiCloudAuthRequiredException(
        "sensitive-account@example.invalid", Mock()
    )
    service = SimpleNamespace(devices=FakeDevices([target]))

    with pytest.raises(
        AuthenticationRequired, match="requires reauthentication"
    ) as error:
        play_sound(service, "opaque-id")

    assert "sensitive-account" not in str(error.value)


def test_play_sound_maps_post_dispatch_error_to_unknown_outcome():
    target = _device()
    target.play_sound.side_effect = PyiCloudAPIResponseException("private response")
    service = SimpleNamespace(devices=FakeDevices([target]))

    with pytest.raises(AppleCommandOutcomeUnknown):
        play_sound(service, "opaque-id")


def test_load_session_retries_one_transient_validation_failure(monkeypatch):
    service = SimpleNamespace(
        session=FakeSession(),
        get_auth_status=Mock(
            side_effect=[{"authenticated": False}, {"authenticated": True}]
        ),
    )
    monkeypatch.setattr(
        "findmy_backend.icloud.create_service", lambda settings: service
    )

    assert load_authenticated_session(Mock()) is service
    assert service.get_auth_status.call_count == 2


def test_load_session_distinguishes_missing_local_state(monkeypatch):
    service = SimpleNamespace(session=FakeSession(persisted=False))
    monkeypatch.setattr(
        "findmy_backend.icloud.create_service", lambda settings: service
    )

    with pytest.raises(
        AuthenticationRequired, match="No valid Apple session is stored"
    ):
        load_authenticated_session(Mock())


def test_mfa_validation_maps_provider_error_without_leaking_details():
    service = SimpleNamespace(
        requires_2fa=True,
        security_key_names=[],
        request_2fa_code=Mock(return_value=True),
        validate_2fa_code=Mock(
            side_effect=PyiCloudAPIResponseException("private MFA response")
        ),
    )

    with pytest.raises(AuthenticationRequired, match="failed to validate") as error:
        complete_interactive_mfa(service, lambda _prompt: "123456")

    assert "private MFA response" not in str(error.value)


def test_mfa_maps_undocumented_provider_error_without_leaking_details():
    class UnstableService:
        @property
        def requires_2fa(self):
            raise ValueError("private undocumented MFA response")

    with pytest.raises(AuthenticationRequired, match="MFA operation failed") as error:
        complete_interactive_mfa(UnstableService(), lambda _prompt: "123456")

    assert "private undocumented" not in str(error.value)


def test_auth_status_maps_provider_error_without_leaking_details():
    service = SimpleNamespace(
        get_auth_status=Mock(
            side_effect=PyiCloudAPIResponseException("private status response")
        )
    )

    with pytest.raises(AuthenticationRequired, match="status request failed") as error:
        read_auth_status(service)

    assert "private status response" not in str(error.value)


def test_json_debug_exception_contains_upstream_traceback():
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("findmy-test-debug")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    try:
        raise RuntimeError("raw provider detail")
    except RuntimeError:
        logger.debug("provider failed", exc_info=True)

    payload = json.loads(stream.getvalue())
    assert payload["level"] == "debug"
    assert "RuntimeError: raw provider detail" in payload["exception"]


def test_info_logging_suppresses_raw_provider_traceback():
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("findmy-test-info")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        raise RuntimeError("raw provider detail")
    except RuntimeError:
        logger.debug("provider failed", exc_info=True)

    assert stream.getvalue() == ""
