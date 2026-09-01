#!/usr/bin/env python3
"""Local, dependency-free web tracker for the manual UPC test protocol."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


SCHEMA_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8780
MAX_BODY_SIZE = 64 * 1024
MAX_ODS_CONTENT_SIZE = 8 * 1024 * 1024
TEST_STATUSES = {
    "Offen",
    "In Arbeit",
    "Bestanden",
    "Fehlgeschlagen",
    "Nicht anwendbar",
}
ISSUE_STATUSES = {"Offen", "Behoben", "Zurückgestellt"}
ISSUE_SEVERITIES = {"Niedrig", "Mittel", "Hoch", "Kritisch"}

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
TABLE_NAME = f"{{{NS['table']}}}name"
ROW_REPEAT = f"{{{NS['table']}}}number-rows-repeated"
COLUMN_REPEAT = f"{{{NS['table']}}}number-columns-repeated"


class ProtocolError(ValueError):
    """Expected input or state error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cell_text(cell: ElementTree.Element) -> str:
    paragraphs = []
    for paragraph in cell.findall(".//text:p", NS):
        paragraphs.append("".join(paragraph.itertext()))
    return "\n".join(paragraphs).strip()


def _sheet_rows(sheet: ElementTree.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in sheet.findall("table:table-row", NS):
        repeat = int(row.get(ROW_REPEAT, "1"))
        if repeat < 1 or repeat > 1_048_576:
            raise ProtocolError("ODS enthält eine ungültige Zeilenwiederholung")
        values: list[str] = []
        for cell in row.findall("table:table-cell", NS):
            column_repeat = int(cell.get(COLUMN_REPEAT, "1"))
            if column_repeat < 1 or column_repeat > 16_384:
                raise ProtocolError("ODS enthält eine ungültige Spaltenwiederholung")
            value = _cell_text(cell)
            if value and column_repeat > 32:
                raise ProtocolError("ODS wiederholt einen Datenwert ungewöhnlich oft")
            if value or len(values) < 32:
                values.extend([value] * min(column_repeat, 32 - len(values)))
        while values and not values[-1]:
            values.pop()
        if values:
            if repeat > 5_000:
                raise ProtocolError("ODS wiederholt eine Datenzeile ungewöhnlich oft")
            rows.extend([values.copy() for _ in range(repeat)])
        if len(rows) > 5_000:
            raise ProtocolError("ODS enthält zu viele Datenzeilen")
    return rows


def _row_values(row: list[str], count: int) -> list[str]:
    return (row + [""] * count)[:count]


def _parse_environment(rows: list[list[str]]) -> dict[str, str]:
    labels = {
        "Datum",
        "Tester",
        "Rechner / VM",
        "Ubuntu-Version",
        "Firefox-Version",
        "Chrome-Version",
        "Elternkonto / UID",
        "Kinderkonto / UID",
        "Signiertes Firefox-XPI",
    }
    result = {}
    for row in rows:
        label, value = _row_values(row, 2)
        if label in labels:
            result[label] = value
    return result


def _parse_tests(rows: list[list[str]]) -> list[dict[str, str]]:
    tests = []
    for row in rows[1:]:
        test_id, area, subsection, account, expected, status, actual, note, priority = (
            _row_values(row, 9)
        )
        if not re.fullmatch(r"T\d+", test_id):
            continue
        if status not in TEST_STATUSES:
            status = "Offen"
        tests.append(
            {
                "id": test_id,
                "area": area,
                "subsection": subsection,
                "account": account,
                "expected": expected,
                "status": status,
                "actual": actual,
                "note": note,
                "priority": priority,
                "updated_at": "",
            }
        )
    if not tests:
        raise ProtocolError("ODS enthält keine erkennbaren Testfälle")
    return tests


def _parse_commands(rows: list[list[str]]) -> list[dict[str, str]]:
    commands = []
    for row in rows[1:]:
        command_id, area, subsection, kind, command, result = _row_values(row, 6)
        if not re.fullmatch(r"K\d+", command_id):
            continue
        commands.append(
            {
                "id": command_id,
                "area": area,
                "subsection": subsection,
                "kind": kind,
                "command": command,
                "result": result,
                "updated_at": "",
            }
        )
    return commands


def _parse_issues(rows: list[list[str]]) -> list[dict[str, str]]:
    issues = []
    for row in rows[1:]:
        issue_id, test_id, severity, title, reproduction, expected, actual, status, comment = (
            _row_values(row, 9)
        )
        if not re.fullmatch(r"F\d+", issue_id):
            continue
        if not any((test_id, title, reproduction, expected, actual)):
            continue
        if severity not in ISSUE_SEVERITIES:
            severity = "Mittel"
        if status not in ISSUE_STATUSES:
            status = "Offen"
        # The source sheet accidentally recorded sudo for F003. The observed
        # crash was produced by the unprivileged invocation.
        if issue_id == "F003" and reproduction.strip() == "sudo upcctl list-user-domains":
            reproduction = "upcctl list-user-domains"
        issues.append(
            {
                "id": issue_id,
                "test_id": test_id,
                "severity": severity,
                "title": title,
                "reproduction": reproduction,
                "expected": expected,
                "actual": actual,
                "status": status,
                "comment": comment,
                "updated_at": "",
            }
        )
    return issues


def normalize_issue_test_ids(state: dict[str, Any]) -> None:
    """Map legacy links such as T29 to the actual test ID T029."""
    test_ids = {
        item.get("id")
        for item in state.get("tests", [])
        if isinstance(item.get("id"), str)
    }
    by_number = {
        int(test_id[1:]): test_id
        for test_id in test_ids
        if re.fullmatch(r"T\d+", test_id)
    }
    for issue in state.get("issues", []):
        test_id = issue.get("test_id")
        if (
            isinstance(test_id, str)
            and test_id not in test_ids
            and re.fullmatch(r"T\d+", test_id)
        ):
            canonical = by_number.get(int(test_id[1:]))
            if canonical is not None:
                issue["test_id"] = canonical


def import_ods(path: Path) -> dict[str, Any]:
    try:
        with ZipFile(path) as archive:
            info = archive.getinfo("content.xml")
            if info.file_size > MAX_ODS_CONTENT_SIZE:
                raise ProtocolError("ODS-Inhalt ist ungewöhnlich groß")
            content = archive.read(info)
            if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
                raise ProtocolError("ODS enthält nicht erlaubte XML-Entitäten")
            root = ElementTree.fromstring(content)
    except (OSError, KeyError, BadZipFile, ElementTree.ParseError) as exc:
        raise ProtocolError(f"ODS kann nicht gelesen werden: {exc}") from exc

    sheets = {
        sheet.get(TABLE_NAME, ""): _sheet_rows(sheet)
        for sheet in root.findall(".//table:table", NS)
    }
    required = {"Übersicht", "Testfälle", "Kommandos", "Fehlerprotokoll"}
    missing = sorted(required - sheets.keys())
    if missing:
        raise ProtocolError(f"ODS-Blätter fehlen: {', '.join(missing)}")

    imported_at = utc_now()
    state = {
        "schema_version": SCHEMA_VERSION,
        "revision": 1,
        "source": {
            "filename": path.name,
            "sha256": sha256_file(path),
            "imported_at": imported_at,
        },
        "environment": _parse_environment(sheets["Übersicht"]),
        "tests": _parse_tests(sheets["Testfälle"]),
        "commands": _parse_commands(sheets["Kommandos"]),
        "issues": _parse_issues(sheets["Fehlerprotokoll"]),
        "updated_at": imported_at,
    }
    normalize_issue_test_ids(state)
    validate_state(state)
    return state


def validate_state(state: dict[str, Any]) -> None:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("unbekannte Zustandsversion")
    for key in ("environment", "tests", "commands", "issues"):
        if key not in state:
            raise ProtocolError(f"Zustandsfeld fehlt: {key}")
    test_ids = [item.get("id") for item in state["tests"]]
    if len(test_ids) != len(set(test_ids)):
        raise ProtocolError("doppelte Testfall-ID")
    for item in state["tests"]:
        if item.get("status") not in TEST_STATUSES:
            raise ProtocolError(f"ungültiger Teststatus für {item.get('id')}")
    for item in state["issues"]:
        test_id = item.get("test_id")
        if test_id and test_id not in test_ids:
            raise ProtocolError(
                f"verknüpfter Testfall für {item.get('id')} wurde nicht gefunden"
            )


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolError(f"Testzustand kann nicht gelesen werden: {exc}") from exc
        # Version-1 test states created before the resolution comment was
        # introduced do not contain this additive field yet.
        for issue in value.get("issues", []):
            issue.setdefault("comment", "")
        normalize_issue_test_ids(value)
        validate_state(value)
        return value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state))

    def update_environment(self, values: dict[str, Any]) -> dict[str, Any]:
        allowed = set(self._state["environment"])
        if not values or not set(values).issubset(allowed):
            raise ProtocolError("ungültiges Umgebungsfeld")
        for value in values.values():
            if not isinstance(value, str) or len(value) > 2_000:
                raise ProtocolError("ungültiger Umgebungswert")
        with self._lock:
            self._state["environment"].update(values)
            self._save()
            return self.snapshot()

    def update_record(
        self, collection: str, record_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        rules = {
            "tests": ({"status", "actual", "note"}, TEST_STATUSES),
            "commands": ({"result"}, None),
            "issues": (
                {
                    "test_id",
                    "severity",
                    "title",
                    "reproduction",
                    "expected",
                    "actual",
                    "status",
                    "comment",
                },
                None,
            ),
        }
        allowed, statuses = rules.get(collection, (set(), None))
        if not changes or not set(changes).issubset(allowed):
            raise ProtocolError("ungültige Änderung")
        if any(not isinstance(value, str) or len(value) > 20_000 for value in changes.values()):
            raise ProtocolError("ungültiger Textwert")
        if statuses is not None and "status" in changes and changes["status"] not in statuses:
            raise ProtocolError("ungültiger Status")
        if collection == "issues":
            if "status" in changes and changes["status"] not in ISSUE_STATUSES:
                raise ProtocolError("ungültiger Fehlerstatus")
            if "severity" in changes and changes["severity"] not in ISSUE_SEVERITIES:
                raise ProtocolError("ungültiger Schweregrad")
            if (
                "test_id" in changes
                and changes["test_id"]
                and changes["test_id"] not in {item["id"] for item in self._state["tests"]}
            ):
                raise ProtocolError("verknüpfter Testfall wurde nicht gefunden")
        with self._lock:
            record = next(
                (item for item in self._state[collection] if item["id"] == record_id),
                None,
            )
            if record is None:
                raise ProtocolError("Eintrag nicht gefunden")
            record.update(changes)
            record["updated_at"] = utc_now()
            self._save()
            return self.snapshot()

    def create_issue(self, test_id: str = "") -> dict[str, Any]:
        with self._lock:
            test = None
            if test_id:
                test = next(
                    (item for item in self._state["tests"] if item["id"] == test_id),
                    None,
                )
                if test is None:
                    raise ProtocolError("verknüpfter Testfall wurde nicht gefunden")
            used_numbers = {
                int(match.group(1))
                for item in self._state["issues"]
                if (match := re.fullmatch(r"F(\d+)", item.get("id", "")))
            }
            number = next(value for value in range(1, 10_000) if value not in used_numbers)
            now = utc_now()
            self._state["issues"].append(
                {
                    "id": f"F{number:03d}",
                    "test_id": test_id,
                    "severity": "Mittel",
                    "title": f"Fehler bei {test_id}" if test else "",
                    "reproduction": "",
                    "expected": test["expected"] if test else "",
                    "actual": test["actual"] if test else "",
                    "status": "Offen",
                    "comment": "",
                    "updated_at": now,
                }
            )
            self._save()
            return self.snapshot()

    def _save(self) -> None:
        self._state["revision"] = int(self._state.get("revision", 0)) + 1
        self._state["updated_at"] = utc_now()
        validate_state(self._state)
        atomic_write_json(self.path, self._state)


def _summary(state: dict[str, Any]) -> dict[str, int]:
    counts = {status: 0 for status in TEST_STATUSES}
    for test in state["tests"]:
        counts[test["status"]] += 1
    counts["Gesamt"] = len(state["tests"])
    return counts


def export_markdown(state: dict[str, Any]) -> str:
    counts = _summary(state)
    lines = [
        "# Ubuntu Parental Control – Testprotokoll 0.5.3",
        "",
        f"Stand: {state['updated_at']}",
        "",
        "## Testumgebung",
        "",
    ]
    for label, value in state["environment"].items():
        lines.append(f"- {label}: {value or '—'}")
    lines.extend(
        [
            "",
            "## Fortschritt",
            "",
            f"- Gesamt: {counts['Gesamt']}",
            f"- Bestanden: {counts['Bestanden']}",
            f"- Fehlgeschlagen: {counts['Fehlgeschlagen']}",
            f"- In Arbeit: {counts['In Arbeit']}",
            f"- Offen: {counts['Offen']}",
            f"- Nicht anwendbar: {counts['Nicht anwendbar']}",
            "",
            "## Testfälle",
            "",
        ]
    )
    for test in state["tests"]:
        linked_issues = ", ".join(
            issue["id"] for issue in state["issues"] if issue["test_id"] == test["id"]
        )
        lines.extend(
            [
                f"### {test['id']} · {test['expected']}",
                "",
                f"- Bereich: {test['area']} / {test['subsection'] or '—'}",
                f"- Konto: {test['account']}",
                f"- Priorität: {test['priority']}",
                f"- Status: **{test['status']}**",
                f"- Ist-Ergebnis: {test['actual'] or '—'}",
                f"- Fehler-ID / Notiz: {test['note'] or '—'}",
                f"- Verknüpfte Fehler: {linked_issues or '—'}",
                "",
            ]
        )
    lines.extend(["## Fehlerprotokoll", ""])
    for issue in state["issues"]:
        lines.extend(
            [
                f"### {issue['id']} · {issue['title'] or 'Ohne Titel'}",
                "",
                f"- Testfall: {issue['test_id'] or '—'}",
                f"- Schweregrad: {issue['severity']}",
                f"- Status: **{issue['status']}**",
                f"- Reproduktion: {issue['reproduction'] or '—'}",
                f"- Erwartet: {issue['expected'] or '—'}",
                f"- Tatsächlich: {issue['actual'] or '—'}",
                f"- Kommentar / Behebung: {issue.get('comment') or '—'}",
                "",
            ]
        )
    lines.extend(["## Prüfkommandos", ""])
    for command in state["commands"]:
        lines.extend(
            [
                f"### {command['id']} · {command['area']}",
                "",
                f"Unterbereich: {command['subsection'] or '—'}",
                "",
                f"```{command['kind']}",
                command["command"],
                "```",
                "",
                f"Ergebnis / Notiz: {command['result'] or '—'}",
                "",
            ]
        )
    return "\n".join(lines)


def export_tests_csv(state: dict[str, Any]) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(
        [
            "ID",
            "Bereich",
            "Unterbereich",
            "Konto / Umgebung",
            "Prüfschritt / Soll-Ergebnis",
            "Status",
            "Ist-Ergebnis",
            "Fehler-ID / Notiz",
            "Priorität",
        ]
    )
    for test in state["tests"]:
        writer.writerow(
            [
                test["id"],
                test["area"],
                test["subsection"],
                test["account"],
                test["expected"],
                test["status"],
                test["actual"],
                test["note"],
                test["priority"],
            ]
        )
    return "\ufeff" + stream.getvalue()


class ProtocolRequestHandler(BaseHTTPRequestHandler):
    server_version = "UPCTestProtocol/1"

    @property
    def protocol_server(self) -> "ProtocolHTTPServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        self.send_header("Cache-Control", "no-store")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _allowed_host(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]")
        return host in {"127.0.0.1", "localhost"}

    def _allowed_write(self) -> bool:
        origin = self.headers.get("Origin", "")
        allowed_origins = {
            f"http://127.0.0.1:{self.protocol_server.server_port}",
            f"http://localhost:{self.protocol_server.server_port}",
        }
        return (
            self._allowed_host()
            and origin in allowed_origins
            and self.headers.get("X-UPCTest-Request") == "1"
        )

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ProtocolError("ungültige Inhaltslänge") from exc
        if length < 1 or length > MAX_BODY_SIZE:
            raise ProtocolError("ungültige Inhaltsgröße")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("ungültiges JSON") from exc
        if not isinstance(value, dict):
            raise ProtocolError("JSON-Objekt erwartet")
        return value

    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed_host():
            self._json(HTTPStatus.BAD_REQUEST, {"error": "ungültiger Host"})
            return
        route = urlparse(self.path).path
        if route == "/api/state":
            state = self.protocol_server.store.snapshot()
            state["summary"] = _summary(state)
            self._json(HTTPStatus.OK, state)
            return
        if route == "/export/testprotokoll.md":
            body = export_markdown(self.protocol_server.store.snapshot()).encode("utf-8")
            self._send(HTTPStatus.OK, body, "text/markdown; charset=utf-8")
            return
        if route == "/export/testfaelle.csv":
            body = export_tests_csv(self.protocol_server.store.snapshot()).encode("utf-8")
            self._send(HTTPStatus.OK, body, "text/csv; charset=utf-8")
            return
        if route == "/export/sicherung.json":
            body = json.dumps(
                self.protocol_server.store.snapshot(), ensure_ascii=False, indent=2
            ).encode("utf-8")
            self._send(HTTPStatus.OK, body, "application/json; charset=utf-8")
            return
        static_routes = {
            "/": "index.html",
            "/index.html": "index.html",
            "/app.js": "app.js",
            "/style.css": "style.css",
        }
        filename = static_routes.get(route)
        if filename is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "nicht gefunden"})
            return
        content_types = {
            "index.html": "text/html; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
            "style.css": "text/css; charset=utf-8",
        }
        body = (self.protocol_server.static_dir / filename).read_bytes()
        self._send(HTTPStatus.OK, body, content_types[filename])

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._allowed_write():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Schreibzugriff abgelehnt"})
            return
        try:
            body = self._read_json()
            route = unquote(urlparse(self.path).path)
            if route == "/api/environment":
                state = self.protocol_server.store.update_environment(body)
            else:
                match = re.fullmatch(r"/api/(tests|commands|issues)/([A-Z]\d+)", route)
                if not match:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "nicht gefunden"})
                    return
                state = self.protocol_server.store.update_record(
                    match.group(1), match.group(2), body
                )
            state["summary"] = _summary(state)
            self._json(HTTPStatus.OK, state)
        except ProtocolError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed_write():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Schreibzugriff abgelehnt"})
            return
        if urlparse(self.path).path != "/api/issues":
            self._json(HTTPStatus.NOT_FOUND, {"error": "nicht gefunden"})
            return
        try:
            content_length = self.headers.get("Content-Length", "0")
            body = {} if content_length == "0" else self._read_json()
            if not set(body).issubset({"test_id"}):
                raise ProtocolError("ungültige Fehlerdaten")
            test_id = body.get("test_id", "")
            if not isinstance(test_id, str) or len(test_id) > 32:
                raise ProtocolError("ungültige Testfall-ID")
            state = self.protocol_server.store.create_issue(test_id)
            state["summary"] = _summary(state)
            self._json(HTTPStatus.CREATED, state)
        except ProtocolError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


class ProtocolHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], store: StateStore, static_dir: Path):
        self.store = store
        self.static_dir = static_dir
        super().__init__(address, ProtocolRequestHandler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import-ods", help="ODS einmalig importieren")
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("destination", type=Path)
    import_parser.add_argument("--replace", action="store_true")
    validate_parser = subparsers.add_parser(
        "validate-state", help="vorhandenen JSON-Teststand prüfen"
    )
    validate_parser.add_argument("state", type=Path)
    serve_parser = subparsers.add_parser("serve", help="lokalen Webdienst starten")
    serve_parser.add_argument("--state", type=Path, required=True)
    serve_parser.add_argument("--host", default=DEFAULT_HOST)
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "import-ods":
        if args.destination.exists() and not args.replace:
            raise SystemExit("Fehler: Ziel existiert bereits; --replace ist erforderlich")
        state = import_ods(args.source)
        atomic_write_json(args.destination, state)
        print(
            f"Importiert: {len(state['tests'])} Testfälle, "
            f"{len(state['commands'])} Kommandos, {len(state['issues'])} Fehler"
        )
        return 0
    if args.command == "validate-state":
        StateStore(args.state)
        print(f"Teststand ist gültig: {args.state}")
        return 0
    if args.host not in {"127.0.0.1", "::1"}:
        raise SystemExit("Fehler: Der Testdienst darf nur an Loopback gebunden werden")
    if not 1 <= args.port <= 65_535:
        raise SystemExit("Fehler: ungültiger Port")
    store = StateStore(args.state)
    static_dir = Path(__file__).resolve().parent / "static"
    server = ProtocolHTTPServer((args.host, args.port), store, static_dir)
    print(f"Testprotokoll: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
