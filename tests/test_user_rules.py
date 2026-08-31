#!/usr/bin/python3
from __future__ import annotations

import copy
import base64
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "daemon"))

from control_server import ControlServer  # noqa: E402
from admin_helper import apply_request  # noqa: E402
from managed_policy import ManagedPolicyPublisher  # noqa: E402
from native_host import (  # noqa: E402
    read_native_message,
    response_snapshot_revision,
    snapshot_event,
    snapshot_revision,
    wait_for_publication,
    write_native_message,
)
from rule_validator import load_rules  # noqa: E402
from upcctl import CommandError  # noqa: E402
from upcctl import rules_mutation_lock, write_rules_atomic  # noqa: E402
from user_rules import (  # noqa: E402
    EffectiveRulePublisher,
    LiveSnapshotSigner,
    SnapshotGenerationStore,
    UserDomainStore,
    UserRuleError,
    empty_user_rules,
    object_revision,
)


class UserRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.example = load_rules(PROJECT_ROOT / "config" / "rules.example.json")

    def coordinator(self, root: Path, restricted_users: list[int]) -> EffectiveRulePublisher:
        firefox = root / "policies.json"
        firefox.write_text('{"policies":{}}\n', encoding="utf-8")
        config: dict[str, object] = {
            "managed_browsers": ["firefox"],
            "chrome_extension_id": None,
            "chrome_update_url": None,
            "restricted_users": restricted_users,
            "administrator_users": [uid for uid in [os.getuid() or 1000] if uid not in restricted_users],
            "live_public_key_spki": base64.b64encode(b"test-public-key").decode("ascii"),
        }
        store = UserDomainStore(root / "user-domains.json")
        store.write(empty_user_rules())
        class FakeSigner:
            @staticmethod
            def sign_text(_text: str) -> str:
                return base64.b64encode(bytes(64)).decode("ascii")

            def sign(self, managed: dict[str, object]) -> dict[str, object]:
                return {**managed, "live_signature": self.sign_text(str(managed["snapshot_json"]))}

        return EffectiveRulePublisher(
            config,
            store,
            ManagedPolicyPublisher(config, firefox, root / "chrome.json"),
            root / "live-snapshot.json",
            FakeSigner(),
        )

    def test_snapshot_generation_is_persistent_and_monotone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generation"
            store = SnapshotGenerationStore(path)
            self.assertEqual(1, store.next())
            self.assertEqual(2, SnapshotGenerationStore(path).next())
            path.write_text("1\n", encoding="ascii")
            self.assertEqual(2, store.next())

    def test_live_write_failure_restores_managed_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uid = os.getuid() or 1000
            publisher = self.coordinator(root, [uid])
            publisher(self.example)
            firefox = root / "policies.json"
            snapshot = root / "live-snapshot.json"
            before_policy, before_snapshot = firefox.read_bytes(), snapshot.read_bytes()
            changed = copy.deepcopy(self.example)
            changed["blocks"][0]["enabled"] = False
            with patch("user_rules._atomic_write", side_effect=OSError("live write")):
                with self.assertRaises(OSError):
                    publisher(changed)
            self.assertEqual(before_policy, firefox.read_bytes())
            self.assertEqual(before_snapshot, snapshot.read_bytes())

    def test_restricted_user_can_append_to_every_blocking_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uid = os.getuid() or 1000
            publisher = self.coordinator(root, [uid])
            rules = copy.deepcopy(self.example)
            for block in rules["blocks"]:
                if block["action"] == "block":
                    block["user_permissions"]["add_domains"] = False
            publisher(rules)
            result = publisher.add_domain(uid, "self-blocked-sites", "example.com")
            self.assertEqual("example.com", result["domain"])
            stored = publisher.store.load()
            self.assertEqual(
                ["example.com"],
                stored["users"][str(uid)]["self-blocked-sites"],
            )
            snapshot = json.loads(result["managed"]["snapshot_json"])
            block = next(
                item for item in snapshot["rules"]["blocks"] if item["id"] == "self-blocked-sites"
            )
            self.assertEqual(["example.com", "twitch.tv"], block["targets"]["domains"])
            with self.assertRaises(UserRuleError):
                publisher.add_domain(uid, "self-blocked-sites", "example.com")
            second = publisher.add_domain(uid, "social-school-hours", "example.net")
            self.assertEqual("example.net", second["domain"])
            with self.assertRaises(UserRuleError):
                publisher.add_domain(uid, "allow-school-youtube", "allowed.example")
            with self.assertRaises(UserRuleError):
                publisher.add_domain(uid, "self-blocked-sites", "https://example.net")
            with self.assertRaises(UserRuleError):
                publisher.add_domain(uid + 1, "self-blocked-sites", "example.net")

    def test_stale_addition_is_never_merged_into_allow_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uid = os.getuid() or 1000
            publisher = self.coordinator(root, [uid])
            state = empty_user_rules()
            state["users"] = {str(uid): {"allow-school-youtube": ["example.com"]}}
            publisher.store.write(state)
            merged = publisher.store.merge(self.example, publisher.store.load())
            allow = next(item for item in merged["blocks"] if item["id"] == "allow-school-youtube")
            self.assertNotIn("example.com", allow["targets"]["domains"])

    def test_insecure_user_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user-domains.json"
            path.write_text(json.dumps(empty_user_rules()), encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaises(UserRuleError):
                UserDomainStore(path).load()

    def test_control_server_uses_real_peer_uid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uid = os.getuid()
            publisher = self.coordinator(root, [uid])
            publisher(self.example)
            server = ControlServer(root / "control.sock", publisher)
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                try:
                    self.assertEqual(uid, server._peer_uid(left))
                except PermissionError:
                    # The Codex filesystem sandbox blocks SO_PEERCRED. Ubuntu's
                    # production AF_UNIX socket provides it to the service.
                    pass
                signed_status = server.dispatch(uid, {"command": "status", "nonce": "a" * 32})
                status = json.loads(signed_status["authorization_json"])
                self.assertEqual(uid, status["uid"])
                self.assertEqual("restricted", status["role"])
                self.assertEqual("a" * 32, status["nonce"])
                self.assertEqual(
                    ["social-school-hours", "self-blocked-sites"],
                    status["can_add_domains_to"],
                )
                own = server.dispatch(uid, {"command": "own_user_domains"})
                self.assertEqual(
                    {"format_version": 1, "users": {}},
                    own["user_domains"],
                )
                with self.assertRaises(UserRuleError):
                    server.dispatch(uid, {"command": "base_rules"})
                unauthorized_uid = uid + 100
                unauthorized_status = json.loads(
                    server.dispatch(
                        unauthorized_uid, {"command": "status", "nonce": "b" * 32}
                    )["authorization_json"]
                )
                self.assertEqual("unauthorized", unauthorized_status["role"])
                with self.assertRaises(UserRuleError):
                    server.dispatch(unauthorized_uid, {"command": "base_rules"})
                publication = server.dispatch(uid, {"command": "publication"})
                self.assertEqual(1, publication["serial"])
                self.assertRegex(publication["base_revision"], r"^[0-9a-f]{64}$")
                self.assertRegex(publication["user_revision"], r"^[0-9a-f]{64}$")
                with self.assertRaises(UserRuleError):
                    server.dispatch(uid, {"command": "status", "nonce": "too-short"})
            finally:
                left.close()
                right.close()

    def test_native_message_framing_round_trip(self) -> None:
        stream = io.BytesIO()
        message = {"id": "abc", "command": "status", "text": "Grüße"}
        write_native_message(stream, message)
        stream.seek(0)
        self.assertEqual(message, read_native_message(stream))

    def test_native_response_marks_direct_snapshot_revision_as_delivered(self) -> None:
        revision = "a" * 64
        response = {
            "id": "request-1",
            "ok": True,
            "result": {"managed": {"revision": revision}},
        }
        self.assertEqual(revision, response_snapshot_revision(response))
        self.assertIsNone(response_snapshot_revision({"ok": False, "error": "abgelehnt"}))
        self.assertIsNone(response_snapshot_revision({"ok": True, "result": {}}))
        self.assertEqual(revision, snapshot_revision({"revision": revision}))
        with self.assertRaises(ValueError):
            response_snapshot_revision({
                "ok": True,
                "result": {"managed": {"revision": "keine-pruefsumme"}},
            })

    def test_native_watcher_suppresses_only_the_directly_delivered_revision(self) -> None:
        delivered = "a" * 64
        same = {"revision": delivered, "snapshot_json": "same"}
        revision, event = snapshot_event(same, delivered)
        self.assertEqual(delivered, revision)
        self.assertIsNone(event)

        newer = {"revision": "b" * 64, "snapshot_json": "newer"}
        revision, event = snapshot_event(newer, delivered)
        self.assertEqual("b" * 64, revision)
        self.assertEqual({"event": "snapshot", "managed": newer}, event)

    def test_admin_waits_for_matching_daemon_publication(self) -> None:
        expected_snapshot = {"protocol_version": 2, "generation": 4, "live_signature": "signed"}
        publications = [
            {"serial": 3, "base_revision": "old", "user_revision": "users"},
            {"serial": 4, "base_revision": "expected", "user_revision": "users"},
        ]
        with (
            patch("native_host.current_publication", side_effect=publications),
            patch("native_host.load_snapshot", return_value=expected_snapshot),
        ):
            snapshot = wait_for_publication(
                Path("/run/test-snapshot.json"),
                Path("/run/test-control.sock"),
                3,
                "base_revision",
                "expected",
            )
        self.assertEqual(expected_snapshot, snapshot)

    def test_live_signer_emits_webcrypto_sized_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key.pem"
            import subprocess

            subprocess.run(
                [
                    "/usr/bin/openssl",
                    "genpkey",
                    "-algorithm",
                    "EC",
                    "-pkeyopt",
                    "ec_paramgen_curve:P-256",
                    "-out",
                    str(key),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            key.chmod(0o600)
            signed = LiveSnapshotSigner(key).sign({"snapshot_json": "{}"})
            self.assertEqual(64, len(base64.b64decode(signed["live_signature"])))

    def test_admin_helper_validates_complete_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "rules.json"
            user_domains = root / "user-domains.json"
            target.write_text(json.dumps(self.example), encoding="utf-8")
            store = UserDomainStore(user_domains)
            state = empty_user_rules()
            state["users"] = {"1001": {"self-blocked-sites": ["example.com"]}}
            store.write(state)
            changed = copy.deepcopy(self.example)
            changed["blocks"][0]["enabled"] = False
            result = apply_request(
                {
                    "command": "apply_rules",
                    "rules": changed,
                    "expected_base_revision": object_revision(self.example),
                },
                target,
                user_domains,
            )
            self.assertRegex(result["base_revision"], r"^[0-9a-f]{64}$")
            self.assertFalse(load_rules(target)["blocks"][0]["enabled"])
            with self.assertRaises(CommandError):
                apply_request(
                    {
                        "command": "apply_rules",
                        "rules": changed,
                        "expected_base_revision": object_revision(changed),
                        "target": "/etc/shadow",
                    },
                    target,
                    user_domains,
                )
            with self.assertRaises(CommandError):
                apply_request(
                    {
                        "command": "apply_rules",
                        "rules": changed,
                        "expected_base_revision": "0" * 64,
                    },
                    target,
                    user_domains,
                )
            result = apply_request(
                {
                    "command": "remove_user_domain",
                    "uid": 1001,
                    "block_id": "self-blocked-sites",
                    "domain": "example.com",
                },
                target,
                user_domains,
            )
            self.assertRegex(result["user_revision"], r"^[0-9a-f]{64}$")
            self.assertEqual({}, store.load()["users"])

    def test_control_server_slow_peers_are_bounded_and_released(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publisher = self.coordinator(root, [])
            publisher(self.example)
            path = root / "control.sock"
            server = ControlServer(path, publisher)
            try:
                server.start()
            except PermissionError as exc:
                self.skipTest(f"AF_UNIX-Bind ist in dieser Sandbox nicht erlaubt: {exc}")
            peers: list[socket.socket] = []
            try:
                slow = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                peers.append(slow)
                slow.settimeout(1)
                slow.connect(str(path))
                slow.sendall(b'{"command":"')

                # A complete request must proceed while the first peer is idle.
                legitimate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                peers.append(legitimate)
                legitimate.settimeout(1)
                legitimate.connect(str(path))
                legitimate.sendall(
                    b'{"id":1,"command":"status","nonce":"' + b"n" * 32 + b'"}\n'
                )
                response = legitimate.recv(4096)
                self.assertIn(b'"ok":true', response)

                # Keep the second slot occupied with another incomplete peer.
                second_slow = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                peers.append(second_slow)
                second_slow.settimeout(1)
                second_slow.connect(str(path))
                second_slow.sendall(b'{"command":"')
                third = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                peers.append(third)
                third.settimeout(0.5)
                third.connect(str(path))
                started = time.monotonic()
                try:
                    third.sendall(b'{"command":"status"}\n')
                    third.settimeout(0.5)
                    self.assertEqual(b"", third.recv(1))
                except (ConnectionResetError, BrokenPipeError):
                    pass
                except socket.timeout as exc:
                    self.fail(f"Limit-Ablehnung erfolgte nicht zügig: {exc}")
                self.assertLess(time.monotonic() - started, 0.6)
                for peer in peers:
                    peer.close()
                peers.clear()
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    with server._connection_lock:
                        if server._connections_total == 0:
                            break
                    time.sleep(0.01)
                with server._connection_lock:
                    self.assertEqual(0, server._connections_total)
                    self.assertEqual({}, server._connections_by_uid)
            finally:
                for peer in peers:
                    peer.close()
                server.close()
            self.assertFalse(path.exists())

    def test_control_server_start_closes_listener_on_setup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publisher = self.coordinator(root, [])
            server = ControlServer(root / "control.sock", publisher)
            listener = patch("control_server.socket.socket").start()
            fake_listener = listener.return_value
            fake_listener.bind.side_effect = OSError("injected bind failure")
            self.addCleanup(patch.stopall)
            with self.assertRaises(OSError):
                server.start()
            fake_listener.close.assert_called_once_with()
            self.assertIsNone(server._socket)
            self.assertIsNone(server._thread)
            self.assertFalse(server.path.exists())

    def test_control_server_worker_start_failure_releases_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publisher = self.coordinator(root, [])
            server = ControlServer(root / "control.sock", publisher)
            connection, peer = socket.socketpair()
            server._connections_total = 0
            with patch("control_server.threading.Thread") as thread_type:
                thread_type.return_value.start.side_effect = RuntimeError("thread limit")
                class FakeListener:
                    def accept(self):
                        server._stop.set()
                        return connection, None

                server._socket = FakeListener()
                with patch.object(server, "_peer_uid", return_value=os.getuid()):
                    server._serve()
            self.assertEqual(0, server._connections_total)
            self.assertEqual({}, server._connections_by_uid)
            connection.close()
            peer.close()

    def test_admin_apply_rejects_stale_revision_after_overlapping_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "rules.json"
            domains = root / "user-domains.json"
            target.write_text(json.dumps(self.example), encoding="utf-8")
            UserDomainStore(domains).write(empty_user_rules())
            expected = object_revision(self.example)
            competing = copy.deepcopy(self.example)
            competing["blocks"][0]["enabled"] = False
            requested = copy.deepcopy(self.example)
            requested["blocks"][0]["name"] = "Concurrent admin change"
            entered = threading.Event()
            release = threading.Event()

            def competitor() -> None:
                with rules_mutation_lock(target):
                    write_rules_atomic(target, competing)
                    entered.set()
                    release.wait(2)

            thread = threading.Thread(target=competitor)
            thread.start()
            self.assertTrue(entered.wait(2))
            result: list[BaseException] = []

            def admin() -> None:
                try:
                    apply_request(
                        {"command": "apply_rules", "rules": requested, "expected_base_revision": expected},
                        target,
                        domains,
                    )
                except BaseException as exc:  # capture worker failure for assertion
                    result.append(exc)

            admin_thread = threading.Thread(target=admin)
            admin_thread.start()
            time.sleep(0.05)
            release.set()
            thread.join(2)
            admin_thread.join(2)
            self.assertTrue(result and isinstance(result[0], CommandError))
            self.assertFalse(load_rules(target)["blocks"][0]["enabled"])


if __name__ == "__main__":
    unittest.main()
