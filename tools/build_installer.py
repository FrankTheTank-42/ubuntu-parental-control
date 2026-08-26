#!/usr/bin/python3
"""Build a deterministic source installer bundle for milestone 2."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ubuntu-parental-control-installer-m2.zip"
PACKAGE_ROOT = "ubuntu-parental-control"
TOP_LEVEL_FILES = {".gitignore", "LICENSE", "README.md"}
TOP_LEVEL_DIRECTORIES = {
    "browser-extension",
    "config",
    "daemon",
    "docs",
    "installer",
    "schema",
    "tests",
    "tools",
}
DIST_FILES = {
    "ubuntu-parental-control-webfilter-firefox-unsigned.xpi",
    "ubuntu-parental-control-webfilter-chrome.zip",
}


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if "__pycache__" in relative.parts or path.suffix == ".pyc":
        return False
    if len(relative.parts) == 1:
        return relative.name in TOP_LEVEL_FILES
    if relative.parts[0] == "dist":
        return len(relative.parts) == 2 and relative.name in DIST_FILES
    return relative.parts[0] in TOP_LEVEL_DIRECTORIES


def main() -> None:
    subprocess.run(["python3", str(ROOT / "tools" / "build_extension.py")], check=True)
    files = sorted(path for path in ROOT.rglob("*") if path.is_file() and included(path))
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/{relative}", (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = path.stat().st_mode & 0o777
            info.external_attr = (0o100000 | mode) << 16
            archive.writestr(info, path.read_bytes())
    print(OUTPUT)


if __name__ == "__main__":
    main()
