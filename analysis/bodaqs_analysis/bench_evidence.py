"""Immutable bench evidence intake using canonical readers, with fail-closed joins.

No physical/admission qualification is inferred. Missing historical identities are
unknown; conflicting identities fail. First-loss snapshots never stand in for final.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from .bench_snapshot import validate as validate_snapshot, exact64
from .first_imu_recording import assess_first_imu_recording
from .io_bdq import read_bdq


def digest(path:Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
    return h.hexdigest()


def write_json(path:Path,value) -> None:
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def counter_delta(values:list[int]) -> int|None:
    """One identity/epoch, unsigned cumulative values; resets need new baselines."""
    if not values:return None
    if any(type(n) is not int or n<0 for n in values):raise ValueError("Invalid cumulative counter")
    if any(b<a for a,b in zip(values,values[1:])):return None
    return sum(b-a for a,b in zip(values,values[1:]))


def validate_spec(spec:dict) -> dict:
    if spec.get("schema")!="bodaqs.bench-run.v1" or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",spec.get("run_id","")):
        raise ValueError("Invalid run spec schema/id")
    if spec.get("profile") not in ("production","first-recording","mixed-diagnostic"):
        raise ValueError("Unknown run profile")
    for key in ("candidate_manifest_sha256","configuration_sha256"):
        if not re.fullmatch("[0-9a-f]{64}",spec.get(key,"")):raise ValueError("Missing exact "+key)
    if not isinstance(spec.get("expected_images"),dict) or any(
        not re.fullmatch("[0-9a-f]{64}",h) for h in spec["expected_images"].values()):
        raise ValueError("Invalid image hashes")
    if not isinstance(spec.get("adc_columns"),list) or any(not isinstance(c,str) for c in spec["adc_columns"]):
        raise ValueError("Explicit ADC columns required (empty for IMU only)")
    if type(spec.get("minimum_imu_readings")) is not int or spec["minimum_imu_readings"]<1:
        raise ValueError("Minimum IMU participation must be positive")
    return spec


def make_spec(manifest_path:Path,run_id:str,configuration_sha256:str,adc_columns:list[str]) -> dict:
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status")!="passed":raise ValueError("Requires a passed sealed candidate manifest")
    images={}
    for item in manifest.get("artifacts",[]):
        path=item["path"]
        role="logger" if path.endswith("firmware.bin") else "master" if "master-acquisition/" in path and path.endswith(".out") else "node" if "node-acquisition/" in path and path.endswith(".out") else None
        if role:
            if digest(manifest_path.parent/path)!=item["sha256"]:raise ValueError("Candidate image hash mismatch")
            images[role]=item["sha256"]
    return validate_spec({"schema":"bodaqs.bench-run.v1","run_id":run_id,
        "profile":manifest["candidate_profile"],"candidate_manifest_sha256":digest(manifest_path),
        "configuration_sha256":configuration_sha256,"logger_recipe_id":manifest.get("logger_recipe_id"),
        "expected_images":images,"minimum_imu_readings":1,"adc_columns":adc_columns,
        "expected_imu":{"provider":"can:0","endpoint":"imu"},
        "physical_qualification":"unqualified","required_inputs":["bdq","serial","manifest","readiness"]})


def readiness(spec:dict,observations:dict) -> dict:
    validate_spec(spec)
    checks={"installed_images":set(spec["expected_images"])=={"logger","master","node"} and
            observations.get("installed_images")==spec["expected_images"],
            "configuration":observations.get("configuration_sha256")==spec["configuration_sha256"]}
    want=spec["expected_imu"]
    matches=[s for s in observations.get("sensors",[]) if s.get("provider")==want["provider"] and s.get("endpoint")==want["endpoint"]]
    remote=matches[0].get("remote_control",{}) if len(matches)==1 else {}
    effective=remote.get("effective",{})
    checks["imu_reconciled"]=len(matches)==1 and not matches[0].get("muted",False) and not matches[0].get("runtime_muted",False) and all(
        value is True for value in (remote.get("configuration_reconciled"),remote.get("acquisition_link_compatible"),effective.get("available"),effective.get("current")))
    return {"schema":"bodaqs.bench-readiness.v1","run_id":spec["run_id"],"ready":all(checks.values()),
        "checks":checks,"image_basis":"operator_declared_installed_hashes_not_runtime_attestation"}


def _assess(spec:dict,paths:dict[str,Path]) -> dict:
    gates={name:"unknown" for name in ("manifest_identity","logger_identity","serial_context","snapshot_context","readiness","imu_participation","adc_participation")}
    report={"schema":"bodaqs.bench-evidence.v1","run_id":spec["run_id"],"gates":gates,
            "physical_qualification":"unqualified","whole_run_loss_percent":None,"issues":[]}
    if "manifest" in paths:
        manifest=json.loads(paths["manifest"].read_text(encoding="utf-8"))
        gates["manifest_identity"]="passed" if digest(paths["manifest"])==spec["candidate_manifest_sha256"] and manifest.get("status")=="passed" else "failed"
    if "readiness" in paths:
        observed=json.loads(paths["readiness"].read_text(encoding="utf-8"))
        report["readiness"]=readiness(spec,observed)
        gates["readiness"]="passed" if report["readiness"]["ready"] else "failed"
    if "bdq" in paths:
        try:
            info=read_bdq(paths["bdq"])
            report["file"]={"integrity":not bool(info.detected_errors),"footer_present":bool(info.final_summary),
                            "errors":list(info.detected_errors),"metadata":info.metadata,"catalog":info.stream_catalog}
            recipe=info.metadata.get("firmware_recipe_id")
            expected=spec.get("logger_recipe_id")
            if recipe and recipe!="unknown" and expected:
                gates["logger_identity"]="passed" if recipe==expected else "failed"
            descriptors=info.stream_catalog.get("streams",[])
            primary=next((d for d in descriptors if d.get("stream_key")=="primary"),{})
            columns={c.get("field") for c in primary.get("channels",[])}
            gates["adc_participation"]="passed" if not spec["adc_columns"] or (set(spec["adc_columns"])<=columns and info.stream_record_count(primary.get("stream_id",0))>0) else "failed"
            try:
                assessment,_=assess_first_imu_recording(paths["bdq"])
                report["assessment"]=assessment
                gates["imu_participation"]="passed" if assessment["sample_count"]>=spec["minimum_imu_readings"] else "failed"
                source=assessment["source"]
                report["whole_run_loss_percent"]=assessment["metrics"]["sample_delivery"]["whole_run_missing_percent"]
                if "serial" in paths:
                    serial=paths["serial"].read_text(encoding="utf-8",errors="replace")
                    contexts=re.findall(r"\[FLOW\] stage=finished context=(\d+)",serial)
                    expected_context=int(source["measurement_context"])
                    gates["serial_context"]="passed" if contexts and all(int(c)==expected_context for c in contexts) and "[Logging] stop requested" in serial else "failed"
                    levels=[int(n) for context,n in re.findall(
                        r"\[FLOW\] stage=(?:first_loss|finished) context=(\d+)[^\n]* loss_counter=(\d+)",serial)
                        if int(context)==expected_context]
                    report["serial_loss_counter"]={"unit":"reported_loss_count",
                        "window":"first_serial_observation_to_last_serial_observation",
                        "baseline":levels[0] if levels else None,"endpoint":levels[-1] if levels else None,
                        "delta":counter_delta(levels),"denominator":None,"unique_sample_loss":False}
                snapshots=[p for k,p in paths.items() if k.startswith("snapshot")]
                if snapshots:
                    valid=True
                    report["snapshots"]=[]
                    for path in snapshots:
                        try:
                            snapshot=validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
                            matched=(exact64(snapshot["drain"]["context"])==int(source["measurement_context"]) and
                                exact64(snapshot["drain"]["recording"])==int(source["recording_id"]) and
                                exact64(snapshot["master_boot"])==int(source["master_boot"]))
                            report["snapshots"].append({"scope":snapshot["scope"],"matched":matched,
                                "whole_run":False,"window":"master_START_admission_to_"+snapshot["scope"],
                                "spi_request_drops":{"unit":"requests","baseline":snapshot["drain"]["spi_dropped_base"],
                                    "endpoint":snapshot["drain"]["spi_dropped"],"denominator":None,
                                    "delta":counter_delta([snapshot["drain"]["spi_dropped_base"],snapshot["drain"]["spi_dropped"]])}})
                            valid &= matched
                        except (KeyError,TypeError,ValueError) as error:
                            valid=False;report["issues"].append(str(error))
                    gates["snapshot_context"]="passed" if valid else "failed"
            except (ValueError,KeyError) as error:
                gates["imu_participation"]="failed";report["issues"].append(str(error))
        except (OSError,ValueError,KeyError) as error:
            report["issues"].append(str(error))
    required=["manifest_identity","logger_identity","serial_context","readiness","imu_participation","adc_participation"]
    if any(k.startswith("snapshot") for k in paths):required.append("snapshot_context")
    closed=report.get("file",{}).get("footer_present",False) and report.get("file",{}).get("integrity",False)
    report["comparison_ready"]=closed and all(gates[k]=="passed" for k in required)
    report["strict_delivery_accepted"]=report.get("assessment",{}).get("file_outcome") in (
        "complete_delivery","isolated_five_sample_gap_warning")
    report["classification"]="comparison_ready" if report["comparison_ready"] else "evidence_incomplete" if not closed or any(gates[k]=="unknown" for k in required) else "comparison_rejected"
    report["missing_inputs"]=[k for k in spec.get("required_inputs",[]) if k not in paths]
    return report


def ingest(root:Path,spec:dict,inputs:dict[str,Path]) -> Path:
    """Content-addressed ownership; repeated intake verifies rather than overwrites."""
    validate_spec(spec)
    if any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,40}",k) for k in inputs):raise ValueError("Invalid input role")
    inputs={k:Path(p).resolve() for k,p in inputs.items()}
    missing=[k for k,p in inputs.items() if not p.is_file()]
    inputs={k:p for k,p in inputs.items() if k not in missing}
    hashes={k:digest(p) for k,p in inputs.items()}
    engine_files=("bench_evidence.py","bench_snapshot.py","first_imu_recording.py","io_bdq.py","can_imu_packets.py")
    engine={name:digest(Path(__file__).with_name(name)) for name in engine_files}
    identity={"schema":"bodaqs.bench-intake.v1","spec":spec,"sha256":hashes,"missing_files":missing,"assessment_engine":engine}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    destination=root/key
    if destination.exists():
        inventory=json.loads((destination/"inventory.json").read_text(encoding="utf-8"))
        if inventory.get("content_id")!=key or inventory.get("identity")!=identity:
            raise ValueError("Preserved evidence inventory changed")
        for entry in inventory["files"]:
            if digest(destination/entry["path"])!=entry["sha256"]:raise ValueError("Preserved evidence changed")
        return destination
    root.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix=".intake-",dir=root))
    folder=temporary/"inputs";folder.mkdir()
    paths={};files=[]
    for role,source in inputs.items():
        target=folder/(role+(".bdq" if role=="bdq" else ".log" if role=="serial" else ".json"))
        shutil.copyfile(source,target)
        if digest(source)!=hashes[role] or digest(target)!=hashes[role]:raise ValueError("Input changed during intake")
        paths[role]=target
    write_json(temporary/"run-spec.json",spec)
    try:report=_assess(spec,paths)
    except (ValueError,KeyError,TypeError) as error:
        report={"schema":"bodaqs.bench-evidence.v1","classification":"evidence_incomplete","comparison_ready":False,"issues":[str(error)]}
    if missing:
        report["missing_files"]=missing;report["classification"]="evidence_incomplete";report["comparison_ready"]=False
    # Store paths relative to intake, not its temporary directory.
    if "assessment" in report:report["assessment"]["file"]="inputs/bdq.bdq"
    write_json(temporary/"report.json",report)
    (temporary/"REPORT.md").write_text(f"Run {spec['run_id']}: {report['classification']}\n\n"+
        "\n".join(f"- {k}: {v}" for k,v in report.get("gates",{}).items())+
        "\n\nPhysical qualification remains unqualified. Whole-run loss is unknown without exact source bounds/identity.\n",encoding="utf-8")
    for path in sorted(temporary.rglob("*")):
        if path.is_file():files.append({"path":path.relative_to(temporary).as_posix(),"sha256":digest(path)})
    write_json(temporary/"inventory.json",{"schema":"bodaqs.bench-intake.v1","content_id":key,"identity":identity,"files":files})
    temporary.rename(destination)
    return destination
