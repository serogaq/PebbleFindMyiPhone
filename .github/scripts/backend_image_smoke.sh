#!/bin/sh
set -eu

image=${1:?usage: backend_image_smoke.sh IMAGE [PORT]}
port=${2:-18080}
container="find-my-backend-smoke-$$"
token=00000000000000000000000000000000

cleanup() {
  docker rm --force "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

uid=$(docker run --rm --entrypoint id "$image" -u)
test "$uid" = 10001 || {
  printf 'error: image must run as UID 10001, got %s\n' "$uid" >&2
  exit 1
}

notice=$(docker image inspect --format '{{index .Config.Labels "io.github.serogaq.required-notice"}}' "$image")
test "$notice" = 'Required Notice: Copyright © serogaq (https://github.com/serogaq/PebbleFindMyiPhone)' || {
  printf '%s\n' 'error: required notice OCI label is missing or incorrect' >&2
  exit 1
}

image_env=$(docker image inspect --format '{{json .Config.Env}}' "$image")
case "$image_env" in
  *API_TOKEN*|*APPLE_ID*|*TARGET_DEVICE_ID*)
    printf '%s\n' 'error: runtime secret/config names leaked into image environment' >&2
    exit 1
    ;;
esac

docker run --detach --name "$container" \
  --publish "127.0.0.1:$port:8080" \
  --env APPLE_ID=ci@example.invalid \
  --env TARGET_DEVICE_ID=ci-target \
  --env API_TOKEN="$token" \
  "$image" >/dev/null

ready=false
i=0
while test "$i" -lt 30; do
  if curl --fail --silent "http://127.0.0.1:$port/healthz" >/dev/null; then
    ready=true
    break
  fi
  i=$((i + 1))
  sleep 1
done

test "$ready" = true || {
  docker logs "$container" >&2 || true
  printf '%s\n' 'error: backend container did not become healthy' >&2
  exit 1
}

docker run --rm --entrypoint python "$image" -c \
  'from pathlib import Path; n="Required Notice: Copyright © serogaq (https://github.com/serogaq/PebbleFindMyiPhone)"; t=Path("/usr/share/licenses/pebble-find-my-iphone/NOTICE").read_text(); assert n in t; assert Path("/usr/share/licenses/pebble-find-my-iphone/LICENSE.md").is_file()'

printf 'backend image smoke passed: %s\n' "$image"
