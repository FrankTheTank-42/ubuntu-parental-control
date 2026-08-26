#!/usr/bin/python3
"""Create a temporary Firefox policy that removes the managed extension."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extension-id", required=True)
    args = parser.parse_args()

    document: dict[str, object] = {"policies": {}}
    if args.base and args.base.exists():
        with args.base.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("Firefox-Policy muss ein JSON-Objekt sein")
        document = loaded

    policies = document.setdefault("policies", {})
    if not isinstance(policies, dict):
        raise ValueError("'policies' muss ein JSON-Objekt sein")

    # Eine eventuell aus der ursprünglichen Policy stammende Regel für dieselbe
    # ID darf die temporäre Deinstallation nicht überstimmen. Beim Finalisieren
    # wird das Original bytegenau zurückgespielt.
    settings = policies.get("ExtensionSettings")
    if isinstance(settings, dict):
        settings.pop(args.extension_id, None)
        if not settings:
            policies.pop("ExtensionSettings", None)

    extensions = policies.setdefault("Extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("'Extensions' muss ein JSON-Objekt sein")
    uninstall = extensions.setdefault("Uninstall", [])
    if not isinstance(uninstall, list):
        raise ValueError("'Extensions.Uninstall' muss eine Liste sein")
    if args.extension_id not in uninstall:
        uninstall.append(args.extension_id)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(temporary, 0o644)
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
