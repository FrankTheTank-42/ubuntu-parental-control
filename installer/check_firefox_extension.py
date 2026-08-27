#!/usr/bin/python3
"""Verify that an extension disappeared from known Firefox profile layouts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROFILE_PATTERNS = (
    "home/*/.mozilla/firefox/*",
    "home/*/snap/firefox/common/.mozilla/firefox/*",
    "home/*/.var/app/org.mozilla.firefox/.mozilla/firefox/*",
    "root/.mozilla/firefox/*",
    "root/snap/firefox/common/.mozilla/firefox/*",
    "root/.var/app/org.mozilla.firefox/.mozilla/firefox/*",
)


def inspect(root: Path, extension_id: str) -> tuple[list[Path], list[str]]:
    found: set[Path] = set()
    errors: list[str] = []
    profiles: set[Path] = set()
    for pattern in PROFILE_PATTERNS:
        profiles.update(path for path in root.glob(pattern) if path.is_dir())

    for profile in sorted(profiles):
        extension_path = profile / "extensions" / f"{extension_id}.xpi"
        extension_directory = profile / "extensions" / extension_id
        if extension_path.exists() or extension_directory.exists():
            found.add(profile)

        registry = profile / "extensions.json"
        if not registry.exists():
            continue
        try:
            with registry.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
            addons = document.get("addons", []) if isinstance(document, dict) else None
            if not isinstance(addons, list):
                raise ValueError("'addons' ist keine Liste")
            if any(isinstance(addon, dict) and addon.get("id") == extension_id for addon in addons):
                found.add(profile)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{registry}: {exc}")
    return sorted(found), errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--extension-id", required=True)
    args = parser.parse_args()

    found, errors = inspect(args.root, args.extension_id)
    for profile in found:
        print(f"Extension noch im Firefox-Profil vorhanden: {profile}")
    for error in errors:
        print(f"Firefox-Profil konnte nicht sicher geprüft werden: {error}", file=sys.stderr)
    if errors:
        return 2
    if found:
        return 1
    print("Extension ist aus allen gefundenen Firefox-Profilen entfernt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
