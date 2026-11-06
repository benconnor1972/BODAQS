"""Worked examples at the public workload-to-capacity report boundary."""
import unittest
import tempfile
from pathlib import Path

from drain_capacity import bench_accounting, evaluate, build_report


class CapacityReportTests(unittest.TestCase):
    def test_bus_ownership_limit_and_useful_drain_remain_separate_gates(self):
        report = evaluate({"nodes": 1}, {"exchange_us": 200, "mutex_hold_us": 101})
        self.assertIn("mutex_hold", report["failed_gates"])
        report = evaluate({"nodes": 4}, {"exchange_us": 147.3375733855186})
        self.assertLess(report["concurrent_drain_ratio"], 1.25)

    def test_reproducible_report_checks_baseline_and_holds_dependents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_bytes(b"abc")
            config = {"baseline": {"files": {"source.txt":
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}},
                "scenarios": {"measured": {"exchange_us": 147.3375733855186}},
                "workloads": {"four": {"nodes": 4}}}
            report = build_report(config, root)
            self.assertEqual(report, build_report(config, root))
            self.assertEqual(report["frontier_decision"], "no-go")
            self.assertFalse(report["dependents_may_start"])
            (root / "source.txt").write_bytes(b"abd")
            with self.assertRaises(ValueError):
                build_report(config, root)

    def test_wire_floor_is_separate_from_measured_failure_and_thresholds(self):
        report = evaluate({"nodes": 4}, {"exchange_us": 64, "encode_us": 0,
            "master_request_us": 0, "retirement_us": 0, "publication_us": 0,
            "master_can_us": 0, "master_batch_us": 0,
            "storage_encode_us_per_byte": 0, "logger_background_fraction": 0})
        self.assertAlmostEqual(report["sample_only_catchup_wire_fraction"], .426624)
        self.assertEqual(report["decision"], "conditional")
        self.assertFalse(report["production_admitted"])
        # Worked CAN boundary:744.6normal frames/s and196.25us/frame.
        below = evaluate({"nodes": 1, "can_burst_frames": 2822}, {"exchange_us": 100})
        above = evaluate({"nodes": 1, "can_burst_frames": 2823}, {"exchange_us": 100})
        self.assertNotIn("can", below["failed_gates"])
        self.assertIn("can", above["failed_gates"])
        # One-node catch-up2629.926923slots/s:323us fits,324us fails85%.
        below = evaluate({"nodes": 1}, {"exchange_us": 64, "encode_us": 259})
        above = evaluate({"nodes": 1}, {"exchange_us": 64, "encode_us": 260})
        self.assertNotIn("catchup_spi", below["failed_gates"])
        self.assertIn("catchup_spi", above["failed_gates"])

    def test_invalid_or_unknown_inputs_cannot_fabricate_admission(self):
        for workload, costs in [({"nodes": 0}, {"exchange_us": 100}),
                                ({"nodes": 5}, {"exchange_us": 100}),
                                ({"nodes": 1, "batch_records": 14}, {"exchange_us": 100}),
                                ({"nodes": 1}, {"exchange_us": float("nan")}),
                                ({"nodes": 1}, {"exchange_us": 63}),
                                ({"nodes": 1, "adc_workers_sps": [-1]}, {"exchange_us": 100})]:
            with self.subTest(workload=workload, costs=costs):
                with self.assertRaises(ValueError):
                    evaluate(workload, costs)

    def test_all_banks_buffer_coverage_persistence_and_burst_gates_are_reported(self):
        report = evaluate({"nodes": 4, "logger_free_bytes": 1024,
                           "storage_bytes_s": 1000}, {"exchange_us": 100})
        # Independent storage geometry: 100ms arrivals(67 packets), node
        # 50ms backlog(34), selected13, two in flight and four burst =120.
        self.assertEqual(report["memory"]["master_packets_per_node_required"], 120)
        self.assertEqual(report["memory"]["node_packets_required"], 50)
        self.assertIn("logger_memory", report["failed_gates"])
        self.assertIn("persistence", report["failed_gates"])
        self.assertEqual(set(report["memory"]["master_banks"]), {"BANK0", "BANK1"})
        self.assertGreater(report["persistence_bytes_s"], 160000)
        self.assertGreater(report["spi_burst_recovery_us"], 0)
        self.assertGreater(report["can_fraction"], .52)

    def test_request_capacity_and_encoding_can_fail_a_wire_time_pass(self):
        report = evaluate({"nodes": 4}, {
            "exchange_us": 64, "encode_us": 20, "master_request_us": 609,
            "retirement_us": 10, "publication_us": 10,
        })
        self.assertGreater(report["request_interval_us"], 680)
        self.assertGreater(report["request_capacity_fraction"], 1)
        self.assertIn("request_capacity", report["failed_gates"])
        self.assertEqual(report["decision"], "no-go")

    def test_partials_and_one_selected_head_keep_publication_cost_visible(self):
        full = evaluate({"nodes": 1}, {"exchange_us": 100})
        partial = evaluate({"nodes": 1, "batch_records": 1}, {"exchange_us": 100})
        # One record seals96bytes -> three40byte fragments, not two.
        self.assertAlmostEqual(partial["sample_fragments_s"], 1999.8)
        self.assertAlmostEqual(full["selected_batches_s"], 51.27692307692308)
        self.assertGreater(partial["sample_slots_s"], partial["sample_fragments_s"])
        self.assertEqual(full["selected_batches_per_node"], 1)
        self.assertGreater(partial["delivery_estimate_us"], 20000)

    def test_shared_bus_charges_adc_workers_and_mandatory_deadlines(self):
        report = evaluate({"nodes": 1, "adc_workers_sps": [2000, 2000]},
                          {"exchange_us": 147.3375733855186})
        # Each conversion sends WREG(5), START(1), RDATA(4) bytes at1MHz.
        # Two2000sps workers need320ms wire, irrespective of logger row rate.
        self.assertAlmostEqual(report["adc_wire_fraction"], .32)
        self.assertEqual(report["authorization_frames_s"], 4)
        self.assertEqual(report["authorization_horizon_s"], 5)
        self.assertGreater(report["auxiliary_slots_s"], 100)
        self.assertGreater(report["catchup_spi_fraction"],
                           report["catchup_sample_exchange_fraction"] + .32)

    def test_four_nodes_cannot_catch_up_at_observed_exchange_cost(self):
        report = evaluate({"nodes": 4}, {"exchange_us": 147.3375733855186})
        # 13 CAN records/batch, five samples/record, 1008 bytes/batch,
        # 40 bytes/fragment -> 26 fragments, 205.107692 batches/s.
        self.assertAlmostEqual(report["sample_fragments_s"], 5332.8)
        self.assertAlmostEqual(report["catchup_sample_fragments_s"], 6666.0)
        self.assertGreater(report["catchup_sample_exchange_fraction"], .982)
        self.assertEqual(report["decision"], "no-go")
        self.assertFalse(report["production_admitted"])

    def test_frozen_failure_conserves_records_without_claiming_steady_state(self):
        # Debugger snapshot for context 10547103591045405970: independent
        # receipt/retirement counters, not rates inferred from the BDQ prefix.
        report = bench_accounting({
            "elapsed_us": 430963, "retained_frames": 269,
            "data_acked_records": [128, 12], "ingress_depth": [128, 0, 0, 0],
            "data_records": [128, 13], "data_objects": [12, 13],
            "calls": [900, 900, 240], "polls": [280, 63, 137, 210, 75],
            "acks": [24, 25, 2, 30, 4], "fragments": [273, 50, 6, 60, 4],
            "data_unique_fragments": [256, 37],
        })
        self.assertEqual(report["retained_records"], 129)
        self.assertEqual(report["selected_records"], 1)
        self.assertEqual(report["non_data_polls"], 422)
        self.assertEqual(report["unclassified_requests"], 50)
        self.assertEqual(report["repeated_sample_fragments"], 17)
        self.assertFalse(report["steady_state_evidence"])


if __name__ == "__main__":
    unittest.main()
