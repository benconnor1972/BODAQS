"""Check validation/packaging boundaries without compilers or devices."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import build_imu_software_candidate as runner


class CandidateRunnerTests(unittest.TestCase):
    def arguments(self, mode, output=None):
        argv = ["candidate", "--mode", mode]
        if output:
            argv += ["--output-dir", str(output)]
        with patch.object(sys, "argv", argv):
            return runner.arguments()

    def test_preflight_needs_no_output_directory(self):
        args = self.arguments("preflight")
        self.assertIsNone(args.output_dir)

    def test_host_plan_contains_existing_suites_without_target_builds(self):
        args = self.arguments("host", Path("unused"))
        names = [step["name"] for step in runner.plan(args, Path("unused"))]
        self.assertIn("firmware-host", names)
        self.assertIn("master-host", names)
        self.assertIn("analysis", names)
        self.assertNotIn("a8-build", names)
        self.assertNotIn("node-acquisition", names)

    def test_failed_preflight_creates_no_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            args = self.arguments("preflight", output)
            with patch.object(runner, "arguments", return_value=args), \
                    patch.object(runner, "preflight", side_effect=RuntimeError("missing SDK")), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner.main(), 1)
            self.assertFalse(output.exists())

    def run_bundle(self, exit_code, mode="candidate"):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
            subprocess.run(["git", "config", "core.eol", "lf"], cwd=root, check=True)
            (root / "input.txt").write_bytes(b"known source\n")
            subprocess.run(["git", "add", "input.txt"], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "-qm", "source"], cwd=root, check=True)
            output = Path(temp) / "bundle"
            args = self.arguments(mode, output)
            sdk = Path(temp) / "sdk/.metadata"
            sdk.mkdir(parents=True)
            (sdk / "product.json").write_text('{"version":"fixture"}', encoding="utf-8")
            args.sdk = sdk.parent
            if mode == "host":
                args.sdk = Path(temp) / "missing-sdk"
                (root / "input.txt").write_bytes(b"working edits\n")
            command = {"name": "validation", "argv": [sys.executable, "-c", f"raise SystemExit({exit_code})"],
                       "cwd": str(root), "artifacts": []}
            with patch.object(runner, "ROOT", root), patch.object(runner, "arguments", return_value=args), \
                    patch.object(runner, "preflight", return_value=[]), \
                    patch.object(runner, "plan", return_value=[command]), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner.main(), 0 if exit_code == 0 else 1)
            manifest = json.loads((output / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "passed" if exit_code == 0 else "failed")
            self.assertEqual((output / "SOURCE.zip").exists(), exit_code == 0 and mode == "candidate")
            if exit_code == 0 and mode == "candidate":
                with zipfile.ZipFile(output / "SOURCE.zip") as archive:
                    self.assertEqual(archive.read("input.txt"), b"known source\n")
            for line in (output / "SHA256SUMS.txt").read_text().splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)

    def test_failed_validation_retains_logs_without_archiving_source(self):
        self.run_bundle(7)

    def test_successful_validation_archives_exact_source_and_checksums(self):
        self.run_bundle(0)

    def test_host_validation_allows_edits_and_needs_no_sdk_or_archive(self):
        self.run_bundle(0, mode="host")


if __name__ == "__main__":
    unittest.main()
