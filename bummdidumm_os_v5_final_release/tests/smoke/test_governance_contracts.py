import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).parent.parent.parent.parent
RELEASE_DIR = REPO_ROOT / "bummdidumm_os_v5_final_release"


class TestAuditNoArtifactsByDefault(unittest.TestCase):
    def test_default_run_writes_no_files(self):
        """release_audit.py default run must not write files to the repo tree."""
        audit_json = RELEASE_DIR / "release_audit.json"
        self_audit_md = RELEASE_DIR / "SELF_AUDIT.md"
        audit_json.unlink(missing_ok=True)
        self_audit_md.unlink(missing_ok=True)

        env = os.environ.copy()
        env.pop("WRITE_AUDIT_ARTIFACTS", None)
        subprocess.run(
            [sys.executable, str(RELEASE_DIR / "release_audit.py")],
            cwd=str(REPO_ROOT),
            env=env,
            check=False,
        )

        self.assertFalse(audit_json.exists(), "release_audit.json must not be written by default run")
        self.assertFalse(self_audit_md.exists(), "SELF_AUDIT.md must not be written by default run")

    def test_explicit_flag_writes_files(self):
        """WRITE_AUDIT_ARTIFACTS=1 must produce artifact files."""
        audit_json = RELEASE_DIR / "release_audit.json"
        self_audit_md = RELEASE_DIR / "SELF_AUDIT.md"
        audit_json.unlink(missing_ok=True)
        self_audit_md.unlink(missing_ok=True)

        env = os.environ.copy()
        env["WRITE_AUDIT_ARTIFACTS"] = "1"
        subprocess.run(
            [sys.executable, str(RELEASE_DIR / "release_audit.py")],
            cwd=str(REPO_ROOT),
            env=env,
            check=False,
        )

        self.assertTrue(audit_json.exists(), "release_audit.json must be written when WRITE_AUDIT_ARTIFACTS=1")
        self.assertTrue(self_audit_md.exists(), "SELF_AUDIT.md must be written when WRITE_AUDIT_ARTIFACTS=1")
        # Cleanup
        audit_json.unlink(missing_ok=True)
        self_audit_md.unlink(missing_ok=True)


class TestSafeSortCloudRunFailFast(unittest.TestCase):
    def test_fails_fast_without_brain_index_root(self):
        """main_safe_sort.run_safe_sort() must raise RuntimeError in Cloud Run without BRAIN_INDEX_ROOT."""
        import main_safe_sort

        saved_k = os.environ.get("K_SERVICE")
        saved_root = os.environ.get("BRAIN_INDEX_ROOT")
        try:
            os.environ["K_SERVICE"] = "bummdidumm-safe-sort"
            os.environ.pop("BRAIN_INDEX_ROOT", None)
            with self.assertRaises(RuntimeError, msg="Must fail-fast in Cloud Run without BRAIN_INDEX_ROOT"):
                main_safe_sort.run_safe_sort()
        finally:
            if saved_k is not None:
                os.environ["K_SERVICE"] = saved_k
            else:
                os.environ.pop("K_SERVICE", None)
            if saved_root is not None:
                os.environ["BRAIN_INDEX_ROOT"] = saved_root

    def test_does_not_fail_fast_with_brain_index_root(self):
        """run_safe_sort() must not raise RuntimeError when BRAIN_INDEX_ROOT is set."""
        import main_safe_sort

        saved_k = os.environ.get("K_SERVICE")
        saved_root = os.environ.get("BRAIN_INDEX_ROOT")
        try:
            os.environ["K_SERVICE"] = "bummdidumm-safe-sort"
            os.environ["BRAIN_INDEX_ROOT"] = "/tmp/brain_index_test"
            # Should NOT raise RuntimeError from the Cloud Run guard;
            # will raise ValueError (missing CONTROL_SHEET_ID) or similar — that's fine.
            try:
                main_safe_sort.run_safe_sort()
            except RuntimeError as exc:
                self.fail(f"run_safe_sort raised RuntimeError despite BRAIN_INDEX_ROOT being set: {exc}")
            except Exception:
                pass  # other errors (missing sheet etc.) are expected in test env
        finally:
            if saved_k is not None:
                os.environ["K_SERVICE"] = saved_k
            else:
                os.environ.pop("K_SERVICE", None)
            if saved_root is not None:
                os.environ["BRAIN_INDEX_ROOT"] = saved_root
            else:
                os.environ.pop("BRAIN_INDEX_ROOT", None)


class TestDeployShContracts(unittest.TestCase):
    def setUp(self):
        self.deploy_text = (RELEASE_DIR / "deploy.sh").read_text(encoding="utf-8")

    def test_no_plaintext_api_key_via_set_env_vars(self):
        """deploy.sh must not pass API_KEY values via --set-env-vars."""
        for line in self.deploy_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertFalse(
                "--set-env-vars" in stripped and "API_KEY" in stripped,
                f"Plaintext API_KEY found in --set-env-vars: {stripped!r}",
            )

    def test_secret_manager_integration_present(self):
        """deploy.sh must use --set-secrets for GEMINI_API_KEY."""
        self.assertIn("--set-secrets", self.deploy_text, "deploy.sh must contain --set-secrets")
        self.assertIn(
            "GEMINI_API_KEY=projects/",
            self.deploy_text,
            "deploy.sh must pass GEMINI_API_KEY via projects/ Secret Manager path",
        )

    def test_brain_index_root_fail_fast(self):
        """: "${BRAIN_INDEX_ROOT:?...}" fail-fast must be present in deploy.sh."""
        self.assertIn(': "${BRAIN_INDEX_ROOT:?', self.deploy_text)

    def test_sa_email_fail_fast(self):
        """: "${SA_EMAIL:?...}" fail-fast must be present in deploy.sh."""
        self.assertIn(': "${SA_EMAIL:?', self.deploy_text)

    def test_volume_mount_for_pass2_and_safe_sort(self):
        """Both pass2 and safe-sort jobs must declare the brain-index volume mount."""
        self.assertIn("bummdidumm-pass2-ocr-index", self.deploy_text)
        self.assertIn("bummdidumm-safe-sort", self.deploy_text)
        self.assertEqual(
            self.deploy_text.count("add-volume-mount"),
            2,
            "Exactly two --add-volume-mount entries expected (pass2 and safe-sort)",
        )


class TestGitignoreCoversArtifacts(unittest.TestCase):
    def setUp(self):
        self.gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    def test_review_output_md_ignored(self):
        self.assertIn("REVIEW_OUTPUT.md", self.gitignore)

    def test_brain_index_ignored(self):
        self.assertIn("brain_index/", self.gitignore)

    def test_audit_artifacts_ignored(self):
        self.assertIn("release_audit.json", self.gitignore)
        self.assertIn("SELF_AUDIT.md", self.gitignore)

    def test_tool_caches_ignored(self):
        self.assertIn(".pytest_cache/", self.gitignore)
        self.assertIn(".mypy_cache/", self.gitignore)
        self.assertIn(".ruff_cache/", self.gitignore)


if __name__ == "__main__":
    unittest.main()
