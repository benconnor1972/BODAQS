"""Public offline tool contracts; no mocked acceptance, tools or device access."""
import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import bench
from bench_profiles import PROFILES, review_result
from build_identity import identity
from bodaqs_analysis.bench_snapshot import BASE,PHASE,QUEUE,V5,RUNTIME
import build_imu_software_candidate as runner


class BenchTools(unittest.TestCase):
    def test_operator_packet_hashes_inputs_and_public_gate_stays_closed(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);artifacts=[]
            for name in ("a8/firmware.bin","master-acquisition/master.out","node-acquisition/node.out"):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
                artifacts.append({"path":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
            manifest=root/"BUILD_MANIFEST.json"
            manifest.write_text(json.dumps({"status":"passed","candidate_profile":"mixed-diagnostic","artifacts":artifacts}))
            config=root/"loggercfg.txt";config.write_bytes(b"configuration\n")
            packet=root/"packet"
            result=subprocess.run([sys.executable,"-B",str(Path(bench.__file__)),"packet","--manifest",str(manifest),
                "--config",str(config),"--run-id","one","--output-dir",str(packet)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((packet/"configuration.txt").read_bytes(),config.read_bytes())
            self.assertEqual((packet/"candidate-manifest.json").read_bytes(),manifest.read_bytes())
            spec=json.loads((packet/"run-spec.json").read_text())
            self.assertEqual(set(spec["expected_images"]),{"logger","master","node"})
            self.assertIsNone(json.loads((packet/"readiness-template.json").read_text())["installed_images"])
            gate=subprocess.run([sys.executable,"-B",str(Path(bench.__file__)),"gate","--spec",str(packet/"run-spec.json"),
                "--observations",str(packet/"readiness-template.json")],capture_output=True,text=True)
            self.assertEqual(gate.returncode,1,gate.stderr)
    def test_historical_source_contrast_contains_adc_buffer_fix(self):
        value=bench.contrast({"source_commit":"e7613577c92bb1ab88e7c8db59d474864daa11d0","application":{}},
            {"source_commit":"3ef8a34b3c65b2227d8b616dff606e5d5d193f8d","application":{}})
        # A source archive alone may not retain historical objects.
        if value["source_contrast"] is None:self.skipTest("Historical commits unavailable")
        self.assertIn("AnalogInputManager.cpp",value["source_contrast"])
        self.assertIn("alignas(4)",value["source_contrast"])
    def test_recipe_tracks_selected_custom_board_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"boards").mkdir()
            board=root/"boards/a8.json";board.write_text('{"build":{"f_cpu":"240000000L"}}')
            first=identity(root,"mixed",{"board":"a8"})
            board.write_text('{"build":{"f_cpu":"80000000L"}}')
            self.assertNotEqual(first["id"],identity(root,"mixed",{"board":"a8"})["id"])
    def test_snapshot_contract_covers_every_actual_master_member(self):
        import re
        text=(bench.ROOT/"firmware/can-fd/master/src/main.c").read_text(encoding="utf-8")
        text=re.sub(r"/\*.*?\*/","",text,flags=re.S)
        for name,expected in (("MasterRuntimeInfo",RUNTIME),("MasterDrainInfo",{**BASE,**PHASE,**QUEUE,**V5})):
            body=re.search(r"typedef struct \{([^{}]*)\} "+name+";",text,re.S).group(1)
            actual={}
            for declaration in re.finditer(r"(?:uint\d+_t|bool)\s+([^;]+);",body):
                for member in declaration.group(1).split(","):
                    field=re.fullmatch(r"\s*(\w+)((?:\[\d+\])*)\s*",member)
                    self.assertIsNotNone(field,member)
                    actual[field.group(1)]=tuple(map(int,re.findall(r"\d+",field.group(2))))
            self.assertEqual(actual,expected)
    def test_recipe_is_normalized_and_ignores_tests_but_tracks_options_and_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"src").mkdir();(root/"test").mkdir()
            path=root/"src/a.cpp";path.write_bytes(b"source\r\n")
            first=identity(root,"mixed",{"flags":"v2"})
            path.write_bytes(b"source\n");(root/"test/test.cpp").write_text("test")
            self.assertEqual(first,identity(root,"mixed",{"flags":"v2"}))
            self.assertNotEqual(first["id"],identity(root,"mixed",{"flags":"v1"})["id"])
            path.write_text("changed")
            self.assertNotEqual(first["id"],identity(root,"mixed",{"flags":"v2"})["id"])

    def test_mixed_candidate_plan_declares_exact_rx2_and_existing_suites(self):
        from unittest.mock import patch
        with patch.object(sys,"argv",["candidate","--profile","mixed-diagnostic"]):args=runner.arguments()
        plan=runner.plan(args,Path("unused"))
        self.assertIn("common-host",[c["name"] for c in plan]) # independent CRC vectors already in common suite
        self.assertIn("node-host",[c["name"] for c in plan])
        for command in plan:
            if command["name"].startswith("master-") and command["artifacts"]:
                self.assertIn("SPI_RX_CAPACITY=2",command["argv"])
                self.assertIn("SPI_QUEUE_TIMING=1",command["argv"])
        self.assertIn(PROFILES["mixed-diagnostic"]["logger_env"],next(c["argv"] for c in plan if c["name"]=="a8-build"))
        args.validation_scope="logger";args.reuse_peers=Path("declared-peers.json")
        names=[c["name"] for c in runner.plan(args,Path("unused"))]
        self.assertNotIn("master-acquisition",names);self.assertNotIn("common-host",names)
        self.assertIn("firmware-host",names)

    def test_review_is_typed_and_source_bound(self):
        value={"schema":"bodaqs.review.v1","base":"a"*40,"head":"b"*40,"outcome":"passed","findings":[],
            "evidence":[{"path":"review.txt","sha256":"c"*64}]}
        self.assertEqual(review_result(value,"a"*40,"b"*40),value)
        with self.assertRaises(ValueError):review_result(value,"a"*40,"d"*40)
        value["findings"]=[{"resolution":"pending"}]
        with self.assertRaises(ValueError):review_result(value,"a"*40,"b"*40)

    def test_device_dry_run_scope_cannot_escalate_observation(self):
        spec={"schema":"bodaqs.bench-run.v1","run_id":"one","profile":"mixed-diagnostic",
            "candidate_manifest_sha256":"0"*64,"configuration_sha256":"0"*64,"adc_columns":["analog1"],
            "minimum_imu_readings":1,"expected_images":{"logger":"1"*64,"master":"2"*64,"node":"3"*64}}
        spec["expected_imu"]={"provider":"can:0","endpoint":"imu"}
        scope={"schema":"bodaqs.bench-device-scope.v1","run_id":"one","action":"serial_observe","port":"COM9",
            "duration_seconds":30,"expected_images":spec["expected_images"],
            "expires_utc":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),"commands":[]}
        self.assertFalse(bench.scoped_device_plan(scope,spec)["devices_accessed"])
        for key,value in (("action","flash"),("duration_seconds",0),("commands",["case 1 status"]),("run_id","other")):
            broken=copy.deepcopy(scope);broken[key]=value
            with self.assertRaises(ValueError):bench.scoped_device_plan(broken,spec)
        scope.update(action="bounded_cases",commands=["case 1 owner_flow 256"],case_ids=[1])
        bench.scoped_device_plan(scope,spec)
        scope["commands"]=["case 1 owner_flow\nreset"]
        with self.assertRaises(ValueError):bench.scoped_device_plan(scope,spec)

    def test_public_cli_snapshot_and_workspace_status(self):
        command=[sys.executable,"-B",str(Path(bench.__file__))]
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/"snapshot.js"
            subprocess.run([*command,"snapshot-script","--output",str(script)],check=True,capture_output=True)
            text=script.read_text()
            self.assertIn(" >> 32",text);self.assertIn("phase_total_us",text)
            self.assertNotIn("target.halt",text);self.assertNotIn("symbol.load",text)
            result=json.loads(subprocess.check_output([*command,"status"]))
            self.assertIsNone(result["guardrails"]["remotely_exercised_at"])
            self.assertIn("debt",result)


if __name__=="__main__":unittest.main()
