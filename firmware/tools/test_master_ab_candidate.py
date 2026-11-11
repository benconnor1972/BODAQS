"""Shared-runner A/B plan and immutable reused-bundle checks; no device access."""
import hashlib
import contextlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import build_imu_software_candidate as runner


class MasterAbCandidate(unittest.TestCase):
    def packaged_fixture(self,identical=False,experiment="spi-tx-prime-ab",broken=None):
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory);root=temp/"source";root.mkdir()
            docs=root/"docs/firmware";docs.mkdir(parents=True)
            (docs/"CAN-FD_SPI_TX_Priming_Bench.md").write_text("Matched master A/B fixture runbook\n")
            (docs/"CAN-FD_SPI_Mode_Bench.md").write_text("Matched mode0/1 fixture runbook\n")
            (docs/"CAN-FD_SPI_Init_Sustained_Runbook.md").write_text("Sustained fixture runbook\n")
            if experiment in ("spi-boundary-trace","spi-disabled-init"):
                (docs/"CAN-FD_SPI_Boundary_Trace_Runbook.md").write_text("Trace fixture runbook\n")
                (docs/"CAN-FD_SPI_Disabled_Init_Runbook.md").write_text("Disabled init fixture runbook\n")
                for filename in ("firmware/tools/export_spi_trace.js","firmware/can-fd/master/ticlang/MSPM0G3518_XDS110.ccxml"):
                    p=root/filename;p.parent.mkdir(parents=True,exist_ok=True);p.write_text("export fixture\n")
            (root/".gitignore").write_text(".build/\n")
            subprocess.run(["git","init","-q",str(root)],check=True)
            subprocess.run(["git","add","."],cwd=root,check=True)
            subprocess.run(["git","-c","user.name=Fixture","-c","user.email=fixture@example.invalid","commit","-qm","source"],cwd=root,check=True)
            head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
            fixed=temp/"fixed";fixed.mkdir();images={}
            for key,name in (("application","logger.bin"),("unchanged_master","master.out"),("unchanged_node","node.out")):
                path=fixed/name;path.write_bytes(b"bodaqs_a8_imu_adc_trace_r8" if experiment in ("spi-disabled-init","spi-init-sustained") and key=="application" else name.encode())
                images[key]={"path":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
            images["application"]["firmware_name"]="bodaqs_a8_imu_adc_buffers_r5"
            fixed_manifest={"environment":"bodaqs_s3_mini_n4r2_imu_adc_smoke",**images}
            if experiment=="spi-mode-ab":
                fixed_manifest={"status":"passed","experiment":"spi-tx-prime-ab","candidate_profile":"mixed-diagnostic",
                    "source":{"commit":head},
                    "variants":{"B":{**images["unchanged_master"],"spi_tx_prime":True}},
                    "artifacts":[{**images["application"],"role":"logger"},{**images["unchanged_node"],"role":"node"},images["unchanged_master"]],
                    "fixed_bundle":{"firmware_name":"bodaqs_a8_imu_adc_buffers_r5","images":[
                        {"role":"logger","source_commit":head},{"role":"node","source_commit":None}]}}
            if experiment in ("spi-boundary-trace","spi-disabled-init","spi-init-sustained"):
                fixed_manifest={"status":"passed","experiment":"spi-disabled-init" if experiment=="spi-init-sustained" else "spi-boundary-trace" if experiment=="spi-disabled-init" else "spi-mode-ab","candidate_profile":"mixed-diagnostic",
                    "source":{"commit":head},"variants":{"trace" if experiment in ("spi-disabled-init","spi-init-sustained") else "mode0":{"spi_mode":0,"spi_tx_prime":True,"spi_disabled_init":True,
                        "boundary_trace_version":1,"boundary_trace_bytes":7328,"master":images["unchanged_master"],"logger":images["application"]}},
                    "artifacts":[images["application"],{**images["unchanged_node"],"role":"node"},images["unchanged_master"]],
                    "fixed_bundle":{"images":[{"role":"node","source_commit":None}]}}
            (fixed/"BUILD_MANIFEST.json").write_text(json.dumps(fixed_manifest))
            review_text=temp/"review.txt";review_text.write_text("Fixture review evidence\n")
            review=temp/"review.json";review.write_text(json.dumps({"schema":"bodaqs.review.v1","base":head,"head":head,"outcome":"passed",
                "findings":[],"evidence":[{"path":review_text.name,"sha256":hashlib.sha256(review_text.read_bytes()).hexdigest()}]}))
            output=temp/"bundle"
            argv=["candidate","--profile","mixed-diagnostic","--experiment",experiment,"--validation-scope","master" if experiment in ("spi-tx-prime-ab","spi-disabled-init") else "full",
                "--fixed-bundle",str(fixed),"--review-result",str(review),"--review-base",head,"--output-dir",str(output)]
            with patch.object(sys,"argv",argv):args=runner.arguments()
            sdk=temp/"sdk/.metadata";sdk.mkdir(parents=True);(sdk/"product.json").write_text('{"version":"fixture"}')
            args.sdk=sdk.parent
            build=root/".build";build.mkdir();commands=[]
            variants=("sustained",) if experiment=="spi-init-sustained" else ("init-reference","init-disabled") if experiment=="spi-disabled-init" else ("trace",) if experiment=="spi-boundary-trace" else ("mode0","mode1") if experiment=="spi-mode-ab" else ("A","B")
            for variant in variants:
                image=build/(variant+".out");image.write_bytes(b"A" if identical else variant.encode())
                commands.append({"name":"master-"+variant,"argv":[sys.executable,"-c","pass"],"cwd":str(root),
                    "artifacts":[(image.relative_to(root).as_posix(),f"artifacts/master-{variant}/bodaqs_can_master.out")]})
                if experiment=="spi-disabled-init":
                    generated=build/(variant+'.c');generated.write_bytes(b'changed' if broken=="changed-config" and variant=="init-disabled" else b'generated config')
                    commands[-1]["artifacts"].append((generated.relative_to(root).as_posix(),f"artifacts/master-{variant}/generated/ti_msp_dl_config.c"))
                if experiment in ("spi-mode-ab","spi-boundary-trace","spi-init-sustained"):
                    mode=0 if variant in ("trace","sustained") else int(variant[-1]);logger=build/(variant+".bin")
                    logger.write_bytes(b"bodaqs_a8_imu_adc_mode0_r7 bodaqs_a8_imu_adc_mode1_r7" if broken=="identical-logger" else b"unknown" if broken=="wrong-name" else b"bodaqs_a8_imu_adc_sustained_r10" if variant=="sustained" else b"bodaqs_a8_imu_adc_trace_r8" if variant=="trace" else f"bodaqs_a8_imu_adc_{variant}_r7".encode())
                    recipe=build/(variant+".json");recipe.write_text(json.dumps({"id":variant}))
                    commands.append({"name":"contract-"+variant,"argv":[sys.executable,"-c",
                        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])",
                        str(output/f"SPI_SOURCE_CONTRACT_{variant}.json"),json.dumps({"spi_mode":(1-mode) if broken=="wrong-mode" else mode})],"cwd":str(root),"artifacts":[]})
                    commands.append({"name":"logger-"+variant,"argv":[sys.executable,"-c","pass"],"cwd":str(root),
                        "artifacts":([] if broken=="missing-logger" else [(logger.relative_to(root).as_posix(),f"artifacts/logger-{variant}/firmware.bin")])+
                            [(recipe.relative_to(root).as_posix(),f"artifacts/logger-{variant}/identity/build-recipe.json")]})
            boot=temp/"boot.bin";boot.write_bytes(b"boot fixture")
            with patch.object(runner,"ROOT",root),patch.object(runner,"arguments",return_value=args), \
                    patch.object(runner,"preflight",return_value=[]),patch.object(runner,"plan",return_value=commands),patch.object(runner,"boot_app0_path",return_value=boot), \
                    contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                result=runner.main()
            fails=identical or broken is not None
            self.assertEqual(result,1 if fails else 0)
            manifest=json.loads((output/"BUILD_MANIFEST.json").read_text())
            self.assertEqual(manifest["status"],"failed" if fails else "passed")
            self.assertEqual((output/"SOURCE.zip").exists(),not fails)
            self.assertEqual((output/"artifacts/fixed-logger/logger.bin").read_bytes(),b"bodaqs_a8_imu_adc_trace_r8" if experiment in ("spi-disabled-init","spi-init-sustained") else b"logger.bin")
            if not fails and experiment=="spi-init-sustained":
                self.assertTrue(manifest["variants"]["sustained"]["spi_disabled_init"])
                self.assertFalse(manifest["variants"]["sustained"]["boundary_trace_enabled"])
                self.assertEqual((output/"RUNBOOK.md").read_text(),"Sustained fixture runbook\n")
                self.assertFalse((output/"export_spi_trace.js").exists())
            if not fails and experiment=="spi-tx-prime-ab":
                self.assertNotEqual(manifest["variants"]["A"]["sha256"],manifest["variants"]["B"]["sha256"])
                self.assertEqual((output/"RUNBOOK.md").read_text(),"Matched master A/B fixture runbook\n")
            if not fails and experiment=="spi-mode-ab":
                self.assertEqual(manifest["variants"]["mode1"]["spi_mode"],1)
                self.assertEqual((output/"RUNBOOK.md").read_text(),"Matched mode0/1 fixture runbook\n")
            if not fails and experiment=="spi-boundary-trace":
                self.assertEqual(manifest["variants"]["trace"]["boundary_trace_bytes"],7328)
                self.assertEqual((output/"RUNBOOK.md").read_text(),"Trace fixture runbook\n")
                self.assertTrue((output/"export_spi_trace.js").exists())
                self.assertTrue((output/"MASTER_TARGET.ccxml").exists())
            if not fails and experiment=="spi-disabled-init":
                self.assertTrue(manifest["variants"]["trace"]["spi_disabled_init"])
                self.assertFalse(manifest["compatibility_reference"]["spi_disabled_init"])
                self.assertEqual((output/"RUNBOOK.md").read_text(),"Disabled init fixture runbook\n")
            for line in (output/"SHA256SUMS.txt").read_text().splitlines():
                sha,name=line.split("  ",1);self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(),sha)

    def test_public_candidate_packages_matched_images_and_fixed_peers(self):
        self.packaged_fixture()

    def test_identical_ab_images_keep_failed_evidence_without_archive(self):
        self.packaged_fixture(identical=True)

    def test_plan_changes_only_master_priming_and_keeps_existing_affected_suites(self):
        argv=["candidate","--profile","mixed-diagnostic","--experiment","spi-tx-prime-ab",
            "--validation-scope","master","--fixed-bundle","fixed"]
        with patch.object(sys,"argv",argv):args=runner.arguments()
        commands=runner.plan(args,Path("out"))
        names=[c["name"] for c in commands]
        self.assertIn("common-host",names);self.assertIn("master-host",names)
        self.assertNotIn("a8-build",names);self.assertNotIn("node-acquisition",names)
        a=next(c for c in commands if c["name"]=="master-A")
        b=next(c for c in commands if c["name"]=="master-B")
        self.assertEqual([x for x in a["argv"] if not x.startswith("SPI_TX_PRIME=")],
                         [x for x in b["argv"] if not x.startswith("SPI_TX_PRIME=")])
        self.assertIn("SPI_TX_PRIME=0",a["argv"]);self.assertIn("SPI_TX_PRIME=1",b["argv"])
        self.assertIn("SPI_RX_CAPACITY=2",a["argv"])
        self.assertNotEqual(a["artifacts"],b["artifacts"])

    def test_fixed_r5_images_are_hashed_and_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);images={}
            for key,name in (("application","logger/firmware.bin"),("unchanged_master","master/master.out"),("unchanged_node","node/node.out")):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
                images[key]={"path":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
            images["application"]["firmware_name"]="bodaqs_a8_imu_adc_buffers_r5"
            manifest={"source_commit":"a"*40,"environment":"bodaqs_s3_mini_n4r2_imu_adc_smoke",**images}
            (root/"BUILD_MANIFEST.json").write_text(json.dumps(manifest))
            result=runner.load_fixed_bundle(root)
            self.assertEqual({i["role"] for i in result["images"]},{"logger","node","rollback-master"})
            (root/"logger/firmware.bin").write_bytes(b"wrong image")
            with self.assertRaises(ValueError):runner.load_fixed_bundle(root)
            manifest["application"]["path"]="../escape.bin"
            (root/"BUILD_MANIFEST.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):runner.load_fixed_bundle(root)


if __name__=="__main__":unittest.main()
