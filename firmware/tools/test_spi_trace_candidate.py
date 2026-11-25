"""Matched trace bundle and read-only exporter checks; no devices."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_imu_software_candidate as runner
import test_master_ab_candidate as ab_fixture


class SpiTraceCandidate(unittest.TestCase):
    def test_packaging_matched_pair_and_broken_inputs(self):
        fixture=ab_fixture.MasterAbCandidate()
        fixture.packaged_fixture(experiment="spi-boundary-trace")
        for broken in ("missing-logger","wrong-name","wrong-mode"):
            with self.subTest(broken=broken):fixture.packaged_fixture(experiment="spi-boundary-trace",broken=broken)

    def test_explicit_full_pair_plan(self):
        with patch.object(sys,"argv",["candidate","--profile","mixed-diagnostic","--experiment","spi-boundary-trace","--fixed-bundle","fixed"]):
            args=runner.arguments()
        commands=runner.plan(args,Path("out"))
        master=next(c for c in commands if c["name"]=="master-trace")
        self.assertTrue({"SPI_BOUNDARY_TRACE=1","SPI_TX_PRIME=1","SPI_BENCH_MODE=0","SPI_RX_CAPACITY=2"}.issubset(master["argv"]))
        self.assertIn("bodaqs_s3_mini_n4r2_imu_adc_trace",next(c for c in commands if c["name"]=="logger-trace")["argv"])
        self.assertFalse(any(c["name"].startswith("node-acquisition") for c in commands))

    def test_old_bundles_cannot_be_mislabeled_as_r7_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            for experiment in ("spi-tx-prime-ab",None):
                (path/"BUILD_MANIFEST.json").write_text(json.dumps({"experiment":experiment}))
                with self.assertRaisesRegex(ValueError,"r7"):runner.load_fixed_bundle(path,"spi-boundary-trace")

    def test_exporter_execution_has_no_device_api(self):
        node=shutil.which("node")
        self.assertIsNotNone(node,"Node is required for the CCS exporter regression")
        subprocess.run([node,str(Path(__file__).with_name("test_spi_trace_export.js"))],check=True)


if __name__=="__main__":unittest.main()
