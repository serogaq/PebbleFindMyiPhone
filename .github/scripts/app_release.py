#!/usr/bin/env python3
"""Build-time validation and packaging helpers for the Pebble app release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import NoReturn

APP_UUID = "91d0ef11-0f9b-424a-9876-d96b6067e388"
REQUIRED_NOTICE = (
    "Required Notice: Copyright © serogaq "
    "(https://github.com/serogaq/PebbleFindMyiPhone)"
)
EXPECTED_PLATFORMS = {"diorite", "emery", "flint", "gabbro"}


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def validate_pbw(pbw: Path, version: str) -> None:
    """Validate the release invariants embedded in a PBW archive."""

    if not pbw.is_file():
        _fail(f"PBW was not created: {pbw}")

    try:
        with zipfile.ZipFile(pbw) as archive:
            if archive.testzip() is not None:
                _fail("PBW contains a corrupt ZIP member")
            appinfo = json.loads(archive.read("appinfo.json"))
            companion = archive.read("pebble-js-app.js").decode("utf-8")
    except (
        OSError,
        KeyError,
        ValueError,
        UnicodeDecodeError,
        zipfile.BadZipFile,
    ) as exc:
        _fail(f"unable to read PBW: {exc}")

    if appinfo.get("versionLabel") != version:
        _fail("PBW version does not match the expected version")
    if str(appinfo.get("uuid", "")).lower() != APP_UUID:
        _fail("PBW contains an unexpected application UUID")
    if set(appinfo.get("targetPlatforms", [])) != EXPECTED_PLATFORMS:
        _fail("PBW target platform set is incomplete or unexpected")
    if REQUIRED_NOTICE not in companion:
        _fail("PBW does not contain the required notice")


def _release_notes(changelog: Path, version: str) -> str:
    text = changelog.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## {re.escape(version)}(?:\s+-[^\n]*)?\n(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    matches = pattern.findall(text)
    if len(matches) != 1 or not matches[0].strip():
        _fail(f"CHANGELOG.md must contain one non-empty section for {version}")
    return matches[0].strip() + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_dist(pbw: Path, version: str, changelog: Path, dist: Path) -> None:
    """Create the exact bundle consumed by release and smoke jobs."""

    dist.mkdir(parents=True, exist_ok=True)
    release_pbw = dist / f"pebble-find-my-iphone-{version}.pbw"
    release_pbw.write_bytes(pbw.read_bytes())
    (dist / "LICENSE.md").write_bytes(Path("LICENSE.md").read_bytes())
    (dist / "NOTICE").write_bytes(Path("NOTICE").read_bytes())
    (dist / "release-notes.md").write_text(
        _release_notes(changelog, version), encoding="utf-8"
    )

    expected = [
        release_pbw,
        dist / "LICENSE.md",
        dist / "NOTICE",
        dist / "release-notes.md",
    ]
    manifest = "".join(f"{_sha256(path)}  {path.name}\n" for path in expected)
    (dist / "SHA256SUMS").write_text(manifest, encoding="utf-8")


def validate_dist(dist: Path, version: str) -> None:
    """Validate a downloaded release bundle and its checksums."""

    expected_names = {
        f"pebble-find-my-iphone-{version}.pbw",
        "LICENSE.md",
        "NOTICE",
        "release-notes.md",
        "SHA256SUMS",
    }
    actual_names = {path.name for path in dist.iterdir() if path.is_file()}
    if actual_names != expected_names:
        _fail(
            "release bundle files differ from expected set: "
            f"expected {sorted(expected_names)}, got {sorted(actual_names)}"
        )

    manifest_lines = (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    expected_hashes: dict[str, str] = {}
    for line in manifest_lines:
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            _fail("SHA256SUMS contains an invalid entry")
        expected_hashes[fields[1]] = fields[0]
    if set(expected_hashes) != expected_names - {"SHA256SUMS"}:
        _fail("SHA256SUMS does not cover the expected release files")
    for name, expected in expected_hashes.items():
        actual = _sha256(dist / name)
        if actual != expected:
            _fail(f"SHA256 mismatch for {name}")

    validate_pbw(dist / f"pebble-find-my-iphone-{version}.pbw", version)
    if not (dist / "release-notes.md").read_text(encoding="utf-8").strip():
        _fail("release-notes.md is empty")
    if REQUIRED_NOTICE not in (dist / "NOTICE").read_text(encoding="utf-8"):
        _fail("NOTICE does not contain the required notice")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-pbw")
    validate.add_argument("--version", required=True)
    validate.add_argument("pbw", type=Path)

    prepare = subparsers.add_parser("prepare-dist")
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    prepare.add_argument("--dist", type=Path, default=Path("dist"))
    prepare.add_argument("pbw", type=Path)

    changelog = subparsers.add_parser("validate-changelog")
    changelog.add_argument("--version", required=True)
    changelog.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))

    bundle = subparsers.add_parser("validate-dist")
    bundle.add_argument("--version", required=True)
    bundle.add_argument("dist", type=Path)

    args = parser.parse_args(argv)
    if args.command == "validate-pbw":
        validate_pbw(args.pbw, args.version)
    elif args.command == "prepare-dist":
        prepare_dist(args.pbw, args.version, args.changelog, args.dist)
    elif args.command == "validate-changelog":
        _release_notes(args.changelog, args.version)
    else:
        validate_dist(args.dist, args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
