#!/usr/bin/python3
from __future__ import annotations

import copy
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "daemon"))

from rule_validator import load_rules  # noqa: E402
from upcctl import (  # noqa: E402
    CommandError,
    command_add_domain,
    command_apply,
    command_add_window,
    command_create_block,
    command_clear_schedule,
    command_delete_block,
    command_history,
    command_list_user_domains,
    command_remove_domain,
    command_remove_user_domain,
    command_remove_window,
    command_rollback,
    command_set_block,
    command_set_profile,
    command_set_schedule_timezone,
    command_update_string_matcher,
    command_update_url_regex,
    history_dir_for,
    history_versions,
    write_rules_atomic,
)


class UpcctlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.example = load_rules(PROJECT_ROOT / "config" / "rules.example.json")

    @staticmethod
    def write(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_apply_rejects_invalid_source_without_changing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, source = root / "rules.json", root / "invalid.json"
            self.write(target, self.example)
            original = copy.deepcopy(self.example)
            invalid = copy.deepcopy(self.example)
            invalid["blocks"][0]["targets"]["domains"] = ["https://example.com"]
            self.write(source, invalid)
            with self.assertRaises(CommandError):
                command_apply(target, source)
            self.assertEqual(original, load_rules(target))

    def test_apply_dry_run_shows_diff_without_writing_or_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, source = root / "rules.json", root / "proposed.json"
            self.write(target, self.example)
            proposed = copy.deepcopy(self.example)
            proposed["profile"]["default_action"] = "block"
            self.write(source, proposed)
            original = target.read_bytes()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                command_apply(target, source, dry_run=True)
            self.assertEqual(original, target.read_bytes())
            self.assertFalse(history_dir_for(target).exists())
            self.assertIn('-    "default_action": "allow"', output.getvalue())
            self.assertIn('+    "default_action": "block"', output.getvalue())

    def test_apply_repairs_invalid_target_without_archiving_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, source = root / "rules.json", root / "valid.json"
            target.write_text('{"broken": true}\n', encoding="utf-8")
            self.write(source, self.example)
            command_apply(target, source)
            self.assertEqual(self.example, load_rules(target))
            self.assertFalse(history_dir_for(target).exists())

    def test_history_and_atomic_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            original = copy.deepcopy(self.example)
            command_add_domain(target, "self-blocked-sites", "example.com")
            versions = history_versions(history_dir_for(target))
            self.assertEqual(1, len(versions))
            original_version, original_snapshot = versions[0]
            self.assertEqual(0o700, history_dir_for(target).stat().st_mode & 0o777)
            self.assertEqual(0o600, original_snapshot.stat().st_mode & 0o777)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                command_history(target)
            self.assertIn(original_version, output.getvalue())

            changed = target.read_bytes()
            with self.assertRaises(CommandError):
                command_rollback(
                    target,
                    original_version,
                    confirmed=False,
                    dry_run=False,
                )
            self.assertEqual(changed, target.read_bytes())

            preview = io.StringIO()
            with contextlib.redirect_stdout(preview):
                command_rollback(
                    target,
                    original_version,
                    confirmed=False,
                    dry_run=True,
                )
            self.assertEqual(changed, target.read_bytes())
            self.assertIn("Rollback-Vorschau", preview.getvalue())

            command_rollback(
                target,
                original_version,
                confirmed=True,
                dry_run=False,
            )
            self.assertEqual(original, load_rules(target))
            self.assertEqual(2, len(history_versions(history_dir_for(target))))

    def test_rollback_rejects_invalid_version_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            with self.assertRaises(CommandError):
                command_rollback(
                    target,
                    "../../rules",
                    confirmed=True,
                    dry_run=False,
                )

    def test_rollback_rejects_tampered_history_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            command_add_domain(target, "self-blocked-sites", "example.com")
            version, snapshot = history_versions(history_dir_for(target))[0]
            tampered = load_rules(snapshot)
            tampered["profile"]["timezone"] = "UTC"
            self.write(snapshot, tampered)
            current = target.read_bytes()
            with self.assertRaises(CommandError):
                command_rollback(
                    target,
                    version,
                    confirmed=True,
                    dry_run=False,
                )
            self.assertEqual(current, target.read_bytes())

    def test_profile_settings_are_validated_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            command_set_profile(target, timezone="UTC", default_action="block")
            rules = load_rules(target)
            self.assertEqual("UTC", rules["profile"]["timezone"])
            self.assertEqual("block", rules["profile"]["default_action"])
            self.assertEqual(1, len(history_versions(history_dir_for(target))))
            current = target.read_bytes()
            with self.assertRaises(CommandError):
                command_set_profile(
                    target,
                    timezone="Not/A-Timezone",
                    default_action=None,
                )
            with self.assertRaises(CommandError):
                command_set_profile(target, timezone=None, default_action=None)
            self.assertEqual(current, target.read_bytes())

    def test_insecure_history_directory_blocks_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            history = history_dir_for(target)
            history.mkdir(mode=0o700)
            history.chmod(0o755)
            original = target.read_bytes()
            with self.assertRaises(CommandError):
                command_add_domain(target, "self-blocked-sites", "example.com")
            self.assertEqual(original, target.read_bytes())

    def test_atomic_write_preserves_mode_and_leaves_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            target.chmod(0o640)
            changed = copy.deepcopy(self.example)
            changed["blocks"][0]["enabled"] = False
            write_rules_atomic(target, changed)
            self.assertEqual(0o640, target.stat().st_mode & 0o777)
            self.assertFalse(load_rules(target)["blocks"][0]["enabled"])
            self.assertEqual([], list(target.parent.glob(".*.tmp")))

    def test_add_and_remove_domain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            command_add_domain(target, "self-blocked-sites", "example.com")
            domains = load_rules(target)["blocks"][1]["targets"]["domains"]
            self.assertEqual(["example.com", "twitch.tv"], domains)
            with self.assertRaises(CommandError):
                command_add_domain(target, "self-blocked-sites", "example.com")
            command_remove_domain(target, "self-blocked-sites", "example.com")
            self.assertEqual(
                ["twitch.tv"],
                load_rules(target)["blocks"][1]["targets"]["domains"],
            )

    def test_invalid_domain_and_missing_block_do_not_change_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            original = target.read_bytes()
            with self.assertRaises(CommandError):
                command_add_domain(target, "self-blocked-sites", "https://example.com")
            with self.assertRaises(CommandError):
                command_add_domain(target, "missing", "example.com")
            self.assertEqual(original, target.read_bytes())

    def test_create_and_configure_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            command_create_block(
                target,
                "homework-sites",
                "Hausaufgaben-Seiten",
                "allow",
                50,
                ["school.example", "library.example"],
            )
            created = load_rules(target)["blocks"][-1]
            self.assertEqual("homework-sites", created["id"])
            self.assertEqual("allow", created["action"])
            self.assertEqual(50, created["priority"])
            self.assertFalse(created["user_permissions"]["add_domains"])
            self.assertEqual(
                ["library.example", "school.example"],
                created["targets"]["domains"],
            )
            command_set_block(
                target,
                "homework-sites",
                name="Schulangebote",
                action="block",
                priority=25,
                enabled=False,
            )
            changed = load_rules(target)["blocks"][-1]
            self.assertEqual("Schulangebote", changed["name"])
            self.assertEqual("block", changed["action"])
            self.assertEqual(25, changed["priority"])
            self.assertFalse(changed["enabled"])
            self.assertTrue(changed["user_permissions"]["add_domains"])

    def test_invalid_block_changes_leave_rules_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            original = target.read_bytes()
            with self.assertRaises(CommandError):
                command_create_block(
                    target,
                    "self-blocked-sites",
                    "Doppelt",
                    "block",
                    0,
                    ["example.com"],
                )
            with self.assertRaises(CommandError):
                command_create_block(
                    target,
                    "another-social-block",
                    f"  {self.example['blocks'][0]['name'].upper()}  ",
                    "block",
                    0,
                    ["example.com"],
                )
            with self.assertRaises(CommandError):
                command_set_block(
                    target,
                    "self-blocked-sites",
                    name=self.example["blocks"][0]["name"],
                    action=None,
                    priority=None,
                    enabled=None,
                )
            with self.assertRaises(CommandError):
                command_set_block(
                    target,
                    "self-blocked-sites",
                    name=None,
                    action="deny",
                    priority=None,
                    enabled=None,
                )
            with self.assertRaises(CommandError):
                command_set_block(
                    target,
                    "self-blocked-sites",
                    name=None,
                    action=None,
                    priority=None,
                    enabled=None,
                )
            self.assertEqual(original, target.read_bytes())

    def test_delete_block_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            original = target.read_bytes()
            with self.assertRaises(CommandError):
                command_delete_block(target, "self-blocked-sites", False)
            self.assertEqual(original, target.read_bytes())
            command_delete_block(target, "self-blocked-sites", True)
            ids = [block["id"] for block in load_rules(target)["blocks"]]
            self.assertNotIn("self-blocked-sites", ids)

    def test_url_patterns_and_regex_can_be_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            pattern = "*://example.com/games/*"
            regex = "^https?://(?:www\\.)?example\\.com/play"
            command_update_string_matcher(
                target,
                "self-blocked-sites",
                "targets",
                "url_patterns",
                pattern,
                add=True,
            )
            command_update_url_regex(
                target,
                "self-blocked-sites",
                regex,
                True,
                add=True,
            )
            block = load_rules(target)["blocks"][1]
            self.assertEqual([pattern], block["targets"]["url_patterns"])
            self.assertEqual(
                [{"pattern": regex, "case_sensitive": True}],
                block["targets"]["url_regex"],
            )
            command_update_url_regex(
                target,
                "self-blocked-sites",
                regex,
                True,
                add=False,
            )
            command_update_string_matcher(
                target,
                "self-blocked-sites",
                "targets",
                "url_patterns",
                pattern,
                add=False,
            )
            block = load_rules(target)["blocks"][1]
            self.assertEqual([], block["targets"]["url_patterns"])
            self.assertEqual([], block["targets"]["url_regex"])

    def test_domain_exceptions_can_be_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            command_update_string_matcher(
                target,
                "self-blocked-sites",
                "exceptions",
                "domains",
                "school.twitch.tv",
                add=True,
            )
            block = load_rules(target)["blocks"][1]
            self.assertEqual(["school.twitch.tv"], block["exceptions"]["domains"])
            command_update_string_matcher(
                target,
                "self-blocked-sites",
                "exceptions",
                "domains",
                "school.twitch.tv",
                add=False,
            )
            self.assertEqual(
                [],
                load_rules(target)["blocks"][1]["exceptions"]["domains"],
            )

    def test_schedule_windows_and_timezone_can_be_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            command_add_window(
                target,
                "self-blocked-sites",
                "Europe/Berlin",
                "18:00",
                "20:00",
                "MO,TU,WE,TH,FR",
            )
            command_add_window(
                target,
                "self-blocked-sites",
                "Europe/Berlin",
                "10:00",
                "12:00",
                "SA,SU",
            )
            schedule = load_rules(target)["blocks"][1]["schedule"]
            self.assertEqual(2, len(schedule["windows"]))
            with self.assertRaises(CommandError):
                command_add_window(
                    target,
                    "self-blocked-sites",
                    "UTC",
                    "08:00",
                    "09:00",
                    "MO",
                )
            command_set_schedule_timezone(target, "self-blocked-sites", "UTC")
            self.assertEqual(
                "UTC",
                load_rules(target)["blocks"][1]["schedule"]["timezone"],
            )
            command_remove_window(target, "self-blocked-sites", 2)
            command_remove_window(target, "self-blocked-sites", 1)
            self.assertNotIn("schedule", load_rules(target)["blocks"][1])

    def test_clear_schedule_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            original = target.read_bytes()
            with self.assertRaises(CommandError):
                command_clear_schedule(target, "social-school-hours", False)
            self.assertEqual(original, target.read_bytes())
            command_clear_schedule(target, "social-school-hours", True)
            self.assertNotIn("schedule", load_rules(target)["blocks"][0])

    def test_parent_can_list_and_remove_user_domain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "user-domains.json"
            self.write(
                target,
                {
                    "format_version": 1,
                    "users": {"1001": {"self-blocked-sites": ["example.com"]}},
                },
            )
            target.chmod(0o600)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                command_list_user_domains(target)
            self.assertIn("UID 1001", output.getvalue())
            original = target.read_bytes()
            with self.assertRaises(CommandError):
                command_remove_user_domain(
                    target,
                    1001,
                    "self-blocked-sites",
                    "example.com",
                    False,
                )
            self.assertEqual(original, target.read_bytes())
            command_remove_user_domain(
                target,
                1001,
                "self-blocked-sites",
                "example.com",
                True,
            )
            self.assertEqual({}, json.loads(target.read_text(encoding="utf-8"))["users"])

    def test_symlink_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual, link = root / "actual.json", root / "rules.json"
            self.write(actual, self.example)
            link.symlink_to(actual)
            with self.assertRaises(CommandError):
                write_rules_atomic(link, copy.deepcopy(self.example))

    def test_list_cli_summarizes_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "daemon" / "upcctl.py"),
                    "--rules",
                    str(target),
                    "list",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("self-blocked-sites", result.stdout)
            self.assertIn("block", result.stdout)

    def test_versioning_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rules.json"
            self.write(target, self.example)
            cli = [
                sys.executable,
                str(PROJECT_ROOT / "daemon" / "upcctl.py"),
                "--rules",
                str(target),
            ]
            subprocess.run(
                cli + ["set-profile", "--timezone", "UTC"],
                check=True,
                capture_output=True,
                text=True,
            )
            listing = subprocess.run(
                cli + ["history"],
                check=True,
                capture_output=True,
                text=True,
            )
            version = listing.stdout.split()[0]
            preview = subprocess.run(
                cli + ["rollback", version, "--dry-run"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("Rollback-Vorschau", preview.stdout)
            subprocess.run(
                cli + ["rollback", version, "--yes"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(self.example, load_rules(target))


if __name__ == "__main__":
    unittest.main()
