from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CiWorkflowTests(unittest.TestCase):
    def test_installer_job_installs_pkexec_before_integration_test(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        installer_job = workflow[workflow.index("  installer-and-build:") :]

        update = installer_job.index("sudo apt-get update")
        install = installer_job.index(
            "sudo apt-get install --no-install-recommends --yes pkexec"
        )
        integration_test = installer_job.index("run: bash tests/test-installer.sh")

        self.assertLess(update, install)
        self.assertLess(install, integration_test)

    def test_actions_are_pinned_to_reviewed_v7_commits(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        expected = {
            "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
            "actions/setup-node": "820762786026740c76f36085b0efc47a31fe5020",
            "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
            "actions/upload-artifact": "bbbca2ddaa5d8feaa63e36b76fdaad77386f024f",
        }
        for action, sha in expected.items():
            self.assertIn(f"uses: {action}@{sha} # v7.0.0", workflow)


if __name__ == "__main__":
    unittest.main()
