"""Duration candidate preserves r9 control and turns off boundary tracing only."""
import hashlib
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

    def test_reused_logger_keeps_original_source_and_requires_unique_hash_join(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);images={}
            for role in ("logger","master","node"):
                p=root/(role+".bin");p.write_bytes(role.encode())
                images[role]={"path":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
            original={"role":"logger","sha256":images["logger"]["sha256"],"source_commit":"b"*40}
            m={"status":"passed","candidate_profile":"mixed-diagnostic","experiment":"spi-disabled-init",
               "source":{"commit":"a"*40},"variants":{"trace":{"spi_mode":0,"spi_tx_prime":True,
               "spi_disabled_init":True,"boundary_trace_version":1,"boundary_trace_bytes":7328,
               "master":images["master"],"logger":images["logger"]}},
               "artifacts":[images["logger"],images["master"],{**images["node"],"role":"node"}],
               "fixed_bundle":{"images":[]}}
            for logger_sources in ([original],[],[original,original],[{**original,"sha256":"0"*64}]):
                m["fixed_bundle"]["images"]=[{"role":"node","source_commit":None},*logger_sources]
                (root/"BUILD_MANIFEST.json").write_text(json.dumps(m))
                if logger_sources==[original]:
                    value=runner.load_fixed_bundle(root,"spi-init-sustained")
                    self.assertEqual(next(i["source_commit"] for i in value["images"] if i["role"]=="logger"),"b"*40)
                else:
                    with self.assertRaisesRegex(ValueError,"logger provenance"):
                        runner.load_fixed_bundle(root,"spi-init-sustained")


if __name__=="__main__":unittest.main()
