#!/usr/bin/python3
"""Install browser-specific manifests for the shared native messaging host."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


HOST_NAME = "ubuntu_parental_control"
FIREFOX_EXTENSION_ID = "webfilter@ubuntu-parental-control.local"
CHROME_ID_RE = re.compile(r"^[a-p]{32}$")


def write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o644)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-path", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--firefox-output", type=Path, required=True)
    parser.add_argument("--chrome-output", type=Path, required=True)
    parser.add_argument("--chrome-extension-id")
    args = parser.parse_args()

    chrome_extension_id = args.chrome_extension_id
    if not chrome_extension_id:
        with args.config.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        if "chrome" in config.get("managed_browsers", []):
            chrome_extension_id = config.get("chrome_extension_id")

    common = {
        "name": HOST_NAME,
        "description": "Ubuntu Parental Control live rules and restricted administration",
        "path": args.host_path,
        "type": "stdio",
    }
    write(
        args.firefox_output,
        {**common, "allowed_extensions": [FIREFOX_EXTENSION_ID]},
    )
    if chrome_extension_id:
        if not CHROME_ID_RE.fullmatch(chrome_extension_id):
            raise ValueError("Chrome-Extension-ID ist ungültig")
        write(
            args.chrome_output,
            {
                **common,
                "allowed_origins": [f"chrome-extension://{chrome_extension_id}/"],
            },
        )
    else:
        args.chrome_output.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
