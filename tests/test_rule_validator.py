#!/usr/bin/python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "daemon"))

from rule_validator import DuplicateKeyError, RuleValidator, load_rules  # noqa: E402


class RuleValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.example = load_rules(PROJECT_ROOT / "config" / "rules.example.json")
        cls.defaults = load_rules(PROJECT_ROOT / "config" / "rules.json")

    def errors(self, value: dict) -> list[str]:
        return [str(issue) for issue in RuleValidator().validate(value)]

    def test_example_is_valid(self) -> None:
        self.assertEqual([], self.errors(copy.deepcopy(self.example)))

    def test_default_rules_provide_an_always_active_blocklist(self) -> None:
        self.assertEqual([], self.errors(copy.deepcopy(self.defaults)))
        self.assertEqual(1, len(self.defaults["blocks"]))
        block = self.defaults["blocks"][0]
        self.assertEqual("default-block", block["id"])
        self.assertEqual("block", block["action"])
        self.assertTrue(block["enabled"])
        self.assertTrue(block["user_permissions"]["add_domains"])
        self.assertEqual(
            {"domains": [], "url_patterns": [], "url_regex": []},
            block["targets"],
        )
        self.assertNotIn("schedule", block)

    def test_duplicate_block_id_is_rejected(self) -> None:
        value = copy.deepcopy(self.example)
        value["blocks"][1]["id"] = value["blocks"][0]["id"]
        self.assertTrue(any("Block-ID bereits" in error for error in self.errors(value)))

    def test_legacy_duplicate_visible_block_names_are_accepted(self) -> None:
        value = copy.deepcopy(self.example)
        value["blocks"][1]["name"] = f"  {value['blocks'][0]['name'].upper()}  "
        self.assertEqual([], self.errors(value))

    def test_user_may_only_add_domains_to_block_rule(self) -> None:
        value = copy.deepcopy(self.example)
        value["blocks"][2]["user_permissions"]["add_domains"] = True
        self.assertTrue(any("nur bei action 'block'" in error for error in self.errors(value)))

    def test_unknown_timezone_is_rejected(self) -> None:
        value = copy.deepcopy(self.example)
        value["profile"]["timezone"] = "Europe/Entenhausen"
        self.assertTrue(any("unbekannte IANA-Zeitzone" in error for error in self.errors(value)))

    def test_duplicate_rrule_day_is_rejected(self) -> None:
        value = copy.deepcopy(self.example)
        value["blocks"][0]["schedule"]["windows"][0]["rrule"] = "FREQ=WEEKLY;BYDAY=MO,MO"
        self.assertTrue(any("Wochentage doppelt" in error for error in self.errors(value)))

    def test_invalid_url_pattern_is_rejected(self) -> None:
        value = copy.deepcopy(self.example)
        value["blocks"][0]["targets"]["url_patterns"] = ["https://example.com"]
        self.assertTrue(any("WebExtension-Pattern" in error for error in self.errors(value)))

    def test_re2_lookahead_is_rejected(self) -> None:
        value = copy.deepcopy(self.example)
        value["blocks"][0]["targets"]["url_regex"][0]["pattern"] = "example(?=\\.com)"
        self.assertTrue(any("RE2" in error for error in self.errors(value)))

    def test_empty_targets_are_valid_for_a_prepared_blocklist(self) -> None:
        value = copy.deepcopy(self.example)
        value["blocks"][0]["targets"] = {"domains": [], "url_patterns": [], "url_regex": []}
        self.assertEqual([], self.errors(value))

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text('{"format_version":"1.0","format_version":"2.0"}', encoding="utf-8")
            with self.assertRaises(DuplicateKeyError):
                load_rules(path)

    def test_machine_readable_cli_result(self) -> None:
        # The output shape is intentionally stable for daemon/UI integration.
        issues = RuleValidator().validate(copy.deepcopy(self.example))
        result = {"valid": not issues, "errors": [issue.__dict__ for issue in issues]}
        self.assertEqual({"valid": True, "errors": []}, json.loads(json.dumps(result)))


if __name__ == "__main__":
    unittest.main()
