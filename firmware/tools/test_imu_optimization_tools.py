"""Admission/readiness refusal and payload window boundary checks."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import sys

import assess_imu_optimization as tool


class OptimizationToolsTests(unittest.TestCase):
    def test_readiness_rejects_primary_only_and_multiple_attempts(self):
        self.assertFalse(tool.serial_membership("BDQ v2 begin streams=1")["ready"])
        self.assertFalse(tool.serial_membership("BDQ v2 begin streams=5\nBDQ v2 begin streams=5")["ready"])
        self.assertTrue(tool.serial_membership("[Storage] BDQ v2 begin streams=5 primaryColumns=0")["ready"])
        self.assertFalse(tool.serial_membership("")["ready"])

    def test_window_excludes_startup_and_exact_end_and_handles_tick_wrap(self):
        start = 0xffff0000
        descriptor = {"stream_id": 34, "acquisition": {
            "payload_schema": "bodaqs.can_imu_packets.v1", "node_address": 0}}
        def packet(offset, order):
            return {"native_tick": (start + offset) & 0xffffffff, "packet_flags": 5,
                    "packet_length": 64, "master_receive_ordinal_high": 0,
                    "master_receive_ordinal_low": order}
        data = [packet(-1, 1), packet(0, 2), packet(999999, 3), packet(1000000, 4)]
        primary = [{"native_tick": start}, {"native_tick": (start + 1000000) & 0xffffffff}]
        with patch.object(tool, "read_bdq", return_value=SimpleNamespace(stream_catalog={"streams": [descriptor]})), \
             patch.object(tool, "iter_bdq_stream_records", side_effect=lambda p, s: iter(primary if s == "primary" else data)):
            result = tool.payload_window(Path("unused"), 1)
        self.assertEqual(result["nodes"][0]["stored_readings"], 10)
        self.assertEqual(result["nodes"][0]["raw_axis_bytes"], 120)

    def test_missing_export_and_reused_output_are_refused_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            case, output = Path(tmp)/"case", Path(tmp)/"report"
            case.mkdir(); (case/"a.bdq").write_bytes(b"captured")
            with self.assertRaisesRegex(ValueError, "missing input"):
                tool.ingest(case, output, [0, 1], "recipe", case/"config", 100)
            self.assertFalse(output.exists())

    def test_actual_invalid_source_descriptor_cannot_match_plan(self):
        # Independently CRC-framed two-node recordings; no mocked assessor.
        tests = Path(__file__).resolve().parents[2] / "analysis/tests"
        sys.path.insert(0, str(tests))
        from test_multi_imu_recording import multi_recording
        with tempfile.TemporaryDirectory() as tmp:
            for invalid in (False, True):
                case = Path(tmp)/str(invalid); case.mkdir()
                path = multi_recording(case, source_override={"node_boot": 0} if invalid else None)
                for name, text in (("serial.txt", "BDQ v2 begin streams=5"),
                                   ("loggercfg.txt", "sample_rate=500"), ("ccs.txt", "{}")):
                    (case/name).write_text(text, encoding="utf-8")
                recipe = tool.read_bdq(path).metadata.get("firmware_recipe_id")
                result = tool.ingest(case, Path(tmp)/("report"+str(invalid)), [0, 1],
                                     recipe, case/"loggercfg.txt", 1)
                self.assertEqual(result["capture_matches_plan"], not invalid)

    def test_pacing_environment_diff_is_only_name_and_spacing(self):
        import configparser
        config = configparser.ConfigParser(interpolation=None)
        config.read(Path(__file__).resolve().parents[1]/"platformio.ini", encoding="utf-8")
        original = config["env:bodaqs_s3_mini_n4r2_imu_adc_ack_sweep"]["build_flags"]
        original = original.replace("${spi_mode_bench.build_flags}", config["spi_mode_bench"]["build_flags"])
        candidate = config["env:bodaqs_s3_mini_n4r2_imu_adc_ack_pacing"]["build_flags"]
        normalize = lambda value: {line.strip() for line in value.splitlines() if line.strip()}
        expected = original.replace("START_SPACING_US=500", "START_SPACING_US=600").replace(
            "bodaqs_a8_imu_adc_ack_sweep_r17", "bodaqs_a8_imu_adc_ack_pacing_r18")
        self.assertEqual(normalize(candidate), normalize(expected))


if __name__ == "__main__":
    unittest.main()
