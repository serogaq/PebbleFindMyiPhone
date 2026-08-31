"""Small, testable adapter around pyicloud's unofficial Find My API."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pyicloud import PyiCloudService
from pyicloud.exceptions import (
    PyiCloudAPIResponseException,
    PyiCloudAuthRequiredException,
    PyiCloudFailedLoginException,
    PyiCloudNoDevicesException,
    PyiCloudServiceNotActivatedException,
    PyiCloudServiceUnavailable,
)
from requests import RequestException
from requests.adapters import HTTPAdapter

from .config import Settings


class ICloudProbeError(RuntimeError):
    """Base error with a safe operator-facing message."""


class AuthenticationRequired(ICloudProbeError):
    """The persisted Apple session is missing or expired."""


class TargetDeviceNotFound(ICloudProbeError):
    """The configured opaque device identifier was not returned by Apple."""


class SoundUnavailable(ICloudProbeError):
    """Apple reports that Play Sound is unavailable for the device."""


class AppleRequestFailed(ICloudProbeError):
    """Apple rejected or failed an iCloud request."""


class AppleDeviceLookupFailed(AppleRequestFailed):
    """A read-only Find My device lookup failed before command dispatch."""


class AppleCommandOutcomeUnknown(AppleRequestFailed):
    """The Play Sound request was attempted but its outcome is not trustworthy."""


class TimeoutHTTPAdapter(HTTPAdapter):
    """Apply a connect/read timeout when pyicloud does not specify one."""

    def __init__(self, timeout: tuple[float, float]) -> None:
        self._default_timeout = timeout
        super().__init__(max_retries=0)

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self._default_timeout
        return super().send(request, **kwargs)


@dataclass(frozen=True)
class DeviceSummary:
    """The non-location fields required to select and validate a target."""

    id: str
    name: str
    device_class: str
    display_name: str
    model: str
    sound_available: bool


def create_service(settings: Settings, password: str | None = None) -> PyiCloudService:
    """Create a non-authenticating service and attach bounded HTTP timeouts."""

    service = PyiCloudService(
        apple_id=settings.apple_id,
        password=password,
        cookie_directory=settings.session_dir,
        china_mainland=settings.china_mainland,
        with_family=settings.with_family,
        refresh_interval=24 * 60 * 60,
        authenticate=False,
    )
    adapter = TimeoutHTTPAdapter((settings.connect_timeout, settings.read_timeout))
    service.session.mount("https://", adapter)
    return service


def authenticate(settings: Settings, password: str) -> PyiCloudService:
    """Authenticate with an in-memory password and persist only session state."""

    service = create_service(settings, password=password)
    try:
        service.authenticate()
    except (PyiCloudFailedLoginException, PyiCloudAuthRequiredException) as exc:
        raise AuthenticationRequired(
            "Apple rejected the credentials or the account requires additional setup"
        ) from exc
    except (PyiCloudAPIResponseException, RequestException) as exc:
        raise AppleRequestFailed("Apple authentication request failed") from exc
    return service


def load_authenticated_session(settings: Settings) -> PyiCloudService:
    """Load and validate a persisted session without reading a password."""

    service = create_service(settings)
    has_local_session = bool(
        service.session.data.get("session_token")
        and service.session.cookies.get("X-APPLE-WEBAUTH-TOKEN")
    )
    if not has_local_session:
        raise AuthenticationRequired(
            "No valid Apple session is stored; run `auth login`"
        )

    # Apple's validation endpoint can fail transiently. pyicloud deliberately
    # reduces that response to authenticated=false, so make one bounded retry.
    for _attempt in range(2):
        try:
            status = service.get_auth_status()
        except (
            PyiCloudAPIResponseException,
            PyiCloudAuthRequiredException,
            RequestException,
        ):
            continue
        if status.get("authenticated"):
            return service

    raise AuthenticationRequired(
        "Apple did not validate the persisted session; retry, then run `auth login` "
        "only if the failure persists"
    )


def complete_interactive_mfa(service: PyiCloudService, prompt_code) -> None:
    """Complete code-based 2FA/2SA and make the browser session trusted."""

    if service.requires_2fa:
        if service.security_key_names:
            raise AuthenticationRequired(
                "This account requires a hardware security key; code-based 2FA is unavailable"
            )
        try:
            requested = service.request_2fa_code()
        except PyiCloudAPIResponseException as exc:
            raise AuthenticationRequired("Apple failed to deliver a 2FA code") from exc
        if not requested:
            raise AuthenticationRequired(
                "Apple did not expose a trusted-device or SMS 2FA route"
            )
        for _attempt in range(3):
            code = prompt_code("Enter Apple 2FA code: ").strip()
            if service.validate_2fa_code(code):
                break
        else:
            raise AuthenticationRequired("Apple rejected the 2FA code three times")

    elif service.requires_2sa:
        trusted_devices = list(service.trusted_devices or [])
        if not trusted_devices:
            raise AuthenticationRequired("No trusted devices are available for 2SA")
        device = trusted_devices[0]
        if not service.send_verification_code(device):
            raise AuthenticationRequired("Apple failed to deliver a 2SA code")
        code = prompt_code("Enter Apple 2SA code: ").strip()
        if not service.validate_verification_code(device, code):
            raise AuthenticationRequired("Apple rejected the 2SA code")

    if not service.is_trusted_session and not service.trust_session():
        raise AuthenticationRequired("Apple did not mark the session as trusted")


def list_devices(service: PyiCloudService) -> list[DeviceSummary]:
    """Return device selection metadata without locations or account identifiers."""

    try:
        devices: Iterable = service.devices
        return [
            DeviceSummary(
                id=str(device.data.get("id", "")),
                name=str(device.data.get("name", "")),
                device_class=str(device.data.get("deviceClass", "")),
                display_name=str(device.data.get("deviceDisplayName", "")),
                model=str(device.data.get("deviceModel", "")),
                sound_available=bool(device.data.get("features", {}).get("SND", False)),
            )
            for device in devices
        ]
    except (PyiCloudNoDevicesException, PyiCloudServiceNotActivatedException) as exc:
        raise TargetDeviceNotFound("Apple returned no Find My devices") from exc
    except (PyiCloudFailedLoginException, PyiCloudAuthRequiredException) as exc:
        raise AuthenticationRequired(
            "The Apple session requires reauthentication"
        ) from exc
    except (
        PyiCloudAPIResponseException,
        PyiCloudServiceUnavailable,
        RequestException,
    ) as exc:
        raise AppleDeviceLookupFailed("Apple device lookup failed") from exc


def resolve_device(
    service: PyiCloudService, device_id: str
):  # pyicloud does not publish a stable protocol for AppleDevice
    """Resolve an exact opaque identifier and require an iPhone with SND support."""

    summaries = {device.id: device for device in list_devices(service)}
    summary = summaries.get(device_id)
    if summary is None:
        raise TargetDeviceNotFound(
            "The exact target device ID was not returned by Apple"
        )
    if summary.device_class.casefold() != "iphone":
        raise TargetDeviceNotFound("The selected target is not an iPhone")
    if not summary.sound_available:
        raise SoundUnavailable("Apple reports that Play Sound is unavailable")

    try:
        return service.devices[device_id], summary
    except KeyError as exc:
        raise TargetDeviceNotFound(
            "The target disappeared during device lookup"
        ) from exc


def send_play_sound(device) -> None:  # pyicloud does not publish AppleDevice protocol
    """Attempt one command on an already-resolved device; never retry here."""

    try:
        device.play_sound()
    except PyiCloudServiceUnavailable as exc:
        raise SoundUnavailable("Apple reports that Play Sound is unavailable") from exc
    except (PyiCloudFailedLoginException, PyiCloudAuthRequiredException) as exc:
        raise AuthenticationRequired(
            "The Apple session requires reauthentication"
        ) from exc
    except (PyiCloudAPIResponseException, RequestException) as exc:
        raise AppleCommandOutcomeUnknown(
            "Apple Play Sound command outcome is unknown"
        ) from exc


def play_sound(service: PyiCloudService, device_id: str) -> DeviceSummary:
    """Resolve an exact target and attempt Apple's real Play Sound command once."""

    device, summary = resolve_device(service, device_id)
    send_play_sound(device)
    return summary
