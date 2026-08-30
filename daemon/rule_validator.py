#!/usr/bin/python3
"""Validate Ubuntu Parental Control web-rule files without third-party modules."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BLOCK_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
TIME_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
RRULE_RE = re.compile(
    r"^FREQ=WEEKLY;BYDAY=(MO|TU|WE|TH|FR|SA|SU)"
    r"(?:,(MO|TU|WE|TH|FR|SA|SU))*$"
)
URL_PATTERN_RE = re.compile(
    r"^(?P<scheme>\*|https?)://(?P<host>\*|\*\.[a-z0-9.-]+|[a-z0-9.-]+)"
    r"(?P<path>/[^\s]*)$"
)
UNSUPPORTED_RE2 = (
    re.compile(r"\\[1-9]"),
    re.compile(r"\(\?(?:[=!]|<[=!]|P[=<]|\(|>|#)"),
    re.compile(r"\(\?[a-zA-Z-]+:?"),
)


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"doppelter JSON-Schlüssel: {key!r}")
        result[key] = value
    return result


def load_rules(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, dict):
        raise ValueError("die Wurzel muss ein JSON-Objekt sein")
    return value


class RuleValidator:
    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def error(self, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(path, message))

    def object(
        self,
        value: Any,
        path: str,
        required: Iterable[str],
        allowed: Iterable[str],
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self.error(path, "muss ein Objekt sein")
            return None
        required_set, allowed_set = set(required), set(allowed)
        for key in sorted(required_set - value.keys()):
            self.error(path, f"Pflichtfeld {key!r} fehlt")
        for key in sorted(value.keys() - allowed_set):
            self.error(f"{path}.{key}", "unbekanntes Feld")
        return value

    def validate(self, rules: dict[str, Any]) -> list[ValidationIssue]:
        self.issues = []
        root = self.object(
            rules, "$", ("format_version", "profile", "blocks"),
            ("$schema", "format_version", "profile", "blocks"),
        )
        if root is None:
            return self.issues
        if root.get("format_version") != "1.0":
            self.error("$.format_version", "muss '1.0' sein")
        self.validate_profile(root.get("profile"), "$.profile")
        blocks = root.get("blocks")
        if not isinstance(blocks, list):
            self.error("$.blocks", "muss eine Liste sein")
        else:
            if len(blocks) > 1000:
                self.error("$.blocks", "darf höchstens 1000 Blocks enthalten")
            ids: dict[str, int] = {}
            for index, block in enumerate(blocks):
                self.validate_block(block, f"$.blocks[{index}]")
                if isinstance(block, dict) and isinstance(block.get("id"), str):
                    block_id = block["id"]
                    if block_id in ids:
                        self.error(
                            f"$.blocks[{index}].id",
                            f"Block-ID bereits in $.blocks[{ids[block_id]}] verwendet",
                        )
                    else:
                        ids[block_id] = index
        return self.issues

    def validate_profile(self, value: Any, path: str) -> None:
        profile = self.object(
            value, path, ("timezone", "default_action", "conflict_policy"),
            ("timezone", "default_action", "conflict_policy"),
        )
        if profile is None:
            return
        self.validate_timezone(profile.get("timezone"), f"{path}.timezone")
        self.validate_action(profile.get("default_action"), f"{path}.default_action")
        if profile.get("conflict_policy") != "priority_then_deny":
            self.error(f"{path}.conflict_policy", "muss 'priority_then_deny' sein")

    def validate_block(self, value: Any, path: str) -> None:
        fields = (
            "id", "name", "enabled", "priority", "action", "user_permissions",
            "targets", "exceptions", "schedule", "limits",
        )
        block = self.object(value, path, (x for x in fields if x != "schedule"), fields)
        if block is None:
            return
        block_id = block.get("id")
        if not isinstance(block_id, str) or not (1 <= len(block_id) <= 64) or not BLOCK_ID_RE.fullmatch(block_id):
            self.error(
                f"{path}.id",
                "muss mit einem Kleinbuchstaben beginnen und darf nur Kleinbuchstaben, "
                "Ziffern und einzelne Bindestriche enthalten (höchstens 64 Zeichen; "
                "Beispiel: soziale-medien)",
            )
        name = block.get("name")
        if not isinstance(name, str) or not (1 <= len(name) <= 120):
            self.error(f"{path}.name", "muss 1 bis 120 Zeichen lang sein")
        if type(block.get("enabled")) is not bool:
            self.error(f"{path}.enabled", "muss true oder false sein")
        priority = block.get("priority")
        if type(priority) is not int or not (-1000 <= priority <= 1000):
            self.error(f"{path}.priority", "muss eine ganze Zahl von -1000 bis 1000 sein")
        self.validate_action(block.get("action"), f"{path}.action")
        self.validate_permissions(
            block.get("user_permissions"), block.get("action"), f"{path}.user_permissions"
        )
        self.validate_matchers(block.get("targets"), f"{path}.targets")
        self.validate_matchers(block.get("exceptions"), f"{path}.exceptions")
        if "schedule" in block:
            self.validate_schedule(block["schedule"], f"{path}.schedule")
        if block.get("limits", object()) is not None:
            self.error(f"{path}.limits", "ist in Version 1.0 reserviert und muss null sein")

    def validate_action(self, value: Any, path: str) -> None:
        if value not in ("allow", "block"):
            self.error(path, "muss 'allow' oder 'block' sein")

    def validate_permissions(self, value: Any, action: Any, path: str) -> None:
        fields = (
            "add_domains", "remove_domains", "add_url_patterns", "add_url_regex",
            "modify_exceptions", "modify_schedule", "disable_block",
        )
        permissions = self.object(value, path, fields, fields)
        if permissions is None:
            return
        for field in fields:
            item = permissions.get(field)
            if type(item) is not bool:
                self.error(f"{path}.{field}", "muss true oder false sein")
            elif field != "add_domains" and item:
                self.error(f"{path}.{field}", "muss in Version 1.0 false sein")
        if permissions.get("add_domains") is True and action != "block":
            self.error(f"{path}.add_domains", "ist nur bei action 'block' erlaubt")

    def validate_matchers(self, value: Any, path: str) -> None:
        fields = ("domains", "url_patterns", "url_regex")
        matchers = self.object(value, path, fields, fields)
        if matchers is None:
            return
        validators = (
            ("domains", 10000, self.validate_domain),
            ("url_patterns", 1000, self.validate_url_pattern),
            ("url_regex", 100, self.validate_url_regex),
        )
        for field, maximum, validator in validators:
            items = matchers.get(field)
            item_path = f"{path}.{field}"
            if not isinstance(items, list):
                self.error(item_path, "muss eine Liste sein")
                continue
            if len(items) > maximum:
                self.error(item_path, f"darf höchstens {maximum} Einträge enthalten")
            seen: set[str] = set()
            for index, item in enumerate(items):
                marker = json.dumps(item, ensure_ascii=True, sort_keys=True)
                if marker in seen:
                    self.error(f"{item_path}[{index}]", "doppelter Eintrag")
                seen.add(marker)
                validator(item, f"{item_path}[{index}]")
    def validate_domain(self, value: Any, path: str) -> None:
        if not isinstance(value, str) or not (3 <= len(value) <= 253) or not DOMAIN_RE.fullmatch(value):
            self.error(path, "muss eine kleingeschriebene ASCII-Domain ohne Schema, Port oder Pfad sein")
            return
        for label in value.split("."):
            if label.startswith("xn--"):
                try:
                    label.encode("ascii").decode("idna")
                except UnicodeError:
                    self.error(path, f"ungültiges Punycode-Label {label!r}")

    def validate_url_pattern(self, value: Any, path: str) -> None:
        if not isinstance(value, str) or not (7 <= len(value) <= 2048):
            self.error(path, "muss ein HTTP(S)-URL-Pattern mit 7 bis 2048 Zeichen sein")
            return
        match = URL_PATTERN_RE.fullmatch(value)
        if not match:
            self.error(path, "ungültiges WebExtension-Pattern; erwartet SCHEMA://HOST/PFAD")
            return
        host = match.group("host")
        if host == "*":
            return
        domain = host[2:] if host.startswith("*.") else host
        self.validate_domain(domain, path)

    def validate_url_regex(self, value: Any, path: str) -> None:
        regex = self.object(value, path, ("pattern", "case_sensitive"), ("pattern", "case_sensitive"))
        if regex is None:
            return
        pattern = regex.get("pattern")
        if not isinstance(pattern, str) or not (1 <= len(pattern) <= 512):
            self.error(f"{path}.pattern", "muss 1 bis 512 Zeichen lang sein")
        elif any(ord(char) < 32 or ord(char) > 126 for char in pattern):
            self.error(f"{path}.pattern", "darf nur druckbare ASCII-Zeichen enthalten")
        else:
            if any(check.search(pattern) for check in UNSUPPORTED_RE2):
                self.error(f"{path}.pattern", "enthält ein von RE2 nicht unterstütztes Konstrukt")
            try:
                re.compile(pattern)
            except re.error as exc:
                self.error(f"{path}.pattern", f"ungültiger regulärer Ausdruck: {exc}")
        if type(regex.get("case_sensitive")) is not bool:
            self.error(f"{path}.case_sensitive", "muss true oder false sein")

    def validate_schedule(self, value: Any, path: str) -> None:
        schedule = self.object(value, path, ("timezone", "windows"), ("timezone", "windows"))
        if schedule is None:
            return
        self.validate_timezone(schedule.get("timezone"), f"{path}.timezone")
        windows = schedule.get("windows")
        if not isinstance(windows, list):
            self.error(f"{path}.windows", "muss eine Liste sein")
            return
        if not (1 <= len(windows) <= 100):
            self.error(f"{path}.windows", "muss 1 bis 100 Zeitfenster enthalten")
        seen: set[str] = set()
        for index, window in enumerate(windows):
            window_path = f"{path}.windows[{index}]"
            marker = json.dumps(window, ensure_ascii=True, sort_keys=True)
            if marker in seen:
                self.error(window_path, "doppeltes Zeitfenster")
            seen.add(marker)
            self.validate_window(window, window_path)

    def validate_window(self, value: Any, path: str) -> None:
        window = self.object(value, path, ("start", "end", "rrule"), ("start", "end", "rrule"))
        if window is None:
            return
        for field in ("start", "end"):
            if not isinstance(window.get(field), str) or not TIME_RE.fullmatch(window[field]):
                self.error(f"{path}.{field}", "muss eine Uhrzeit im Format HH:MM sein")
        rrule = window.get("rrule")
        if not isinstance(rrule, str) or not RRULE_RE.fullmatch(rrule):
            self.error(f"{path}.rrule", "muss FREQ=WEEKLY;BYDAY=... verwenden")
            return
        days = rrule.removeprefix("FREQ=WEEKLY;BYDAY=").split(",")
        duplicates = sorted(day for day in set(days) if days.count(day) > 1)
        if duplicates:
            self.error(f"{path}.rrule", f"Wochentage doppelt: {', '.join(duplicates)}")

    def validate_timezone(self, value: Any, path: str) -> None:
        if not isinstance(value, str) or not (3 <= len(value) <= 64):
            self.error(path, "muss eine IANA-Zeitzone sein")
            return
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            self.error(path, f"unbekannte IANA-Zeitzone {value!r}")


def validate_file(path: Path) -> list[ValidationIssue]:
    return RuleValidator().validate(load_rules(path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Webfilter-Regeldatei prüfen")
    parser.add_argument("rules", type=Path, help="Pfad zur JSON-Regeldatei")
    parser.add_argument("--json", action="store_true", help="Ergebnis maschinenlesbar ausgeben")
    args = parser.parse_args()
    try:
        issues = validate_file(args.rules)
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError, ValueError) as exc:
        issues = [ValidationIssue("$", str(exc))]
    if args.json:
        print(json.dumps({"valid": not issues, "errors": [issue.__dict__ for issue in issues]}, ensure_ascii=False))
    elif issues:
        print(f"Ungültige Regeldatei ({len(issues)} Fehler):", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
    else:
        print("Regeldatei ist gültig.")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
