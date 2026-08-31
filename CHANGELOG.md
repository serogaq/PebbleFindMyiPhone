# Changelog

## 1.2.0 - 2026-08-31

- Improved Play Sound reliability: the watch now ignores stale responses and
  reports dropped or ambiguous command results without suggesting an unsafe
  retry.
- Limited the automatic device-lookup retry to responses explicitly confirmed
  by the backend as safe and pre-dispatch.
- Added consistent user-facing Apple authentication and MFA errors instead of
  exposing internal exceptions.
- Replaced the Settings build-time label with the source commit and its commit
  timestamp, making the installed app version easier to identify.

## 1.1.0 - 2026-08-31 / app

- Added automatic English and Russian localization for the Pebble watchapp and
  phone Settings, with directory-based language discovery and English fallback.
- Added app version and UTC build timestamp information to Settings.

## 1.0.1 - 2026-08-31 / backend

- Fixed `auth login` to force a fresh Apple authentication instead of reusing
  a session whose Find My authorization has expired.

## 1.0.0 - 2026-08-31

- Added a Docker Compose backend for Apple's real Find My Play Sound command.
- Added persistent Apple trusted-session authentication and exact opaque iPhone
  selection.
- Added Bearer authentication, required idempotency keys, cooldown protection,
  stable error codes, structured logs, and narrow Clay status CORS.
- Added a native C Pebble watchapp for Pebble 2, Pebble 2 Duo, Pebble Time 2,
  and Pebble Round 2.
- Added the iOS PebbleKit JS companion with safe retry semantics and Clay
  settings for address, SSL, token, and live Apple/backend readiness.
- Verified the complete path on physical Pebble and iPhone hardware.
