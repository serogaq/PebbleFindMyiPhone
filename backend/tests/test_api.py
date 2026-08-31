"""HTTP contract and security tests."""

from fastapi.testclient import TestClient
from helpers import settings

from findmy_backend import __version__
from findmy_backend.api import create_app
from findmy_backend.icloud import AppleDeviceLookupFailed, AuthenticationRequired
from findmy_backend.service import (
    BackendStatus,
    CommandOutcomeUnknown,
    CooldownActive,
    InvalidIdempotencyKey,
    PlaySoundResult,
)

TOKEN = "a" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Controller:
    def __init__(self) -> None:
        self.keys = []
        self.status_result = BackendStatus("ready", True, True, "ice-id")
        self.play_result = PlaySoundResult(
            request_id="command-id",
            submitted_at="2026-08-30T12:00:00+00:00",
            target_id_suffix="ice-id",
        )

    def status(self):
        if isinstance(self.status_result, Exception):
            raise self.status_result
        return self.status_result

    def play_sound(self, key):
        self.keys.append(key)
        if isinstance(self.play_result, Exception):
            raise self.play_result
        return self.play_result


def _client(controller=None):
    return TestClient(
        create_app(settings(api_token=TOKEN), controller or Controller()),
        raise_server_exceptions=False,
    )


def test_api_uses_package_version():
    app = create_app(settings(api_token=TOKEN), Controller())

    assert app.version == __version__


def test_health_is_public_but_contains_no_icloud_state():
    response = _client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_request_id_accepts_safe_value_and_replaces_unsafe_value():
    client = _client()
    safe = client.get("/healthz", headers={"X-Request-ID": "pebble.release-1"})
    unsafe = client.get("/healthz", headers={"X-Request-ID": "contains spaces"})

    assert safe.headers["x-request-id"] == "pebble.release-1"
    assert unsafe.headers["x-request-id"] != "contains spaces"
    assert len(unsafe.headers["x-request-id"]) == 36


def test_clay_settings_origin_can_read_status_with_bearer_token():
    response = _client().get(
        "/v1/status",
        headers={**AUTH, "Origin": "null"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "null"
    assert response.headers["vary"] == "Origin"


def test_clay_settings_cors_preflight_allows_get_but_not_play_sound_post():
    client = _client()
    get_preflight = client.options(
        "/v1/status",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    post_preflight = client.options(
        "/v1/find-my/play-sound",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Idempotency-Key",
        },
    )

    assert get_preflight.status_code == 200
    assert get_preflight.headers["access-control-allow-origin"] == "null"
    assert "GET" in get_preflight.headers["access-control-allow-methods"]
    assert post_preflight.status_code == 400
    assert "POST" not in post_preflight.headers["access-control-allow-methods"]


def test_cors_rejects_non_clay_origins():
    response = _client().get(
        "/v1/status",
        headers={**AUTH, "Origin": "https://attacker.example"},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_protected_routes_require_exact_bearer_token():
    client = _client()
    missing = client.get("/v1/status")
    wrong = client.get("/v1/status", headers={"Authorization": f"Bearer {TOKEN}x"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["error"]["code"] == "api.unauthorized"
    assert "Bearer" in missing.headers["www-authenticate"]


def test_status_reports_exact_target_readiness():
    response = _client().get("/v1/status", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {
        "state": "ready",
        "target_configured": True,
        "target_available": True,
        "target_id_suffix": "ice-id",
        "error_code": None,
    }


def test_play_sound_returns_accepted_contract_and_forwards_idempotency_key():
    controller = Controller()
    response = _client(controller).post(
        "/v1/find-my/play-sound",
        headers={**AUTH, "Idempotency-Key": "pebble-12345"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "submitted"
    assert response.json()["request_id"] == "command-id"
    assert controller.keys == ["pebble-12345"]


def test_rate_limit_has_stable_error_and_retry_after():
    controller = Controller()
    controller.play_result = CooldownActive(17)
    response = _client(controller).post(
        "/v1/find-my/play-sound",
        headers={**AUTH, "Idempotency-Key": "pebble-rate-limit"},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.json()["error"]["code"] == "api.rate_limited"


def test_invalid_idempotency_key_is_rejected_before_controller_dispatch():
    controller = Controller()
    controller.play_result = InvalidIdempotencyKey("invalid")
    response = _client(controller).post(
        "/v1/find-my/play-sound",
        headers={**AUTH, "Idempotency-Key": "bad key"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "api.invalid_idempotency_key"


def test_missing_idempotency_key_is_rejected_before_controller_dispatch():
    controller = Controller()
    response = _client(controller).post("/v1/find-my/play-sound", headers=AUTH)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "api.invalid_idempotency_key"
    assert controller.keys == []


def test_unknown_route_uses_stable_error_contract():
    response = _client().get("/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "api.not_found"


def test_expired_apple_session_is_distinct_and_safe():
    controller = Controller()
    controller.status_result = AuthenticationRequired("private Apple detail")
    response = _client(controller).get("/v1/status", headers=AUTH)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "icloud.authentication_required"
    assert "private Apple detail" not in response.text


def test_pre_dispatch_lookup_failure_is_explicitly_retryable():
    controller = Controller()
    controller.play_result = AppleDeviceLookupFailed("private Apple detail")
    response = _client(controller).post(
        "/v1/find-my/play-sound",
        headers={**AUTH, "Idempotency-Key": "pebble-lookup-failure"},
    )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "icloud.device_lookup_failed",
        "message": "Apple Find My device lookup failed",
        "retryable": True,
        "command_dispatched": False,
    }


def test_unknown_command_outcome_tells_client_not_to_retry():
    controller = Controller()
    controller.play_result = CommandOutcomeUnknown("operation-123")
    response = _client(controller).post(
        "/v1/find-my/play-sound",
        headers={**AUTH, "Idempotency-Key": "pebble-unknown-result"},
    )

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "icloud.command_outcome_unknown"
    assert error["retryable"] is False
    assert error["command_may_have_been_dispatched"] is True
    assert error["operation_id"] == "operation-123"


def test_request_id_is_returned_without_echoing_invalid_unicode():
    response = _client().get("/healthz", headers={"X-Request-ID": "known-request-123"})
    assert response.headers["x-request-id"] == "known-request-123"
