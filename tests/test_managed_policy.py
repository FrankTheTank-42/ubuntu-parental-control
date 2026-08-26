#!/usr/bin/python3
from __future__ import annotations

import copy
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "daemon"))

from daemon import RuleStore  # noqa: E402
from managed_policy import (  # noqa: E402
    FIREFOX_EXTENSION_ID,
    ManagedPolicyPublisher,
    PolicyPublicationError,
    make_managed_data,
)
from rule_validator import load_rules  # noqa: E402


CHROME_ID = "abcdefghijklmnopabcdefghijklmnop"


class ManagedPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)
        cls.example = load_rules(PROJECT_ROOT / "config" / "rules.example.json")

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    def test_same_snapshot_is_published_to_firefox_and_chrome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            firefox = root / "firefox" / "policies.json"
            chrome = root / "chrome" / "ubuntu-parental-control.json"
            firefox.parent.mkdir()
            firefox.write_text(
                json.dumps({"policies": {"DisableTelemetry": True}}), encoding="utf-8"
            )
            config = {
                "managed_browsers": ["firefox", "chrome"],
                "chrome_extension_id": CHROME_ID,
                "chrome_update_url": "https://clients2.google.com/service/update2/crx",
            }
            ManagedPolicyPublisher(config, firefox, chrome)(self.example)

            firefox_data = json.loads(firefox.read_text(encoding="utf-8"))
            chrome_data = json.loads(chrome.read_text(encoding="utf-8"))
            firefox_managed = firefox_data["policies"]["3rdparty"]["Extensions"][FIREFOX_EXTENSION_ID]
            chrome_managed = chrome_data["3rdparty"]["extensions"][CHROME_ID]
            self.assertEqual(firefox_managed, chrome_managed)
            self.assertTrue(firefox_data["policies"]["DisableTelemetry"])
            snapshot = json.loads(firefox_managed["snapshot_json"])
            self.assertEqual(firefox_managed["revision"], snapshot["revision"])
            self.assertNotIn("$schema", snapshot["rules"])
            self.assertEqual(
                "force_installed",
                chrome_data["ExtensionSettings"][CHROME_ID]["installation_mode"],
            )
            self.assertEqual(1, chrome_data["IncognitoModeAvailability"])
            self.assertFalse(chrome_data["BrowserGuestModeEnabled"])
            self.assertEqual(2, chrome_data["DeveloperToolsAvailability"])

    def test_invalid_chrome_id_is_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            firefox = root / "policies.json"
            firefox.write_text('{"policies": {}}', encoding="utf-8")
            config = {
                "managed_browsers": ["chrome"],
                "chrome_extension_id": "invalid",
                "chrome_update_url": "https://example.test/update",
            }
            with self.assertRaises(PolicyPublicationError):
                ManagedPolicyPublisher(config, firefox, root / "chrome.json")(self.example)
            self.assertFalse((root / "chrome.json").exists())

    def test_publication_failure_keeps_active_rules_and_last_good(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, last_good = root / "rules.json", root / "last.json"
            source.write_text(json.dumps(self.example), encoding="utf-8")
            calls = 0

            def publisher(_rules: dict[str, object]) -> None:
                nonlocal calls
                calls += 1
                if calls > 1:
                    raise PolicyPublicationError("simulierter Policy-Fehler")

            store = RuleStore(source, last_good, publisher)
            original = copy.deepcopy(store.start())
            changed = copy.deepcopy(self.example)
            changed["blocks"][0]["enabled"] = False
            source.write_text(json.dumps(changed), encoding="utf-8")
            self.assertFalse(store.reload_if_changed())
            self.assertEqual(original, store.active)
            self.assertEqual(original, json.loads(last_good.read_text(encoding="utf-8")))

    def test_snapshot_size_is_bounded(self) -> None:
        oversized = copy.deepcopy(self.example)
        oversized["blocks"][0]["name"] = "x" * 1_000_001
        with self.assertRaises(PolicyPublicationError):
            make_managed_data(oversized)

    def test_non_domain_exception_is_rejected_instead_of_broadly_allowed(self) -> None:
        rules = copy.deepcopy(self.example)
        rules["blocks"][0]["exceptions"]["url_patterns"] = [
            "*://youtube.com/allowed/*"
        ]
        with self.assertRaisesRegex(PolicyPublicationError, "nicht verlustfrei"):
            make_managed_data(rules)

    def test_publication_failure_is_retried_without_another_file_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, last_good = root / "rules.json", root / "last.json"
            source.write_text(json.dumps(self.example), encoding="utf-8")
            attempts = 0

            def publisher(_rules: dict[str, object]) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 2:
                    raise PolicyPublicationError("einmaliger Fehler")

            store = RuleStore(source, last_good, publisher)
            store.start()
            changed = copy.deepcopy(self.example)
            changed["blocks"][0]["enabled"] = False
            source.write_text(json.dumps(changed), encoding="utf-8")
            self.assertFalse(store.reload_if_changed())
            self.assertTrue(store.reload_if_changed())
            self.assertFalse(store.active["blocks"][0]["enabled"])


if __name__ == "__main__":
    unittest.main()
