#!/usr/bin/python3
"""Manage the Firefox Snap portal consent for the local native host."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from urllib.parse import urlparse


GDBUS = "/usr/bin/gdbus"
DESTINATION = "org.freedesktop.impl.portal.PermissionStore"
OBJECT_PATH = "/org/freedesktop/impl/portal/PermissionStore"
INTERFACE = "org.freedesktop.impl.portal.PermissionStore"
TABLE = "webextensions"
HOST = "ubuntu_parental_control"
APP = "snap.firefox"
CONSENT_URI = "ubuntu-parental-control://firefox-consent/allow"


class ConsentError(RuntimeError):
    pass


def portal_call(method: str, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            [
                GDBUS,
                "call",
                "--session",
                "--dest",
                DESTINATION,
                "--object-path",
                OBJECT_PATH,
                "--method",
                f"{INTERFACE}.{method}",
                *arguments,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise ConsentError("gdbus ist nicht installiert") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConsentError("Das Firefox-Berechtigungsportal antwortet nicht") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "Unbekannter Portalfehler").strip()
        raise ConsentError(detail) from exc
    return completed.stdout.strip()


def grant() -> None:
    portal_call("SetPermission", TABLE, "true", HOST, APP, "['yes']")


def reset() -> None:
    portal_call("DeletePermission", TABLE, HOST, APP)


def status() -> str:
    try:
        result = portal_call("GetPermission", TABLE, HOST, APP)
    except ConsentError as exc:
        if "not found" in str(exc).lower() or "nicht gefunden" in str(exc).lower():
            return "nicht entschieden"
        raise
    permissions = re.findall(r"['\"]([^'\"]*)['\"]", result)
    if permissions == ["yes"]:
        return "erlaubt"
    if permissions == ["no"]:
        return "verweigert"
    # PermissionStore.GetPermission returns a string array. After
    # DeletePermission, current GLib versions may represent the missing app
    # decision as an empty typed array (`(@as [],)`) instead of raising a
    # not-found error. Both forms mean that Firefox should ask again.
    if not permissions and re.search(r"\[\s*\]", result):
        return "nicht entschieden"
    return f"unbekannt ({result})"


def validate_consent_uri(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "ubuntu-parental-control"
        or parsed.netloc != "firefox-consent"
        or parsed.path != "/allow"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConsentError("Unbekannte oder ungültige Reparatur-Anfrage")


def interactive() -> int:
    print("Ubuntu Parental Control – Firefox verbinden")
    print()
    print("Firefox darf dann ausschließlich mit dem lokal installierten")
    print("Ubuntu-Parental-Control-Dienst kommunizieren. Im Kinderkonto")
    print("können damit nur weitere Domains blockiert werden; Regeln lassen")
    print("sich weder löschen noch lockern.")
    print()
    try:
        answer = input("Diese lokale Verbindung jetzt erlauben? [j/N] ").strip().lower()
    except EOFError:
        return 2
    if answer not in {"j", "ja", "y", "yes"}:
        print("Keine Änderung vorgenommen.")
        return 1
    grant()
    print()
    print("Die Firefox-Einwilligung wurde erteilt.")
    print("Öffne jetzt die Regelverwaltung oder verwende das Kontextmenü erneut.")
    if sys.stdin.isatty():
        try:
            input("\nEingabetaste drücken, um dieses Fenster zu schließen …")
        except EOFError:
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Firefox-Snap-Einwilligung für Ubuntu Parental Control verwalten",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("status", "allow", "reset"),
        help="Status anzeigen, Zugriff erlauben oder die Entscheidung zurücksetzen",
    )
    parser.add_argument(
        "--from-uri",
        nargs="?",
        const=CONSENT_URI,
        metavar="URI",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("als betroffenes Benutzerkonto ausführen, nicht mit sudo")
    try:
        if args.from_uri is not None:
            if args.action is not None:
                raise ConsentError("URI-Aufruf darf keine zusätzliche Aktion enthalten")
            validate_consent_uri(args.from_uri)
            return interactive()
        if args.action is None:
            return interactive()
        if args.action == "status":
            print(f"Firefox-Einwilligung: {status()}")
        elif args.action == "allow":
            grant()
            print("Firefox-Einwilligung wurde erteilt.")
        else:
            reset()
            print("Firefox-Einwilligung wurde zurückgesetzt; Firefox fragt beim nächsten Bedarf erneut.")
    except ConsentError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
