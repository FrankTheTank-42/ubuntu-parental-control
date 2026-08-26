#!/usr/bin/python3
"""Merge the project's managed keys into an existing Firefox policy."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extension-id", required=True)
    parser.add_argument("--install-url", required=True)
    args = parser.parse_args()

    document: dict[str, object] = {"policies": {}}
    if args.input and args.input.exists():
        with args.input.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("Firefox-Policy muss ein JSON-Objekt sein")
        document = loaded

    policies = document.setdefault("policies", {})
    if not isinstance(policies, dict):
        raise ValueError("'policies' muss ein JSON-Objekt sein")
    extension_settings = policies.setdefault("ExtensionSettings", {})
    if not isinstance(extension_settings, dict):
        raise ValueError("'ExtensionSettings' muss ein JSON-Objekt sein")

    extension_settings[args.extension_id] = {
        "installation_mode": "force_installed",
        "install_url": args.install_url,
        "updates_disabled": True,
        "private_browsing": True,
    }
    policies["BlockAboutConfig"] = True

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(temporary, 0o644)
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
