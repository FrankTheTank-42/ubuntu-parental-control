#!/usr/bin/python3
"""Build deterministic Firefox and Chrome extension submission archives."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "browser-extension"
FIREFOX_OUTPUT = ROOT / "dist" / "ubuntu-parental-control-webfilter-firefox-unsigned.xpi"
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
    firefox = json.loads(firefox_manifest.read_text(encoding="utf-8"))
    chrome = json.loads(chrome_manifest.read_text(encoding="utf-8"))
    if firefox["browser_specific_settings"]["gecko"]["id"] != "webfilter@ubuntu-parental-control.local":
        raise SystemExit("unerwartete Extension-ID")
    if firefox["version"] != chrome["version"]:
        raise SystemExit("Firefox- und Chrome-Version stimmen nicht überein")
    if firefox.get("background", {}).get("scripts") != [
        "common/rule-engine.js",
        "background/service-worker.js",
    ]:
        raise SystemExit("Firefox-Hintergrundskripte haben nicht die erforderliche Ladereihenfolge")
    expected_hosts = ["http://*/*", "https://*/*"]
    for browser, manifest in (("Firefox", firefox), ("Chrome", chrome)):
        if manifest.get("host_permissions") != expected_hosts:
            raise SystemExit(f"{browser}-Hostberechtigungen sind für die Blockseite unvollständig")
        accessible = manifest.get("web_accessible_resources", [])
        if not any("blocked/blocked.html" in entry.get("resources", []) for entry in accessible):
            raise SystemExit(f"{browser}-Manifest veröffentlicht die Blockseite nicht")
        if "nativeMessaging" not in manifest.get("permissions", []):
            raise SystemExit(f"{browser}-Manifest enthält nativeMessaging nicht")
        if "contextMenus" not in manifest.get("permissions", []):
            raise SystemExit(f"{browser}-Manifest enthält contextMenus nicht")
        if manifest.get("options_ui", {}).get("page") != "options/options.html":
            raise SystemExit(f"{browser}-Manifest bindet die Optionsseite nicht ein")
    for required in (SOURCE / "options" / "options.html", SOURCE / "options" / "options.js"):
        if not required.is_file():
            raise SystemExit(f"Optionsseiten-Datei fehlt: {required}")
    build_archive(FIREFOX_OUTPUT, firefox_manifest)
    build_archive(CHROME_OUTPUT, chrome_manifest)
    print(f"Extension-Version {firefox['version']}")
    print(FIREFOX_OUTPUT)
    print(CHROME_OUTPUT)
    print("Hinweis: Das XPI muss vor Firefox Release über AMO signiert werden.")
    print("Das Chrome-ZIP ist für die Einreichung im Chrome Web Store bestimmt.")


if __name__ == "__main__":
    main()
