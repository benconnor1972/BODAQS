"""Validate firmware or build a source-pinned candidate without accessing devices.

Host mode validates working edits without a TI SDK. Full candidate mode requires
committed source and includes both TI link profiles, A8, logs, scenario evidence,
checksums and a source archive created after validation. Outputs are external.
Preflight only observes tools/SDK. No mode makes a physical qualification claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from bench_profiles import PROFILES, review_result


ROOT = Path(__file__).resolve().parents[2]
DEFERRED = {
    "175": ["FIFO/DRDY/SYNC association", "SPI rearm and mutex timing",
            "measured four-node throughput and mixed ADC load",
            "clock phase/drift and 10 us alignment", "stack/heap watermarks"],
    "176": ["physical disconnect/reconnect", "CCS halt/resume",
            "node/master reset and electrical fault qualification"],
}
# Import names differ from distribution names for a few test dependencies.
# Versions come from requirements.txt; optional desktop/notebook applications
# are not required to run the firmware/analysis suites.
TEST_IMPORTS = {
    "pytest": "pytest", "numpy": "numpy", "pandas": "pandas", "scipy": "scipy",
    "PyYAML": "yaml", "fastparquet": "fastparquet", "matplotlib": "matplotlib", "plotly": "plotly",
    "fitparse": "fitparse", "fastapi": "fastapi", "uvicorn": "uvicorn",
    "IPython": "IPython", "ipywidgets": "ipywidgets", "traitlets": "traitlets",
    "anywidget": "anywidget", "ipydatagrid": "ipydatagrid", "ipyleaflet": "ipyleaflet",
    "zeroconf": "zeroconf",
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def source_unchanged(commit:str) -> bool:
    return (git("rev-parse","HEAD")==commit and
            not git("status","--porcelain","--untracked-files=no") and
            not any(not p.startswith(".scratch/") for p in git("ls-files","--others","--exclude-standard").splitlines()))


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "host", "candidate"), default="candidate",
                        help="Tool checks only, host validation, or full target candidate (default)")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--make", default=shutil.which("make") or "C:/ti/ccs2101/ccs/utils/bin/gmake.exe")
    parser.add_argument("--cxx", default=shutil.which("g++") or "C:/msys64/ucrt64/bin/g++.exe")
    parser.add_argument("--cc", default=shutil.which("gcc") or "C:/msys64/ucrt64/bin/gcc.exe")
    parser.add_argument("--sdk", type=Path, default=Path("C:/ti/mspm0_sdk_2_11_00_07"))
    parser.add_argument("--ti-compiler", type=Path, default=Path(
        "C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS"))
    parser.add_argument("--sysconfig", type=Path, default=Path(
        "C:/ti/ccs2101/ccs/utils/sysconfig_1.28.1/sysconfig_cli.bat"))
    parser.add_argument("--pio", default=shutil.which("pio") or str(
        Path.home() / ".platformio/penv" / ("Scripts/pio.exe" if os.name == "nt" else "bin/pio")))
    parser.add_argument("--profile", choices=tuple(PROFILES), default="production",
                        help="Select restricted single-IMU v2 candidate explicitly")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--validation-scope", choices=("full", "logger", "master"), default="full",
                        help="Logger scope requires declared unchanged peer images; no full-suite claim")
    parser.add_argument("--reuse-peers", type=Path, help="bodaqs.peer-images.v1 JSON with immutable image paths/hashes")
    parser.add_argument("--experiment",choices=("spi-tx-prime-ab","spi-mode-ab","spi-boundary-trace","spi-disabled-init","spi-init-sustained","adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing"))
    parser.add_argument("--fixed-bundle",type=Path,help="Sealed r5/r6 bundle: preserve exact reference logger/node/master")
    parser.add_argument("--review-result", type=Path, help="bodaqs.review.v1 source-bound result")
    parser.add_argument("--review-base", help="Exact commit reviewed against HEAD")
    parser.add_argument("--list-commands", action="store_true",
                        help="Print command plan without running or creating files")
    return parser.parse_args()


def plan(args: argparse.Namespace, output: Path) -> list[dict]:
    def step(name: str, argv: list[str], artifacts: list[tuple[str, str]] | None = None,
             cwd: Path = ROOT) -> dict:
        return {"name": name, "argv": argv, "cwd": str(cwd),
                "artifacts": artifacts or []}

    def ti_step(target,link,label,extra=()):
        folder=f"firmware/can-fd/{target}/ticlang";basename=f"bodaqs_can_{target}"
        artifacts=[(f"{folder}/{basename}.{suffix}",f"artifacts/{label}/{basename}.{suffix}") for suffix in ("out","map")]
        return step(label,[args.make,"-B","-C",folder,
            f"MSPM0_SDK_INSTALL_DIR={args.sdk.as_posix()}",f"TICLANG_ARMCOMPILER={args.ti_compiler.as_posix()}",
            f"SYSCONFIG_TOOL={args.sysconfig.as_posix()}",f"CAN_LINK_PROFILE={link}",
            *([*PROFILES[args.profile]["master_flags"],"CFLAGS_EXTRA=-fstack-usage"] if target=="master" else []),*extra],artifacts)

    make = [args.make, "-B"]
    recipe = PROFILES[args.profile]
    logger_env = recipe["logger_env"]
    if args.experiment=="adc-ack-pacing":logger_env="bodaqs_s3_mini_n4r2_imu_adc_ack_pacing"
    elif args.experiment=="adc-ack-sweep":logger_env="bodaqs_s3_mini_n4r2_imu_adc_ack_sweep"
    elif args.experiment=="adc-multi-node":logger_env="bodaqs_s3_mini_n4r2_imu_adc_multi_node"
    elif args.experiment=="adc-scaling":logger_env="bodaqs_s3_mini_n4r2_imu_adc_scaling"
    elif args.experiment=="adc-channel-rate":logger_env="bodaqs_s3_mini_n4r2_imu_adc_channel_rate"
    elif args.experiment=="storage-worker-priority":logger_env="bodaqs_s3_mini_n4r2_imu_adc_storage_priority"
    elif args.experiment=="adc-worker-priority":logger_env="bodaqs_s3_mini_n4r2_imu_adc_priority"
    elif args.experiment=="adc-spi-timing":logger_env="bodaqs_s3_mini_n4r2_imu_adc_spi_timing"
    commands = [
        step("a8-dependencies", [args.pio, "pkg", "install", "-d", "firmware", "-e",
             "bodaqs_s3_mini_n4r2"]),
        step("firmware-host", [*make, "-C", "firmware/test", "test",
             f"CXX={args.cxx}", f"CC={args.cc}", f"PYTHON={Path(sys.executable).as_posix()}"]),
        step("common-host", [*make, "-C", "firmware/can-fd/common/test", "test",
             f"CC={args.cc}", f"CXX={args.cxx}", f"PYTHON={Path(sys.executable).as_posix()}"]),
        step("master-host", [*make, "-C", "firmware/can-fd/master/test", "test",
             f"CC={args.cc}", f"PYTHON={Path(sys.executable).as_posix()}"]),
        step("node-host", [*make, "-C", "firmware/can-fd/node/test", "test",
             f"CC={args.cc}"]),
        step("sample-unit-recording", [sys.executable,
             "firmware/tools/test_sample_unit_recording_runtime.py",
             "--compiler", args.cxx, "--cc", args.cc]),
        step("integrated-sample-unit-recording", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py",
             "--first-recording", "--sample-units", "--compiler", args.cxx,
             "--cc", args.cc, "--output-dir", str(output / "sample-unit-scenarios")]),
        step("integrated-two-node-sample-units", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py",
             "--first-recording", "--sample-units", "--two-node", "--compiler", args.cxx,
             "--cc", args.cc, "--output-dir", str(output / "two-node-unit-scenarios")]),
        step("integrated-v3-reclaim", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py",
             "--first-recording", "--sample-units", "--two-node", "--idle-control-fetch", "--compiler", args.cxx,
             "--cc", args.cc, "--output-dir", str(output / "v3-reclaim-scenarios")]),
        step("integrated-v4-window", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py",
             "--window", "--idle-control-fetch", "--compiler", args.cxx,
             "--cc", args.cc, "--output-dir", str(output / "v4-window-scenarios")]),
        step("integrated-v4-pressure", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py",
             "--window", "--idle-control-fetch", "--pressure-diagnostics", "--compiler", args.cxx,
             "--cc", args.cc, "--output-dir", str(output / "v4-pressure-scenarios")]),
        step("bulk-geometry-screen", [sys.executable,
             "firmware/tools/test_window_ack_fairness_runtime.py", "--bulk-screen", "--compiler", args.cxx]),
        step("integrated-v5-bulk512", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py", "--bulk-bytes", "512",
             "--idle-control-fetch", "--pressure-diagnostics", "--compiler", args.cxx,
             "--cc", args.cc, "--output-dir", str(output / "v5-bulk512-scenarios")]),
        step("integrated-v5-bulk1024", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py", "--bulk-bytes", "1024",
             "--idle-control-fetch", "--pressure-diagnostics", "--compiler", args.cxx,
             "--cc", args.cc, "--output-dir", str(output / "v5-bulk1024-scenarios")]),
        step("integrated-v4-four-node", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py",
             "--four-node", "--idle-control-fetch", "--pressure-diagnostics", "--compiler", args.cxx,
             "--cc", args.cc, "--output-dir", str(output / "v4-four-node-scenarios")]),
        step("control-apply-regression", [sys.executable,
             "firmware/tools/test_control_apply_runtime.py", "--compiler", args.cxx]),
        step("integrated-recording", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py",
             "--compiler", args.cxx, "--cc", args.cc,
             "--output-dir", str(output / "scenarios")]),
        step("analysis", [sys.executable, "-m", "pytest", "-q"], cwd=ROOT / "analysis"),
    ]
    if args.profile!="production":
        commands.insert(1,step("restricted-a8-dependencies", [args.pio,"pkg","install","-d","firmware","-e",logger_env]))
        commands.append(step("integrated-first-recording", [sys.executable,
            "firmware/tools/test_integrated_imu_recording_runtime.py", "--first-recording",
            "--compiler", args.cxx, "--cc", args.cc,
            "--output-dir", str(output / "scenarios-first-recording")]))
    if args.validation_scope=="logger":
        commands=[c for c in commands if c["name"] in ("a8-dependencies", "restricted-a8-dependencies", "firmware-host")]
    if args.validation_scope=="master":
        commands=[c for c in commands if c["name"] in ("common-host","master-host")]
        commands.append(step("candidate-runner-tests",[sys.executable,"-m","unittest","discover","-s","firmware/tools","-p","test_*candidate*.py"]))
    elif args.experiment:
        commands.append(step("candidate-runner-tests",[sys.executable,"-m","unittest","discover","-s","firmware/tools","-p","test_*candidate*.py"]))
    if args.experiment in ("adc-multi-node","adc-ack-sweep","adc-ack-pacing"):
        commands.append(step("multi-node-analysis",[sys.executable,"-m","pytest","-q","tests/test_multi_imu_recording.py","tests/test_first_imu_recording.py"],cwd=ROOT/"analysis"))
    if args.mode == "host":
        return commands
    if args.experiment=="spi-tx-prime-ab":
        for label,enabled in (("A",0),("B",1)):
            commands.append(ti_step("master","acquisition","master-"+label,[f"SPI_TX_PRIME={enabled}"]))
        return commands
    if args.experiment=="spi-disabled-init":
        for label,enabled in (("init-reference",0),("init-disabled",1)):
            command=ti_step("master","acquisition","master-"+label,
                ["SPI_TX_PRIME=1","SPI_BENCH_MODE=0","SPI_BOUNDARY_TRACE=1",f"SPI_DISABLED_INIT={enabled}"])
            command["artifacts"] += [(f"firmware/can-fd/master/ticlang/ti_msp_dl_config.{ext}",
                f"artifacts/master-{label}/generated/ti_msp_dl_config.{ext}") for ext in ("c","h")]
            commands.append(command)
        return commands
    if args.experiment in ("spi-mode-ab","spi-boundary-trace","spi-init-sustained","adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing"):
        trace=args.experiment=="spi-boundary-trace"
        sustained=args.experiment=="spi-init-sustained"
        adc_priority=args.experiment in ("adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
        adc_timing=args.experiment in ("adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
        for mode in ((0,) if trace or sustained or adc_timing else (0,1)):
            label="ack_pacing" if args.experiment=="adc-ack-pacing" else "ack_sweep" if args.experiment=="adc-ack-sweep" else "multi_node" if args.experiment=="adc-multi-node" else "scaling" if args.experiment=="adc-scaling" else "channel_rate" if args.experiment=="adc-channel-rate" else "storage_priority" if args.experiment=="storage-worker-priority" else "priority" if adc_priority else "spi_timing" if adc_timing else "sustained" if sustained else "trace" if trace else f"mode{mode}"
            if not adc_timing:
                commands.append(ti_step("master","acquisition","master-"+label,["SPI_TX_PRIME=1",f"SPI_BENCH_MODE={mode}",
                    *(["SPI_BOUNDARY_TRACE=0","SPI_DISABLED_INIT=1"] if sustained else ["SPI_BOUNDARY_TRACE=1"] if trace else [])]))
            logger_env=f"bodaqs_s3_mini_n4r2_imu_adc_{label}"
            folder=f"firmware/.pio/build/{logger_env}"
            commands.append(step("contract-"+label,[sys.executable,"firmware/tools/collect_spi_contract.py",
                "--compiler",args.cxx,"--mode",str(mode),"--output",str(output/f"SPI_SOURCE_CONTRACT_{label}.json")]))
            commands.append(step("logger-clean-"+label,[args.pio,"run","-d","firmware","-e",logger_env,"-t","clean"]))
            commands.append(step("logger-"+label,[args.pio,"run","-d","firmware","-e",logger_env,f"-j{args.jobs}"],
                [(f"{folder}/{name}",f"artifacts/logger-{label}/{name}") for name in
                 ("firmware.elf","firmware.bin","bootloader.bin","partitions.bin","firmware.map","identity/build-recipe.json")]))
        return commands
    for profile in ("bringup", "acquisition"):
        for target in ("node", "master"):
            if args.reuse_peers:
                continue
            commands.append(ti_step(target,profile,f"{target}-{profile}"))
    a8 = f"firmware/.pio/build/{logger_env}"
    commands.append(step("spi-source-contract",[sys.executable,"firmware/tools/collect_spi_contract.py",
        "--compiler",args.cxx,"--output",str(output/"SPI_SOURCE_CONTRACT.json")]))
    commands.append(step("a8-clean", [args.pio, "run", "-d", "firmware", "-e",
        logger_env, "-t", "clean"]))
    commands.append(step("a8-build", [args.pio, "run", "-d", "firmware", "-e",
        logger_env, f"-j{args.jobs}"],
        [(f"{a8}/{name}", f"artifacts/a8-{logger_env}/{name}") for name in
         ("firmware.elf", "firmware.bin", "bootloader.bin", "partitions.bin")]))
    return commands


def load_fixed_bundle(bundle:Path,experiment:str="spi-tx-prime-ab") -> dict:
    """Explicit compatibility reader for the sealed, physically observed r5 pair.

    This declaration is provenance, not runtime image attestation. Unknown node
    source remains unknown. No member can escape the selected bundle directory.
    """
    bundle=bundle.resolve();path=bundle/"BUILD_MANIFEST.json"
    value=json.loads(path.read_text(encoding="utf-8"))
    if experiment in ("spi-boundary-trace","spi-disabled-init","spi-init-sustained","adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing"):
        disabled_init=experiment=="spi-disabled-init"
        sustained=experiment=="spi-init-sustained"
        ack_pacing=experiment=="adc-ack-pacing"
        ack_sweep=experiment in ("adc-ack-sweep","adc-ack-pacing")
        multi_node=experiment in ("adc-multi-node","adc-ack-sweep","adc-ack-pacing")
        scaling=experiment in ("adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
        channel_rate=experiment in ("adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
        storage_priority=experiment in ("storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
        adc_priority=experiment in ("adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
        adc_timing=experiment in ("adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
        expected="adc-ack-sweep" if ack_pacing else "adc-multi-node" if ack_sweep else "adc-scaling" if multi_node else "adc-channel-rate" if scaling else "storage-worker-priority" if channel_rate else "adc-worker-priority" if storage_priority else "adc-spi-timing" if adc_priority else "spi-init-sustained" if adc_timing else "spi-disabled-init" if sustained else "spi-boundary-trace" if disabled_init else "spi-mode-ab"
        parent="r17" if ack_pacing else "r16" if ack_sweep else "r15" if multi_node else "r14" if scaling else "r13" if channel_rate else "r12" if storage_priority else "r11" if adc_priority else "r10" if adc_timing else "r9" if sustained else "r8 trace" if disabled_init else "r7 mode"
        if value.get("status")!="passed" or value.get("candidate_profile")!="mixed-diagnostic" or value.get("experiment")!=expected:
            raise ValueError(f"Experiment requires the passed {parent} bundle")
        selected=value.get("variants",{}).get("ack_sweep" if ack_pacing else "multi_node" if ack_sweep else "scaling" if multi_node else "channel_rate" if scaling else "storage_priority" if channel_rate else "priority" if storage_priority else "spi_timing" if adc_priority else "sustained" if adc_timing else "trace" if disabled_init or sustained else "mode0",{})
        if selected.get("spi_mode")!=0 or selected.get("spi_tx_prime") is not True:
            raise ValueError(f"Rollback requires {parent} primed mode0")
        if (disabled_init or sustained) and (selected.get("boundary_trace_version"),selected.get("boundary_trace_bytes"))!=(1,7328):
            raise ValueError("Disabled initialization requires the exact r8 trace layout")
        if sustained and selected.get("spi_disabled_init") is not True:
            raise ValueError("Sustained control requires r9 disabled initialization")
        if adc_timing and (selected.get("spi_disabled_init") is not True or selected.get("boundary_trace_enabled") is not False):
            raise ValueError("ADC timing requires unchanged r10 disabled-init/trace-off master")
        if adc_priority and (selected.get("adc_spi_phase_timing") is not True or selected.get("master_reused") is not True):
            raise ValueError("ADC priority trial requires the r11 phase-timing logger and reused master")
        if storage_priority and selected.get("adc_task_priority")!=3:
            raise ValueError("Storage priority trial requires the r12 priority-3 ADC logger")
        if channel_rate and selected.get("storage_task_priority")!=2:
            raise ValueError("Channel/rate bench requires r13 storage priority2")
        if scaling and selected.get("adc_channel_rate_bench") is not True:
            raise ValueError("Scaling bench requires r14 channel/rate scope")
        if multi_node and selected.get("adc_scaling_bench") is not True:
            raise ValueError("Multi-node bench requires r15 scaling scope")
        if ack_sweep and selected.get("multi_node_bench") is not True:
            raise ValueError("ACK-fetch sweep requires r16 multi-node scope")
        if ack_pacing and selected.get("ack_fetch_fragment_sweep") is not True:
            raise ValueError("Pacing requires the sealed r17 ACK-fetch sweep")
        images=[]
        for role,key in (("logger","logger"),("rollback-master","master"),("node",None)):
            matches=([a for a in value["artifacts"] if a.get("role")=="node"] if key is None else
                     [a for a in value["artifacts"] if a["path"]==selected[key]["path"] and a["sha256"]==selected[key]["sha256"]])
            if len(matches)!=1:raise ValueError("Missing or duplicate r7 fixed artifact")
            image=matches[0];source=(bundle/image["path"]).resolve()
            if bundle not in source.parents or sha256(source)!=image["sha256"]:raise ValueError("r7 fixed image path/hash mismatch")
            provenance=([a for a in value["fixed_bundle"]["images"] if a["role"]=="node"] if key is None else [])
            if key is None and len(provenance)!=1:raise ValueError("Missing r7 node provenance")
            source_commit=provenance[0].get("source_commit") if key is None else value["source"]["commit"]
            if adc_priority and role=="rollback-master":
                provenance=[a for a in value["fixed_bundle"]["images"]
                            if a["role"]==role and a["sha256"]==image["sha256"]]
                if len(provenance)!=1 or not provenance[0].get("source_commit"):
                    raise ValueError("Missing reused r10 master provenance")
                source_commit=provenance[0]["source_commit"]
            if sustained and role=="logger":
                provenance=[a for a in value["fixed_bundle"]["images"]
                            if a["role"]=="logger" and a["sha256"]==image["sha256"]]
                if len(provenance)!=1 or not provenance[0].get("source_commit"):
                    raise ValueError("Missing or duplicate r9 reused logger provenance")
                source_commit=provenance[0]["source_commit"]
            images.append({"role":role,"path":image["path"],"sha256":image["sha256"],
                           "source_commit":source_commit})
        return {"manifest_sha256":sha256(path),"bundle":str(bundle),"images":images,
                "firmware_name":"bodaqs_a8_imu_adc_ack_sweep_r17" if ack_pacing else "bodaqs_a8_imu_adc_multi_node_r16" if ack_sweep else "bodaqs_a8_imu_adc_scaling_r15" if multi_node else "bodaqs_a8_imu_adc_channel_rate_r14" if scaling else "bodaqs_a8_imu_adc_storage_priority_r13" if channel_rate else "bodaqs_a8_imu_adc_priority_r12" if storage_priority else "bodaqs_a8_imu_adc_spi_timing_r11" if adc_priority else "bodaqs_a8_imu_adc_sustained_r10" if adc_timing else "bodaqs_a8_imu_adc_trace_r8" if disabled_init or sustained else "bodaqs_a8_imu_adc_mode0_r7",
                "configuration":"operator_preserves_same_mixed_configuration"}
    if experiment=="spi-mode-ab" and value.get("experiment")!="spi-tx-prime-ab":
        raise ValueError("Mode comparison requires the sealed r6 primed-master bundle, not r5")
    if value.get("experiment")=="spi-tx-prime-ab":
        if experiment!="spi-mode-ab":raise ValueError("Priming comparison requires the sealed r5 bundle")
        if value.get("status")!="passed" or value.get("candidate_profile")!="mixed-diagnostic" or value.get("variants",{}).get("B",{}).get("spi_tx_prime") is not True:
            raise ValueError("Mode comparison requires the passed r6 primed-master bundle")
        def one(items,predicate):
            selected=[item for item in items if predicate(item)]
            if len(selected)!=1:raise ValueError("Missing or duplicate r6 fixed artifact")
            return selected[0]
        images=[]
        for role in ("logger","node","rollback-master"):
            if role=="rollback-master":
                image=value["variants"]["B"]
                artifact=one(value["artifacts"],lambda a:a["path"]==image["path"])
                if artifact["sha256"]!=image["sha256"]:raise ValueError("r6 variant/artifact hash mismatch")
                source_commit=value["source"]["commit"]
            else:
                image=one(value["artifacts"],lambda a:a.get("role")==role)
                source_commit=one(value["fixed_bundle"]["images"],lambda a:a["role"]==role).get("source_commit")
            source=(bundle/image["path"]).resolve()
            if bundle not in source.parents or sha256(source)!=image["sha256"]:
                raise ValueError("r6 fixed image path/hash mismatch")
            images.append({"role":role,"path":image["path"],"sha256":image["sha256"],"source_commit":source_commit})
        firmware_name=value["fixed_bundle"]["firmware_name"]
        if firmware_name!="bodaqs_a8_imu_adc_buffers_r5":raise ValueError("Unexpected r6 logger")
        return {"manifest_sha256":sha256(path),"bundle":str(bundle),"images":images,
                "firmware_name":firmware_name,"configuration":"operator_preserves_same_mixed_configuration"}
    if value.get("environment")!="bodaqs_s3_mini_n4r2_imu_adc_smoke" or value.get("application",{}).get("firmware_name")!="bodaqs_a8_imu_adc_buffers_r5":
        raise ValueError("A/B requires the existing r5 logger bundle")
    images=[]
    for role,key in (("logger","application"),("node","unchanged_node"),("rollback-master","unchanged_master")):
        image=value[key];source=(bundle/image["path"]).resolve()
        if bundle not in source.parents:raise ValueError("Fixed image escapes selected bundle")
        if sha256(source)!=image["sha256"]:raise ValueError("Fixed image hash mismatch")
        images.append({"role":role,"path":image["path"],"sha256":image["sha256"],
            "source_commit":value.get("source_commit") if role=="logger" else image.get("source_commit")})
    return {"manifest_sha256":sha256(path),"bundle":str(bundle),"images":images,
            "firmware_name":value["application"]["firmware_name"],"configuration":"operator_preserves_same_mixed_configuration"}


def load_peers(path: Path, profile: str) -> dict:
    import re
    value=json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema")!="bodaqs.peer-images.v1" or value.get("profile")!=profile:
        raise ValueError("Peer declaration schema/profile mismatch")
    if {i.get("role") for i in value.get("images", [])}!={"master", "node"} or len(value["images"])!=2:
        raise ValueError("Declare exactly master and node images")
    for image in value["images"]:
        source=(path.parent / image["path"]).resolve()
        if source.suffix!=".out" or image.get("sha256")!=sha256(source) or not re.fullmatch("[0-9a-f]{40}",image.get("source_commit","")):
            raise ValueError("Peer image hash/source missing or mismatched")
        if image.get("can_link_profile")!="acquisition":
            raise ValueError("Reused peers must declare matching acquisition link")
        if image["role"]=="master" and image.get("settings",{}).get("measurement_version")!=(1 if profile=="production" else 2):
            raise ValueError("Reused master measurement version does not match logger")
        if image["role"]=="master" and profile=="mixed-diagnostic" and image.get("settings")!={
                "spi_rx_capacity":2,"measurement_version":2,"phase_timing":True,"queue_timing":True}:
            raise ValueError("Reused mixed master must declare RX2/v2/phase/queue diagnostics")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def boot_app0_path() -> Path:
    return Path.home()/".platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin"


def write_manifest(output: Path, manifest: dict) -> None:
    (output / "BUILD_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def preflight(args: argparse.Namespace) -> list[dict]:
    """Observe tools and target SDK before creating output or running a build."""
    if args.mode != "host":
        metadata = args.sdk / ".metadata/product.json"
        try:
            version = json.loads(metadata.read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError) as error:
            raise RuntimeError(f"Invalid MSPM0 SDK metadata: {metadata}") from error
        if not version:
            raise RuntimeError("MSPM0 SDK version is missing")
    dependency_probe = """
