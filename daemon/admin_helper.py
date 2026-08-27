#!/usr/bin/python3
"""Polkit-authorized helper for applying complete administrator rule edits."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from managed_policy import PolicyPublicationError, make_managed_data
from rule_validator import RuleValidator
from upcctl import CommandError, SYSTEM_RULES, SYSTEM_USER_DOMAINS, write_rules_atomic
from user_rules import UserDomainStore, UserRuleError, object_revision


MAX_REQUEST_BYTES = 1_000_000


def respond(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def apply_request(
    request: object,
    target: Path = SYSTEM_RULES,
    user_domains: Path = SYSTEM_USER_DOMAINS,
) -> dict[str, str]:
    if not isinstance(request, dict) or not isinstance(request.get("command"), str):
        raise CommandError("Unbekannte oder unerwartete Administrator-Anfrage")
    if request["command"] == "apply_rules":
        if set(request) != {"command", "rules"}:
            raise CommandError("Unerwartete Felder in Administrator-Anfrage")
        rules = request.get("rules")
        issues = RuleValidator().validate(rules)
        if issues:
            raise CommandError(f"Regeln sind ungültig: {issues[0]}")
        try:
            store = UserDomainStore(user_domains)
            effective_rules = store.merge(rules, store.load())
            make_managed_data(effective_rules)
        except (PolicyPublicationError, UserRuleError) as exc:
            raise CommandError(f"Regeln können nicht im Browser veröffentlicht werden: {exc}") from exc
        write_rules_atomic(target, rules)
        return {"base_revision": object_revision(rules)}
    if request["command"] == "remove_user_domain":
        if set(request) != {"command", "uid", "block_id", "domain"}:
            raise CommandError("Unerwartete Felder in Administrator-Anfrage")
        uid = request["uid"]
        if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
            raise CommandError("UID ist ungültig")
        if not isinstance(request["block_id"], str) or not isinstance(request["domain"], str):
            raise CommandError("Block-ID und Domain müssen Text sein")
        try:
            store = UserDomainStore(user_domains)
            store.remove(uid, request["block_id"], request["domain"])
        except UserRuleError as exc:
            raise CommandError(str(exc)) from exc
        return {"user_revision": object_revision(store.load())}
    raise CommandError("Unbekannte Administrator-Anfrage")


def main() -> int:
    if os.geteuid() != 0:
        respond({"ok": False, "error": "Administrator-Helfer muss als root laufen"})
        return 1
    raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        respond({"ok": False, "error": "Administrator-Anfrage ist zu groß"})
        return 1
    try:
        result = apply_request(json.loads(raw.decode("utf-8")))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        CommandError,
        UserRuleError,
        ValueError,
    ) as exc:
        respond({"ok": False, "error": str(exc)})
        return 1
    respond({"ok": True, "result": {"applied": True, **result}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
