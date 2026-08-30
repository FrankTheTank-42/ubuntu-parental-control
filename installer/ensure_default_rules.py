#!/usr/bin/python3
"""Create or migrate the neutral default block during installation."""

from __future__ import annotations

import argparse
import copy
import json
import os
import stat
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "daemon"))

from rule_validator import RuleValidator, load_rules  # noqa: E402


def validate_rules(value: dict, label: str) -> None:
    validator = RuleValidator()
    issues = validator.validate(value)
    if issues:
        details = "\n".join(str(issue) for issue in issues)
        raise ValueError(f"{label} ist ungültig:\n{details}")


def default_block(defaults: dict) -> dict:
    matches = [block for block in defaults["blocks"] if block.get("id") == "default-block"]
    if len(matches) != 1:
        raise ValueError("Standardregel muss genau einen Block mit ID 'default-block' enthalten")
    return copy.deepcopy(matches[0])


def write_atomic(path: Path, value: dict, existing: os.stat_result | None) -> None:
    mode = stat.S_IMODE(existing.st_mode) if existing is not None else 0o644
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        if existing is not None:
            os.chown(temporary, existing.st_uid, existing.st_gid)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_default_rules(path: Path, defaults_path: Path) -> str:
    defaults = load_rules(defaults_path)
    validate_rules(defaults, "Standardregel")

    existing: os.stat_result | None = None
    if path.exists() or path.is_symlink():
        existing = path.lstat()
        if not stat.S_ISREG(existing.st_mode):
            raise ValueError(f"Regelpfad ist keine reguläre Datei: {path}")
        rules = load_rules(path)
        if rules.get("blocks") != []:
            return "unchanged"
        rules["blocks"] = [default_block(defaults)]
        result = "migrated"
    else:
        rules = defaults
        result = "created"

    validate_rules(rules, "resultierende Regeldatei")
    write_atomic(path, rules, existing)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--defaults", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = ensure_default_rules(arguments.rules, arguments.defaults)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Fehler: Standard-Blockierliste konnte nicht vorbereitet werden: {exc}")
    if result == "created":
        print("Standard-Blockierliste 'Webseiten sperren' angelegt.")
    elif result == "migrated":
        print("Leere Regeldatei um Standard-Blockierliste 'Webseiten sperren' ergänzt.")


if __name__ == "__main__":
    main()
