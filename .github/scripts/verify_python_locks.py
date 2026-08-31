#!/usr/bin/env python3
"""Require the development lock to contain the exact production package graph."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ENTRY = re.compile(r"^([A-Za-z0-9_.-]+)==([^ \\]+)")


def _versions(path: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ENTRY.match(line)
        if not match:
            continue
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        if name in versions:
            raise SystemExit(f"error: duplicate package in {path}: {name}")
        versions[name] = match.group(2)
    if not versions:
        raise SystemExit(f"error: no locked packages found in {path}")
    return versions


def _require_declared_versions(
    source: Path, lock: Path, locked: dict[str, str]
) -> None:
    declared = _versions(source)
    mismatch = [
        f"{name}: declared={version}, locked={locked.get(name, 'missing')}"
        for name, version in sorted(declared.items())
        if locked.get(name) != version
    ]
    if mismatch:
        raise SystemExit(
            f"error: {lock} does not match direct pins in {source}:\n  "
            + "\n  ".join(mismatch)
        )


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: verify_python_locks.py PRODUCTION_INPUT PRODUCTION_LOCK "
            "DEVELOPMENT_INPUT DEVELOPMENT_LOCK"
        )
    production_input, production_path, development_input, development_path = map(
        Path, sys.argv[1:]
    )
    production = _versions(production_path)
    development = _versions(development_path)
    _require_declared_versions(production_input, production_path, production)
    _require_declared_versions(development_input, development_path, development)
    mismatch = [
        f"{name}: production={version}, development={development.get(name, 'missing')}"
        for name, version in sorted(production.items())
        if development.get(name) != version
    ]
    if mismatch:
        raise SystemExit(
            "error: development lock does not preserve the production graph:\n  "
            + "\n  ".join(mismatch)
        )
    print(
        f"development lock preserves all {len(production)} production package versions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
