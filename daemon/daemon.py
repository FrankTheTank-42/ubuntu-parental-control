#!/usr/bin/python3
"""System service for validated Ubuntu Parental Control web rules."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable

from control_server import ControlServer
from managed_policy import ManagedPolicyPublisher, PolicyPublicationError
from rule_validator import DuplicateKeyError, RuleValidator, ValidationIssue, load_rules
from user_rules import EffectiveRulePublisher, LiveSnapshotSigner, UserDomainStore, UserRuleError


LOGGER = logging.getLogger("ubuntu-parental-control")
STOP = False


def stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def load_config(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Konfiguration muss ein Objekt sein")
    if data.get("schema_version") != 1:
        raise ValueError("nicht unterstützte schema_version")
    if not isinstance(data.get("enabled"), bool):
        raise ValueError("enabled muss true oder false sein")
    browsers = data.get("managed_browsers")
    if not isinstance(browsers, list) or not browsers:
        raise ValueError("managed_browsers muss eine nicht leere Liste sein")
    if len(browsers) != len(set(browsers)) or any(
        browser not in ("firefox", "chrome") for browser in browsers
    ):
        raise ValueError("managed_browsers darf nur firefox und chrome eindeutig enthalten")
    if "chrome" in browsers:
        extension_id = data.get("chrome_extension_id")
        update_url = data.get("chrome_update_url")
        if not isinstance(extension_id, str) or len(extension_id) != 32 or any(
            character not in "abcdefghijklmnop" for character in extension_id
        ):
            raise ValueError("chrome_extension_id muss aus 32 Zeichen a-p bestehen")
        if not isinstance(update_url, str) or not update_url.startswith("https://"):
            raise ValueError("chrome_update_url muss eine HTTPS-URL sein")
    restricted_users = data.get("restricted_users")
    if (
        not isinstance(restricted_users, list)
        or len(restricted_users) != len(set(restricted_users))
        or any(
            not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0 or uid > 2**32 - 1
            for uid in restricted_users
        )
    ):
        raise ValueError("restricted_users muss eindeutige positive Linux-UIDs enthalten")
    public_key = data.get("live_public_key_spki")
    if public_key is not None:
        try:
            decoded_key = base64.b64decode(public_key, validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("live_public_key_spki muss gültiges Base64 sein") from exc
        if not 64 <= len(decoded_key) <= 256:
            raise ValueError("live_public_key_spki hat eine ungültige Länge")
    return data


class InvalidRulesError(ValueError):
    def __init__(self, path: Path, issues: list[ValidationIssue]) -> None:
        self.path = path
        self.issues = issues
        super().__init__(f"{path}: {len(issues)} Validierungsfehler")


def load_valid_rules(path: Path) -> dict[str, Any]:
    rules = load_rules(path)
    issues = RuleValidator().validate(rules)
    if issues:
        raise InvalidRulesError(path, issues)
    return rules


class RuleStore:
    """Keeps active rules valid and persists a last-known-good snapshot."""

    def __init__(
        self,
        source: Path,
        last_good: Path,
        publisher: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.source = source
        self.last_good = last_good
        self.active: dict[str, Any] | None = None
        self.publisher = publisher
        self._source_signature: tuple[int, int, int] | None = None

    def source_signature(self) -> tuple[int, int, int] | None:
        try:
            stat = self.source.stat()
        except OSError:
            return None
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def start(self) -> dict[str, Any]:
        self._source_signature = self.source_signature()
        try:
            rules = load_valid_rules(self.source)
        except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError, ValueError) as source_error:
            self._log_rejection(self.source, source_error)
            try:
                rules = load_valid_rules(self.last_good)
            except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError, ValueError) as backup_error:
                raise ValueError(
                    "weder Regeldatei noch letzte gültige Version verwendbar: "
                    f"Quelle={source_error}; Sicherung={backup_error}"
                ) from backup_error
            self._activate(rules)
            LOGGER.warning("Letzte gültige Regeln aus %s geladen", self.last_good)
            return rules
        self._activate(rules)
        return rules

    def reload_if_changed(self) -> bool:
        signature = self.source_signature()
        if signature == self._source_signature:
            return False
        try:
            rules = load_valid_rules(self.source)
            self._activate(rules)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            DuplicateKeyError,
            ValueError,
            PolicyPublicationError,
            UserRuleError,
        ) as exc:
            # Invalid source content should not be parsed every second. A
            # publication failure, however, can be transient and is retried.
            if not isinstance(exc, PolicyPublicationError):
                self._source_signature = signature
            self._log_rejection(self.source, exc)
            LOGGER.warning("Bisherige aktive Regeln bleiben unverändert")
            return False
        self._source_signature = signature
        return True

    def _activate(self, rules: dict[str, Any]) -> None:
        if self.publisher is not None:
            self.publisher(rules)
        self._write_last_good(rules)
        self.active = rules
        LOGGER.info("Regeln aktiviert: %d Blocks", len(rules["blocks"]))

    def _write_last_good(self, rules: dict[str, Any]) -> None:
        self.last_good.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.last_good.with_name(f".{self.last_good.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(rules, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.last_good)
            directory_fd = os.open(self.last_good.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _log_rejection(path: Path, error: Exception) -> None:
        LOGGER.error("Regeln aus %s abgelehnt: %s", path, error)
        if isinstance(error, InvalidRulesError):
            for issue in error.issues:
                LOGGER.error("Regelfehler %s", issue)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--last-good", type=Path)
    parser.add_argument("--user-domains", type=Path)
    parser.add_argument("--live-snapshot", type=Path)
    parser.add_argument("--control-socket", type=Path)
    parser.add_argument("--live-signing-key", type=Path)
    parser.add_argument(
        "--firefox-policy",
        type=Path,
        default=Path("/etc/firefox/policies/policies.json"),
    )
    parser.add_argument(
        "--chrome-policy",
        type=Path,
        default=Path("/etc/opt/chrome/policies/managed/ubuntu-parental-control.json"),
    )
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.poll_interval <= 0:
        LOGGER.error("poll-interval muss größer als 0 sein")
        return 1
    try:
        config = load_config(args.config)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, DuplicateKeyError) as exc:
        LOGGER.error("Konfiguration ungültig: %s", exc)
        return 1

    if args.check:
        try:
            rules = load_valid_rules(args.rules)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError, DuplicateKeyError) as exc:
            LOGGER.error("Regeln ungültig: %s", exc)
            if isinstance(exc, InvalidRulesError):
                for issue in exc.issues:
                    LOGGER.error("Regelfehler %s", issue)
            return 1
        LOGGER.info("Konfiguration und Regeln sind gültig (%d Blocks)", len(rules["blocks"]))
        return 0

    if args.last_good is None:
        LOGGER.error("--last-good ist für den Dienstbetrieb erforderlich")
        return 1
    optional_service_paths = (
        args.user_domains,
        args.live_snapshot,
        args.control_socket,
        args.live_signing_key,
    )
    if any(optional_service_paths) and not all(optional_service_paths):
        LOGGER.error(
            "--user-domains, --live-snapshot, --control-socket und --live-signing-key "
            "müssen gemeinsam gesetzt werden"
        )
        return 1
    if all(optional_service_paths) and config.get("live_public_key_spki") is None:
        LOGGER.error("live_public_key_spki fehlt für den Native-Live-Dienst")
        return 1
    policy_publisher = ManagedPolicyPublisher(config, args.firefox_policy, args.chrome_policy)
    effective_publisher: EffectiveRulePublisher | None = None
    publisher: Callable[[dict[str, Any]], None] = policy_publisher
    if all(optional_service_paths):
        effective_publisher = EffectiveRulePublisher(
            config,
            UserDomainStore(args.user_domains),
            policy_publisher,
            args.live_snapshot,
            LiveSnapshotSigner(args.live_signing_key),
        )
        publisher = effective_publisher
    store = RuleStore(args.rules, args.last_good, publisher)
    try:
        store.start()
    except (ValueError, OSError, PolicyPublicationError, UserRuleError) as exc:
        LOGGER.error("Dienst kann nicht sicher starten: %s", exc)
        return 1

    control_server: ControlServer | None = None
    if effective_publisher is not None:
        control_server = ControlServer(args.control_socket, effective_publisher)
        try:
            control_server.start()
        except (OSError, RuntimeError) as exc:
            LOGGER.error("Lokale Verwaltungsschnittstelle kann nicht starten: %s", exc)
            return 1

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOGGER.info("Dienst gestartet (enabled=%s)", config["enabled"])
    try:
        while not STOP:
            time.sleep(args.poll_interval)
            store.reload_if_changed()
            if effective_publisher is not None:
                try:
                    effective_publisher.reload_user_rules_if_changed()
                except (OSError, ValueError, PolicyPublicationError, UserRuleError) as exc:
                    LOGGER.error("Geänderte Benutzerregeln abgelehnt: %s", exc)
    finally:
        if control_server is not None:
            control_server.close()
    LOGGER.info("Dienst beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
