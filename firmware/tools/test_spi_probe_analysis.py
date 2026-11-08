"""Independent worked captures at the public offline command/result seam."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).with_name("analyze_spi_probe.py")
FIXTURE = Path(__file__).with_name("spi_probe_fixtures") / "mixed.jsonl"
ROUND2 = FIXTURE.with_name("round2-mixed.jsonl")
FAILURES = FIXTURE.with_name("round2-failures.jsonl")
EMITTED_SWITCH = FIXTURE.with_name("round2-emitted-switch.jsonl")


class ProbeAnalysisTests(unittest.TestCase):
    def round9_sample(self,name="pipeline"):
        return json.loads(FIXTURE.with_name(f"round9-{name}.jsonl").read_text(encoding="utf-8"))

    def test_round9_worked_turnover_and_scope(self):
        run=self.invoke(json.dumps(self.round9_sample("baseline"))+"\n"+json.dumps(self.round9_sample()))
        self.assertEqual(run.returncode,0,run.stderr);r=json.loads(run.stdout)
        self.assertEqual(r["schema"],"bodaqs.spi-probe-report.v9")
        self.assertEqual(r["cases"][0]["master_receive_turnover"]["status"],"not_applicable")
        p=r["cases"][1]["master_receive_turnover"]
        self.assertEqual(p["status"],"observed");self.assertEqual(p["capacity"],4)
        self.assertEqual(p["counter_deltas"],dict(enqueued=110,dequeued=109,full_reply_ready=1,full_other=2))
        self.assertEqual(p["turnover"]["queue_wait_mean_us"],40)
        self.assertEqual(p["turnover"]["reply_deferred_mean_us"],90)
        self.assertEqual(r["cases"][1]["candidate_evidence"],"failed")
        self.assertFalse(r["production_qualified"])

    def test_round9_invalid_metadata_and_conservation_fail(self):
        for mutation in range(13):
            c=self.round9_sample();m=c["master"]
            if mutation==0:m["receive_after"][1]=1
            elif mutation==1:m["receive_after"][2]=3
            elif mutation==2:m["receive_after"][3]=5
            elif mutation==3:m["receive_after"][4]=2
            elif mutation==4:m["turnover_after"][8]=0
            elif mutation==5:m["turnover_before"][9]=1
            elif mutation==6:m["receive_before"][5]=1
            elif mutation==7:m["turnover_after"][3]=49
            elif mutation==8:m["turnover_after"][6]=149
            elif mutation==9:m["turnover_after"][7]=1000
            elif mutation==10:
                m["receive_before"][1:4]=[1,0,1];m["receive_after"][1:4]=[1,0,1]
                m["receive_before"][6:8]=[100,100];m["receive_after"][6:8]=[210,210]
            elif mutation==11:m["receive_after"][3]=3
            else:
                m["receive_before"]=[1,4,0,0,1,0,0,0,0,0];m["receive_after"]=m["receive_before"][:]
                m["turnover_before"]=[1,0,0,0,0,0,0,0,1,0];m["turnover_after"]=m["turnover_before"][:]
            run=self.invoke(json.dumps(c));self.assertEqual(run.returncode,0,run.stderr)
            r=json.loads(run.stdout)["cases"][0]
            self.assertEqual(r["master_receive_turnover"]["status"],"invalid",mutation)
            self.assertIsNone(r["master_receive_turnover"]["turnover"])
            self.assertEqual(r["candidate_evidence"],"failed")

    def test_round9_missing_unsupported_pages_are_unknown(self):
        for mutation in range(4):
            c=self.round9_sample();m=c["master"]
            if mutation==0:m["receive_measured"]=False
            elif mutation==1:m["receive_before"][0]=0
            elif mutation==2:m["turnover_after"][0]=2
            else:m["receive_after"][1]=8
            run=self.invoke(json.dumps(c));self.assertEqual(run.returncode,0,run.stderr)
            r=json.loads(run.stdout)["cases"][0]["master_receive_turnover"]
            self.assertEqual(r["status"],"unknown");self.assertIsNone(r["turnover"])

    def test_round9_modular_counters_endpoint_states_and_capacity1(self):
        for cap in (1,4):
            c=self.round9_sample();m=c["master"]
            if cap==1:
                m["receive_before"][1:4]=[1,0,1];m["receive_after"][1:4]=[1,0,1]
                m["receive_before"][6:8]=[100,100];m["receive_after"][6:8]=[210,210]
                m["turnover_before"][7]=m["turnover_after"][7]=0
            else:
                m["receive_before"][6:8]=[4294967294,4294967293]
                m["receive_after"][6:8]=[108,106]
                m["turnover_before"][1:3]=[4294967293,4294967000]
                m["turnover_after"][1:3]=[107,4104]
            run=self.invoke(json.dumps(c));self.assertEqual(run.returncode,0,run.stderr)
            p=json.loads(run.stdout)["cases"][0]["master_receive_turnover"]
            self.assertEqual(p["status"],"observed");self.assertEqual(p["capacity"],cap)
            self.assertEqual(p["counter_deltas"]["enqueued"],110)
            self.assertEqual(p["turnover"]["queue_wait_mean_us"],40)
            self.assertEqual(p["turnover"]["queue_wait_boot_max_after_us"],75)

    def test_round9_rejects_malformed_or_adc_observations(self):
        for mutation in range(4):
            c=self.round9_sample("baseline" if mutation==3 else "pipeline");m=c["master"]
            if mutation==0:m["receive_after"][0]=True
            elif mutation==1:m["turnover_after"]=[0]*9
            elif mutation==2:m["receive_measured"]=1
            else:m["receive_measured"]=True
            self.assertEqual(self.invoke(json.dumps(c)).returncode,2)

    def round8_sample(self,name="pipeline"):
        return json.loads(FIXTURE.with_name(f"round8-{name}.jsonl").read_text(encoding="utf-8"))

    def test_round8_emitted_cadence_and_crc_remain_diagnostic(self):
        for name in ("baseline","pipeline","stop"):
            c=self.round8_sample(name)
            run=self.invoke(json.dumps(c));self.assertEqual(run.returncode,0,run.stderr)
            report=json.loads(run.stdout);result=report["cases"][0]
            self.assertEqual(report["schema"],"bodaqs.spi-probe-report.v8")
            self.assertEqual(result["logger_cost"]["crc_algorithm"],"table")
            self.assertIn("not causal blocking time",result["logger_cost"]["scope"])
            self.assertEqual(result["logger_cost"]["cadence"],c["logger_cost"]["cadence"])
            self.assertGreaterEqual(result["logger_cost"]["outside_completed_cycles_us"],0)
            self.assertNotEqual(result["candidate_evidence"],"clean_measurement_candidate")
            self.assertFalse(report["production_qualified"])

    def test_round8_rejects_forged_or_missing_cadence(self):
        zero={"count":0,"min_us":0,"max_us":0,"total_us":0}
        for mutation in range(10):
            c=self.round8_sample("baseline" if mutation>=8 else "pipeline")
            cost=c["logger_cost"];cadence=cost["cadence"]
            if mutation==0:cost["crc_algorithm"]="bitwise"
            elif mutation==1:cadence["active"]=False
            elif mutation==2:cadence["decisions"]["dispatch"]=zero
            elif mutation==3:cadence["cycle"]=zero
            elif mutation==4:cadence["adc_ready_service"]=cadence["cycle"]
            elif mutation==5:cadence["dispatch_headroom"]={"count":c["slots"],"min_us":800,"max_us":800,"total_us":800*c["slots"]}
            elif mutation==6:cadence["transport_service"]=zero
            elif mutation==7:c["artifacts"]["logger_build"]="unknown"
            elif mutation==8:
                for key,value in cadence.items():
                    if key=="decisions":
                        for name in value:value[name]=zero
                    elif isinstance(value,dict):cadence[key]=zero
            else:
                for key in ("cycle","adc_ready_service","row_service","adc_start_service"):
                    cadence[key]={"count":1,"min_us":0,"max_us":0,"total_us":0}
                cadence["decisions"]["adc_only"]={"count":1,"min_us":0,"max_us":0,"total_us":0}
            self.assertEqual(self.invoke(json.dumps(c)).returncode,2,mutation)

    def test_round8_rejects_impossible_nested_crc_or_work_totals(self):
        for mutation in range(5):
            c=self.round8_sample();timings=c["diagnostics"]["timing"]
            if mutation==0:timings["object_crc"]={"count":c["unique_objects"]+2,"min_us":0,"max_us":0,"total_us":0}
            elif mutation==1:timings["object_crc"]={"count":c["unique_objects"],"min_us":1000000,"max_us":1000000,"total_us":1000000*c["unique_objects"]}
            elif mutation==2:c["logger_cost"]["cadence"]["adc_start_service"]={"count":1,"min_us":0,"max_us":0,"total_us":0}
            elif mutation==3:c["row_publication"]["master_deferrals"]+=1
            else:c["diagnostics"]["pacing_deferred"]+=1
            self.assertEqual(self.invoke(json.dumps(c)).returncode,2,mutation)

    def test_round8_both_crc_options_and_matching_baselines(self):
        cases=[]
        for mode in (0,1):
            for name in ("baseline","pipeline"):
                c=self.round8_sample(name);c["case_id"]+=mode*100
                c["artifacts"]["logger_build"]=c["artifacts"]["logger_build"][:-1]+str(mode)
                c["logger_cost"]["crc_algorithm"]="table" if mode else "bitwise"
                cases.append(c)
        run=self.invoke("\n".join(map(json.dumps,cases)));self.assertEqual(run.returncode,0,run.stderr)
        report=json.loads(run.stdout)
        self.assertEqual(report["cases"][1]["baseline_case_ids"],[33])
        self.assertEqual(report["cases"][3]["baseline_case_ids"],[133])

    def round7_sample(self,name="pipeline"):
        return json.loads(FIXTURE.with_name(f"round7-{name}.jsonl").read_text(encoding="utf-8"))

    def test_round7_component_costs_are_nested_and_nonqualifying(self):
        c=self.round7_sample();baseline=self.round7_sample("baseline")
        run=self.invoke(json.dumps(baseline)+"\n"+json.dumps(c))
        self.assertEqual(run.returncode,0,run.stderr)
        report=json.loads(run.stdout);result=report["cases"][1]
        self.assertEqual(report["schema"],"bodaqs.spi-probe-report.v7")
        costs=result["master_processing_components"]
        self.assertEqual(costs["status"],"observed")
        self.assertEqual(costs["crc_algorithm"],"bitwise")
        self.assertEqual(set(costs["phases"]),{"decode","command","encode","frame_crc","object_crc"})
        self.assertIn("nests",costs["scope"])
        self.assertEqual(result["row_freshness_status"],"healthy")
        self.assertNotEqual(result["candidate_evidence"],"clean_measurement_candidate")
        self.assertFalse(report["production_qualified"])

    def test_round7_invalid_epoch_algorithm_or_sticky_flag_never_passes(self):
        for mutation in range(5):
            c=self.round7_sample();m=c["master"]
            if mutation==0:m["processing_meta_after"][2]+=1
            elif mutation==1:m["processing_meta_after"][1]=1
            elif mutation==2:m["processing_meta_before"][3]=1
            elif mutation==3:m["processing_meta_after"][3]=1
            else:m["processing_meta_before"][2]=0
            run=self.invoke(json.dumps(c));self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads(run.stdout)["cases"][0]
            self.assertEqual(result["master_processing_components"]["status"],"invalid")
            self.assertEqual(result["candidate_evidence"],"failed")

    def test_round7_missing_unsupported_and_uninstrumented_are_unknown(self):
        for mutation in range(5):
            c=self.round7_sample();m=c["master"]
            if mutation==0:m["processing_measured"]=False
            elif mutation==1:m["processing_meta_after"][0]=2
            elif mutation==2:m["processing_meta_after"][4]=0
            elif mutation==3:m["processing_meta_after"][1]=2
            else:m["processing_meta_after"][5]=1
            run=self.invoke(json.dumps(c));self.assertEqual(run.returncode,0,run.stderr)
            p=json.loads(run.stdout)["cases"][0]["master_processing_components"]
            self.assertEqual(p["status"],"unknown");self.assertIsNone(p["phases"])

    def test_round7_counters_wrap_but_metadata_does_not(self):
        c=self.round7_sample();m=c["master"]
        expected=(m["processing_after"][0]-m["processing_before"][0])&4294967295
        m["processing_before"][0]=4294967294;m["processing_after"][0]=(4294967294+expected)&4294967295
        run=self.invoke(json.dumps(c));self.assertEqual(run.returncode,0,run.stderr)
        p=json.loads(run.stdout)["cases"][0]["master_processing_components"]
        self.assertEqual(p["phases"]["decode"]["calls"],expected)
        self.assertEqual(p["metadata_before"][2],p["metadata_after"][2])

    def test_round7_rejects_malformed_pages_and_adc_observations(self):
        for mutation in range(3):
            c=self.round7_sample("baseline" if mutation==2 else "pipeline");m=c["master"]
            if mutation==0:m["processing_after"]=[0]*9
            elif mutation==1:m["processing_meta_before"][1]=True
            else:m["processing_measured"]=True
            self.assertEqual(self.invoke(json.dumps(c)).returncode,2)

    def test_round7_rejects_impossible_nested_costs(self):
        for index in (6,7,8,9):
            c=self.round7_sample();m=c["master"]
            m["processing_after"][index]=(m["processing_before"][index]+100000000)&4294967295
            run=self.invoke(json.dumps(c));self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads(run.stdout)["cases"][0]
            self.assertEqual(result["master_processing_components"]["status"],"invalid")
            self.assertEqual(result["candidate_evidence"],"failed")

    def round6_sample(self,name="pipeline"):
        return json.loads(FIXTURE.with_name(f"round6-{name}.jsonl").read_text(encoding="utf-8"))

    def test_round6_emitted_pipeline_retains_freshness_and_diagnostic_scope(self):
        for name in ("pipeline","recovery"):
            baseline=self.round6_sample("baseline");case=self.round6_sample(name)
            run=self.invoke(json.dumps(baseline)+"\n"+json.dumps(case))
            self.assertEqual(run.returncode,0,run.stderr)
            report=json.loads(run.stdout);result=report["cases"][1]
            self.assertEqual(report["schema"],"bodaqs.spi-probe-report.v6")
            self.assertEqual(result["row_freshness_status"],"healthy")
            self.assertEqual(result["baseline_case_ids"],[baseline["case_id"]])
            self.assertEqual(result["request_window"],case["request_window"])
            self.assertNotEqual(result["candidate_evidence"],"clean_measurement_candidate")
            self.assertFalse(report["production_qualified"])

    def test_round6_rejects_impossible_window_and_legacy_schema_claims(self):
        for mutation in range(9):
            case=self.round6_sample();w=case["request_window"]
            if mutation==0:w["pending"]=5
            elif mutation==1:w["new_requests"]+=1
            elif mutation==2:w["clock_requests"]+=1
            elif mutation==3:w["limit"]=5
            elif mutation==4:w["active"]=False
            elif mutation==5:w["retry_exhausted"]=1
            elif mutation==6:case["schema"]="bodaqs.spi-probe.v5"
            elif mutation==7:w["retry_limit"]=9
            else:
                w["high_water"]=w["pending"]=0
                w["new_requests"]=w["reply_age"]["count"]
                w["clock_requests"]=case["slots"]-w["new_requests"]-w["retry_requests"]
            self.assertEqual(self.invoke(json.dumps(case)).returncode,2,mutation)

    def test_round6_stop_and_per_request_exhaustion_cannot_pass(self):
        for name in ("stop","exhausted"):
            run=self.invoke(json.dumps(self.round6_sample(name)))
            self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads(run.stdout)["cases"][0]
            self.assertEqual(result["candidate_evidence"],"failed")
            self.assertNotEqual(result["row_freshness_status"],"healthy")

    def test_round6_failed_baseline_blocks_pipeline_evidence(self):
        baseline=self.round6_sample("baseline");baseline["outcome"]="failed"
        case=self.round6_sample()
        run=self.invoke(json.dumps(baseline)+"\n"+json.dumps(case))
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout)["cases"][1]["candidate_evidence"],"failed")

    def round5_sample(self,name="rows"):
        return json.loads(FIXTURE.with_name(f"round5-{name}.jsonl").read_text(encoding="utf-8"))

    def test_round5_real_row_publication_and_owner_baseline(self):
        baseline=self.round5_sample("baseline")
        case=self.round5_sample()
        run=self.invoke(json.dumps(baseline)+"\n"+json.dumps(case))
        self.assertEqual(run.returncode,0,run.stderr)
        report=json.loads(run.stdout)
        self.assertEqual(report["schema"],"bodaqs.spi-probe-report.v5")
        result=report["cases"][1]
        self.assertEqual(result["baseline_case_ids"],[baseline["case_id"]])
        self.assertEqual(result["row_freshness_status"],"healthy")
        self.assertEqual(result["row_publication"]["fresh_both"],50)
        self.assertEqual(result["row_publication"]["samples"][0]["counts"],[0,319])
        self.assertEqual(result["master_receive_pressure"],"no_spi_drops_observed")
        self.assertNotEqual(result["candidate_evidence"],"clean_measurement_candidate")
        self.assertFalse(report["admission_authorized"])

    def test_round5_reuse_timeout_and_stop_cannot_report_freshness_success(self):
        for name in ("reuse","timeout","stop"):
            with self.subTest(name=name):
                run=self.invoke(json.dumps(self.round5_sample(name)))
                self.assertEqual(run.returncode,0,run.stderr)
                c=json.loads(run.stdout)["cases"][0]
                self.assertNotEqual(c["row_freshness_status"],"healthy")
                self.assertEqual(c["candidate_evidence"],"failed")

    def test_round5_failed_owner_baseline_blocks_combined_evidence(self):
        baseline=self.round5_sample("baseline")
        baseline["adc"][0]["fresh"]-=1
        baseline["adc"][0]["reused"]+=1
        baseline["row_publication"]["fresh_both"]-=1
        case=self.round5_sample()
        run=self.invoke(json.dumps(baseline)+"\n"+json.dumps(case))
        self.assertEqual(run.returncode,0,run.stderr)
        result=json.loads(run.stdout)["cases"][1]
        self.assertEqual(result["baseline_status"],"failed")
        self.assertEqual(result["candidate_evidence"],"failed")

    def test_round5_rejects_false_row_provenance(self):
        for mutation in range(10):
            with self.subTest(mutation=mutation):
                c=self.round5_sample();p=c["row_publication"]
                if mutation==0:p["published"]+=1
                elif mutation==1:p["last"]["conversion"]=p["samples"][0]["conversion"][:]
                elif mutation==2:p["last"]["scheduled_us"]+=1
                elif mutation==3:p["samples"][1]["conversion"]=p["samples"][0]["conversion"][:]
                elif mutation==4:p["samples"][0]["acquired_us"][0]=p["samples"][0]["published_us"]+1
                elif mutation==5:p["last"]["fresh_mask"]=0
                elif mutation==6:p["samples"][0]["valid_mask"]=0
                elif mutation==7:p["active"]=False
                elif mutation==8:p["deadline_guard_us"]=0
                else:p["samples"][0]["counts"][0]=True
                self.assertEqual(self.invoke(json.dumps(c)).returncode,2)

    def round4_sample(self, name="workers"):
        return json.loads(FIXTURE.with_name(f"round4-{name}.jsonl").read_text(encoding="utf-8"))

    def test_round4_execution_reports_actual_rates_without_admission(self):
        for name in ("workers", "same-core", "owner", "timeout"):
            with self.subTest(name=name):
                case=self.round4_sample(name)
                run=self.invoke(json.dumps(case))
                self.assertEqual(run.returncode,0,run.stderr)
                report=json.loads(run.stdout)
                self.assertEqual(report["schema"],"bodaqs.spi-probe-report.v4")
                c=report["cases"][0]
                self.assertEqual(c["adc_status"],"not_applicable")
                self.assertNotEqual(c["candidate_evidence"],"clean_measurement_candidate")
                e=c["execution_control"]
                for p in e["traffic_rates"]:
                    self.assertAlmostEqual(p["transfers_per_second"],p["transfers"]*1e6/(e["window_ended_us"]-e["window_started_us"]))
                self.assertFalse(report["admission_authorized"])
                if name=="timeout":self.assertEqual(c["candidate_evidence"],"failed")

    def test_round4_execution_metadata_rejects_false_attribution(self):
        for mutation in range(11):
            with self.subTest(mutation=mutation):
                c=self.round4_sample()
                e=c["execution"]
                adc=next(p for p in e["traffic"] if p["cs"]==21)
                if mutation==0:e["adc_mask"]=True
                elif mutation==1:e["adc_core"]=2
                elif mutation==2:e["cycle_us"]=1499
                elif mutation==3:e["adc_mask"]=1
                elif mutation==4:adc["core_mask"]=2
                elif mutation==5:adc["operations"][2]=True
                elif mutation==6:adc["transfers"]=10000000
                elif mutation==7:e["window_ended_us"]=e["window_started_us"]-1
                elif mutation==8:e["traffic"].append(adc.copy())
                elif mutation==9:adc["operations"][2]=0
                else:e["window_ended_us"]=e["window_started_us"]+1
                self.assertEqual(self.invoke(json.dumps(c)).returncode,2)

    def round3_sample(self, name="failures"):
        return json.loads(FIXTURE.with_name(f"round3-{name}.jsonl").read_text(encoding="utf-8"))

    def test_round3_actual_controls_and_faults_keep_operation_metadata(self):
        for name in ("shape", "selected", "failures", "timeout"):
            with self.subTest(name=name):
                case = self.round3_sample(name)
                run = self.invoke(json.dumps(case))
                self.assertEqual(run.returncode, 0, run.stderr)
                report = json.loads(run.stdout)
                self.assertEqual(report["schema"], "bodaqs.spi-probe-report.v3")
                result = report["cases"][0]
                self.assertEqual(result["adc_status"], "not_applicable")
                self.assertNotEqual(result["candidate_evidence"], "clean_measurement_candidate")
                self.assertEqual(result["decode_by_previous_operation"], case["diagnostics"]["by_previous_operation"])
                if name == "failures":
                    self.assertEqual(result["decoder_counts"]["magic"], 6)
                    self.assertEqual([s["bus"]["previous_operation"]["bytes"] for s in result["failure_samples"]], [5,1,4,5])
                if name == "timeout":
                    self.assertEqual(result["candidate_evidence"], "failed")
                    self.assertEqual(result["sequential_control"]["timeouts"], 1)
                self.assertFalse(report["production_qualified"])

    def test_round3_metadata_rejects_inconsistent_operations_and_workers(self):
        for mutation in range(8):
            with self.subTest(mutation=mutation):
                case = self.round3_sample()
                d = case["diagnostics"]
                if mutation == 0:
                    d["by_previous_operation"][0]["operation"]["bytes"] = True
                elif mutation == 1:
                    d["sequence"]["worker_start_requested"] = True
                elif mutation == 2:
                    d["sequence"]["operations"][0][2] = 0
                elif mutation == 3:
                    d["by_previous_operation"][0]["decode_failures"] -= 1
                    d["operation_buckets_omitted"] = 1
                elif mutation == 4:
                    # An omitted success cannot justify an unknown-key failure.
                    bucket = next(b for b in d["by_previous_operation"] if b["responses"])
                    bucket["responses"] -= 1
                    d["operation_buckets_omitted"] = 1
                    d["failure_samples"][0]["bus"]["previous_operation"]["tx0"] = 0x99
                elif mutation == 5:
                    d["by_previous_operation"].append(d["by_previous_operation"][0].copy())
                elif mutation == 6:
                    d["failure_samples"][0]["bus"]["previous_operation"]["has_rx"] = 1
                else:
                    d["sequence"]["active"] = False
                self.assertNotEqual(self.invoke(json.dumps(case)).returncode, 0)

    def test_emitted_round2_switch_accepts_only_declared_synthetic_spi_participant(self):
        capture = EMITTED_SWITCH.read_text(encoding="utf-8")
        run = self.invoke(capture)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report["cases"][0]["profile"]["mode"], "switch")
        self.assertEqual(report["cases"][0]["adc_status"], "not_applicable")
        self.assertNotEqual(report["cases"][0]["candidate_evidence"], "clean_measurement_candidate")
        self.assertIn(-2, [s["cs"] for s in report["cases"][0]["raw_measurements"]["spi"]])
        for schema, cs in (("bodaqs.spi-probe.v1", -2), ("bodaqs.spi-probe.v2", -1),
                           ("bodaqs.spi-probe.v2", -3), ("bodaqs.spi-probe.v2", False)):
            with self.subTest(schema=schema, cs=cs):
                case = self.sample() if schema.endswith("v1") else json.loads(capture)
                if schema.endswith("v1"):
                    case["spi"] = [{"cs": cs, "transfers": 0, "bytes": 0, "lock_failures": 0,
                                    "lock_wait": {"count": 0, "min_us": 0, "max_us": 0, "total_us": 0},
                                    "ownership": {"count": 0, "min_us": 0, "max_us": 0, "total_us": 0}}]
                else:
                    next(s for s in case["spi"] if s["cs"] == -2)["cs"] = cs
                self.assertEqual(self.invoke(json.dumps(case)).returncode, 2)

    def sample(self):
        return json.loads(FIXTURE.read_text())

    def test_round2_worked_capture_reports_crc_pacing_and_page2_scopes(self):
        run = self.invoke(ROUND2.read_text(encoding="utf-8"))
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        case = report["cases"][0]
        self.assertEqual(case["decoder_counts"], {
            "ok": 200, "argument": 0, "frame_size": 0, "magic": 0,
            "version": 0, "profile": 0, "payload_length": 0, "crc": 0, "padding": 0})
        self.assertEqual(case["experimental_control"], {
            "crc_mode": "legacy", "start_interval_us": 0, "synthetic_switch": False})
        self.assertEqual(case["master_component_timing"]["counter_deltas"], {
            "process_calls": 150, "process_total_us": 48, "boundary_calls": 200,
            "retire_total_us": 12, "publish_calls": 150, "publish_wait_total_us": 30})
        self.assertEqual(case["master_component_timing"]["boot_maxima"]["process_max_us"],
                         {"before": 80, "after": 90})
        self.assertEqual(case["master_component_timing"]["timing_invalid"], {"before": 0, "after": 0})
        self.assertEqual(case["master_component_timing"]["status"], "observed")
        self.assertFalse(report["production_qualified"])
        self.assertFalse(report["t01_go"])
        self.assertFalse(report["admission_authorized"])

    def test_round2_decoder_accounting_rejects_incomplete_or_inconsistent_evidence(self):
        for field, value in (
                ("decode_counts", [200]),
                ("decode_counts", [199, 0, 0, 0, 0, 0, 0, 0, 0]),
                ("decode_counts", [200, False, 0, 0, 0, 0, 0, 0, 0]),
                ("failure_samples_omitted", 1),
                ("by_previous_cs", []),
                ("by_previous_cs", [{"cs": -1, "responses": 199, "decode_failures": 0}]),
                ("expected_crc_calls", 3),
                ("switch_transfers", 1),
                ("switch_failures", 1)):
            with self.subTest(field=field, value=value):
                case = json.loads(ROUND2.read_text(encoding="utf-8"))
                case["diagnostics"][field] = value
                self.assertEqual(self.invoke(json.dumps(case)).returncode, 2)

    def test_round2_failure_samples_keep_complete_bytes_requests_and_safe_intervals(self):
        run = self.invoke(FAILURES.read_text(encoding="utf-8"))
        self.assertEqual(run.returncode, 0, run.stderr)
        case = json.loads(run.stdout)["cases"][0]
        self.assertEqual(case["decoder_counts"]["magic"], 1)
        self.assertEqual(case["decoder_counts"]["crc"], 2)
        self.assertEqual(case["failure_samples_omitted"], 1)
        first, second = case["failure_samples"]
        self.assertEqual(first["bus_intervals_us"], {"cs_ownership": 8, "since_previous_release": None})
        self.assertEqual(second["bus_intervals_us"], {"cs_ownership": 12, "since_previous_release": 6})
        self.assertEqual(second["request"], {"opcode": 2, "case_id": 203, "profile": 24,
                         "node": 0, "fragment": 1, "object_id": 1, "logical_crc": 0})
        self.assertEqual(len(bytes.fromhex(second["rx_hex"])), 64)
        self.assertEqual(case["decode_by_previous_cs"], [
            {"cs": -1, "responses": 1, "decode_failures": 1},
            {"cs": 10, "responses": 5, "decode_failures": 2}])
        self.assertEqual(case["decode_previous_cs_distribution"][0]["decode_calls"], 2)
        self.assertEqual(case["decode_previous_cs_distribution"][0]["failure_fraction_of_decode_calls"], 0.5)
        self.assertAlmostEqual(case["decode_previous_cs_distribution"][1]["failure_fraction_of_decode_calls"], 0.2857142857)
        self.assertEqual(case["candidate_evidence"], "failed")
        # A known preceding release at zero must retain a measured interval.
        sample = json.loads(FAILURES.read_text(encoding="utf-8"))
        sample["diagnostics"]["failure_samples"][1]["bus"].update(
            previous_release_us=0, cs_assert_us=6, cs_release_us=18)
        run = self.invoke(json.dumps(sample))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["cases"][0]["failure_samples"][1]["bus_intervals_us"],
                         {"cs_ownership": 12, "since_previous_release": 6})

    def test_round2_invalid_sample_context_is_rejected(self):
        for field, value in (
                ("reason", 0), ("reason", 8), ("slot", 0), ("slot", 11),
                ("frame_bytes", 128), ("rx_hex", "00"), ("rx_hex", "z" * 128),
                ("request.case_id", 202), ("request.profile", 25),
                ("request.node", 4), ("request.fragment", 26),
                ("request.object_id", 0), ("request.logical_crc", -1),
                ("bus.sequence", 4294967296), ("bus.previous_valid", 1),
                ("bus.cs", -1), ("bus.previous_cs", -3), ("bus.cs_assert_us", -1)):
            with self.subTest(field=field):
                case = json.loads(FAILURES.read_text(encoding="utf-8"))
                target = case["diagnostics"]["failure_samples"][0]
                parts = field.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                self.assertEqual(self.invoke(json.dumps(case)).returncode, 2)
        for change in ("duplicates", "saturation", "distribution"):
            case = json.loads(FAILURES.read_text(encoding="utf-8"))
            d = case["diagnostics"]
            if change == "duplicates":
                d["failure_samples"][1]["slot"] = 2
            elif change == "saturation":
                d["failure_samples"] *= 3
            else:
                d["by_previous_cs"][0]["decode_failures"] = 0
                d["by_previous_cs"][1]["decode_failures"] = 3
            self.assertEqual(self.invoke(json.dumps(case)).returncode, 2)

    def test_round2_comparisons_keep_crc_pacing_and_full_profile_separate(self):
        cases = []
        for number, mode, crc, interval in (
                (210, "bulk", "legacy", 0), (211, "mixed", "legacy", 0),
                (212, "bulk", "cached", 0), (213, "mixed", "legacy", 500)):
            case = json.loads(ROUND2.read_text(encoding="utf-8"))
            case["case_id"] = number
            case["profile"].update(mode=mode, crc_mode=crc, start_interval_us=interval)
            if mode == "bulk":
                case["rows"] = 0
                for adc in case["adc"]:
                    adc.update(fresh=0, uses=0)
            cases.append(case)
        run = self.invoke("\n".join(json.dumps(c) for c in cases))
        self.assertEqual(run.returncode, 0, run.stderr)
        groups = [c for c in json.loads(run.stdout)["comparison"] if
                  c["frame_bytes"] == 64 and c["requested_sck_hz"] == 8000000]
        self.assertEqual(len(groups), 3)
        self.assertEqual([(g["bulk_case_ids"], g["mixed_case_ids"]) for g in groups],
                         [([212], []), ([210], [211]), ([], [213])])
        self.assertEqual([g["mixed_to_bulk_rate_ratios"] for g in groups], [[], [1], []])

    def test_round2_page2_unknown_invalid_and_no_observations_never_pass(self):
        for variation, expected in (("missing", "unknown"), ("unsupported", "unknown"),
                                    ("sticky", "invalid"), ("empty", "no_observations")):
            with self.subTest(variation=variation):
                case = json.loads(ROUND2.read_text(encoding="utf-8"))
                if variation == "missing":
                    del case["master"]
                elif variation == "unsupported":
                    case["master"].update(diagnostic_measured=False, timing_measured=False, timing_scope="unmeasured")
                elif variation == "sticky":
                    case["master"]["diagnostic_before"][9] = 1
                    case["master"]["diagnostic_after"][9] = 1
                else:
                    case["master"]["diagnostic_after"] = case["master"]["diagnostic_before"][:]
                run = self.invoke(json.dumps(case))
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads(run.stdout)["cases"][0]
                self.assertEqual(result["master_component_timing"]["status"], expected)
                self.assertNotEqual(result["candidate_evidence"], "clean_measurement_candidate")
                self.assertNotEqual(result["master_diagnostics_status"], "clean")

    def test_round2_controls_keep_observed_adc_health_separate_from_eligibility(self):
        for mode, crc, interval in (("switch", "legacy", 500), ("mixed", "legacy", 500),
                                    ("mixed", "cached", 0), ("bulk", "cached", 0)):
            with self.subTest(mode=mode, crc=crc, interval=interval):
                case = json.loads(ROUND2.read_text(encoding="utf-8"))
                case["profile"].update(mode=mode, crc_mode=crc, start_interval_us=interval)
                if mode in ("switch", "bulk"):
                    case["rows"] = 0
                    for adc in case["adc"]:
                        adc.update(fresh=0, uses=0)
                if mode == "switch":
                    case["diagnostics"].update(switch_transfers=180, switch_failures=0)
                run = self.invoke(json.dumps(case))
                self.assertEqual(run.returncode, 0, run.stderr)
                report = json.loads(run.stdout)
                result = report["cases"][0]
                self.assertEqual(result["candidate_evidence"], "diagnostic_control")
                self.assertEqual(result["adc_status"], "healthy" if mode == "mixed" else "not_applicable")
                self.assertFalse(report["production_qualified"])
                self.assertFalse(report["t01_go"])
                self.assertFalse(report["admission_authorized"])

    def baseline(self):
        baseline = self.sample()
        baseline["case_id"] = 100
        baseline["profile"]["mode"] = "adc"
        for name in ("slots", "valid_responses", "unique_objects", "accepted_bytes", "retired_objects"):
            baseline[name] = 0
        return baseline

    def manifest(self, capture):
        return {"schema": "bodaqs.spi-probe-manifest.v1", "protocol": 1,
                "capture_sha256": hashlib.sha256(capture.encode("utf-8")).hexdigest(),
                "capture_path": "external/literal.txt", "wiring": "literal test fixture",
                "instrumentation": "host fixture; no physical measurements",
                "logger": {"board": "A8", "source_revision": "a" * 40,
                           "artifact_sha256": "b" * 64, "build": "literal-fixture"},
                "master": {"board": "MSPM0", "source_revision": "c" * 40, "artifact_sha256": "d" * 64}}

    def test_round2_paired_bulk_needs_actual_diagnostic_observations(self):
        for variation, expected in (("observed", "clean_measurement_candidate"),
                                    ("page_unknown", "unknown"), ("iteration_empty", "unknown"),
                                    ("interval_empty", "unknown"), ("validate_empty", "unknown"),
                                    ("crc_empty", "unknown"), ("sticky", "failed")):
            with self.subTest(variation=variation):
                case = json.loads(ROUND2.read_text(encoding="utf-8"))
                case["profile"]["mode"] = "bulk"
                case["rows"] = 0
                for adc in case["adc"]:
                    adc.update(fresh=0, uses=0)
                if variation == "page_unknown":
                    case["master"].update(diagnostic_measured=False, timing_measured=False, timing_scope="unmeasured")
                elif variation.endswith("_empty"):
                    key = {"iteration_empty": "iteration", "interval_empty": "request_interval",
                           "validate_empty": "validate", "crc_empty": "expected_crc"}[variation]
                    case["diagnostics"]["timing"][key] = {"count": 0, "min_us": 0, "max_us": 0, "total_us": 0}
                    if key == "expected_crc":
                        case["diagnostics"]["expected_crc_calls"] = 0
                elif variation == "sticky":
                    case["master"]["diagnostic_before"][9] = 1
                    case["master"]["diagnostic_after"][9] = 1
                capture = json.dumps(case)
                run = self.invoke(capture, self.manifest(capture))
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads(run.stdout)["cases"][0]
                self.assertEqual(result["candidate_evidence"], expected)

    def test_round2_switch_failures_are_observed_failures(self):
        case = json.loads(ROUND2.read_text(encoding="utf-8"))
        case["profile"]["mode"] = "switch"
        case["rows"] = 0
        for adc in case["adc"]:
            adc.update(fresh=0, uses=0)
        # A failed first clock burst has no successful switch transfer.
        for successes in (0, 10):
            with self.subTest(successes=successes):
                case["diagnostics"].update(switch_transfers=successes, switch_failures=1)
                run = self.invoke(json.dumps(case))
                self.assertEqual(run.returncode, 0, run.stderr)
                report = json.loads(run.stdout)
                self.assertEqual(report["cases"][0]["candidate_evidence"], "failed")
                self.assertFalse(report["production_qualified"])
                self.assertFalse(report["t01_go"])
                self.assertFalse(report["admission_authorized"])

    def test_round2_switch_counts_reject_malformed_values(self):
        for field in ("switch_transfers", "switch_failures"):
            for value in (-1, False, 1.5, "1"):
                with self.subTest(field=field, value=value):
                    case = json.loads(EMITTED_SWITCH.read_text(encoding="utf-8"))
                    case["diagnostics"][field] = value
                    self.assertEqual(self.invoke(json.dumps(case)).returncode, 2)

    def test_round2_ready_and_status_retain_required_source_identity(self):
        for kind in ("ready", "status"):
            event = {"schema": "bodaqs.spi-probe.v2", "type": kind, "ready": True,
                     "blocked": False, "logger_build": "literal-fixture"}
            capture = json.dumps(event) + "\n" + ROUND2.read_text(encoding="utf-8")
            run = self.invoke(capture)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["serial_events"][0]["logger_build"], "literal-fixture")
            del event["logger_build"]
            self.assertEqual(self.invoke(json.dumps(event) + "\n" + ROUND2.read_text(encoding="utf-8")).returncode, 2)

    def invoke(self, capture, manifest=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capture.txt"
            path.write_bytes(capture.encode("utf-8"))
            command = [sys.executable, str(TOOL), str(path)]
            if manifest:
                manifest_path = Path(folder) / "manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                command += ["--manifest", str(manifest_path)]
            return subprocess.run(command,
                                  capture_output=True, text=True)

    def test_worked_capture_has_unique_useful_rate_and_honest_limits(self):
        run = self.invoke("ESP-ROM boot\n[SPI] ordinary boot diagnostic\n" + FIXTURE.read_text())
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        case = report["cases"][0]
        self.assertEqual(case["accepted_bytes_per_second"], 2016)
        self.assertEqual(case["retired_bytes_per_second"], 1512)
        self.assertEqual(case["pending_ack_objects"], 1)
        self.assertEqual(case["actual_sck_hz"], None)
        self.assertEqual(case["adc_status"], "healthy")
        self.assertEqual(case["transport_status"], "clean")
        self.assertEqual(case["candidate_evidence"], "unknown")
        self.assertEqual(report["production_qualified"], False)
        self.assertNotIn("acquisition_hz", case)
        self.assertEqual(report["baseline_status"], "unknown")

    def test_inconsistent_case_results_are_rejected(self):
        changes = [
            ("schema", "future"), ("case_id", 0), ("rows", -1),
            ("rows", True), ("accepted_bytes", 4033), ("retired_objects", 5),
            ("elapsed_us", 0), ("outcome", "pass"),
            ("profile.frame_bytes", 512), ("profile.requested_sck_hz", 20000000),
            ("profile.nodes", 0), ("profile.guard_us", 0),
            ("profile.configured_sps", [500, 500]),
            ("profile.configured_sps", [1000.0, 1000]), ("profile.ain", [False, 4]),
            ("profile.actual_sck_hz", 16000000),
            ("adc.0.fresh", 999), ("adc.1.uses", 999),
            ("adc.1.index", 0), ("errors.wire", -1),
            ("timing.slot.count", -1), ("master.after", [0]),
        ]
        for name, value in changes:
            with self.subTest(field=name):
                sample = self.sample()
                target = sample
                parts = name.split(".")
                for part in parts[:-1]:
                    target = target[int(part)] if isinstance(target, list) else target[part]
                target[parts[-1]] = value
                self.assertEqual(self.invoke(json.dumps(sample)).returncode, 2)
        for text in [FIXTURE.read_text() * 2, '{"schema":', "[]", "boot only"]:
            with self.subTest(capture=text[:30]):
                self.assertEqual(self.invoke(text).returncode, 2)

    def test_baseline_failure_is_separate_from_mixed_transport_and_pipeline_diagnostics(self):
        baseline = self.baseline()
        baseline["adc"][0].update(fresh=999, reused=1)
        run = self.invoke(json.dumps(baseline) + "\n" + FIXTURE.read_text())
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report["baseline_status"], "failed")
        mixed = report["cases"][1]
        self.assertEqual(mixed["transport_status"], "clean")
        self.assertEqual(mixed["adc_status"], "healthy")
        self.assertEqual(mixed["baseline_status"], "failed")
        self.assertEqual(mixed["candidate_evidence"], "failed")
        self.assertEqual(mixed["pipeline_diagnostics"], {"stale": 8, "duplicate": 2})

    def test_error_and_missing_master_evidence_never_pass(self):
        for field in ("transfer", "wire", "accept", "commands"):
            with self.subTest(error=field):
                sample = self.sample()
                sample["errors"][field] = 1
                case = json.loads(self.invoke(json.dumps(sample)).stdout)["cases"][0]
                self.assertEqual(case["transport_status"], "failed")
                self.assertEqual(case["candidate_evidence"], "failed")
        sample = self.sample()
        del sample["master"]
        case = json.loads(self.invoke(json.dumps(sample)).stdout)["cases"][0]
        self.assertEqual(case["master_diagnostics_status"], "unknown")
        self.assertEqual(case["candidate_evidence"], "unknown")
        sample = self.sample()
        sample["master"]["adapter_after"][1] = 1
        case = json.loads(self.invoke(json.dumps(sample)).stdout)["cases"][0]
        self.assertEqual(case["master_diagnostics_status"], "failed")
        self.assertEqual(case["candidate_evidence"], "failed")

    def test_adapter_clock_health_preserves_states_instead_of_subtracting_them(self):
        for before, after, invalid_before, invalid_after, measured, status in (
                (3, 3, 1, 1, True, "failed"),
                (3, 4, 0, 0, True, "failed"),
                (0, 0, 0, 0, True, "failed"),
                (3, 3, 0, 0, False, "unknown"),
                (3, 3, 0, 0, True, "clean")):
            with self.subTest(epoch=(before, after), invalid=(invalid_before, invalid_after), measured=measured):
                sample = self.sample()
                master = sample["master"]
                master["adapter_before"][8:] = [before, invalid_before]
                master["adapter_after"][8:] = [after, invalid_after]
                master["adapter_measured"] = measured
                run = self.invoke(json.dumps(sample))
                self.assertEqual(run.returncode, 0, run.stderr)
                case = json.loads(run.stdout)["cases"][0]
                self.assertEqual(case["master_diagnostics_status"], status)
                self.assertEqual(case["candidate_evidence"], "failed" if status == "failed" else "unknown")
                self.assertEqual(case["raw_measurements"]["master"], master)
                if measured:
                    self.assertEqual(case["master_adapter_states"], {
                        "clock_epoch": {"before": before, "after": after},
                        "timing_invalid": {"before": invalid_before, "after": invalid_after}})
                    self.assertEqual(set(case["master_adapter_deltas"]), {
                        "slots_received", "spi_rx_dropped", "malformed_slots", "spi_recoveries",
                        "cs_release_timeouts", "can_rx_frames", "can_rx_dropped", "can_rx_hardware_losses"})
                else:
                    self.assertIsNone(case["master_adapter_states"])
                    self.assertIsNone(case["master_adapter_deltas"])

    def test_row_rate_allows_only_one_row_quantization_and_never_acquisition_rate(self):
        for rows, status in ((999, "healthy"), (998, "failed"), (1001, "healthy"), (1002, "failed")):
            with self.subTest(rows=rows):
                sample = self.sample()
                sample["rows"] = rows
                for adc in sample["adc"]:
                    adc.update(fresh=rows, uses=rows)
                run = self.invoke(json.dumps(sample))
                if status == "failed":
                    self.assertEqual(run.returncode, 2)
                    continue
                case = json.loads(run.stdout)["cases"][0]
                self.assertEqual(case["adc_status"], status)
                self.assertNotIn("acquisition_hz", case)
        sample = self.sample()
        sample.update(rows=999, missed_rows=1)
        for adc in sample["adc"]:
            adc.update(fresh=999, uses=999)
        case = json.loads(self.invoke(json.dumps(sample)).stdout)["cases"][0]
        self.assertEqual(case["adc_status"], "failed")

    def test_paired_manifest_and_comparison_are_reproducible_measurement_evidence(self):
        mixed = self.sample()
        bulk = self.sample()
        bulk["case_id"] = 102
        bulk["profile"]["mode"] = "bulk"
        bulk["rows"] = 0
        for adc in bulk["adc"]:
            adc.update(fresh=0, uses=0)
        capture = "\n".join(json.dumps(c) for c in (self.baseline(), bulk, mixed))
        manifest = {"schema": "bodaqs.spi-probe-manifest.v1",
                    "capture_sha256": hashlib.sha256(capture.encode()).hexdigest(),
                    "capture_path": "external/capture.txt", "protocol": 1,
                    "logger": {"board": "A8-ESP32-S3MiniN4R2", "source_revision": "a" * 40,
                               "artifact_sha256": "b" * 64, "build": "literal-fixture"},
                    "master": {"board": "MSPM0G3518", "source_revision": "c" * 40,
                               "artifact_sha256": "d" * 64},
                    "wiring": "unchanged shared SPI", "instrumentation": "SCK unmeasured"}
        first = self.invoke(capture, manifest)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, self.invoke(capture, manifest).stdout)
        report = json.loads(first.stdout)
        self.assertEqual(report["cases"][2]["candidate_evidence"], "clean_measurement_candidate")
        self.assertFalse(report["t01_go"])
        self.assertEqual(len(report["comparison"]), 6)
        self.assertEqual(report["comparison"][0]["bulk_case_ids"], [102])
        self.assertEqual(report["comparison"][0]["mixed_case_ids"], [101])
        self.assertEqual(report["comparison"][0]["mixed_to_bulk_rate_ratios"], [1])
        self.assertEqual(report["comparison"][1]["coverage"], "missing")
        manifest["capture_sha256"] = "0" * 64
        self.assertEqual(self.invoke(capture, manifest).returncode, 2)

    def test_startup_failure_and_unmeasured_pages_are_preserved_without_false_rates(self):
        sample = self.baseline()
        sample.update(outcome="failed", reason="analog_rail_fault", elapsed_us=0, rows=0)
        for adc in sample["adc"]:
            adc.update(fresh=0, uses=0)
        run = self.invoke(json.dumps(sample))
        self.assertEqual(run.returncode, 0, run.stderr)
        case = json.loads(run.stdout)["cases"][0]
        self.assertEqual(case["candidate_evidence"], "failed")
        self.assertEqual(case["adc_status"], "failed")
        self.assertIsNone(case["rows_per_second"])
        sample = self.sample()
        sample["master"].update(measured=False, adapter_measured=False)
        case = json.loads(self.invoke(json.dumps(sample)).stdout)["cases"][0]
        self.assertEqual(case["master_diagnostics_status"], "unknown")
        self.assertIsNone(case["master_engine_deltas"])
        sample = self.sample()
        sample["master"]["adapter_before"][1] = 4294967295
        sample["master"]["adapter_after"][1] = 1
        case = json.loads(self.invoke(json.dumps(sample)).stdout)["cases"][0]
        self.assertEqual(case["master_adapter_deltas"]["spi_rx_dropped"], 2)
        self.assertEqual(case["master_diagnostics_status"], "failed")

    def test_late_completion_and_early_stop_keep_nominal_scheduled_window(self):
        late = self.sample()
        late["elapsed_us"] = 2011000
        run = self.invoke(json.dumps(late))
        self.assertEqual(run.returncode, 0, run.stderr)
        case = json.loads(run.stdout)["cases"][0]
        self.assertEqual(case["candidate_evidence"], "failed")
        self.assertEqual(case["duration_status"], "late")
        self.assertEqual(case["scheduled_rows_target"], 1000)
        stopped = self.sample()
        stopped.update(outcome="stopped", elapsed_us=1000000, rows=500)
        for adc in stopped["adc"]:
            adc.update(fresh=500, uses=500)
        run = self.invoke(json.dumps(stopped))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["cases"][0]["scheduled_rows_target"], 500)


if __name__ == "__main__":
    unittest.main()
