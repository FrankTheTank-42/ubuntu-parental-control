#!/usr/bin/python3
"""Safe command-line administration for Ubuntu Parental Control rules."""

from __future__ import annotations

import argparse
import fcntl
import copy
import difflib
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import unicodedata
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Any

from rule_validator import DuplicateKeyError, RuleValidator, ValidationIssue, load_rules
from user_rules import UserDomainStore, UserRuleError


SYSTEM_RULES = Path("/etc/ubuntu-parental-control/rules.json")
SYSTEM_HISTORY = Path("/var/lib/ubuntu-parental-control/rule-history")
SYSTEM_USER_DOMAINS = Path("/var/lib/ubuntu-parental-control/user-domains.json")
VERSION_RE = re.compile(
    r"^[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-[0-9a-f]{12}-[0-9a-f]{4}$"
)


class CommandError(RuntimeError):
    pass


@contextmanager
def rules_mutation_lock(path: Path):
    lock_path = path.with_name(f"{path.name}.lock")
    if lock_path.is_symlink():
        raise CommandError(f"Regelsperre darf kein symbolischer Link sein: {lock_path}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise CommandError("Regelsperre ist nicht ausreichend geschützt")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def locked_mutation(function):
    @wraps(function)
    def wrapper(path: Path, *args, **kwargs):
        with rules_mutation_lock(path):
            return function(path, *args, **kwargs)
    return wrapper


def normalized_block_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip().casefold()


def reject_duplicate_block_name(
    rules: dict[str, Any],
    name: str,
    *,
    exclude_id: str | None = None,
) -> None:
    normalized = normalized_block_name(name)
    duplicate = next(
        (
            block
            for block in rules["blocks"]
            if block["id"] != exclude_id
            and normalized_block_name(block["name"]) == normalized
        ),
        None,
    )
    if duplicate is not None:
        raise CommandError(
            f"Blockname wird bereits von ID {duplicate['id']!r} verwendet: {duplicate['name']}"
        )


def format_issues(issues: list[ValidationIssue]) -> str:
    return "\n".join(f"- {issue}" for issue in issues)


def load_valid_rules(path: Path) -> dict[str, Any]:
    try:
        rules = load_rules(path)
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError, ValueError) as exc:
        raise CommandError(f"{path}: {exc}") from exc
    issues = RuleValidator().validate(rules)
    if issues:
        raise CommandError(
            f"{path} enthält {len(issues)} Validierungsfehler:\n{format_issues(issues)}"
        )
    return rules


def require_system_root(path: Path) -> None:
    if path.resolve(strict=False) == SYSTEM_RULES and os.geteuid() != 0:
        raise CommandError("Änderungen an der Systemregeldatei müssen als root ausgeführt werden")


def history_dir_for(path: Path, override: Path | None = None) -> Path:
    if override is not None:
        return override
    if path.resolve(strict=False) == SYSTEM_RULES:
        return SYSTEM_HISTORY
    return path.parent / f".{path.name}.history"


