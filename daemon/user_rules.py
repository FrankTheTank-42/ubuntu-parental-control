#!/usr/bin/python3
"""Root-owned append-only domain additions from restricted user accounts."""

from __future__ import annotations

import copy
import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from managed_policy import ManagedPolicyPublisher, _atomic_write, capture_file, restore_file
from rule_validator import RuleValidator


STATE_VERSION = 1
MAX_DOMAINS_PER_USER = 2000
MAX_DOMAINS_TOTAL = 10000
BLOCK_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class UserRuleError(RuntimeError):
    pass


class SnapshotGenerationStore:
    """Persist a strictly increasing generation before publishing a snapshot."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def next(self) -> int:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise UserRuleError("Snapshot-Generationssperre ist nicht ausreichend geschützt")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = 0
            if self.path.exists():
                if self.path.is_symlink() or not self.path.is_file():
                    raise UserRuleError("Snapshot-Generation ist keine reguläre Datei")
                mode = stat.S_IMODE(self.path.stat().st_mode)
                if mode & 0o077:
                    raise UserRuleError("Snapshot-Generation ist nicht ausreichend geschützt")
                try:
                    current = int(self.path.read_text(encoding="ascii").strip())
                except (OSError, UnicodeError, ValueError) as exc:
                    raise UserRuleError("Snapshot-Generation ist ungültig") from exc
                if current < 0:
                    raise UserRuleError("Snapshot-Generation ist ungültig")
            following = current + 1
            temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            write_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                write_flags |= os.O_NOFOLLOW
            try:
                output = os.open(temporary, write_flags, 0o600)
                with os.fdopen(output, "w", encoding="ascii", newline="\n") as handle:
                    handle.write(f"{following}\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
            return following
        finally:
            os.close(descriptor)


def object_revision(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _der_length(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise UserRuleError("ECDSA-Signatur ist abgeschnitten")
    first = data[offset]
    if first < 0x80:
        return first, offset + 1
    count = first & 0x7F
    if count == 0 or count > 2 or offset + 1 + count > len(data):
        raise UserRuleError("ECDSA-Signaturlänge ist ungültig")
    return int.from_bytes(data[offset + 1 : offset + 1 + count], "big"), offset + 1 + count


def ecdsa_der_to_raw(signature: bytes) -> bytes:
    if not signature or signature[0] != 0x30:
        raise UserRuleError("ECDSA-Signatur ist keine DER-Sequenz")
    sequence_length, offset = _der_length(signature, 1)
    if offset + sequence_length != len(signature):
        raise UserRuleError("ECDSA-Sequenzlänge stimmt nicht")
    values: list[bytes] = []
    for _index in range(2):
        if offset >= len(signature) or signature[offset] != 0x02:
            raise UserRuleError("ECDSA-Signatur enthält keine Ganzzahl")
        integer_length, value_offset = _der_length(signature, offset + 1)
        value = signature[value_offset : value_offset + integer_length]
        if len(value) != integer_length:
            raise UserRuleError("ECDSA-Ganzzahl ist abgeschnitten")
        value = value.lstrip(b"\0")
        if len(value) > 32:
            raise UserRuleError("ECDSA-Ganzzahl ist zu groß")
        values.append(value.rjust(32, b"\0"))
        offset = value_offset + integer_length
    if offset != len(signature):
        raise UserRuleError("ECDSA-Signatur enthält unerwartete Daten")
    return b"".join(values)


class LiveSnapshotSigner:
    def __init__(self, private_key: Path) -> None:
        self.private_key = private_key

    def sign_text(self, text: str) -> str:
        if self.private_key.is_symlink() or not self.private_key.is_file():
            raise UserRuleError(f"Live-Signaturschlüssel fehlt oder ist unsicher: {self.private_key}")
        mode = stat.S_IMODE(self.private_key.stat().st_mode)
        if mode & 0o077:
            raise UserRuleError(
                f"Live-Signaturschlüssel ist nicht ausreichend geschützt ({mode:04o})"
            )
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/openssl",
                    "dgst",
                    "-sha256",
                    "-sign",
                    str(self.private_key),
                ],
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UserRuleError(f"Live-Snapshot konnte nicht signiert werden: {exc}") from exc
        return base64.b64encode(
            ecdsa_der_to_raw(completed.stdout)
        ).decode("ascii")

    def sign(self, managed: dict[str, object]) -> dict[str, object]:
        signed = dict(managed)
        signed["live_signature"] = self.sign_text(str(managed["snapshot_json"]))
        return signed


def empty_user_rules() -> dict[str, Any]:
    return {"format_version": STATE_VERSION, "users": {}}


def validate_domain(domain: str) -> None:
    validator = RuleValidator()
    validator.validate_domain(domain, "domain")
    if validator.issues:
        raise UserRuleError(str(validator.issues[0]))


class UserDomainStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def signature(self) -> tuple[int, int, int] | None:
        try:
            info = self.path.stat()
        except OSError:
            return None
        return (info.st_ino, info.st_size, info.st_mtime_ns)

    @contextmanager
    def mutation_lock(self):
        """Serialize read-modify-write operations across daemon and Polkit helper."""
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        if lock_path.is_symlink():
            raise UserRuleError(f"Benutzerregel-Sperrdatei darf kein symbolischer Link sein: {lock_path}")
        lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise UserRuleError(f"Benutzerregeln können nicht gesperrt werden: {exc}") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise UserRuleError("Benutzerregel-Sperrdatei ist nicht ausreichend geschützt")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def load(self) -> dict[str, Any]:
        try:
            if not self.path.exists():
                return empty_user_rules()
            if self.path.is_symlink() or not self.path.is_file():
                raise UserRuleError(f"Benutzerregeln sind keine reguläre Datei: {self.path}")
            mode = stat.S_IMODE(self.path.stat().st_mode)
        except OSError as exc:
            raise UserRuleError(f"Benutzerregeln können nicht geprüft werden: {exc}") from exc
        if mode & 0o077:
            raise UserRuleError(
                f"Benutzerregeln sind nicht ausreichend geschützt ({mode:04o}): {self.path}"
            )
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise UserRuleError(f"Benutzerregeln können nicht gelesen werden: {exc}") from exc
        self.validate(value)
        return value

    @staticmethod
    def validate(value: object) -> None:
        if not isinstance(value, dict) or set(value) != {"format_version", "users"}:
            raise UserRuleError("Benutzerregeln müssen format_version und users enthalten")
        if value["format_version"] != STATE_VERSION or not isinstance(value["users"], dict):
            raise UserRuleError("Benutzerregel-Format ist ungültig")
        total = 0
        for uid, blocks in value["users"].items():
            if not isinstance(uid, str) or not uid.isdecimal() or int(uid) <= 0:
                raise UserRuleError(f"Ungültige Benutzer-ID in Benutzerregeln: {uid!r}")
            if not isinstance(blocks, dict):
                raise UserRuleError(f"Benutzerregeln für UID {uid} müssen ein Objekt sein")
            user_total = 0
            for block_id, domains in blocks.items():
                if not isinstance(block_id, str) or not BLOCK_ID_RE.fullmatch(block_id):
                    raise UserRuleError(f"Ungültige Block-ID in Benutzerregeln: {block_id!r}")
                if not isinstance(domains, list) or len(domains) != len(set(domains)):
                    raise UserRuleError(f"Domains für Block {block_id!r} sind ungültig oder doppelt")
                for domain in domains:
                    if not isinstance(domain, str):
                        raise UserRuleError(f"Domain für Block {block_id!r} muss Text sein")
                    validate_domain(domain)
                user_total += len(domains)
            if user_total > MAX_DOMAINS_PER_USER:
                raise UserRuleError(
                    f"UID {uid} überschreitet das Limit von {MAX_DOMAINS_PER_USER} Domains"
                )
            total += user_total
        if total > MAX_DOMAINS_TOTAL:
            raise UserRuleError(f"Benutzerregeln überschreiten das Limit von {MAX_DOMAINS_TOTAL} Domains")

    def write(self, value: dict[str, Any]) -> None:
        self.validate(value)
        if self.path.is_symlink():
            raise UserRuleError(f"Benutzerregeldatei darf kein symbolischer Link sein: {self.path}")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def remove(self, uid: int, block_id: str, domain: str) -> None:
        with self.mutation_lock():
            state = self.load()
            blocks = state["users"].get(str(uid))
            domains = blocks.get(block_id) if blocks else None
            if domains is None or domain not in domains:
                raise UserRuleError("Benutzer-Domain wurde nicht gefunden")
            domains.remove(domain)
            if not domains:
                blocks.pop(block_id)
            if not blocks:
                state["users"].pop(str(uid))
            self.write(state)

    @staticmethod
    def merge(base_rules: dict[str, Any], user_rules: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(base_rules)
        blocks = {block["id"]: block for block in merged["blocks"]}
        for user_blocks in user_rules["users"].values():
            for block_id, domains in user_blocks.items():
                block = blocks.get(block_id)
                # Stale additions stay recorded but dormant. They must never be
                # merged into an allow block after an administrator changes it.
                if block is None or block["action"] != "block":
                    continue
                targets = block["targets"]["domains"]
                targets.extend(domain for domain in domains if domain not in targets)
                targets.sort()
        return merged


class EffectiveRulePublisher:
    """Merge user additions, publish browser policies, and expose a live snapshot."""

    def __init__(
        self,
        config: dict[str, object],
        store: UserDomainStore,
        policy_publisher: ManagedPolicyPublisher,
        live_snapshot: Path,
        signer: LiveSnapshotSigner,
        generation_store: SnapshotGenerationStore | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.policy_publisher = policy_publisher
        self.live_snapshot = live_snapshot
        self.signer = signer
        self.generation_store = generation_store or SnapshotGenerationStore(
            live_snapshot.with_name("snapshot-generation")
        )
        self.base_rules: dict[str, Any] | None = None
        self.managed_data: dict[str, object] | None = None
        self._user_signature: tuple[int, int, int] | None = None
        self._publication_serial = 0
        self._base_revision: str | None = None
        self._user_revision: str | None = None
        self._lock = threading.RLock()

    def __call__(self, base_rules: dict[str, Any]) -> None:
        with self._lock:
            user_rules = self.store.load()
            effective = self.store.merge(base_rules, user_rules)
            issues = RuleValidator().validate(effective)
            if issues:
                raise UserRuleError(f"Effektive Regeln sind ungültig: {issues[0]}")
            generation = self.generation_store.next()
            browsers = self.policy_publisher.config["managed_browsers"]
            policy_paths = []
            if "chrome" in browsers:
                policy_paths.append(self.policy_publisher.chrome_policy)
            if "firefox" in browsers:
                policy_paths.append(self.policy_publisher.firefox_policy)
            captured = {path: capture_file(path) for path in policy_paths}
            live_captured = capture_file(self.live_snapshot)
            try:
                managed = self.policy_publisher(effective, generation=generation)
                signed_managed = self.signer.sign(managed)
                _atomic_write(self.live_snapshot, signed_managed)
            except Exception as publication_error:
                rollback_errors = []
                for path in reversed(policy_paths):
                    try:
                        restore_file(path, captured[path])
                    except Exception as rollback_error:
                        rollback_errors.append(f"{path}: {rollback_error}")
                try:
                    restore_file(self.live_snapshot, live_captured)
                except Exception as rollback_error:
                    rollback_errors.append(f"{self.live_snapshot}: {rollback_error}")
                if rollback_errors:
                    raise UserRuleError(
                        f"Publikation fehlgeschlagen; Rollback unvollständig: {'; '.join(rollback_errors)}"
                    ) from publication_error
                raise
            self.base_rules = copy.deepcopy(base_rules)
            self.managed_data = signed_managed
            self._user_signature = self.store.signature()
            self._base_revision = object_revision(base_rules)
            self._user_revision = object_revision(user_rules)
            self._publication_serial += 1

    def publication_status(self) -> dict[str, object]:
        with self._lock:
            return {
                "serial": self._publication_serial,
                "base_revision": self._base_revision,
                "user_revision": self._user_revision,
            }

    def status(self, uid: int, nonce: object) -> dict[str, object]:
        with self._lock:
            if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce):
                raise UserRuleError("Status-Nonce ist ungültig")
            restricted = uid in self.config["restricted_users"]
            administrator = uid in self.config["administrator_users"]
            role = "restricted" if restricted else "administrator" if administrator else "unauthorized"
            allowed: list[str] = []
            if self.base_rules is not None and restricted:
                allowed = [
                    block["id"]
                    for block in self.base_rules["blocks"]
                    if block["action"] == "block"
                ]
            authorization = {
                "protocol_version": 2,
                "nonce": nonce,
                "uid": uid,
                "role": role,
                "can_add_domains_to": allowed,
            }
            authorization_json = json.dumps(
                authorization,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            return {
                "authorization_json": authorization_json,
                "authorization_signature": self.signer.sign_text(authorization_json),
            }

    def base_snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self.base_rules is None:
                raise UserRuleError("Aktive Basisregeln sind noch nicht verfügbar")
            return copy.deepcopy(self.base_rules)

    def user_domain_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.store.load())

    def own_user_domain_snapshot(self, uid: int) -> dict[str, Any]:
        with self._lock:
            state = self.store.load()
            own = state["users"].get(str(uid))
            return {
                "format_version": state["format_version"],
                "users": {str(uid): copy.deepcopy(own)} if own is not None else {},
            }

    def add_domain(self, uid: int, block_id: str, domain: str) -> dict[str, object]:
        with self._lock:
            if uid not in self.config["restricted_users"]:
                raise UserRuleError("Benutzerkonto ist nicht als eingeschränktes Konto registriert")
            if self.base_rules is None:
                raise UserRuleError("Aktive Basisregeln sind noch nicht verfügbar")
            if not isinstance(block_id, str) or not BLOCK_ID_RE.fullmatch(block_id):
                raise UserRuleError("Block-ID ist ungültig")
            if not isinstance(domain, str):
                raise UserRuleError("Domain muss Text sein")
            validate_domain(domain)
            block = next(
                (item for item in self.base_rules["blocks"] if item["id"] == block_id),
                None,
            )
            if block is None:
                raise UserRuleError("Block wurde nicht gefunden")
            if block["action"] != "block":
                raise UserRuleError("Domains können nur zu Blockierlisten ergänzt werden")
            current_effective = self.store.merge(self.base_rules, self.store.load())
            current_block = next(item for item in current_effective["blocks"] if item["id"] == block_id)
            if domain in current_block["targets"]["domains"]:
                raise UserRuleError("Domain ist bereits in diesem Block enthalten")

            with self.store.mutation_lock():
                previous = self.store.load()
                updated = copy.deepcopy(previous)
                user = updated["users"].setdefault(str(uid), {})
                domains = user.setdefault(block_id, [])
                domains.append(domain)
                domains.sort()
                self.store.write(updated)
                try:
                    self(self.base_rules)
                except Exception:
                    self.store.write(previous)
                    try:
                        self(self.base_rules)
                    except Exception:
                        pass
                    raise
            return {
                "block_id": block_id,
                "domain": domain,
                "managed": self.managed_data,
            }

    def reload_user_rules_if_changed(self) -> bool:
        signature = self.store.signature()
        if signature == self._user_signature or self.base_rules is None:
            return False
        try:
            self(self.base_rules)
        except Exception:
            self._user_signature = signature
            raise
        return True
