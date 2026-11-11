"""Logger-only phase instrumentation must preserve the exact r10 peers."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_imu_software_candidate as runner
import test_master_ab_candidate as fixture


class AdcSpiCandidate(unittest.TestCase):
    def test_packages_logger_and_exact_peers_with_failure_refusal(self):
        case=fixture.MasterAbCandidate()
        case.packaged_fixture(experiment="adc-spi-timing")
        for broken in ("missing-logger","wrong-name","wrong-mode"):
            with self.subTest(broken=broken):case.packaged_fixture(experiment="adc-spi-timing",broken=broken)

    def test_logger_only_plan_has_no_ti_build_or_flash(self):
        with patch.object(sys,"argv",["candidate","--profile","mixed-diagnostic","--experiment","adc-spi-timing",
                                     "--validation-scope","logger","--fixed-bundle","fixed"]):args=runner.arguments()
        commands=runner.plan(args,Path("out"));names={c["name"] for c in commands}
        self.assertEqual(names,{"a8-dependencies","restricted-a8-dependencies","firmware-host","candidate-runner-tests",
                                "contract-spi_timing","logger-clean-spi_timing","logger-spi_timing"})
        deps=next(c for c in commands if c["name"]=="restricted-a8-dependencies")
        self.assertIn("bodaqs_s3_mini_n4r2_imu_adc_spi_timing",deps["argv"])

    def test_requires_passed_r10_trace_off_master(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for value in ({"experiment":"spi-disabled-init"},
                          {"status":"passed","candidate_profile":"mixed-diagnostic","experiment":"spi-init-sustained",
                           "variants":{"sustained":{"spi_mode":0,"spi_tx_prime":True,"spi_disabled_init":True,
                                                     "boundary_trace_enabled":True}}}):
                (root/"BUILD_MANIFEST.json").write_text(json.dumps(value))
                with self.assertRaises(ValueError):runner.load_fixed_bundle(root,"adc-spi-timing")


if __name__=="__main__":unittest.main()
