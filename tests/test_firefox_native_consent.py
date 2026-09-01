from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "installer"))

import firefox_native_consent as consent  # noqa: E402


class FirefoxNativeConsentTest(unittest.TestCase):
    @patch("firefox_native_consent.subprocess.run")
    def test_grant_uses_session_permission_store_without_shell(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "()\n", "")
        consent.grant()
        command = run.call_args.args[0]
        self.assertEqual(consent.GDBUS, command[0])
        self.assertIn(f"{consent.INTERFACE}.SetPermission", command)
        self.assertEqual(
            [consent.TABLE, "true", consent.HOST, consent.APP, "['yes']"],
            command[-5:],
        )
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertTrue(run.call_args.kwargs["check"])

    @patch("firefox_native_consent.subprocess.run")
    def test_reset_removes_only_the_firefox_host_decision(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "()\n", "")
        consent.reset()
        command = run.call_args.args[0]
        self.assertIn(f"{consent.INTERFACE}.DeletePermission", command)
        self.assertEqual([consent.TABLE, consent.HOST, consent.APP], command[-3:])

    @patch("firefox_native_consent.subprocess.run")
    def test_status_translates_portal_values(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "(['yes'],)\n", "")
        self.assertEqual("erlaubt", consent.status())
        run.return_value = subprocess.CompletedProcess([], 0, "(['no'],)\n", "")
        self.assertEqual("verweigert", consent.status())

    @patch("firefox_native_consent.subprocess.run")
    def test_status_treats_empty_permission_array_as_undecided(self, run) -> None:
        for output in ("(@as [],)\n", "([],)\n"):
            with self.subTest(output=output):
                run.return_value = subprocess.CompletedProcess([], 0, output, "")
                self.assertEqual("nicht entschieden", consent.status())

    @patch("firefox_native_consent.subprocess.run")
    def test_status_keeps_unknown_permission_values_visible(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "(['ask'],)\n", "")
        self.assertEqual("unbekannt ((['ask'],))", consent.status())

    def test_only_exact_repair_uri_is_accepted(self) -> None:
        consent.validate_consent_uri(consent.CONSENT_URI)
        for value in (
            "https://firefox-consent/allow",
            "ubuntu-parental-control://firefox-consent/reset",
            "ubuntu-parental-control://firefox-consent/allow?automatic=true",
            "ubuntu-parental-control://attacker/allow",
        ):
            with self.subTest(value=value), self.assertRaises(consent.ConsentError):
                consent.validate_consent_uri(value)


if __name__ == "__main__":
    unittest.main()
