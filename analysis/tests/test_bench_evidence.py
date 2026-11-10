"""Independent file vectors and exact identity failures for the public bench seam."""
import copy
import json
import pytest
from bodaqs_analysis.bench_evidence import ingest, make_spec, readiness, counter_delta
from bodaqs_analysis.bench_snapshot import exact64, fields, validate, RUNTIME, U64
from test_first_imu_recording import recording


def spec_for(manifest):
    return make_spec(manifest, "case-1", "0"*64, adc_columns=[])


def fixture(tmp_path):
    bdq=recording(tmp_path)
    manifest=tmp_path/"manifest.json"
    manifest.write_text(json.dumps({"status":"passed","candidate_profile":"first-recording",
        "source":{"commit":"a"*40},"logger_recipe_id":"recipe-sha256:"+"b"*64,"artifacts":[]}))
    spec=spec_for(manifest)
    serial=tmp_path/"serial.log"
    serial.write_text("[Logging] stop requested reason=user_request\n[FLOW] stage=finished context=9 loss_counter=0\n")
    return bdq,manifest,spec,serial


def test_immutable_content_intake_and_unknown_old_identity(tmp_path):
    bdq,manifest,spec,serial=fixture(tmp_path)
    out=ingest(tmp_path/"evidence",spec,{"bdq":bdq,"manifest":manifest,"serial":serial})
    report=json.loads((out/"report.json").read_text())
    assert report["assessment"]["file_outcome"]=="complete_delivery"
    assert report["gates"]["serial_context"]=="passed"
    assert report["gates"]["logger_identity"]=="unknown" # Historical metadata has no recipe ID.
    assert report["comparison_ready"] is False
    assert ingest(tmp_path/"evidence",spec,{"bdq":bdq,"manifest":manifest,"serial":serial})==out
    (out/"inputs/bdq.bdq").write_bytes(b"tamper")
    with pytest.raises(ValueError,match="changed"):ingest(tmp_path/"evidence",spec,{"bdq":bdq,"manifest":manifest,"serial":serial})


def test_wrong_manifest_serial_and_truncation_are_retained(tmp_path):
    bdq,manifest,spec,serial=fixture(tmp_path)
    serial.write_text("[FLOW] stage=finished context=9007199254740993\n")
    manifest.write_text("{}")
    out=ingest(tmp_path/"evidence",spec,{"bdq":bdq,"manifest":manifest,"serial":serial})
    report=json.loads((out/"report.json").read_text())
    assert report["gates"]["manifest_identity"]=="failed" and report["gates"]["serial_context"]=="failed"
    bdq.write_bytes(bdq.read_bytes()[:-10])
    out2=ingest(tmp_path/"evidence",spec,{"bdq":bdq,"manifest":manifest})
    assert out2!=out and (out2/"inputs/bdq.bdq").exists()
    report2=json.loads((out2/"report.json").read_text())
    assert report2["classification"]=="evidence_incomplete" and not report2["comparison_ready"]


def test_ready_gate_rejects_wrong_images_and_unreconciled_imu(tmp_path):
    _,manifest,spec,_=fixture(tmp_path)
    spec["expected_images"]={"logger":"1"*64,"master":"2"*64,"node":"3"*64}
    observation={"installed_images":spec["expected_images"],"configuration_sha256":spec["configuration_sha256"],
        "sensors":[{"provider":"can:0","endpoint":"imu","remote_control":{
            "configuration_reconciled":True,"acquisition_link_compatible":True,"effective":{"available":True,"current":True}}}]}
    assert readiness(spec,observation)["ready"]
    observation["installed_images"]={"logger":"9"*64}
    assert not readiness(spec,observation)["ready"]
    observation["installed_images"]=spec["expected_images"]
    observation["sensors"][0]["remote_control"]["configuration_reconciled"]=False
    assert not readiness(spec,observation)["ready"]


def test_uint64_and_arrays_exact():
    assert exact64("18446744073709551615")==2**64-1
    for value in (9007199254740992,9007199254740992.0,"18446744073709551616"):
        with pytest.raises(ValueError):exact64(value)
    def zero(shape,wide=False):return [zero(shape[1:],wide) for _ in range(shape[0])] if shape else "0" if wide else 0
    snapshot={"schema":"bodaqs.master-snapshot.v1","master_boot":"99","scope":"first_loss",
        "layout":{"phase_timing":True,"queue_timing":True},
        "drain":{k:zero(s,k in U64) for k,s in fields(5,True,True).items()},
        "runtime":{k:zero(s) for k,s in RUNTIME.items()}}
    snapshot["drain"].update(version=5,state=2,finish_reason=1,layout_flags=3,size_bytes=1000,context="9007199254740993")
    validate(snapshot)
    broken=copy.deepcopy(snapshot);broken["drain"]["phase_total_us"][0].pop()
    with pytest.raises(ValueError):validate(broken)
    broken=copy.deepcopy(snapshot);broken["drain"]["context"]=9007199254740992
    with pytest.raises(ValueError):validate(broken)


def test_cumulative_counter_delta_not_repeated_sum():
    assert counter_delta([0,5,5,7])==7
    assert counter_delta([9,9,9])==0
    assert counter_delta([9,2]) is None # Reset/wrap cannot be guessed.


def test_new_identity_allows_complete_comparison_and_missing_file_is_retained(tmp_path):
    bdq,manifest,spec,serial=fixture(tmp_path)
    recording(tmp_path,recipe=spec["logger_recipe_id"])
    spec["expected_images"]={"logger":"1"*64,"master":"2"*64,"node":"3"*64}
    observed=tmp_path/"ready.json"
    observed.write_text(json.dumps({"installed_images":spec["expected_images"],"configuration_sha256":spec["configuration_sha256"],
        "sensors":[{"provider":"can:0","endpoint":"imu","remote_control":{"configuration_reconciled":True,
            "acquisition_link_compatible":True,"effective":{"available":True,"current":True}}}]}))
    inputs={"bdq":bdq,"manifest":manifest,"serial":serial,"readiness":observed}
    result=ingest(tmp_path/"evidence",spec,inputs)
    report=json.loads((result/"report.json").read_text())
    assert report["comparison_ready"] and report["strict_delivery_accepted"]
    assert report["serial_loss_counter"]["delta"]==0
    result2=ingest(tmp_path/"evidence",spec,{**inputs,"snapshot_missing":tmp_path/"missing.json"})
    report2=json.loads((result2/"report.json").read_text())
    assert not report2["comparison_ready"] and report2["missing_files"]==["snapshot_missing"]