def canonical_rules(rules: dict[str, Any]) -> str:
    return json.dumps(rules, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def rules_digest(rules: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_rules(rules).encode("utf-8")).hexdigest()[:12]


def require_safe_history_dir(path: Path, *, create: bool) -> None:
    if path.is_symlink():
        raise CommandError(f"Versionsverzeichnis darf kein symbolischer Link sein: {path}")
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise CommandError(f"Versionsverzeichnis kann nicht angelegt werden: {path}: {exc}") from exc
    if not path.is_dir():
        raise CommandError(f"Versionsverzeichnis fehlt oder ist kein Verzeichnis: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise CommandError(
            f"Versionsverzeichnis ist nicht ausreichend geschützt ({mode:04o}): {path}"
        )


def create_history_snapshot(history_dir: Path, rules: dict[str, Any]) -> str:
    require_safe_history_dir(history_dir, create=True)
    content = canonical_rules(rules)
    digest = rules_digest(rules)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    version = f"{timestamp}-{digest}-{secrets.token_hex(2)}"
    target = history_dir / f"{version}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        directory_fd = os.open(history_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise CommandError(f"Regelversion konnte nicht gesichert werden: {exc}") from exc
    return version


def history_versions(history_dir: Path) -> list[tuple[str, Path]]:
    require_safe_history_dir(history_dir, create=False)
    versions: list[tuple[str, Path]] = []
    for item in history_dir.iterdir():
        if not item.name.endswith(".json"):
            continue
        version = item.name.removesuffix(".json")
        if not VERSION_RE.fullmatch(version):
            raise CommandError(f"Ungültiger Dateiname im Versionsverzeichnis: {item.name}")
        if item.is_symlink() or not item.is_file():
            raise CommandError(f"Regelversion ist keine reguläre Datei: {item}")
        versions.append((version, item))
    return sorted(versions, reverse=True)


def load_history_version(history_dir: Path, version: str) -> dict[str, Any]:
    if not VERSION_RE.fullmatch(version):
        raise CommandError(f"Ungültige Versions-ID: {version}")
    require_safe_history_dir(history_dir, create=False)
    snapshot = history_dir / f"{version}.json"
    if snapshot.is_symlink() or not snapshot.is_file():
        raise CommandError(f"Regelversion nicht gefunden: {version}")
    mode = stat.S_IMODE(snapshot.stat().st_mode)
    if mode & 0o077:
        raise CommandError(
            f"Regelversion ist nicht ausreichend geschützt ({mode:04o}): {version}"
        )
    rules = load_valid_rules(snapshot)
    expected_digest = version.split("-")[-2]
    if rules_digest(rules) != expected_digest:
        raise CommandError(f"Prüfsumme der Regelversion stimmt nicht: {version}")
    return rules


def render_diff(current: dict[str, Any], proposed: dict[str, Any]) -> str:
    before = canonical_rules(current).splitlines(keepends=True)
    after = canonical_rules(proposed).splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            before,
            after,
            fromfile="aktive-regeln.json",
            tofile="vorgeschlagene-regeln.json",
        )
    )


def write_rules_atomic(
    path: Path,
    rules: dict[str, Any],
    *,
    history_dir: Path | None = None,
) -> str | None:
    issues = RuleValidator().validate(rules)
    if issues:
        raise CommandError(
            f"Änderung würde ungültige Regeln erzeugen:\n{format_issues(issues)}"
        )
    require_system_root(path)
    if path.is_symlink():
        raise CommandError(f"Zieldatei darf kein symbolischer Link sein: {path}")
    if not path.parent.is_dir():
        raise CommandError(f"Zielverzeichnis fehlt: {path.parent}")

    previous = None
    if path.exists():
        previous = path.stat()
        if not stat.S_ISREG(previous.st_mode):
            raise CommandError(f"Ziel ist keine reguläre Datei: {path}")

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_rules(rules))
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), stat.S_IMODE(previous.st_mode) if previous else 0o644)
            if previous and os.geteuid() == 0:
                os.fchown(handle.fileno(), previous.st_uid, previous.st_gid)
        version = None
        if previous:
            try:
                current = load_valid_rules(path)
            except CommandError:
                # Eine bereits beschädigte aktive Datei darf durch `apply`
                # repariert werden, wird aber nie als gültige Version archiviert.
                current = None
            if current is not None:
                if current == rules:
                    return None
                version = create_history_snapshot(history_dir_for(path, history_dir), current)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return version


def find_block(rules: dict[str, Any], block_id: str) -> dict[str, Any]:
    for block in rules["blocks"]:
        if block["id"] == block_id:
            return block
    raise CommandError(f"Block nicht gefunden: {block_id}")


def validate_domain(domain: str) -> None:
    validator = RuleValidator()
    validator.validate_domain(domain, "domain")
    if validator.issues:
        raise CommandError(format_issues(validator.issues))


def print_activation_hint(path: Path) -> None:
    if path.resolve(strict=False) == SYSTEM_RULES:
        print(
            "Hinweis: Der Native Host überträgt die Änderung an laufende Browser. "
            "Zeigt die Extension den Nur-Lesen-Modus, benötigt Firefox für den "
            "Managed-Storage-Fallback einen vollständigen Browserneustart."
        )


def command_validate(path: Path) -> None:
    rules = load_valid_rules(path)
    print(f"Regeldatei ist gültig ({len(rules['blocks'])} Blocks).")


