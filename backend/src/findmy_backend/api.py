"""Minimal authenticated HTTP API for the future Pebble companion."""

from __future__ import annotations

import hmac
import logging
import re
import time
from dataclasses import asdict
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .icloud import (
    AppleDeviceLookupFailed,
    AppleRequestFailed,
    AuthenticationRequired,
    SoundUnavailable,
    TargetDeviceNotFound,
)
from .service import (
    CommandOutcomeUnknown,
    CooldownActive,
    FindMyController,
    InvalidIdempotencyKey,
)

LOGGER = logging.getLogger(__name__)
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ApiProblem(Exception):
    """A deliberately public, stable API error."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.details = details or {}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _problem_response(request: Request, problem: ApiProblem) -> JSONResponse:
    error = {"code": problem.code, "message": problem.message}
    error.update(problem.details)
    return JSONResponse(
        status_code=problem.status_code,
        headers=problem.headers,
        content={
            "error": error,
            "request_id": _request_id(request),
        },
    )


def create_app(
    settings: Settings | None = None,
    controller: FindMyController | None = None,
) -> FastAPI:
    """Create an app with injectable dependencies for integration tests."""

    settings = settings or Settings.from_environment()
    settings.validate_api()
    controller = controller or FindMyController(settings)

    app = FastAPI(
        title="Find My iPhone backend",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.controller = controller

    # Clay settings pages are loaded from a data: URL by the Pebble mobile app,
    # which gives their WKWebView an opaque ("null") origin.  Permit that page
    # to read diagnostics, but deliberately omit POST so it cannot dispatch a
    # Find My command directly.  The Bearer token is still required by /v1/status.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null"],
        allow_methods=["GET"],
        allow_headers=["Authorization"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            incoming if REQUEST_ID.fullmatch(incoming) else str(uuid4())
        )
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        LOGGER.info(
            "%s %s",
            request.method,
            request.url.path,
            extra={
                "event": "http.request",
                "request_id": request.state.request_id,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
        return response

    @app.exception_handler(ApiProblem)
    async def api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
        return _problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _problem_response(
            request,
            ApiProblem(422, "api.invalid_request", "The HTTP request is invalid"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = "api.not_found" if exc.status_code == 404 else "api.http_error"
        message = (
            "Route not found" if exc.status_code == 404 else "HTTP request rejected"
        )
        headers = dict(exc.headers or {})
        return _problem_response(
            request, ApiProblem(exc.status_code, code, message, headers=headers)
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.error(
            "Unhandled internal error type=%s",
            type(exc).__name__,
            extra={"event": "api.internal_error", "request_id": _request_id(request)},
        )
        return _problem_response(
            request,
            ApiProblem(500, "api.internal_error", "An internal error occurred"),
        )

    @app.exception_handler(AuthenticationRequired)
    async def auth_required_handler(
        request: Request, _exc: AuthenticationRequired
    ) -> JSONResponse:
        LOGGER.warning(
            "Apple session requires authentication",
            extra={"event": "icloud.auth_required"},
        )
        return _problem_response(
            request,
            ApiProblem(
                503,
                "icloud.authentication_required",
                "Apple session requires reauthentication",
            ),
        )

    @app.exception_handler(TargetDeviceNotFound)
    async def target_not_found_handler(
        request: Request, _exc: TargetDeviceNotFound
    ) -> JSONResponse:
        LOGGER.error(
            "Configured target was not found",
            extra={"event": "icloud.target_not_found"},
        )
        return _problem_response(
            request,
            ApiProblem(
                503, "target.not_found", "Configured iPhone was not returned by Apple"
            ),
        )

    @app.exception_handler(SoundUnavailable)
    async def sound_unavailable_handler(
        request: Request, _exc: SoundUnavailable
    ) -> JSONResponse:
        LOGGER.warning(
            "Play Sound is unavailable", extra={"event": "icloud.sound_unavailable"}
        )
        return _problem_response(
            request,
            ApiProblem(
                409,
                "target.sound_unavailable",
                "Play Sound is unavailable for the target",
            ),
        )

    @app.exception_handler(AppleRequestFailed)
    async def apple_failed_handler(
        request: Request, _exc: AppleRequestFailed
    ) -> JSONResponse:
        LOGGER.error("Apple request failed", extra={"event": "icloud.request_failed"})
        return _problem_response(
            request,
            ApiProblem(
                502, "icloud.request_failed", "Apple rejected or failed the request"
            ),
        )

    @app.exception_handler(AppleDeviceLookupFailed)
    async def apple_lookup_failed_handler(
        request: Request, _exc: AppleDeviceLookupFailed
    ) -> JSONResponse:
        LOGGER.error(
            "Apple device lookup failed before command dispatch",
            extra={"event": "icloud.device_lookup_failed"},
        )
        return _problem_response(
            request,
            ApiProblem(
                502,
                "icloud.device_lookup_failed",
                "Apple Find My device lookup failed",
                details={"retryable": True, "command_dispatched": False},
            ),
        )

    @app.exception_handler(CommandOutcomeUnknown)
    async def command_outcome_unknown_handler(
        request: Request, exc: CommandOutcomeUnknown
    ) -> JSONResponse:
        return _problem_response(
            request,
            ApiProblem(
                502,
                "icloud.command_outcome_unknown",
                "Play Sound may have been accepted; automatic retry is suppressed",
                details={
                    "retryable": False,
                    "command_may_have_been_dispatched": True,
                    "operation_id": exc.operation_id,
                    "replayed": exc.replayed,
                },
            ),
        )

    def require_api_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        scheme, separator, credential = (authorization or "").partition(" ")
        valid = bool(
            separator
            and scheme.casefold() == "bearer"
            and settings.api_token
            and hmac.compare_digest(credential, settings.api_token)
        )
        if not valid:
            raise ApiProblem(
                401,
                "api.unauthorized",
                "A valid Bearer token is required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    protected = [Depends(require_api_token)]

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/status", dependencies=protected)
    def status() -> dict:
        return asdict(controller.status())

    @app.post("/v1/find-my/play-sound", status_code=202, dependencies=protected)
    def submit_play_sound(
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict:
        if idempotency_key is None:
            raise ApiProblem(
                400,
                "api.invalid_idempotency_key",
                "A valid Idempotency-Key header is required",
            )
        try:
            result = controller.play_sound(idempotency_key)
        except InvalidIdempotencyKey as exc:
            raise ApiProblem(400, "api.invalid_idempotency_key", str(exc)) from exc
        except CooldownActive as exc:
            raise ApiProblem(
                429,
                "api.rate_limited",
                "Play Sound was triggered too recently",
                headers={"Retry-After": str(exc.retry_after)},
                details={"retryable": True},
            ) from exc
        return {"status": "submitted", **asdict(result)}

    return app
