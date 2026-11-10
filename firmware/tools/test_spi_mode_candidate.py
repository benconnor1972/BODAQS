"""Mode trial checks actual board selection and matched candidate commands."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_imu_software_candidate as runner
import collect_spi_contract
from test_master_ab_candidate import MasterAbCandidate


class SpiModeCandidate(unittest.TestCase):
    def test_mode1_logger_cannot_escape_the_explicit_mixed_build(self):
        root = Path(__file__).resolve().parents[1]
        compiler = "C:/msys64/ucrt64/bin/g++.exe" if sys.platform == "win32" else "g++"
        for flags in (("-DBODAQS_CAN_SPI_BENCH_MODE=2",),
                ("-DBODAQS_CAN_SPI_BENCH_MODE=1","-DBODAQS_SPI_MEASUREMENT_V2=1"),
                ("-DBODAQS_CAN_SPI_BENCH_MODE=1","-DBODAQS_SPI_MEASUREMENT_V2=0","-DBODAQS_SINGLE_NODE_IMU_ADC_SMOKE=1")):
            result = subprocess.run([compiler,"-std=c++20","-fsyntax-only",*flags,
                "-I",str(root/"test/stubs"),"-I",str(root/"src"),str(root/"src/BoardProfile.cpp")],capture_output=True)
            self.assertNotEqual(result.returncode,0)

    def test_public_packaging_requires_both_endpoint_images_and_correct_modes(self):
        fixture = MasterAbCandidate()
        fixture.packaged_fixture(experiment="spi-mode-ab")
        fixture.packaged_fixture(experiment="spi-mode-ab",identical=True)
        for broken in ("identical-logger","missing-logger","wrong-mode"):
            with self.subTest(broken=broken):
                fixture.packaged_fixture(experiment="spi-mode-ab",broken=broken)

    def test_compiled_board_table_selects_only_can_phase(self):
        default = collect_spi_contract.collect("C:/msys64/ucrt64/bin/g++.exe" if sys.platform == "win32" else "g++")
        for mode in (0, 1):
            selected = collect_spi_contract.collect("C:/msys64/ucrt64/bin/g++.exe" if sys.platform == "win32" else "g++", mode=mode)
            self.assertEqual(selected["spi_mode"], mode)
            for key in ("pins", "legacy_master_hz", "adc_hz"):
                self.assertEqual(selected[key], default[key])

    def test_phase_pair_keeps_priming_and_builds_both_endpoints(self):
        with patch.object(sys, "argv", ["candidate", "--profile", "mixed-diagnostic",
                "--experiment", "spi-mode-ab", "--fixed-bundle", "fixed"]):
            args = runner.arguments()
        commands = runner.plan(args, Path("out"))
        names = [c["name"] for c in commands]
        for required in ("firmware-host", "common-host", "master-host", "analysis", "candidate-runner-tests"):
            self.assertIn(required, names)
        self.assertNotIn("node-acquisition", names)
        for mode in (0, 1):
            master = next(c for c in commands if c["name"] == f"master-mode{mode}")
            self.assertIn("SPI_TX_PRIME=1", master["argv"])
            self.assertIn(f"SPI_BENCH_MODE={mode}", master["argv"])
            self.assertIn("SPI_RX_CAPACITY=2", master["argv"])
            logger = next(c for c in commands if c["name"] == f"logger-mode{mode}")
            self.assertIn(f"bodaqs_s3_mini_n4r2_imu_adc_mode{mode}", logger["argv"])
            self.assertTrue(any(dest.endswith("firmware.bin") for _, dest in logger["artifacts"]))
            self.assertTrue(any(dest.endswith("identity/build-recipe.json") for _, dest in logger["artifacts"]))
        a = next(c for c in commands if c["name"] == "master-mode0")
        b = next(c for c in commands if c["name"] == "master-mode1")
        self.assertEqual([x for x in a["argv"] if not x.startswith("SPI_BENCH_MODE=")],
                         [x for x in b["argv"] if not x.startswith("SPI_BENCH_MODE=")])

    def test_r6_rollback_is_exact_primed_master(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = []
            for role, name in (("logger", "logger.bin"), ("node", "node.out"), ("master-B", "B.out")):
                path = root / name
                path.write_bytes(role.encode())
                artifacts.append({"path": name, "sha256": runner.sha256(path), "role": role})
            artifacts[-1].pop("role")
            manifest = {"status": "passed", "experiment": "spi-tx-prime-ab", "candidate_profile": "mixed-diagnostic",
                        "source": {"commit": "a"*40}, "artifacts": artifacts,
                        "variants": {"B": {"spi_tx_prime": True, "path": "B.out", "sha256": runner.sha256(root/"B.out")}},
                        "fixed_bundle": {"firmware_name": "bodaqs_a8_imu_adc_buffers_r5", "images": [
                            {"role": "logger", "source_commit": "b"*40}, {"role": "node", "source_commit": None}]}}
            (root/"BUILD_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            fixed = runner.load_fixed_bundle(root)
            rollback = next(i for i in fixed["images"] if i["role"] == "rollback-master")
            self.assertEqual(rollback["path"], "B.out")
            self.assertEqual(rollback["source_commit"], "a"*40)
            self.assertIsNone(next(i for i in fixed["images"] if i["role"] == "node")["source_commit"])
            (root/"B.out").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                runner.load_fixed_bundle(root)


if __name__ == "__main__":
    unittest.main()
