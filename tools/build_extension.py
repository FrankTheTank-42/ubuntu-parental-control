#!/usr/bin/python3
"""Build deterministic Firefox and Chrome extension submission archives."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "browser-extension"
FIREFOX_OUTPUT = ROOT / "dist" / "ubuntu-parental-control-webfilter-firefox-unsigned.xpi"
LEGACY_FIREFOX_OUTPUT = ROOT / "dist" / "ubuntu-parental-control-webfilter-unsigned.xpi"
CHROME_OUTPUT = ROOT / "dist" / "ubuntu-parental-control-webfilter-chrome.zip"


def source_files() -> list[Path]:
    excluded = {SOURCE / "manifest.json", SOURCE / "manifest.chrome.json"}
    return sorted(path for path in SOURCE.rglob("*") if path.is_file() and path not in excluded)


def build_archive(output: Path, manifest_path: Path) -> None:
    files = [("manifest.json", manifest_path), *(
        (path.relative_to(SOURCE).as_posix(), path) for path in source_files()
    )]
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for archive_name, path in files:
            info = zipfile.ZipInfo(archive_name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def main() -> None:
    firefox_manifest = SOURCE / "manifest.json"
    chrome_manifest = SOURCE / "manifest.chrome.json"
    manifest = json.loads(firefox_manifest.read_text(encoding="utf-8"))
    if manifest["browser_specific_settings"]["gecko"]["id"] != "webfilter@ubuntu-parental-control.local":
        raise SystemExit("unerwartete Extension-ID")
    build_archive(FIREFOX_OUTPUT, firefox_manifest)
    # Keep the old output name for existing installer scripts and callers.
    build_archive(LEGACY_FIREFOX_OUTPUT, firefox_manifest)
    build_archive(CHROME_OUTPUT, chrome_manifest)
    print(FIREFOX_OUTPUT)
    print(CHROME_OUTPUT)
    print("Hinweis: Das XPI muss vor Firefox Release über AMO signiert werden.")
    print("Das Chrome-ZIP ist für die Einreichung im Chrome Web Store bestimmt.")


if __name__ == "__main__":
    main()
