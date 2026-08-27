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
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "daemon"))

from control_server import ControlServer  # noqa: E402
from admin_helper import apply_request  # noqa: E402
from managed_policy import ManagedPolicyPublisher  # noqa: E402
from native_host import read_native_message, wait_for_publication, write_native_message  # noqa: E402
from rule_validator import load_rules  # noqa: E402
from upcctl import CommandError  # noqa: E402
from user_rules import (  # noqa: E402
    EffectiveRulePublisher,
    LiveSnapshotSigner,
    UserDomainStore,
    UserRuleError,
    empty_user_rules,
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
                self.assertTrue(status["restricted"])
                self.assertEqual("a" * 32, status["nonce"])
                self.assertEqual(
                    ["social-school-hours", "self-blocked-sites"],
                    status["can_add_domains_to"],
                )
                with self.assertRaises(UserRuleError):
                    server.dispatch(uid, {"command": "base_rules"})
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

    def test_admin_waits_for_matching_daemon_publication(self) -> None:
        expected_snapshot = {"protocol_version": 1, "live_signature": "signed"}
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
                {"command": "apply_rules", "rules": changed},
                target,
                user_domains,
            )
            self.assertRegex(result["base_revision"], r"^[0-9a-f]{64}$")
            self.assertFalse(load_rules(target)["blocks"][0]["enabled"])
            with self.assertRaises(CommandError):
                apply_request(
                    {"command": "apply_rules", "rules": changed, "target": "/etc/shadow"},
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


if __name__ == "__main__":
    unittest.main()
