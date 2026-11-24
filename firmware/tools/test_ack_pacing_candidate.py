"""The pacing candidate must retain r17's exact peers and ACK sweep scope."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import build_imu_software_candidate as runner
import test_master_ab_candidate


class AckPacingCandidateTests(unittest.TestCase):
    def test_only_selected_logger_is_built(self):
        with patch.object(sys, "argv", ["candidate", "--profile", "mixed-diagnostic",
                "--experiment", "adc-ack-pacing", "--validation-scope", "logger",
                "--fixed-bundle", "r17"]):
            args = runner.arguments()
        commands = runner.plan(args, Path("out"))
        self.assertFalse(any(c["name"].startswith("master-") for c in commands))
        builds = [c for c in commands if c["name"].startswith("logger-")]
        self.assertEqual([c["name"] for c in builds], ["logger-clean-ack_pacing", "logger-ack_pacing"])
        self.assertIn("bodaqs_s3_mini_n4r2_imu_adc_ack_pacing", builds[1]["argv"])

    def test_packaging_and_wrong_identity_refusal(self):
        fixture = test_master_ab_candidate.MasterAbCandidate()
        fixture.packaged_fixture(experiment="adc-ack-pacing")
        fixture.packaged_fixture(experiment="adc-ack-pacing", broken="wrong-name")
        fixture.packaged_fixture(experiment="adc-ack-pacing", broken="missing-ack-scope")


if __name__ == "__main__":
    unittest.main()