import importlib, importlib.metadata, json, sys
from pathlib import Path
required = json.loads(sys.argv[2])
pins = {}
for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    line = line.split('#', 1)[0].strip()
    if '==' in line:
        name, version = line.split('==', 1)
        pins[name.lower()] = version
for name, module in required.items():
    expected = pins[name.lower()]
    actual = importlib.metadata.version(name)
    if actual != expected:
        raise RuntimeError(f'{name}: expected {expected}, found {actual}')
    importlib.import_module(module)
print(f'Validated {len(required)} Python test dependency versions/imports')
"""
    versions = [[sys.executable, "-c", dependency_probe, str(ROOT / "requirements.txt"), json.dumps(TEST_IMPORTS)],
                ["git", "--version"], [sys.executable, "--version"],
                [sys.executable, "-c", "import importlib.metadata as m; "
                 "print('\\n'.join(sorted(str(d.metadata['Name'])+'=='+d.version for d in m.distributions())))"],
                [args.cxx, "--version"], [args.cc, "--version"], [args.make, "--version"],
                [args.pio, "--version"]]
    if args.experiment in ("spi-boundary-trace","spi-disabled-init"):
        versions.append([shutil.which("node") or "node","--version"])
    if args.mode != "host":
        compiler = args.ti_compiler / "bin" / ("tiarmclang.exe" if os.name == "nt" else "tiarmclang")
        versions += [[str(compiler), "--version"], [str(args.sysconfig), "--version"]]
    observed = []
    env = build_environment(args)
    for index, argv in enumerate(versions):
        result = subprocess.run(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", check=False)
        if result.returncode:
            label = "Python dependencies" if index == 0 else f"Tool {argv}"
            raise RuntimeError(f"{label} check failed: {result.stdout}")
        observed.append({"argv": argv, "exit_code": result.returncode, "output": result.stdout})
    return observed


def build_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    compiler = shutil.which(args.cxx) or args.cxx
    env["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + env.get("PATH", "")
    env["CXX"] = args.cxx
    env["PYTHONPATH"] = str(ROOT / "analysis")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def main() -> int:
    args = arguments()
    if args.jobs < 1:
        raise SystemExit("--jobs must be positive")
    if args.validation_scope=="logger" and not args.reuse_peers and args.experiment not in ("adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing"):
        raise SystemExit("Logger-only validation requires --reuse-peers")
    if args.experiment:
        if args.mode!="candidate" or args.profile!="mixed-diagnostic" or not args.fixed_bundle or args.reuse_peers:
            raise SystemExit("SPI comparison requires candidate/mixed-diagnostic, --fixed-bundle and no --reuse-peers")
        if args.experiment in ("spi-mode-ab","spi-boundary-trace","spi-init-sustained") and args.validation_scope!="full":
            raise SystemExit("Mode comparison changes both endpoints and requires full validation scope")
        if args.experiment in ("adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing") and args.validation_scope!="logger":
            raise SystemExit("ADC phase timing uses logger-only scope and unchanged r10 peers")
    elif args.fixed_bundle or args.validation_scope=="master":
        raise SystemExit("Fixed bundle/master-only scope requires an explicit experiment")
    if sys.flags.optimize or os.environ.get("PYTHONOPTIMIZE"):
        raise SystemExit("Run acceptance with Python assertions enabled (no PYTHONOPTIMIZE or -O)")
    if args.mode != "preflight" and args.output_dir is None:
        raise SystemExit("--output-dir is required for host validation and candidates")
    output = args.output_dir.resolve() if args.output_dir else ROOT.parent / "candidate-plan"
    if args.mode != "preflight" and (output == ROOT or ROOT in output.parents):
        raise SystemExit("Candidate output must be outside the source worktree")
    commands = [] if args.mode == "preflight" else plan(args, output)
    if args.list_commands:
        print(json.dumps(commands, indent=2))
        return 0
    if args.mode != "preflight" and output.exists():
        raise SystemExit("Output already exists; select a fresh candidate directory")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty and args.mode == "candidate":
        raise SystemExit("Commit or preserve tracked changes before building a source-pinned candidate")
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    # Integration-local handoff/evidence is deliberately outside committed code.
    unexpected = [name for name in untracked if not name.startswith(".scratch/")]
    if unexpected and args.mode == "candidate":
        raise SystemExit("Untracked files could affect the build: " + ", ".join(unexpected))
    source_commit=git("rev-parse","HEAD")
    source_tree=git("rev-parse",source_commit+"^{tree}")
    try:
        peers=load_peers(args.reuse_peers,args.profile) if args.reuse_peers else None
        fixed=load_fixed_bundle(args.fixed_bundle,args.experiment) if args.fixed_bundle else None
        review=None
        if args.review_result:
            review=review_result(json.loads(args.review_result.read_text(encoding="utf-8")),
                                 args.review_base,source_commit)
            for item in review["evidence"]:
                if sha256((args.review_result.parent / item["path"]).resolve())!=item["sha256"]:
                    raise ValueError("Review evidence hash mismatch")
        if args.mode=="candidate" and args.profile=="mixed-diagnostic" and not review:
            raise ValueError("Mixed candidate requires --review-result and --review-base")
    except (OSError, ValueError, KeyError) as error:
        print(error,file=sys.stderr)
        return 1
    try:
        tools = preflight(args)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.mode == "preflight":
        print("Tool, Python dependency and SDK preflight passed; no output, builds or device access.")
        return 0
    if args.mode=="candidate" and not source_unchanged(source_commit):
        print("Source changed during preflight; refusing a different reviewed candidate",file=sys.stderr)
        return 1

    output.mkdir(parents=True)
    (output / "logs").mkdir()
    env = build_environment(args)
    manifest = {
        "kind": "local-software-candidate" if args.mode == "candidate" else "host-validation", "status": "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"commit": source_commit, "tree": source_tree,
                   "tracked_dirty_before": bool(dirty), "untracked_before": untracked},
        "targets": {"node": "MSPM0G3507", "master": "MSPM0G3518",
                    "logger": PROFILES[args.profile]["logger_env"]},
        "candidate_profile": args.profile,
        "measurement": PROFILES[args.profile]["measurement"],
        "validation_scope":args.validation_scope,"review":review,"reused_peers":peers,
        "experiment":args.experiment,"fixed_bundle":fixed,
        "logger_flash_offsets":{"bootloader.bin":"0x0","partitions.bin":"0x8000","boot_app0.bin":"0xe000","firmware.bin":"0x10000"},
        "acquisition": {"lease_ms":5000,"renewal_ms":1000,"challenge_ms":300},
        "link_profiles": {"bringup": [500000, 2000000], "acquisition": [1000000, 4000000]},
        "sdk": str(args.sdk.resolve()) if args.mode == "candidate" else None,
        "validation_mode": args.mode, "qualification": "physical qualification deferred",
        "build_environment": {key: env.get(key) for key in (
            "PATH", "PYTHONPATH", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "MAKEFLAGS",
            "PLATFORMIO_BUILD_FLAGS", "PLATFORMIO_BUILD_SRC_FLAGS")},
        "production_remote_admission": "unqualified/unsupported until measured bounds supplied",
        "deferred": DEFERRED, "commands": [], "artifacts": [],
    }
    try:
        if fixed:
            for image in fixed["images"]:
                source=Path(fixed["bundle"])/image["path"]
                destination=f"artifacts/fixed-{image['role']}/{source.name}"
                target=output/destination;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
                if sha256(target)!=image["sha256"] or sha256(source)!=image["sha256"]:raise RuntimeError("Fixed image changed during copy")
                manifest["artifacts"].append({"path":destination,"sha256":image["sha256"],"bytes":target.stat().st_size,"reused":True,"role":image["role"]})
            shutil.copyfile(args.fixed_bundle/"BUILD_MANIFEST.json",output/"FIXED_BUNDLE_MANIFEST.json")
            if sha256(output/"FIXED_BUNDLE_MANIFEST.json")!=fixed["manifest_sha256"]:raise RuntimeError("Fixed manifest changed")
        if peers:
            for image in peers["images"]:
                source=(args.reuse_peers.parent/image["path"]).resolve()
                destination=f"artifacts/{image['role']}-acquisition/{source.name}"
                target=output/destination;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,target)
                if sha256(target)!=image["sha256"]: raise RuntimeError("Peer changed during copy")
                manifest["artifacts"].append({"path":destination,"sha256":sha256(target),"bytes":target.stat().st_size,"reused":True})
        if args.mode == "candidate":
            shutil.copyfile(args.sdk / ".metadata/product.json", output / "MSPM0_SDK_PRODUCT.json")
        for index, tool in enumerate(tools):
            log = output / "logs" / f"tool-{index}.txt"
            log.write_text(tool["output"], encoding="utf-8")
            manifest.setdefault("tools", []).append(
                {"argv": tool["argv"], "exit_code": tool["exit_code"], "log": log.relative_to(output).as_posix()})
        write_manifest(output, manifest)
        for command in commands:
            print(f"Running {command['name']} (log: {output / 'logs'})", flush=True)
            log = output / "logs" / f"{command['name']}.txt"
            started = datetime.now(timezone.utc).isoformat()
            with log.open("wb") as stream:
                result = subprocess.run(command["argv"], cwd=command["cwd"], env=env,
                                        stdout=stream, stderr=subprocess.STDOUT, check=False)
            entry = {**command, "started_utc": started, "exit_code": result.returncode,
                     "log": log.relative_to(output).as_posix()}
            manifest["commands"].append(entry)
            write_manifest(output, manifest)
            if result.returncode:
                raise RuntimeError(f"{command['name']} failed; inspect {log}")
            for source, destination in command["artifacts"]:
                artifact = ROOT / source
                target = output / destination
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(artifact, target)
                manifest["artifacts"].append({"path": destination, "source": source,
                                               "bytes": target.stat().st_size, "sha256": sha256(target)})
            if command["name"].startswith("master-") and command["artifacts"]:
                for source in sorted((ROOT / "firmware/can-fd/master/ticlang").glob("*.su")):
                    destination=f"artifacts/{command['name']}/stack/{source.name}"
                    target=output / destination;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,target)
                    manifest["artifacts"].append({"path":destination,"bytes":target.stat().st_size,"sha256":sha256(target)})
                    source.unlink() # Only generated compiler reports just collected.
        if args.experiment=="spi-tx-prime-ab":
            variants={}
            for variant,enabled in (("A",False),("B",True)):
                image=next((item for item in manifest["artifacts"] if item["path"]==f"artifacts/master-{variant}/bodaqs_can_master.out"),None)
                if image is None:raise RuntimeError("Missing A/B master image")
                variants[variant]={"spi_tx_prime":enabled,"path":image["path"],"sha256":image["sha256"]}
            if variants["A"]["sha256"]==variants["B"]["sha256"]:raise RuntimeError("A/B images are identical; priming control was not built")
            manifest["variants"]=variants
        if args.experiment=="spi-disabled-init":
            def unique_artifact(predicate):
                matches=[a for a in manifest["artifacts"] if predicate(a)]
                if len(matches)!=1:raise RuntimeError("Missing or duplicate initialization-control artifact")
                return {key:matches[0][key] for key in ("path","sha256")}
            selected=unique_artifact(lambda a:a["path"]=="artifacts/master-init-disabled/bodaqs_can_master.out")
            reference=unique_artifact(lambda a:a["path"]=="artifacts/master-init-reference/bodaqs_can_master.out")
            logger=unique_artifact(lambda a:a.get("role")=="logger")
            if selected["sha256"]==reference["sha256"]:raise RuntimeError("Initialization control images are identical")
            if b"bodaqs_a8_imu_adc_trace_r8" not in (output/logger["path"]).read_bytes():
                raise RuntimeError("Fixed logger is not the r8 trace image")
            generated=[output/f"artifacts/master-{label}/generated/ti_msp_dl_config.c" for label in ("init-reference","init-disabled")]
            if generated[0].read_bytes()!=generated[1].read_bytes():raise RuntimeError("Generated configuration changed between initialization variants")
            manifest["variants"]={"trace":{"spi_mode":0,"spi_tx_prime":True,"spi_disabled_init":True,
                "boundary_trace_version":1,"boundary_trace_bytes":7328,"master":selected,"logger":logger}}
            manifest["compatibility_reference"]={"spi_disabled_init":False,"master":reference}
            manifest["targets"]["logger"]="unchanged sealed r8 trace image"
        if args.experiment in ("spi-mode-ab","spi-boundary-trace","spi-init-sustained","adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing"):
            variants={}
            trace=args.experiment=="spi-boundary-trace"
            sustained=args.experiment=="spi-init-sustained"
            adc_priority=args.experiment in ("adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
            adc_timing=args.experiment in ("adc-spi-timing","adc-worker-priority","storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing")
            for mode in ((0,) if trace or sustained or adc_timing else (0,1)):
                label="ack_pacing" if args.experiment=="adc-ack-pacing" else "ack_sweep" if args.experiment=="adc-ack-sweep" else "multi_node" if args.experiment=="adc-multi-node" else "scaling" if args.experiment=="adc-scaling" else "channel_rate" if args.experiment=="adc-channel-rate" else "storage_priority" if args.experiment=="storage-worker-priority" else "priority" if adc_priority else "spi_timing" if adc_timing else "sustained" if sustained else "trace" if trace else f"mode{mode}"
                def artifact(path):
                    selected=next((a for a in manifest["artifacts"] if a["path"]==path),None)
                    if selected is None:raise RuntimeError("Missing paired mode artifact: "+path)
                    return {key:selected[key] for key in ("path","sha256")}
                variants[label]={"spi_mode":mode,"spi_tx_prime":True,
                    "master":artifact(next(a["path"] for a in manifest["artifacts"] if a.get("role")=="rollback-master") if adc_timing else f"artifacts/master-{label}/bodaqs_can_master.out"),
                    "logger":artifact(f"artifacts/logger-{label}/firmware.bin")}
                expected_name="bodaqs_a8_imu_adc_ack_pacing_r18" if args.experiment=="adc-ack-pacing" else "bodaqs_a8_imu_adc_ack_sweep_r17" if args.experiment=="adc-ack-sweep" else "bodaqs_a8_imu_adc_multi_node_r16" if args.experiment=="adc-multi-node" else "bodaqs_a8_imu_adc_scaling_r15" if args.experiment=="adc-scaling" else "bodaqs_a8_imu_adc_channel_rate_r14" if args.experiment=="adc-channel-rate" else "bodaqs_a8_imu_adc_storage_priority_r13" if args.experiment=="storage-worker-priority" else "bodaqs_a8_imu_adc_priority_r12" if adc_priority else "bodaqs_a8_imu_adc_spi_timing_r11" if adc_timing else "bodaqs_a8_imu_adc_sustained_r10" if sustained else "bodaqs_a8_imu_adc_trace_r8" if trace else f"bodaqs_a8_imu_adc_{label}_r7"
                if expected_name.encode() not in (output/variants[label]["logger"]["path"]).read_bytes():
                    raise RuntimeError("Logger binary is missing its selected mode identity")
                recipe=json.loads((output/f"artifacts/logger-{label}/identity/build-recipe.json").read_text(encoding="utf-8"))
                variants[label]["logger"]["recipe_id"]=recipe["id"]
                variants[label]["logger"]["environment"]=f"bodaqs_s3_mini_n4r2_imu_adc_{label}"
                variants[label]["bus_contract"]=json.loads((output/f"SPI_SOURCE_CONTRACT_{label}.json").read_text(encoding="utf-8"))
                if variants[label]["bus_contract"]["spi_mode"]!=mode:raise RuntimeError("Compiled mode contract mismatch")
                if sustained or adc_timing:
                    variants[label].update(spi_disabled_init=True,boundary_trace_enabled=False)
                if adc_timing:variants[label].update(adc_spi_phase_timing=True,master_reused=True,adc_task_priority=3 if adc_priority else 2)
                if args.experiment in ("storage-worker-priority","adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing"):variants[label].update(storage_task_priority=2)
                if args.experiment in ("adc-channel-rate","adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing"):variants[label].update(adc_channel_rate_bench=True)
                if args.experiment in ("adc-scaling","adc-multi-node","adc-ack-sweep","adc-ack-pacing"):variants[label].update(adc_scaling_bench=True)
                if args.experiment in ("adc-multi-node","adc-ack-sweep","adc-ack-pacing"):variants[label].update(multi_node_bench=True)
                if args.experiment in ("adc-ack-sweep","adc-ack-pacing"):variants[label].update(ack_fetch_fragment_sweep=True)
                if args.experiment=="adc-ack-pacing":
                    variants[label].update(minimum_start_spacing_us=600)
                    manifest["measurement"]={**manifest["measurement"],"minimum_start_spacing_us":600}
                source=boot_app0_path()
                target=output/f"artifacts/logger-{label}/boot_app0.bin";shutil.copyfile(source,target)
                manifest["artifacts"].append({"path":target.relative_to(output).as_posix(),"sha256":sha256(target),"bytes":target.stat().st_size})
            for role in (() if trace or sustained or adc_timing else ("master","logger")):
                if variants["mode0"][role]["sha256"]==variants["mode1"][role]["sha256"]:
                    raise RuntimeError("Mode0/1 images are identical: "+role)
            manifest["variants"]=variants
            manifest["targets"]["logger"]=[v["logger"]["environment"] for v in variants.values()]
        # Existing toolchains create these optional diagnostics on some versions.
        logger_env=PROFILES[args.profile]["logger_env"]
        a8_folder = ROOT / f"firmware/.pio/build/{logger_env}"
        for optional in ("firmware.map", "idedata.json", "identity/build-recipe.json"):
            source = a8_folder / optional
            if args.mode == "candidate" and not args.experiment and source.exists():
                target=output/f"artifacts/a8-{logger_env}"/optional
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
                manifest["artifacts"].append({"path":target.relative_to(output).as_posix(),"sha256":sha256(target),"bytes":target.stat().st_size})
                if optional.endswith("build-recipe.json"):
                    manifest["logger_recipe_id"]=json.loads(target.read_text(encoding="utf-8"))["id"]
        if (output/"SPI_SOURCE_CONTRACT.json").exists():
            manifest["bus_contract"]=json.loads((output/"SPI_SOURCE_CONTRACT.json").read_text(encoding="utf-8"))
        if args.mode=="candidate" and args.experiment:
            runbook={"spi-mode-ab":"CAN-FD_SPI_Mode_Bench.md","spi-boundary-trace":"CAN-FD_SPI_Boundary_Trace_Runbook.md","spi-disabled-init":"CAN-FD_SPI_Disabled_Init_Runbook.md","spi-init-sustained":"CAN-FD_SPI_Init_Sustained_Runbook.md","adc-spi-timing":"ADC_SPI_Phase_Timing_Runbook.md","adc-worker-priority":"ADC_Worker_Priority_Runbook.md","storage-worker-priority":"Storage_Worker_Priority_Runbook.md","adc-channel-rate":"ADC_Channel_Rate_Runbook.md","adc-scaling":"ADC_Four_Channel_Scaling_Runbook.md","adc-multi-node":"IMU_Multi_Node_Polling_Runbook.md","adc-ack-sweep":"IMU_ACK_Fetch_Sweep_Runbook.md","adc-ack-pacing":"IMU_Drain_Efficiency_Round18.md"}.get(args.experiment,"CAN-FD_SPI_TX_Priming_Bench.md")
            shutil.copyfile(ROOT/"docs/firmware"/runbook,output/"RUNBOOK.md")
            if args.experiment in ("adc-multi-node","adc-ack-sweep","adc-ack-pacing"):
                for name in ("prepare_multi_node_cases.py","assess_multi_imu_recording.py"):
                    shutil.copyfile(ROOT/"firmware/tools"/name,output/name)
            if args.experiment=="adc-channel-rate":
                shutil.copyfile(ROOT/"firmware/tools/prepare_adc_channel_cases.py",output/"prepare_adc_channel_cases.py")
            if args.experiment in ("spi-boundary-trace","spi-disabled-init"):
                shutil.copyfile(ROOT/"firmware/tools/export_spi_trace.js",output/"export_spi_trace.js")
                shutil.copyfile(ROOT/"firmware/can-fd/master/ticlang/MSPM0G3518_XDS110.ccxml",output/"MASTER_TARGET.ccxml")
                manifest["variants"]["trace"]["boundary_trace_version"]=1
                manifest["variants"]["trace"]["boundary_trace_bytes"]=7328
        if args.mode == "candidate" and args.profile!="production" and not args.experiment:
            runbook="Bench_Automation.md" if args.profile=="mixed-diagnostic" else "CAN-FD_First_Recording_Runbook.md"
            extras=[(ROOT / "docs/firmware" / runbook, "RUNBOOK.md"),
                    (boot_app0_path(),
                     f"artifacts/a8-{logger_env}/boot_app0.bin")]
            for source,destination in extras:
                target=output / destination;shutil.copyfile(source,target)
                manifest["artifacts"].append({"path":destination,"bytes":target.stat().st_size,"sha256":sha256(target)})
        if args.mode == "candidate":
            if not source_unchanged(source_commit):
                raise RuntimeError("Source changed during validation; refusing to archive")
            subprocess.run(["git", "archive", "--format=zip", "--output", str(output / "SOURCE.zip"),
                            manifest["source"]["commit"]], cwd=ROOT, check=True)
        manifest["status"] = "passed"
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        print(error, file=sys.stderr)
    finally:
        manifest["source"]["tracked_changes_after"] = git("status", "--porcelain", "--untracked-files=no")
        manifest["source"]["commit_after"] = git("rev-parse", "HEAD")
        if args.mode == "candidate" and not source_unchanged(source_commit):
            manifest["status"] = "failed"
            manifest["error"] = "Source changed during acceptance; candidate is not a fixed-source pass"
        if manifest["status"] != "passed":
            # Output was freshly created by this invocation. Keep diagnostics,
            # but never retain a partial or source-rejected candidate archive.
            (output / "SOURCE.zip").unlink(missing_ok=True)
        write_manifest(output, manifest)
        (output / "README.txt").write_text(
            ("Local IMU software candidate.\n" if args.mode == "candidate" else
             "Host validation only; no target images or source archive were produced.\n") +
            "No devices were accessed.\n"
            "Inspect BUILD_MANIFEST.json status and logs before using artifacts.\n" +
            ("r17 ACK-fetch fragment sweep: install selected logger; retain exact master/node/config. See RUNBOOK.md.\n" if args.experiment=="adc-ack-sweep" else
             "r16 multi-node polling bench: install selected logger; retain exact r10 master/node. See RUNBOOK.md.\n" if args.experiment=="adc-multi-node" else
             "r15 four-channel scaling: install ONLY selected logger; retain r10 master/node/settings. See RUNBOOK.md.\n" if args.experiment=="adc-scaling" else
             "r14 channel/rate bench: install ONLY selected logger; retain r10 master/node/settings. See RUNBOOK.md.\n" if args.experiment=="adc-channel-rate" else
             "r13 storage priority trial: install ONLY selected logger; retain r10 master/node/settings. See RUNBOOK.md.\n" if args.experiment=="storage-worker-priority" else
             "r12 ADC priority trial: install ONLY selected logger; retain r10 master/node/settings. See RUNBOOK.md.\n" if args.experiment=="adc-worker-priority" else
             "r11 ADC SPI timing: install ONLY selected logger; retain r10 master/node/settings. See RUNBOOK.md.\n" if args.experiment=="adc-spi-timing" else
             "r10 sustained pair: install BOTH selected logger/master; retain node/configuration. See RUNBOOK.md.\n" if args.experiment=="spi-init-sustained" else
             "r9 master-only initialization control; retain installed r8 logger and node. See RUNBOOK.md.\n" if args.experiment=="spi-disabled-init" else
             "Matched r8 trace pair: flash BOTH logger and master manually. Keep fixed node. See RUNBOOK.md.\n" if args.experiment=="spi-boundary-trace" else
             "Paired mode trial: select BOTH logger and master from the same variant. Keep fixed node. See RUNBOOK.md.\n" if args.experiment=="spi-mode-ab" else
             "Master-only A/B; keep fixed r5 logger/node installed. See RUNBOOK.md and variants in BUILD_MANIFEST.json.\n" if args.experiment else
             "Both TI profiles are separate artifacts; both endpoints must match.\n"
             "A8 images are separate bootloader/partition/application outputs, not a merged flash image.\n"
             if args.mode == "candidate" else "Only host test evidence is included; target builds were not run.\n") +
            "Host results do not qualify electrical behavior, timing, throughput, or stack/heap headroom.\n"
            "Physical tickets #175 and #176 remain deferred; production remote admission is unqualified.\n",
            encoding="utf-8")
        files = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
        (output / "SHA256SUMS.txt").write_text("".join(
            f"{sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in files), encoding="utf-8")
    print(f"Candidate {manifest['status']}: {output}", flush=True)
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
