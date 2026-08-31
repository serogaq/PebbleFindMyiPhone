# Find My iPhone for Pebble

Find My iPhone lets a modern Pebble watch trigger Apple's real **Find My →
Play Sound** alert on its paired iPhone.

```text
Pebble watch
    ↓ Bluetooth / AppMessage
official Pebble app on iPhone
    ↓ authenticated HTTP(S)
self-hosted backend
    ↓ private iCloud web API
iPhone / system Find My alert
```

The watch application supports Pebble Time 2, Pebble Round 2, Pebble 2 Duo,
and Pebble 2. The current phone companion is tested with the official Pebble
application on iOS.

> [!WARNING]
> Apple does not provide a supported public API for this operation. The backend
> uses an undocumented iCloud API through `pyicloud`. Apple may change or
> disable it without notice.

## Install the Pebble application

The RePebble App Store listing will be linked here after publication:

**[Install Find My iPhone from the RePebble App Store](https://apps.repebble.com/d71d5cfc5ec6470ebe8745d2)**

The Pebble application requires a backend deployed and authenticated as
described below.

## Deploy the backend

### Requirements

- a Linux server with Docker Engine and Docker Compose;
- an Apple Account that owns the target iPhone;
- network access from the iPhone to the backend;
- HTTPS or a trusted VPN for any internet-facing deployment.

Clone the repository and prepare the configuration:

```sh
git clone https://github.com/serogaq/pebble-find-my-iphone.git
cd pebble-find-my-iphone/backend
cp .env.example .env
```

Edit `.env` and set at least:

```dotenv
# Use a published backend release, or keep the defaults and build locally.
BACKEND_IMAGE=ghcr.io/serogaq/pebble-find-my-iphone-backend
BACKEND_TAG=<version>

APPLE_ID=owner@example.com
APPLE_REGION=global
TARGET_DEVICE_ID=

# 127.0.0.1 for a reverse proxy on the same server.
# Use 0.0.0.0 only for a firewall-protected trusted LAN.
HOST_BIND_ADDRESS=127.0.0.1
PORT=8080
```

Create the backend API token as a Docker Secret:

```sh
mkdir -p secrets
umask 077
openssl rand -hex 32 > secrets/api_token
```

Never commit `.env`, `secrets/api_token`, or Apple session data. The value in
`secrets/api_token` is the token that must later be entered in the Pebble
application settings.

If you want to build the backend locally instead of pulling a published image,
keep the default `BACKEND_IMAGE` and `BACKEND_TAG` values from `.env.example`,
then run this from the repository root:

```sh
make backend-build
```

### Authenticate Apple and select the iPhone

Authenticate interactively and complete Apple's 2FA prompt:

```sh
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml run --rm backend auth login
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml run --rm backend auth status
```

The Apple password exists only in this interactive process and is not stored by
the project. Try an app-specific password first; if Apple rejects it for Find
My, use the primary account password.

List the account's Find My devices:

```sh
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml run --rm backend devices list
```

Choose the iPhone whose `sound_available` value is `true`, then copy its exact
opaque `id` into `.env` as `TARGET_DEVICE_ID`. Device names and list positions
are deliberately not used because they are not stable identifiers.

Before starting the API, you can perform a direct real-device test:

```sh
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml run --rm backend probe play-sound
```

The test succeeds only when the physical iPhone displays Apple's Find My alert
and plays the system sound.

### Start and verify

```sh
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml pull
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml up -d
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml ps
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml logs -f backend
```

Check process liveness:

```sh
curl -sS http://127.0.0.1:8080/healthz
```

Check the Apple session and selected iPhone:

```sh
API_TOKEN="$(cat secrets/api_token)"
curl -sS \
  -H "Authorization: Bearer $API_TOKEN" \
  http://127.0.0.1:8080/v1/status
```

Perform the complete backend acceptance test with a new idempotency key:

```sh
curl -sS -X POST \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Idempotency-Key: manual-test-0001" \
  http://127.0.0.1:8080/v1/find-my/play-sound
```

An HTTP `202 Accepted` means Apple accepted the command. Only hearing and seeing
the system Find My alert on the physical iPhone proves final delivery.

### Configure the Pebble application

Open the installed application's card in the Pebble iOS application and tap
**Settings**. Enter:

- **Backend address:port**, without `http://`, `https://`, or a path;
- whether the backend uses **SSL (HTTPS)**;
- the token stored in `secrets/api_token`.

Use plain HTTP only on a trusted LAN. For internet deployment, terminate HTTPS
in a reverse proxy or expose the backend through a trusted VPN. The supplied
Compose service itself listens on HTTP.

### Apple session renewal and updates

The persisted `icloud-session` Docker volume survives container restarts,
server reboots, image updates, and `docker compose down` without `--volumes`.
Treat this volume as a credential and do not delete it unnecessarily.

If the application reports that Apple authorization must be renewed:

```sh
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml run --rm backend auth login
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml restart backend
```

Update a published deployment with:

```sh
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml pull
docker compose -f docker-compose.yaml -f docker-compose.secrets.yaml up -d
```

Do not run `docker compose down --volumes` unless deleting the stored Apple
session is intentional.

## License

Required Notice: Copyright © serogaq (https://github.com/serogaq/PebbleFindMyiPhone)

This project is licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE.md). It may be used, modified,
and distributed only for purposes permitted by that license, primarily
noncommercial purposes. Commercial use requires separate permission from the
author. The license text and [required copyright notice](NOTICE) control if
this summary differs from them.
