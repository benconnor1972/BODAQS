"""Duration candidate preserves r9 control and turns off boundary tracing only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_imu_software_candidate as runner
import test_master_ab_candidate as fixture


class SustainedCandidate(unittest.TestCase):
    def test_packages_matched_pair_and_rejects_broken_logger(self):
        case=fixture.MasterAbCandidate()
        case.packaged_fixture(experiment="spi-init-sustained")
        for broken in ("missing-logger","wrong-name","wrong-mode"):
            with self.subTest(broken=broken):
                case.packaged_fixture(experiment="spi-init-sustained",broken=broken)

    def test_full_plan_preserves_r9_flags_and_disables_trace(self):
        with patch.object(sys,"argv",["candidate","--profile","mixed-diagnostic","--experiment",
                                     "spi-init-sustained","--fixed-bundle","fixed"]):
            args=runner.arguments()
        commands=runner.plan(args,Path("out"))
        master=next(c for c in commands if c["name"]=="master-sustained")
        self.assertTrue({"SPI_TX_PRIME=1","SPI_BENCH_MODE=0","SPI_RX_CAPACITY=2","SPI_PHASE_TIMING=1",
                         "SPI_QUEUE_TIMING=1","SPI_DISABLED_INIT=1","SPI_BOUNDARY_TRACE=0"}.issubset(master["argv"]))
        names={c["name"] for c in commands}
        self.assertTrue({"firmware-host","common-host","master-host","node-host","analysis",
                         "integrated-first-recording","candidate-runner-tests"}.issubset(names))
        self.assertFalse(any(n.startswith("node-acquisition") for n in names))
        logger=next(c for c in commands if c["name"]=="logger-sustained")
        self.assertIn("bodaqs_s3_mini_n4r2_imu_adc_sustained",logger["argv"])

    def test_requires_r9_parent_with_disabled_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for value in ({"experiment":"spi-boundary-trace"},
                          {"status":"passed","candidate_profile":"mixed-diagnostic","experiment":"spi-disabled-init",
                           "variants":{"trace":{"spi_mode":0,"spi_tx_prime":True,"spi_disabled_init":False,
                                                "boundary_trace_version":1,"boundary_trace_bytes":7328}}}):
                (root/"BUILD_MANIFEST.json").write_text(json.dumps(value))
                with self.assertRaises(ValueError):runner.load_fixed_bundle(root,"spi-init-sustained")


if __name__=="__main__":unittest.main()
