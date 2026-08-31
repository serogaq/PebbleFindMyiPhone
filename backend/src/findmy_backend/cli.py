"""Administrative CLI for the backend's technical-risk gate."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from dataclasses import asdict

from .config import ConfigurationError, Settings
from .icloud import (
    ICloudProbeError,
    authenticate,
    complete_interactive_mfa,
    list_devices,
    load_authenticated_session,
    play_sound,
)
from .logging_config import configure_logging


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="findmy-backend",
        description="Session-only Apple Find My backend administration",
    )
    groups = parser.add_subparsers(dest="group", required=True)

    auth = groups.add_parser("auth", help="Manage the persisted Apple session")
    auth_commands = auth.add_subparsers(dest="command", required=True)
    auth_commands.add_parser(
        "login", help="Interactively authenticate and trust a session"
    )
    auth_commands.add_parser("status", help="Validate the persisted session")

    devices = groups.add_parser("devices", help="Inspect Find My devices")
    device_commands = devices.add_subparsers(dest="command", required=True)
    device_commands.add_parser("list", help="List stable IDs without location data")

    probe = groups.add_parser("probe", help="Run real-device risk-gate probes")
    probe_commands = probe.add_subparsers(dest="command", required=True)
    sound = probe_commands.add_parser(
        "play-sound", help="Submit a real Apple Find My Play Sound command"
    )
    sound.add_argument(
        "--device-id",
        help="Exact ID from devices list; defaults to TARGET_DEVICE_ID",
    )
    sound.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive target confirmation",
    )

    groups.add_parser("serve", help="Run the authenticated HTTP API")
    return parser


def _auth_login(settings: Settings) -> int:
    print(
        "The password is used only in this process and is not stored. "
        "Try an app-specific password first."
    )
    password = getpass.getpass("Apple Account password: ")
    if not password:
        raise AuthenticationError("An Apple Account password is required")

    service = authenticate(settings, password)
    try:
        complete_interactive_mfa(service, input)
    finally:
        del password  # Drop the CLI reference as soon as authentication finishes.

    status = service.get_auth_status()
    if not status.get("authenticated") or not status.get("trusted_session"):
        raise AuthenticationError("Apple did not return a usable trusted session")
    print("Authenticated trusted session saved successfully.")
    return 0


class AuthenticationError(ICloudProbeError):
    """Local interactive authentication error."""


def _auth_status(settings: Settings) -> int:
    service = load_authenticated_session(settings)
    status = service.get_auth_status()
    print(
        json.dumps(
            {
                "authenticated": bool(status.get("authenticated")),
                "trusted_session": bool(status.get("trusted_session")),
                "requires_2fa": bool(status.get("requires_2fa")),
                "requires_2sa": bool(status.get("requires_2sa")),
            },
            indent=2,
        )
    )
    return 0


def _devices_list(settings: Settings) -> int:
    service = load_authenticated_session(settings)
    devices = list_devices(service)
    print(json.dumps([asdict(device) for device in devices], indent=2))
    return 0


def _probe_play_sound(settings: Settings, args: argparse.Namespace) -> int:
    device_id = (args.device_id or settings.target_device_id or "").strip()
    if not device_id:
        raise ConfigurationError(
            "Pass --device-id or set TARGET_DEVICE_ID after listing devices"
        )
    if not args.yes:
        confirmation = input(
            "This will trigger a real Find My alert. Type PLAY SOUND to continue: "
        )
        if confirmation != "PLAY SOUND":
            print("Cancelled.")
            return 2

    service = load_authenticated_session(settings)
    target = play_sound(service, device_id)
    print(
        json.dumps(
            {
                "status": "submitted",
                "target": {
                    "name": target.name,
                    "display_name": target.display_name,
                    "device_id_suffix": target.id[-6:],
                },
                "note": (
                    "Apple accepted the request without an API error. "
                    "Physically confirm the system Find My alert and sound."
                ),
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point with safe, non-secret error output."""

    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_environment()
        configure_logging(settings.log_level)
        if args.group == "auth" and args.command == "login":
            return _auth_login(settings)
        if args.group == "auth" and args.command == "status":
            return _auth_status(settings)
        if args.group == "devices" and args.command == "list":
            return _devices_list(settings)
        if args.group == "probe" and args.command == "play-sound":
            return _probe_play_sound(settings, args)
        if args.group == "serve":
            settings.validate_api()
            import uvicorn

            from .api import create_app

            uvicorn.run(
                create_app(settings),
                host=settings.bind_address,
                port=settings.port,
                access_log=False,
                log_config=None,
                server_header=False,
            )
            return 0
    except (ConfigurationError, ICloudProbeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    _parser().error("Unsupported command")
    return 2
