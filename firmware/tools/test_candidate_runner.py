"""Check validation/packaging boundaries without compilers or devices."""
import contextlib
import ast
import importlib.metadata
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
from unittest.mock import patch
import zipfile

import build_imu_software_candidate as runner


class CandidateRunnerTests(unittest.TestCase):
    def test_preflight_covers_pinned_direct_analysis_imports(self):
        roots = set()
        for folder in (runner.ROOT / "analysis/bodaqs_analysis", runner.ROOT / "analysis/tests"):
            for path in folder.rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                    if isinstance(node, ast.Import):
                        roots.update(name.name.split(".")[0] for name in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        roots.add(node.module.split(".")[0])
        distributions = importlib.metadata.packages_distributions()
        imported = {dist.lower() for name in roots for dist in distributions.get(name, [])}
        pinned = {line.split("==")[0].lower() for line in
                  (runner.ROOT / "requirements.txt").read_text().splitlines() if "==" in line}
        self.assertFalse((imported & pinned) - {name.lower() for name in runner.TEST_IMPORTS})

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

    def test_common_host_uses_selected_c_compiler_and_python(self):
        args = self.arguments("host", Path("unused"))
        args.cc = "selected/path/gcc"
        common = next(step for step in runner.plan(args, Path("unused")) if step["name"] == "common-host")
        self.assertIn("CC=selected/path/gcc", common["argv"])
        self.assertIn(f"PYTHON={Path(sys.executable).as_posix()}", common["argv"])

    def test_failed_preflight_creates_no_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            args = self.arguments("preflight", output)
            with patch.object(runner, "arguments", return_value=args), \
                    patch.object(runner, "preflight", side_effect=RuntimeError("missing SDK")), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner.main(), 1)
            self.assertFalse(output.exists())

    def run_bundle(self, exit_code, mode="candidate", archive_failure=False, late_change=False):
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
            run = subprocess.run
            def run_external(argv, *positional, **keywords):
                if argv[:2] == ["git", "archive"] and archive_failure:
                    (output / "SOURCE.zip").write_bytes(b"partial archive")
                    raise subprocess.CalledProcessError(2, argv)
                result = run(argv, *positional, **keywords)
                if argv[:2] == ["git", "archive"] and late_change:
                    (root / "input.txt").write_bytes(b"late writer\n")
                return result
            expected_success = exit_code == 0 and not archive_failure and not late_change
            with patch.object(runner, "ROOT", root), patch.object(runner, "arguments", return_value=args), \
                    patch.object(runner, "preflight", return_value=[]), \
                    patch.object(runner, "plan", return_value=[command]), \
                    patch.object(runner.subprocess, "run", side_effect=run_external), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner.main(), 0 if expected_success else 1)
            manifest = json.loads((output / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "passed" if expected_success else "failed")
            self.assertEqual((output / "SOURCE.zip").exists(), expected_success and mode == "candidate")
            if expected_success and mode == "candidate":
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

    def test_failed_archive_is_removed_but_failure_evidence_survives(self):
        self.run_bundle(0, archive_failure=True)

    def test_source_change_after_archive_removes_candidate_archive(self):
        self.run_bundle(0, late_change=True)

    def test_preflight_rejects_python_without_test_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            venv.EnvBuilder(with_pip=False).create(temp)
            python = Path(temp) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            args = self.arguments("host")
            with patch.object(runner.sys, "executable", str(python)):
                with self.assertRaisesRegex(RuntimeError, "Python dependencies"):
                    runner.preflight(args)

    def test_preflight_rejects_wrong_dependency_version_before_import(self):
        with tempfile.TemporaryDirectory() as temp:
            venv.EnvBuilder(with_pip=False).create(temp)
            python = Path(temp) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            subprocess.run([str(python), "-c", "import sysconfig; from pathlib import Path; "
                "p=Path(sysconfig.get_path('purelib'))/'pytest-0.0.dist-info'; p.mkdir(); "
                "(p/'METADATA').write_text('Name: pytest\\nVersion: 0.0\\n')"], check=True)
            args = self.arguments("host")
            with patch.object(runner.sys, "executable", str(python)):
                with self.assertRaisesRegex(RuntimeError, "pytest: expected.*found 0.0"):
                    runner.preflight(args)


if __name__ == "__main__":
    unittest.main()
