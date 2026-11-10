"""Offline bench plans/intake/status. Device stages are dry-run only in this tool."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"analysis"))
from bodaqs_analysis.bench_evidence import digest, ingest, make_spec, readiness, validate_spec, write_json
from bodaqs_analysis.bench_snapshot import ccs_script, validate as validate_snapshot


def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))


def contrast(before:dict,after:dict) -> dict:
    """Facts only; differences are not causal explanations."""
    keys=("candidate_profile","targets","measurement","validation_scope","source","reused_peers","logger_recipe_id")
    result={"schema":"bodaqs.candidate-contrast.v1","changed":{
        k:{"before":before.get(k),"after":after.get(k)} for k in keys if before.get(k)!=after.get(k)},
        "artifacts_before":before.get("artifacts",[]),"artifacts_after":after.get("artifacts",[]),
        "causality":"review_required","missing_fields":"unknown_not_equal",
        "next_measurement":None,"supporting_observations":[],"contradicting_observations":[]}
    result["facts"]={label:{
        "environment":value.get("targets",{}).get("logger"),"profile":value.get("candidate_profile"),
        "protocol_clock_queue_diagnostics":value.get("measurement"),
        "pins_mode_buffer_extent":value.get("bus_contract"),
        "recipe":value.get("logger_recipe_id"),
    } for label,value in (("before",before),("after",after))}
    commits=[v.get("source",{}).get("commit","") for v in (before,after)]
    import re
    if all(re.fullmatch("[0-9a-f]{40}",commit) for commit in commits):
        diff=subprocess.run(["git","diff","--no-ext-diff","--unified=3",*commits,"--",
            "firmware/src/SharedSpiBus.cpp","firmware/src/CanMasterManager.cpp","firmware/src/BoardProfile.cpp",
            "firmware/platformio.ini","firmware/can-fd/master/src/main.c","firmware/can-fd/master/src/master_spi.c"],
            cwd=ROOT,capture_output=True,text=True,check=False)
        result["source_contrast"]=diff.stdout if diff.returncode==0 else None
    else:result["source_contrast"]=None
    return result


def scoped_device_plan(scope:dict,spec:dict) -> dict:
    """Validate future observation/control authority without opening a device.

    No flash, debugger, arbitrary terminal command or endpoint access is supported.
    Actual adapters remain a separately authorized later stage.
    """
    validate_spec(spec)
    if set(scope)-{"schema","run_id","action","port","duration_seconds","expected_images","expires_utc","commands","case_ids"}:
        raise ValueError("Unsupported device authority fields")
    if scope.get("schema")!="bodaqs.bench-device-scope.v1" or scope.get("run_id")!=spec["run_id"]:
        raise ValueError("Device scope/run mismatch")
    if scope.get("action") not in ("serial_observe","bounded_cases") or not isinstance(scope.get("port"),str) or not scope["port"]:
        raise ValueError("Declare a selected port and supported action")
    if type(scope.get("duration_seconds")) is not int or not 1<=scope["duration_seconds"]<=3600:
        raise ValueError("Declare a finite duration (1..3600 seconds)")
    if scope.get("expected_images")!=spec["expected_images"] or set(spec["expected_images"])!={"logger","master","node"}:
        raise ValueError("Expected image identities differ or missing")
    expires=datetime.fromisoformat(scope.get("expires_utc","").replace("Z","+00:00"))
    if expires.tzinfo is None or expires<=datetime.now(timezone.utc):raise ValueError("Device scope expired")
    commands=scope.get("commands",[])
    if not isinstance(commands,list) or len(commands)>32:raise ValueError("Bound case commands")
    if scope["action"]=="serial_observe" and commands:raise ValueError("Observation cannot send commands")
    if scope["action"]=="bounded_cases":
        import re
        ids=[]
        for command in commands:
            if not isinstance(command,str) or len(command)>200 or not re.fullmatch(r"case [0-9]{1,6}(?: [A-Za-z0-9_]+){1,16}",command):
                raise ValueError("Only explicit single-line case commands are supported")
            ids.append(int(command.split()[1]))
        if not ids or len(ids)!=len(set(ids)) or ids!=scope.get("case_ids"):
            raise ValueError("Exact unique finite case IDs required")
    return {"schema":"bodaqs.bench-device-plan.v1","scope":scope,"status":"dry_run_only",
        "stop_conditions":["identity mismatch","duration expired","case outcome missing/failed","operator interruption"],
        "recovery":"retain raw partial capture and classify evidence incomplete; never retry control automatically",
        "devices_accessed":False,"adapter_status":"separate_authorization_and_implementation_required"}


def packet(manifest:Path,config:Path,output:Path,run_id:str,columns:list[str]):
    spec=make_spec(manifest,run_id,digest(config),columns)
    if output.exists():raise ValueError("Select a fresh operator packet directory")
    if set(spec["expected_images"])!={"logger","master","node"}:
        raise ValueError("Operator packet requires all three selected image hashes")
    output.mkdir(parents=True)
    (output/"configuration.txt").write_bytes(config.read_bytes())
    if digest(output/"configuration.txt")!=spec["configuration_sha256"]:raise ValueError("Configuration changed")
    (output/"candidate-manifest.json").write_bytes(manifest.read_bytes())
    if digest(output/"candidate-manifest.json")!=spec["candidate_manifest_sha256"]:raise ValueError("Manifest changed")
    write_json(output/"run-spec.json",spec)
    write_json(output/"readiness-template.json",{"installed_images":None,"configuration_sha256":None,"sensors":[],
        "instruction":"Operator declares installed hashes/config, then copies live /api/v1/sensors entries. Do not treat expected hashes as observed."})
    (output/"export-snapshot.js").write_text(ccs_script(),encoding="utf-8")
    commands={"gate":[sys.executable,str(ROOT/"firmware/tools/bench.py"),"gate","--spec",str(output/"run-spec.json"),"--observations",str(output/"readiness.json")],
        "intake":[sys.executable,str(ROOT/"firmware/tools/bench.py"),"ingest","--spec",str(output/"run-spec.json"),"--output-dir",str(output/"evidence"),
            "--input","manifest="+str(output/"candidate-manifest.json"),"--input","readiness="+str(output/"readiness.json"),
            "--input","bdq=REPLACE_FINALIZED_BDQ_PATH","--input","serial=REPLACE_SERIAL_LOG_PATH"]}
    write_json(output/"commands.json",commands)
    (output/"RUNBOOK.md").write_text(f"# {run_id}\n\nProfile: `{spec['profile']}`. Candidate: `{spec['candidate_manifest_sha256']}`.\n\n"
        "1. Select/install the declared images under the existing manual procedure. This packet performs no flashing.\n"
        "2. With logging stopped, copy live sensors JSON into `readiness.json`; explicitly declare installed image/configuration hashes. Run the gate argv in `commands.json`. Resolve a failed/unknown gate before benchmarking.\n"
        "3. Perform the agreed acquisition. Press the normal logging stop button, preserve STOP/FLOW output and wait for file closure/cleanup. A closed file alone does not prove source STOP.\n"
        "4. Copy the finalized BDQ; retain partial evidence if interrupted. With the selected master halted by the operator, the optional DSS helper exports every array using 32-bit halves; call `exportBodaqsSnapshot(debugSession, exactMasterBootString, true)`. It never connects/halts/resumes/writes/loads an image. Use the layout matching the installed image.\n"
        "5. Replace intake path placeholders in `commands.json`, add `--input snapshot1=PATH` if available, and run the intake argv. Review each gate and completion verdict. Actual IMU records and requested ADC columns must be present.\n\n"
        "Device capture/control stages remain dry-run only. The physical SPI first-byte issue, known-input ADC switching check, controlled storage-stall testing and admission qualification remain outstanding.\n",encoding="utf-8")
    write_json(output/"packet-inventory.json",{"schema":"bodaqs.operator-packet.v1","files":[
        {"path":p.name,"sha256":digest(p)} for p in sorted(output.iterdir()) if p.is_file()]})
    return spec


def status(evidence:Path|None=None,manifest:Path|None=None) -> dict:
    def git(*args):
        result=subprocess.run(["git",*args],cwd=ROOT,capture_output=True,text=True,check=False)
        return result.stdout.strip() if result.returncode==0 else None
    reports=sorted(evidence.glob("*/report.json"),key=lambda p:p.stat().st_mtime) if evidence and evidence.exists() else []
    latest=reports[-1] if reports else None
    value=load(manifest) if manifest else {}
    source=value.get("source",{})
    fixed_pass=(value.get("status")=="passed" and not source.get("tracked_dirty_before",True)
                and not source.get("tracked_changes_after",True) and source.get("commit")==source.get("commit_after"))
    return {"schema":"bodaqs.workspace-status.v1","worktree":str(ROOT),"head":git("rev-parse","HEAD"),
        "branch":git("branch","--show-current"),"dirty":bool(git("status","--porcelain")),
        "expected_bundle":str(manifest.parent) if manifest else None,"profile":value.get("candidate_profile"),
        "runbook":str(manifest.parent/"RUNBOOK.md") if manifest and (manifest.parent/"RUNBOOK.md").exists() else None,
        "latest_assessment":str(latest) if latest else None,"latest_classification":load(latest).get("classification") if latest else None,
        "guardrails":{"command_exists":True,"local_pass_at":source.get("commit") if fixed_pass else None,
            "local_working_edits_passed":value.get("status")=="passed" and not fixed_pass,
            "local_validation_scope":value.get("validation_scope"),"wired_in_branch_ci":(ROOT/".github/workflows/firmware-ci.yml").exists(),
            "remotely_exercised_at":None,"adopted_on_default_branch":None},
        "debt":["physical first-byte SPI fault unresolved","known-input ADC switching unverified","controlled storage stalls deferred",
                "production admission unqualified","remote CI/default-branch adoption not verified"]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("spec","packet"):
        p=sub.add_parser(name);p.add_argument("--manifest",type=Path,required=True);p.add_argument("--config",type=Path,required=True)
        p.add_argument("--run-id",required=True);p.add_argument("--adc-column",action="append",default=[])
        p.add_argument("--output-dir" if name=="packet" else "--output",type=Path,required=True)
    p=sub.add_parser("ingest");p.add_argument("--spec",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--input",action="append",default=[],metavar="ROLE=PATH")
    p=sub.add_parser("gate");p.add_argument("--spec",type=Path,required=True);p.add_argument("--observations",type=Path,required=True)
    p=sub.add_parser("snapshot-script");p.add_argument("--version",type=int,default=5);p.add_argument("--without-phase",action="store_true")
    p.add_argument("--without-queue",action="store_true");p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("check-snapshot");p.add_argument("snapshot",type=Path)
    p=sub.add_parser("compare");p.add_argument("before",type=Path);p.add_argument("after",type=Path)
    p=sub.add_parser("status");p.add_argument("--evidence",type=Path);p.add_argument("--manifest",type=Path)
    p=sub.add_parser("device-plan");p.add_argument("--spec",type=Path,required=True);p.add_argument("--scope",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=="spec":
            value=make_spec(args.manifest,args.run_id,digest(args.config),args.adc_column)
            if args.output.exists():raise ValueError("Output exists")
            write_json(args.output,value)
        elif args.command=="packet":value=packet(args.manifest.resolve(),args.config.resolve(),args.output_dir.resolve(),args.run_id,args.adc_column)
        elif args.command=="ingest":
            entries=[entry.split("=",1) for entry in args.input]
            if any(len(e)!=2 for e in entries) or len({e[0] for e in entries})!=len(entries):raise ValueError("Unique ROLE=PATH entries required")
            destination=ingest(args.output_dir,load(args.spec),{k:Path(p) for k,p in entries})
            value={"evidence":str(destination),"report":load(destination/"report.json")}
        elif args.command=="gate":
            value=readiness(load(args.spec),load(args.observations))
            print(json.dumps(value,indent=2));return 0 if value["ready"] else 1
        elif args.command=="snapshot-script":
            if args.output.exists():raise ValueError("Output exists")
            args.output.write_text(ccs_script(args.version,not args.without_phase,not args.without_queue),encoding="utf-8")
            value={"script":str(args.output),"devices_accessed":False}
        elif args.command=="check-snapshot":validate_snapshot(load(args.snapshot));value={"valid":True}
        elif args.command=="compare":value=contrast(load(args.before),load(args.after))
        elif args.command=="status":value=status(args.evidence,args.manifest)
        else:value=scoped_device_plan(load(args.scope),load(args.spec))
        if args.command=="ingest":print(json.dumps({"evidence":value["evidence"],"classification":value["report"]["classification"]},indent=2))
        else:print(json.dumps(value,indent=2))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(str(error),file=sys.stderr);return 2


if __name__=="__main__":raise SystemExit(main())
