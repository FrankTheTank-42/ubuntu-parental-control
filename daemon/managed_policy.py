#!/usr/bin/python3
"""Publish one validated rule snapshot to Firefox and Chrome managed storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


FIREFOX_EXTENSION_ID = "webfilter@ubuntu-parental-control.local"
CHROME_ID_RE = re.compile(r"^[a-p]{32}$")
MAX_SNAPSHOT_BYTES = 1_000_000


class PolicyPublicationError(RuntimeError):
    """The validated rules could not safely be published to a browser."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def make_managed_data(rules: dict[str, Any]) -> dict[str, object]:
    dynamic_rule_count = 0
    for block in rules.get("blocks", []):
        exceptions = block.get("exceptions", {})
        if exceptions.get("url_patterns") or exceptions.get("url_regex"):
            raise PolicyPublicationError(
                f"Block {block.get('id', '?')}: URL-Pattern-/Regex-Ausnahmen "
                "sind mit DNR nicht verlustfrei darstellbar"
            )
        targets = block.get("targets", {})
        dynamic_rule_count += sum(
            len(targets.get(field, []))
            for field in ("domains", "url_patterns", "url_regex")
        )
    if dynamic_rule_count > 5000:
        raise PolicyPublicationError(
            f"Regeln benötigen bis zu {dynamic_rule_count} dynamische DNR-Regeln (Maximum 5000)"
        )
    normalized = dict(rules)
    normalized.pop("$schema", None)
    rules_json = _canonical_json(normalized)
    encoded = rules_json.encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise PolicyPublicationError(
            f"kompilierter Regelsnapshot ist mit {len(encoded)} Bytes zu groß "
            f"(Maximum {MAX_SNAPSHOT_BYTES})"
        )
    revision = hashlib.sha256(encoded).hexdigest()
    snapshot = {
        "protocol_version": 1,
        "revision": revision,
        "rules": normalized,
    }
    return {
        "protocol_version": 1,
        "revision": revision,
        "snapshot_json": _canonical_json(snapshot),
    }


def _read_object(path: Path, *, missing_ok: bool) -> dict[str, Any]:
    if missing_ok and not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyPublicationError(f"Policy {path} kann nicht gelesen werden: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyPublicationError(f"Policy {path} muss ein JSON-Objekt sein")
    return value


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def publish_firefox(path: Path, managed_data: dict[str, object]) -> None:
    document = _read_object(path, missing_ok=False)
    policies = document.setdefault("policies", {})
    if not isinstance(policies, dict):
        raise PolicyPublicationError("Firefox-Policy 'policies' muss ein Objekt sein")
    third_party = policies.setdefault("3rdparty", {})
    if not isinstance(third_party, dict):
        raise PolicyPublicationError("Firefox-Policy '3rdparty' muss ein Objekt sein")
    extensions = third_party.setdefault("Extensions", {})
    if not isinstance(extensions, dict):
        raise PolicyPublicationError("Firefox-Policy '3rdparty.Extensions' muss ein Objekt sein")
    extensions[FIREFOX_EXTENSION_ID] = managed_data
    _atomic_write(path, document)


def chrome_policy_document(
    managed_data: dict[str, object], extension_id: str, update_url: str
) -> dict[str, object]:
    if not CHROME_ID_RE.fullmatch(extension_id):
        raise PolicyPublicationError("Chrome-Extension-ID muss aus 32 Zeichen a-p bestehen")
    if not update_url.startswith("https://"):
        raise PolicyPublicationError("Chrome-Update-URL muss HTTPS verwenden")
    return {
        "BrowserGuestModeEnabled": False,
        "DeveloperToolsAvailability": 2,
        "ExtensionSettings": {
            extension_id: {
                "installation_mode": "force_installed",
                "update_url": update_url,
            }
        },
        "IncognitoModeAvailability": 1,
        "3rdparty": {
            "extensions": {
                extension_id: managed_data,
            }
        },
    }


def publish_chrome(
    path: Path, managed_data: dict[str, object], extension_id: str, update_url: str
) -> None:
    _atomic_write(path, chrome_policy_document(managed_data, extension_id, update_url))


class ManagedPolicyPublisher:
    def __init__(
        self,
        config: dict[str, object],
        firefox_policy: Path,
        chrome_policy: Path,
    ) -> None:
        self.config = config
        self.firefox_policy = firefox_policy
        self.chrome_policy = chrome_policy

    def __call__(self, rules: dict[str, Any]) -> None:
        managed_data = make_managed_data(rules)
        browsers = self.config["managed_browsers"]
        if "chrome" in browsers:
            publish_chrome(
                self.chrome_policy,
                managed_data,
                str(self.config["chrome_extension_id"]),
                str(self.config["chrome_update_url"]),
            )
        if "firefox" in browsers:
            # Firefox is written last: this is the already mandatory browser and
            # its policy file also contains unrelated administrator settings.
            publish_firefox(self.firefox_policy, managed_data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validated rules as managed browser policy")
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--firefox-policy", type=Path, required=True)
    parser.add_argument("--chrome-policy", type=Path, required=True)
    args = parser.parse_args()

    # Imports stay local so an installed copy can run beside daemon.py.
    from daemon import load_config, load_valid_rules

    try:
        config = load_config(args.config)
        rules = load_valid_rules(args.rules)
        ManagedPolicyPublisher(config, args.firefox_policy, args.chrome_policy)(rules)
    except (OSError, ValueError, PolicyPublicationError) as exc:
        print(f"Fehler: Managed Policy konnte nicht veröffentlicht werden: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
