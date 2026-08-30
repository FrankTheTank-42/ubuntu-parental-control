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

from daemon import RuleStore, load_valid_rules  # noqa: E402
from rule_validator import load_rules  # noqa: E402


class RuleStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)
        cls.example = load_rules(PROJECT_ROOT / "config" / "rules.example.json")

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    @staticmethod
    def write(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_valid_rules_are_activated_and_saved_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, last_good = root / "rules.json", root / "state" / "last.json"
            self.write(source, self.example)
            store = RuleStore(source, last_good)
            self.assertEqual(self.example, store.start())
            self.assertEqual(self.example, load_valid_rules(last_good))
            self.assertEqual([], list(last_good.parent.glob("*.tmp")))

    def test_invalid_reload_keeps_active_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, last_good = root / "rules.json", root / "last.json"
            self.write(source, self.example)
            store = RuleStore(source, last_good)
            original = copy.deepcopy(store.start())
            invalid = copy.deepcopy(self.example)
            invalid["blocks"][0]["targets"]["domains"] = ["https://example.com"]
            self.write(source, invalid)
            self.assertFalse(store.reload_if_changed())
            self.assertEqual(original, store.active)
            self.assertEqual(original, load_valid_rules(last_good))

    def test_valid_reload_replaces_active_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, last_good = root / "rules.json", root / "last.json"
            self.write(source, self.example)
            store = RuleStore(source, last_good)
            store.start()
            changed = copy.deepcopy(self.example)
            changed["blocks"][0]["enabled"] = False
            self.write(source, changed)
            self.assertTrue(store.reload_if_changed())
            self.assertFalse(store.active["blocks"][0]["enabled"])
            self.assertEqual(changed, load_valid_rules(last_good))

    def test_start_falls_back_to_last_good_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, last_good = root / "rules.json", root / "last.json"
            self.write(last_good, self.example)
            source.write_text("{broken", encoding="utf-8")
            store = RuleStore(source, last_good)
            self.assertEqual(self.example, store.start())
            self.assertEqual(self.example, store.active)

    def test_start_fails_without_any_valid_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, last_good = root / "rules.json", root / "missing.json"
            source.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                RuleStore(source, last_good).start()


if __name__ == "__main__":
    unittest.main()
