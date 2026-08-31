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


if __name__ == "__main__":
    unittest.main()
