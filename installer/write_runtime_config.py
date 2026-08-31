#!/usr/bin/python3
"""Write the root-owned daemon configuration selected by the installer."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


CHROME_ID_RE = re.compile(r"^[a-p]{32}$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chrome-extension-id")
    parser.add_argument("--chrome-update-url", default="https://clients2.google.com/service/update2/crx")
    parser.add_argument("--restricted-uid", action="append", type=int, default=[])
    parser.add_argument("--administrator-uid", action="append", type=int, default=[])
    parser.add_argument("--live-public-key-spki", required=True)
    args = parser.parse_args()

    with args.template.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not args.chrome_extension_id and args.output.exists():
        with args.output.open("r", encoding="utf-8") as handle:
            existing = json.load(handle)
        if "chrome" in existing.get("managed_browsers", []):
            existing_id = existing.get("chrome_extension_id")
            existing_url = existing.get("chrome_update_url")
            if CHROME_ID_RE.fullmatch(existing_id or "") and isinstance(existing_url, str):
                args.chrome_extension_id = existing_id
                args.chrome_update_url = existing_url
    browsers = ["firefox"]
    if args.chrome_extension_id:
        if not CHROME_ID_RE.fullmatch(args.chrome_extension_id):
            raise ValueError("Chrome-Extension-ID muss aus 32 Zeichen a-p bestehen")
        if not args.chrome_update_url.startswith("https://"):
            raise ValueError("Chrome-Update-URL muss HTTPS verwenden")
        browsers.append("chrome")
        config["chrome_extension_id"] = args.chrome_extension_id
        config["chrome_update_url"] = args.chrome_update_url
    else:
        config["chrome_extension_id"] = None
        config["chrome_update_url"] = None
    config["managed_browsers"] = browsers
    restricted_uids = args.restricted_uid
    if not restricted_uids and args.output.exists():
        with args.output.open("r", encoding="utf-8") as handle:
            existing = json.load(handle)
        existing_uids = existing.get("restricted_users", [])
        if isinstance(existing_uids, list):
            restricted_uids = existing_uids
    if (
        len(restricted_uids) != len(set(restricted_uids))
        or any(uid <= 0 or uid > 2**32 - 1 for uid in restricted_uids)
    ):
        raise ValueError("Restricted-User-UIDs müssen eindeutig und positiv sein")
    config["restricted_users"] = sorted(restricted_uids)
    administrator_uids = args.administrator_uid
    if not administrator_uids and args.output.exists():
        with args.output.open("r", encoding="utf-8") as handle:
            existing = json.load(handle)
        existing_uids = existing.get("administrator_users", [])
        if isinstance(existing_uids, list):
            administrator_uids = existing_uids
    if (
        len(administrator_uids) != len(set(administrator_uids))
        or any(uid <= 0 or uid > 2**32 - 1 for uid in administrator_uids)
        or set(administrator_uids) & set(restricted_uids)
    ):
        raise ValueError("Administrator-UIDs müssen eindeutig, positiv und von Kinder-UIDs getrennt sein")
    config["administrator_users"] = sorted(administrator_uids)
    config["live_public_key_spki"] = args.live_public_key_spki

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(temporary, 0o644)
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
