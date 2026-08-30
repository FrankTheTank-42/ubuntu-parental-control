#!/usr/bin/python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "installer"))

from detect_restricted_users import Account, Group, detect, uid_bounds  # noqa: E402


class DetectRestrictedUsersTest(unittest.TestCase):
    def test_only_interactive_non_administrator_accounts_are_restricted(self) -> None:
        accounts = [
            Account("root", 0, 0, "/bin/bash"),
            Account("parent", 1000, 1000, "/bin/bash"),
            Account("child", 1001, 1001, "/bin/bash"),
            Account("primary-sudo", 1002, 27, "/bin/bash"),
            Account("service", 1003, 1003, "/usr/sbin/nologin"),
            Account("excluded-invoker", 1004, 1004, "/bin/bash"),
            Account("system", 999, 999, "/bin/bash"),
        ]
        groups = [
            Group("sudo", 27, ("parent",)),
            Group("users", 100, ()),
        ]
        detected = detect(accounts, groups, 1000, 60000, {1004})
        self.assertEqual([("child", 1001)], [(item.name, item.uid) for item in detected])

    def test_login_defs_controls_normal_uid_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "login.defs"
            path.write_text(
                "# lokaler Bereich\nUID_MIN 2000\nUID_MAX 2999 # Kommentar\n",
                encoding="utf-8",
            )
            self.assertEqual((2000, 2999), uid_bounds(path))

    def test_invalid_login_defs_range_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "login.defs"
            path.write_text("UID_MIN 5000\nUID_MAX 1000\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                uid_bounds(path)


if __name__ == "__main__":
    unittest.main()