def command_show(path: Path) -> None:
    rules = load_valid_rules(path)
    json.dump(rules, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    print()


def command_show_block(path: Path, block_id: str) -> None:
    rules = load_valid_rules(path)
    block = find_block(rules, block_id)
    json.dump(block, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    print()


def command_list(path: Path) -> None:
    rules = load_valid_rules(path)
    if not rules["blocks"]:
        print("Keine Blocks konfiguriert.")
        return
    for block in rules["blocks"]:
        status = "aktiv" if block["enabled"] else "inaktiv"
        target_count = sum(len(block["targets"][field]) for field in ("domains", "url_patterns", "url_regex"))
        print(
            f"{block['id']}: {block['name']} "
            f"({status}, {block['action']}, Priorität {block['priority']}, {target_count} Ziele)"
        )


def command_apply(target: Path, source: Path, dry_run: bool = False) -> None:
    rules = load_valid_rules(source)
    if dry_run:
        current = load_valid_rules(target)
        difference = render_diff(current, rules)
        print(difference or "Keine Änderungen.", end="" if difference else "\n")
        print("Vorschau abgeschlossen; die aktive Regeldatei wurde nicht verändert.")
        return
    with rules_mutation_lock(target):
        version = write_rules_atomic(target, rules)
    if version:
        print(f"Vorherige Regelversion gesichert: {version}")
    print(f"Regeln atomar übernommen: {target}")
    print_activation_hint(target)


def command_history(path: Path) -> None:
    history_dir = history_dir_for(path)
    if not history_dir.exists():
        if history_dir.is_symlink():
            raise CommandError(
                f"Versionsverzeichnis darf kein symbolischer Link sein: {history_dir}"
            )
        print("Noch keine früheren Regelversionen vorhanden.")
        return
    versions = history_versions(history_dir)
    if not versions:
        print("Noch keine früheren Regelversionen vorhanden.")
        return
    for version, snapshot in versions:
        rules = load_history_version(history_dir, version)
        print(
            f"{version}  {len(rules['blocks'])} Blocks  "
            f"Standard: {rules['profile']['default_action']}"
        )


@locked_mutation
def command_rollback(
    path: Path,
    version: str,
    *,
    confirmed: bool,
    dry_run: bool,
) -> None:
    rules = load_history_version(history_dir_for(path), version)
    current = load_valid_rules(path)
    difference = render_diff(current, rules)
    if dry_run:
        print(difference or "Keine Änderungen.", end="" if difference else "\n")
        print("Rollback-Vorschau abgeschlossen; die aktive Regeldatei wurde nicht verändert.")
        return
    if not confirmed:
        raise CommandError("Rollback muss ausdrücklich mit --yes bestätigt werden")
    if not difference:
        raise CommandError("Die ausgewählte Version entspricht bereits den aktiven Regeln")
    saved_version = write_rules_atomic(path, rules)
    if saved_version:
        print(f"Vor dem Rollback gesicherte Regelversion: {saved_version}")
    print(f"Rollback auf Regelversion {version} abgeschlossen.")
    print_activation_hint(path)


@locked_mutation
def command_set_profile(
    path: Path,
    *,
    timezone: str | None,
    default_action: str | None,
) -> None:
    if timezone is None and default_action is None:
        raise CommandError("mindestens eine Profileinstellung muss angegeben werden")
    rules = copy.deepcopy(load_valid_rules(path))
    if timezone is not None:
        rules["profile"]["timezone"] = timezone
    if default_action is not None:
        rules["profile"]["default_action"] = default_action
    write_rules_atomic(path, rules)
    print("Profileinstellungen aktualisiert.")
    print_activation_hint(path)


def command_list_user_domains(path: Path) -> None:
    try:
        state = UserDomainStore(path).load()
    except UserRuleError as exc:
        raise CommandError(str(exc)) from exc
    entries = 0
    for uid, blocks in sorted(state["users"].items(), key=lambda item: int(item[0])):
        for block_id, domains in sorted(blocks.items()):
            for domain in domains:
                print(f"UID {uid}  {block_id}  {domain}")
                entries += 1
    if entries == 0:
        print("Keine Domain-Ergänzungen eingeschränkter Benutzer vorhanden.")


def command_remove_user_domain(
    path: Path,
    uid: int,
    block_id: str,
    domain: str,
    confirmed: bool,
) -> None:
    if not confirmed:
        raise CommandError("Entfernen einer Benutzer-Domain muss mit --yes bestätigt werden")
    if path.resolve(strict=False) == SYSTEM_USER_DOMAINS and os.geteuid() != 0:
        raise CommandError("Benutzer-Domains dürfen nur als root entfernt werden")
    store = UserDomainStore(path)
    try:
        store.remove(uid, block_id, domain)
    except UserRuleError as exc:
        raise CommandError(str(exc)) from exc
    print(f"Benutzer-Domain entfernt: UID {uid}, Block {block_id!r}, {domain}")
    if path.resolve(strict=False) == SYSTEM_USER_DOMAINS:
        print("Hinweis: Der Dienst veröffentlicht die Änderung automatisch.")


@locked_mutation
def command_add_domain(path: Path, block_id: str, domain: str) -> None:
    validate_domain(domain)
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    domains = block["targets"]["domains"]
    if domain in domains:
        raise CommandError(f"Domain ist bereits in Block {block_id!r} enthalten: {domain}")
    domains.append(domain)
    domains.sort()
    write_rules_atomic(path, rules)
    print(f"Domain zu Block {block_id!r} hinzugefügt: {domain}")
    print_activation_hint(path)


@locked_mutation
def command_remove_domain(path: Path, block_id: str, domain: str) -> None:
    validate_domain(domain)
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    domains = block["targets"]["domains"]
    if domain not in domains:
        raise CommandError(f"Domain ist nicht in Block {block_id!r} enthalten: {domain}")
    domains.remove(domain)
    write_rules_atomic(path, rules)
    print(f"Domain aus Block {block_id!r} entfernt: {domain}")
    print_activation_hint(path)


@locked_mutation
def command_create_block(
    path: Path,
    block_id: str,
    name: str,
    action: str,
    priority: int,
    domains: list[str],
) -> None:
    for domain in domains:
        validate_domain(domain)
    rules = copy.deepcopy(load_valid_rules(path))
    if any(block["id"] == block_id for block in rules["blocks"]):
        raise CommandError(f"Block-ID wird bereits verwendet: {block_id}")
    reject_duplicate_block_name(rules, name)
    rules["blocks"].append(
        {
            "id": block_id,
            "name": name,
            "enabled": True,
            "priority": priority,
            "action": action,
            "user_permissions": {
                "add_domains": action == "block",
                "remove_domains": False,
                "add_url_patterns": False,
                "add_url_regex": False,
                "modify_exceptions": False,
                "modify_schedule": False,
                "disable_block": False,
            },
            "targets": {
                "domains": sorted(domains),
                "url_patterns": [],
                "url_regex": [],
            },
            "exceptions": {
                "domains": [],
                "url_patterns": [],
                "url_regex": [],
            },
            "limits": None,
        }
    )
    write_rules_atomic(path, rules)
    print(f"Block erstellt: {block_id}")
    print_activation_hint(path)


@locked_mutation
def command_set_block(
    path: Path,
    block_id: str,
    *,
    name: str | None,
    action: str | None,
    priority: int | None,
    enabled: bool | None,
) -> None:
    if name is None and action is None and priority is None and enabled is None:
        raise CommandError("mindestens eine Block-Einstellung muss angegeben werden")
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    if name is not None:
        reject_duplicate_block_name(rules, name, exclude_id=block_id)
        block["name"] = name
    if action is not None:
        block["action"] = action
        block["user_permissions"]["add_domains"] = action == "block"
    if priority is not None:
        block["priority"] = priority
    if enabled is not None:
        block["enabled"] = enabled
    write_rules_atomic(path, rules)
    print(f"Block aktualisiert: {block_id}")
    print_activation_hint(path)


@locked_mutation
def command_delete_block(path: Path, block_id: str, confirmed: bool) -> None:
    if not confirmed:
        raise CommandError("Block-Löschung muss ausdrücklich mit --yes bestätigt werden")
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    rules["blocks"].remove(block)
    write_rules_atomic(path, rules)
    print(f"Block gelöscht: {block_id}")
    print_activation_hint(path)


@locked_mutation
def command_update_string_matcher(
    path: Path,
    block_id: str,
    group: str,
    field: str,
    value: str,
    *,
    add: bool,
) -> None:
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    values = block[group][field]
    if add:
        if value in values:
            raise CommandError(f"Eintrag ist bereits in Block {block_id!r} enthalten: {value}")
        values.append(value)
        values.sort()
        verb = "hinzugefügt"
    else:
        if value not in values:
            raise CommandError(f"Eintrag ist nicht in Block {block_id!r} enthalten: {value}")
        values.remove(value)
        verb = "entfernt"
    write_rules_atomic(path, rules)
    label = {
        ("targets", "url_patterns"): "URL-Pattern",
        ("exceptions", "domains"): "Domain-Ausnahme",
    }.get((group, field), field)
    print(f"{label} in Block {block_id!r} {verb}: {value}")
    print_activation_hint(path)


@locked_mutation
def command_update_url_regex(
    path: Path,
    block_id: str,
    pattern: str,
    case_sensitive: bool,
    *,
    add: bool,
) -> None:
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    values = block["targets"]["url_regex"]
    value = {"pattern": pattern, "case_sensitive": case_sensitive}
    if add:
        if value in values:
            raise CommandError(f"URL-Regex ist bereits in Block {block_id!r} enthalten")
        values.append(value)
        verb = "hinzugefügt"
    else:
        if value not in values:
            raise CommandError(f"URL-Regex ist nicht in Block {block_id!r} enthalten")
        values.remove(value)
        verb = "entfernt"
    write_rules_atomic(path, rules)
    print(f"URL-Regex in Block {block_id!r} {verb}: {pattern}")
    print_activation_hint(path)


def weekly_rrule(days: str) -> str:
    values = [day.strip().upper() for day in days.split(",") if day.strip()]
    if not values:
        raise CommandError("--days muss mindestens einen Wochentag enthalten")
    return f"FREQ=WEEKLY;BYDAY={','.join(values)}"


@locked_mutation
def command_add_window(
    path: Path,
    block_id: str,
    timezone: str,
    start: str,
    end: str,
    days: str,
) -> None:
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    schedule = block.get("schedule")
    if schedule is None:
        schedule = {"timezone": timezone, "windows": []}
        block["schedule"] = schedule
    elif schedule["timezone"] != timezone:
        raise CommandError(
            f"Block verwendet bereits Zeitzone {schedule['timezone']!r}; "
            "ändere sie zuerst mit set-schedule-timezone"
        )
    schedule["windows"].append(
        {"start": start, "end": end, "rrule": weekly_rrule(days)}
    )
    write_rules_atomic(path, rules)
    print(f"Zeitfenster zu Block {block_id!r} hinzugefügt.")
    print_activation_hint(path)


@locked_mutation
def command_remove_window(path: Path, block_id: str, index: int) -> None:
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    schedule = block.get("schedule")
    if schedule is None:
        raise CommandError(f"Block {block_id!r} hat keinen Zeitplan")
    if not 1 <= index <= len(schedule["windows"]):
        raise CommandError(
            f"Zeitfenster-Index muss zwischen 1 und {len(schedule['windows'])} liegen"
        )
    schedule["windows"].pop(index - 1)
    if not schedule["windows"]:
        block.pop("schedule")
    write_rules_atomic(path, rules)
    print(f"Zeitfenster {index} aus Block {block_id!r} entfernt.")
    print_activation_hint(path)


@locked_mutation
def command_set_schedule_timezone(path: Path, block_id: str, timezone: str) -> None:
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    schedule = block.get("schedule")
    if schedule is None:
        raise CommandError(f"Block {block_id!r} hat keinen Zeitplan")
    schedule["timezone"] = timezone
    write_rules_atomic(path, rules)
    print(f"Zeitplan-Zeitzone für Block {block_id!r} geändert: {timezone}")
    print_activation_hint(path)


def command_list_windows(path: Path, block_id: str) -> None:
    rules = load_valid_rules(path)
    block = find_block(rules, block_id)
    schedule = block.get("schedule")
    if schedule is None:
        print(f"Block {block_id!r} hat keinen Zeitplan.")
        return
    print(f"Zeitzone: {schedule['timezone']}")
    for index, window in enumerate(schedule["windows"], start=1):
        days = window["rrule"].removeprefix("FREQ=WEEKLY;BYDAY=")
        print(f"{index}: {days} {window['start']}-{window['end']}")


@locked_mutation
def command_clear_schedule(path: Path, block_id: str, confirmed: bool) -> None:
    if not confirmed:
        raise CommandError("Entfernen des Zeitplans muss ausdrücklich mit --yes bestätigt werden")
    rules = copy.deepcopy(load_valid_rules(path))
    block = find_block(rules, block_id)
    if "schedule" not in block:
        raise CommandError(f"Block {block_id!r} hat keinen Zeitplan")
    block.pop("schedule")
    write_rules_atomic(path, rules)
    print(f"Zeitplan aus Block {block_id!r} entfernt.")
    print_activation_hint(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upcctl",
        description="Ubuntu-Parental-Control-Regeln sicher verwalten",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=SYSTEM_RULES,
        help=f"aktive Regeldatei (Standard: {SYSTEM_RULES})",
    )
    parser.add_argument(
        "--user-domains",
        type=Path,
        default=SYSTEM_USER_DOMAINS,
        help=f"append-only Benutzerregeln (Standard: {SYSTEM_USER_DOMAINS})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Regeldatei vollständig prüfen")
    validate.add_argument("file", nargs="?", type=Path)
    subparsers.add_parser("show", help="vollständige aktive Regeln ausgeben")
    subparsers.add_parser("list", help="konfigurierte Blocks zusammenfassen")

    show_block = subparsers.add_parser("show-block", help="einen Block vollständig ausgeben")
    show_block.add_argument("block_id")

    apply_parser = subparsers.add_parser("apply", help="geprüfte Regeldatei atomar übernehmen")
    apply_parser.add_argument("file", type=Path)
    apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Änderungen nur als Diff anzeigen",
    )

    subparsers.add_parser("history", help="gesicherte Regelversionen auflisten")

    rollback = subparsers.add_parser("rollback", help="frühere Regelversion wiederherstellen")
    rollback.add_argument("version")
    rollback_mode = rollback.add_mutually_exclusive_group()
    rollback_mode.add_argument("--yes", action="store_true", help="Rollback bestätigen")
    rollback_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Rollback nur als Diff anzeigen",
    )

    profile = subparsers.add_parser("set-profile", help="Profileinstellungen ändern")
    profile.add_argument("--timezone")
    profile.add_argument("--default-action", choices=("allow", "block"))

    subparsers.add_parser(
        "list-user-domains",
        help="append-only Domain-Ergänzungen mit UID anzeigen",
    )
    remove_user_domain = subparsers.add_parser(
        "remove-user-domain",
        help="Domain-Ergänzung als Administrator entfernen",
    )
    remove_user_domain.add_argument("uid", type=int)
    remove_user_domain.add_argument("block_id")
    remove_user_domain.add_argument("domain")
    remove_user_domain.add_argument("--yes", action="store_true")

    add_domain = subparsers.add_parser("add-domain", help="Domain zu einem Block hinzufügen")
    add_domain.add_argument("block_id")
    add_domain.add_argument("domain")

    remove_domain = subparsers.add_parser("remove-domain", help="Domain aus einem Block entfernen")
    remove_domain.add_argument("block_id")
    remove_domain.add_argument("domain")

    create_block = subparsers.add_parser("create-block", help="neuen Domain-Block anlegen")
    create_block.add_argument("block_id")
    create_block.add_argument("name")
    create_block.add_argument("--action", choices=("allow", "block"), default="block")
    create_block.add_argument("--priority", type=int, default=0)
    create_block.add_argument(
        "--domain",
        action="append",
        required=True,
        dest="domains",
        help="Zieldomain; für mehrere Domains wiederholen",
    )

    set_block = subparsers.add_parser("set-block", help="Block-Einstellungen ändern")
    set_block.add_argument("block_id")
    set_block.add_argument("--name")
    set_block.add_argument("--action", choices=("allow", "block"))
    set_block.add_argument("--priority", type=int)
    enabled = set_block.add_mutually_exclusive_group()
    enabled.add_argument("--enable", action="store_const", const=True, dest="enabled")
    enabled.add_argument("--disable", action="store_const", const=False, dest="enabled")
    set_block.set_defaults(enabled=None)

    delete_block = subparsers.add_parser("delete-block", help="Block löschen")
    delete_block.add_argument("block_id")
    delete_block.add_argument("--yes", action="store_true", help="Löschung bestätigen")

    for command, help_text in (
        ("add-url-pattern", "URL-Pattern zu einem Block hinzufügen"),
        ("remove-url-pattern", "URL-Pattern aus einem Block entfernen"),
    ):
        matcher = subparsers.add_parser(command, help=help_text)
        matcher.add_argument("block_id")
        matcher.add_argument("pattern")

    for command, help_text in (
        ("add-url-regex", "URL-Regex zu einem Block hinzufügen"),
        ("remove-url-regex", "URL-Regex aus einem Block entfernen"),
    ):
        regex = subparsers.add_parser(command, help=help_text)
        regex.add_argument("block_id")
        regex.add_argument("pattern")
        regex.add_argument("--case-sensitive", action="store_true")

    for command, help_text in (
        ("add-exception-domain", "Domain-Ausnahme zu einem Block hinzufügen"),
        ("remove-exception-domain", "Domain-Ausnahme aus einem Block entfernen"),
    ):
        exception = subparsers.add_parser(command, help=help_text)
        exception.add_argument("block_id")
        exception.add_argument("domain")

    add_window = subparsers.add_parser("add-window", help="wöchentliches Zeitfenster hinzufügen")
    add_window.add_argument("block_id")
    add_window.add_argument("--timezone", required=True)
    add_window.add_argument("--start", required=True)
    add_window.add_argument("--end", required=True)
    add_window.add_argument("--days", required=True, help="z. B. MO,TU,WE,TH,FR")

    remove_window = subparsers.add_parser("remove-window", help="Zeitfenster nach Index entfernen")
    remove_window.add_argument("block_id")
    remove_window.add_argument("index", type=int, help="1-basierter Index aus list-windows")

    list_windows = subparsers.add_parser("list-windows", help="Zeitfenster mit ihren Indizes anzeigen")
    list_windows.add_argument("block_id")

    schedule_timezone = subparsers.add_parser(
        "set-schedule-timezone",
        help="Zeitzone eines vorhandenen Zeitplans ändern",
    )
    schedule_timezone.add_argument("block_id")
    schedule_timezone.add_argument("timezone")

    clear_schedule = subparsers.add_parser("clear-schedule", help="gesamten Zeitplan entfernen")
    clear_schedule.add_argument("block_id")
    clear_schedule.add_argument("--yes", action="store_true", help="Entfernen bestätigen")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "validate":
            command_validate(args.file or args.rules)
        elif args.command == "show":
            command_show(args.rules)
        elif args.command == "show-block":
            command_show_block(args.rules, args.block_id)
        elif args.command == "list":
            command_list(args.rules)
        elif args.command == "apply":
            command_apply(args.rules, args.file, args.dry_run)
        elif args.command == "history":
            command_history(args.rules)
        elif args.command == "rollback":
            command_rollback(
                args.rules,
                args.version,
                confirmed=args.yes,
                dry_run=args.dry_run,
            )
        elif args.command == "set-profile":
            command_set_profile(
                args.rules,
                timezone=args.timezone,
                default_action=args.default_action,
            )
        elif args.command == "list-user-domains":
            command_list_user_domains(args.user_domains)
        elif args.command == "remove-user-domain":
            command_remove_user_domain(
                args.user_domains,
                args.uid,
                args.block_id,
                args.domain,
                args.yes,
            )
        elif args.command == "add-domain":
            command_add_domain(args.rules, args.block_id, args.domain)
        elif args.command == "remove-domain":
            command_remove_domain(args.rules, args.block_id, args.domain)
        elif args.command == "create-block":
            command_create_block(
                args.rules,
                args.block_id,
                args.name,
                args.action,
                args.priority,
                args.domains,
            )
        elif args.command == "set-block":
            command_set_block(
                args.rules,
                args.block_id,
                name=args.name,
                action=args.action,
                priority=args.priority,
                enabled=args.enabled,
            )
        elif args.command == "delete-block":
            command_delete_block(args.rules, args.block_id, args.yes)
        elif args.command in ("add-url-pattern", "remove-url-pattern"):
            command_update_string_matcher(
                args.rules,
                args.block_id,
                "targets",
                "url_patterns",
                args.pattern,
                add=args.command == "add-url-pattern",
            )
        elif args.command in ("add-url-regex", "remove-url-regex"):
            command_update_url_regex(
                args.rules,
                args.block_id,
                args.pattern,
                args.case_sensitive,
                add=args.command == "add-url-regex",
            )
        elif args.command in ("add-exception-domain", "remove-exception-domain"):
            command_update_string_matcher(
                args.rules,
                args.block_id,
                "exceptions",
                "domains",
                args.domain,
                add=args.command == "add-exception-domain",
            )
        elif args.command == "add-window":
            command_add_window(
                args.rules,
                args.block_id,
                args.timezone,
                args.start,
                args.end,
                args.days,
            )
        elif args.command == "remove-window":
            command_remove_window(args.rules, args.block_id, args.index)
        elif args.command == "list-windows":
            command_list_windows(args.rules, args.block_id)
        elif args.command == "set-schedule-timezone":
            command_set_schedule_timezone(args.rules, args.block_id, args.timezone)
        elif args.command == "clear-schedule":
            command_clear_schedule(args.rules, args.block_id, args.yes)
    except CommandError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
