import http.client
import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "tools" / "test_protocol_web" / "server.py"
SPEC = importlib.util.spec_from_file_location("test_protocol_server", MODULE_PATH)
assert SPEC and SPEC.loader
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


def _xml_cell(value: str) -> str:
    escaped = (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"<table:table-cell><text:p>{escaped}</text:p></table:table-cell>"


def _xml_sheet(name: str, rows: list[list[str]]) -> str:
    body = "".join(
        "<table:table-row>"
        + "".join(_xml_cell(value) for value in row)
        + "</table:table-row>"
        for row in rows
    )
    return f'<table:table table:name="{name}">{body}</table:table>'


def write_minimal_ods(path: Path) -> None:
    sheets = [
        _xml_sheet("Übersicht", [["Datum", "2026-09-01"], ["Tester", "Frank"]]),
        _xml_sheet(
            "Testfälle",
            [
                ["ID", "Bereich", "Unterbereich", "Konto", "Soll", "Status"],
                ["T001", "Installation", "Dienst", "System/root", "Dienst läuft", "Offen", "", "", "Pflicht"],
            ],
        ),
        _xml_sheet(
            "Kommandos",
            [
                ["ID", "Bereich", "Unterbereich", "Typ", "Kommando", "Ergebnis"],
                ["K001", "Installation", "Dienst", "bash", "systemctl status test", ""],
            ],
        ),
        _xml_sheet(
            "Fehlerprotokoll",
            [
                ["ID", "Testfall", "Schweregrad", "Titel", "Reproduktion", "Erwartet", "Tatsächlich", "Status"],
                ["F003", "T1", "Mittel", "Rootfehler", "sudo upcctl list-user-domains", "Meldung", "Traceback", "Offen"],
            ],
        ),
    ]
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        "<office:body><office:spreadsheet>"
        + "".join(sheets)
        + "</office:spreadsheet></office:body></office:document-content>"
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("content.xml", xml)


class TestProtocolWebTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.ods = self.directory / "protocol.ods"
        write_minimal_ods(self.ods)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_ods_import_preserves_data_and_corrects_f003_reproduction(self) -> None:
        state = SERVER.import_ods(self.ods)
        self.assertEqual("Frank", state["environment"]["Tester"])
        self.assertEqual("T001", state["tests"][0]["id"])
        self.assertEqual("K001", state["commands"][0]["id"])
        self.assertEqual("T001", state["issues"][0]["test_id"])
        self.assertEqual("upcctl list-user-domains", state["issues"][0]["reproduction"])

    def test_ods_import_rejects_xml_entities(self) -> None:
        malicious = self.directory / "entities.ods"
        with ZipFile(malicious, "w", ZIP_DEFLATED) as archive:
            archive.writestr(
                "content.xml",
                b'<!DOCTYPE x [<!ENTITY y "test">]><x>&y;</x>',
            )
        with self.assertRaisesRegex(SERVER.ProtocolError, "XML-Entitäten"):
            SERVER.import_ods(malicious)

    def test_store_updates_atomically_with_private_mode(self) -> None:
        state_path = self.directory / "state.json"
        SERVER.atomic_write_json(state_path, SERVER.import_ods(self.ods))
        store = SERVER.StateStore(state_path)
        updated = store.update_record("tests", "T001", {"status": "Bestanden", "actual": "OK"})
        self.assertEqual("Bestanden", updated["tests"][0]["status"])
        self.assertEqual("OK", json.loads(state_path.read_text())["tests"][0]["actual"])
        self.assertEqual(0o600, stat.S_IMODE(state_path.stat().st_mode))

    def test_issue_resolution_comment_is_persisted(self) -> None:
        state_path = self.directory / "state.json"
        SERVER.atomic_write_json(state_path, SERVER.import_ods(self.ods))
        store = SERVER.StateStore(state_path)

        updated = store.update_record(
            "issues",
            "F003",
            {"status": "Behoben", "comment": "Fehler abgefangen und erneut geprüft."},
        )

        self.assertEqual("Behoben", updated["issues"][0]["status"])
        self.assertEqual(
            "Fehler abgefangen und erneut geprüft.",
            json.loads(state_path.read_text())["issues"][0]["comment"],
        )

    def test_existing_state_without_issue_comment_is_migrated(self) -> None:
        state_path = self.directory / "state.json"
        state = SERVER.import_ods(self.ods)
        state["issues"][0].pop("comment")
        state["issues"][0]["test_id"] = "T1"
        SERVER.atomic_write_json(state_path, state)

        loaded = SERVER.StateStore(state_path).snapshot()

        self.assertEqual("", loaded["issues"][0]["comment"])
        self.assertEqual("T001", loaded["issues"][0]["test_id"])

    def test_issue_can_be_created_from_and_linked_to_test(self) -> None:
        state_path = self.directory / "state.json"
        state = SERVER.import_ods(self.ods)
        state["tests"][0]["actual"] = "Dienst ist gestoppt"
        SERVER.atomic_write_json(state_path, state)
        store = SERVER.StateStore(state_path)

        updated = store.create_issue("T001")
        issue = updated["issues"][-1]

        self.assertEqual("T001", issue["test_id"])
        self.assertEqual("Dienst läuft", issue["expected"])
        self.assertEqual("Dienst ist gestoppt", issue["actual"])
        self.assertEqual("Fehler bei T001", issue["title"])
        with self.assertRaisesRegex(SERVER.ProtocolError, "nicht gefunden"):
            store.create_issue("T999")

    def test_http_api_serves_and_updates_only_from_local_origin(self) -> None:
        state_path = self.directory / "state.json"
        SERVER.atomic_write_json(state_path, SERVER.import_ods(self.ods))
        store = SERVER.StateStore(state_path)
        static_dir = PROJECT_ROOT / "tools" / "test_protocol_web" / "static"
        try:
            server = SERVER.ProtocolHTTPServer(("127.0.0.1", 0), store, static_dir)
        except PermissionError as exc:
            self.skipTest(f"lokale TCP-Sockets sind in dieser Sandbox gesperrt: {exc}")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/api/state")
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            self.assertEqual(1, json.loads(response.read())["summary"]["Gesamt"])

            payload = json.dumps({"status": "Bestanden"})
            headers = {
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{server.server_port}",
                "X-UPCTest-Request": "1",
            }
            connection.request("PATCH", "/api/tests/T001", payload, headers)
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            self.assertEqual("Bestanden", json.loads(response.read())["tests"][0]["status"])

            issue_payload = json.dumps({"test_id": "T001"})
            connection.request("POST", "/api/issues", issue_payload, headers)
            response = connection.getresponse()
            self.assertEqual(201, response.status)
            created_issue = json.loads(response.read())["issues"][-1]
            self.assertEqual("F001", created_issue["id"])
            self.assertEqual("T001", created_issue["test_id"])

            headers["Origin"] = "https://example.com"
            connection.request("PATCH", "/api/tests/T001", payload, headers)
            response = connection.getresponse()
            self.assertEqual(403, response.status)
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_install_script_supports_isolated_root(self) -> None:
        target = self.directory / "root"
        command = [
            "bash",
            str(PROJECT_ROOT / "tools" / "test_protocol_web" / "install.sh"),
            "--root",
            str(target),
            "--no-start",
            "--import-ods",
            str(self.ods),
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        state_path = target / "var/lib/ubuntu-parental-control-test-protocol/state.json"
        self.assertEqual("T001", json.loads(state_path.read_text())["tests"][0]["id"])
        self.assertTrue((target / "usr/lib/ubuntu-parental-control-test-protocol/static/app.js").is_file())
        self.assertTrue((target / "etc/systemd/system/ubuntu-parental-control-test-protocol.service").is_file())

        state = json.loads(state_path.read_text())
        state["tests"][0]["actual"] = "bleibt erhalten"
        state_path.write_text(json.dumps(state))
        repeated = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual(
            "bleibt erhalten",
            json.loads(state_path.read_text())["tests"][0]["actual"],
        )

    def test_export_contains_results(self) -> None:
        state = SERVER.import_ods(self.ods)
        state["tests"][0]["status"] = "Bestanden"
        state["issues"][0]["comment"] = "Mit Regressionstest bestätigt."
        state["issues"][0]["test_id"] = "T001"
        markdown = SERVER.export_markdown(state)
        csv_text = SERVER.export_tests_csv(state)
        self.assertIn("T001 · Dienst läuft", markdown)
        self.assertIn("Status: **Bestanden**", markdown)
        self.assertIn("K001 · Installation", markdown)
        self.assertIn("systemctl status test", markdown)
        self.assertIn("Kommentar / Behebung: Mit Regressionstest bestätigt.", markdown)
        self.assertIn("Verknüpfte Fehler: F003", markdown)
        self.assertIn("T001;Installation", csv_text)


if __name__ == "__main__":
    unittest.main()
