"""Build the two isolated r19 masters; preserve the sealed 600 us logger/peers.

No serial, debugger, network or flash access. Requires committed clean source.
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
import time

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {"crc-block": (1, 0), "can-first": (0, 1)}
LOGGER_SHA = "1989dc25bddcd3d0d888e935338c741158f6d414bf7309ebcf4af119fdd2b7bd"
MASTER_SHA = "a45fb5b85ad6d82062d4907b777577306a488631e56e3116ce55c524e5e827c9"
NODE_SHA = "fa9800c75badcfdbbec7a4f7535c2a80a26a9cb381c2fe67aef7516647a9643b"
CONFIG_SHA = "60cf84d43d08cb4af730cf6a3930213d3024222ec1b5ae914b18ea3c669b69db"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

def parent_inputs(parent, config):
    manifest = json.loads((parent / "BUILD_MANIFEST.json").read_text(encoding="utf-8-sig"))
    selected = manifest["variants"]["ack_pacing"]
    if (manifest["status"] != "passed" or manifest["experiment"] != "adc-ack-pacing"
            or selected["minimum_start_spacing_us"] != 600 or not selected["ack_fetch_fragment_sweep"]
            or selected["spi_mode"] != 0 or not selected["spi_disabled_init"]
            or selected["boundary_trace_enabled"] or sha(config) != CONFIG_SHA):
        raise ValueError("Requires passed r18 pacing bundle and exact two-node ADC-off config")
    # Refuse damaged parent bundles, and require the known images actually tested.
    for line in (parent / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split(maxsplit=1)
        path = (parent / name.lstrip("*")).resolve()
        if parent.resolve() not in path.parents or sha(path) != digest.lower():
            raise ValueError("Parent checksum mismatch: " + name)
    files = [
        ("artifacts/logger-ack_pacing/firmware.bin", LOGGER_SHA),
        ("artifacts/fixed-rollback-master/bodaqs_can_master.out", MASTER_SHA),
        ("artifacts/fixed-node/bodaqs_can_node.out", NODE_SHA),
    ]
    for name, digest in files:
        if sha(parent / name) != digest:
            raise ValueError("Wrong fixed peer: " + name)
    return manifest

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True, type=Path)
    parser.add_argument("--config-reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--make", default="C:/ti/ccs2101/ccs/utils/bin/gmake.exe")
    parser.add_argument("--cxx", default="C:/msys64/ucrt64/bin/g++.exe")
    parser.add_argument("--cc", default="C:/msys64/ucrt64/bin/gcc.exe")
    parser.add_argument("--sdk", type=Path, default=Path("C:/ti/mspm0_sdk_2_11_00_07"))
    parser.add_argument("--ti", type=Path, default=Path("C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS"))
    parser.add_argument("--sysconfig", default="C:/ti/ccs2101/ccs/utils/sysconfig_1.28.1/sysconfig_cli.bat")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve earlier artifacts")
    parent = parent_inputs(args.parent, args.config_reference)
    commit = git("rev-parse", "HEAD")
    if git("status", "--porcelain"):
        parser.error("Commit source before building a sealed candidate")
    for path in (Path(args.make), Path(args.cxx), Path(args.cc), args.ti / "bin/tiarmclang.exe",
                 Path(args.sysconfig), args.sdk / ".metadata/product.json"):
        if not path.is_file():
            parser.error("Missing build prerequisite: " + str(path))
    if args.preflight_only:
        print("Pinned parent, configuration, clean source and local tools: PASS")
        return
    out = args.output.resolve()
    out.mkdir(parents=True)
    (out / "logs").mkdir()
    env = dict(os.environ)
    env["PATH"] = str(Path(args.cxx).parent) + os.pathsep + env["PATH"]
    manifest = dict(schema="bodaqs.master_drain_round.v1", status="building",
        created_utc=datetime.now(timezone.utc).isoformat(), source_commit=commit,
        parent_bundle=str(args.parent.resolve()), parent_manifest_sha256=sha(args.parent / "BUILD_MANIFEST.json"),
        logger_recipe=parent["variants"]["ack_pacing"]["logger"]["recipe_id"],
        minimum_start_spacing_us=600, expected_nodes=[0, 1], configuration_sha256=CONFIG_SHA,
        variants={}, commands=[], artifacts=[], qualification="unqualified; hardware capture pending",
        review="local source/diff and invariant review; no independent reviewer claim")

    def save():
        (out / "BUILD_MANIFEST.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")

    def run(name, command, cwd=ROOT):
        print(name, flush=True)
        started = time.monotonic()
        log = out / "logs" / (name + ".txt")
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                stdout=stream, stderr=subprocess.STDOUT)
        manifest["commands"].append(dict(name=name, argv=list(map(str, command)), cwd=str(cwd),
            exit_code=result.returncode, seconds=round(time.monotonic()-started, 3),
            log=log.relative_to(out).as_posix(), log_sha256=sha(log)))
        save()
        if result.returncode:
            raise RuntimeError(name + " failed; inspect " + str(log))

    def copy(source, relative, **identity):
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entry = dict(path=relative, sha256=sha(target), bytes=target.stat().st_size, **identity)
        manifest["artifacts"].append(entry)
        return entry

    try:
        py = [sys.executable, "-B"]
        run("intake-gate-tests", [*py, "-m", "unittest", "discover", "-s", "firmware/tools", "-p", "test_master_drain_tools.py"])
        run("common-host", [args.make, "-B", "-C", "firmware/can-fd/common/test", "test",
            "CXX="+args.cxx, "CC="+args.cc, "PYTHON="+sys.executable])
        run("common-host-block-crc", [args.make, "-B", "-C", "firmware/can-fd/common/test", "test",
            "BUILD_DIR=.build/block-crc", "CXX="+args.cxx, "CC="+args.cc, "PYTHON="+sys.executable,
            "CXXFLAGS=-std=c++17 -O2 -Wall -Wextra -Werror -DBODAQS_MASTER_BLOCK_CRC=1"])
        run("master-adapter-host", [args.make, "-B", "-C", "firmware/can-fd/master/test", "test",
            "CC="+args.cc, "PYTHON="+sys.executable])
        for tool, flags in [
            ("test_master_phase_timing_runtime.py", []),
            ("test_measurement_decode_runtime.py", ["--block-crc"]),
            ("test_measurement_v2_runtime.py", ["--ack-sweep", "--block-crc"]),
        ]:
            run(tool[:-3], [*py, "firmware/tools/"+tool, "--compiler", args.cxx, *flags])
        for label, flags in VARIANTS.items():
            folder = ROOT / "firmware/can-fd/master/ticlang"
            run("master-"+label, [args.make, "-B", "-C", folder,
                "MSPM0_SDK_INSTALL_DIR="+args.sdk.as_posix(), "TICLANG_ARMCOMPILER="+args.ti.as_posix(),
                "SYSCONFIG_TOOL="+args.sysconfig, "CAN_LINK_PROFILE=acquisition",
                "SPI_MEASUREMENT_PROFILE=first-recording", "SPI_RX_CAPACITY=2", "SPI_PHASE_TIMING=1",
                "SPI_QUEUE_TIMING=1", "SPI_TX_PRIME=1", "SPI_DISABLED_INIT=1", "SPI_BOUNDARY_TRACE=0",
                "SPI_BENCH_MODE=0", "CFLAGS_EXTRA=-fstack-usage",
                "MASTER_BLOCK_CRC="+str(flags[0]), "MASTER_CAN_FIRST="+str(flags[1])])
            image = copy(folder / "bodaqs_can_master.out", "artifacts/master-"+label+"/bodaqs_can_master.out", source_commit=commit)
            for name in ("bodaqs_can_master.map", "ti_msp_dl_config.c", "ti_msp_dl_config.h", "device.opt", "device_linker.cmd"):
                copy(folder/name, "artifacts/master-"+label+"/"+name)
            for path in sorted(folder.glob("*.su")):
                copy(path, "artifacts/master-"+label+"/stack/"+path.name)
                # Clean-source preflight excludes pre-existing untracked .su files.
                # Remove only this build's copied reports, never source/peer files.
                path.unlink()
            manifest["variants"][label] = dict(master=image, block_crc=bool(flags[0]), can_first=bool(flags[1]),
                debugger_optimization_info=[1, *flags], phase_timing=True, queue_timing=True, spi_rx_capacity=2)
        for name in ("ti_msp_dl_config.c", "ti_msp_dl_config.h", "device.opt", "device_linker.cmd"):
            assert (out/"artifacts/master-crc-block"/name).read_bytes() == (out/"artifacts/master-can-first"/name).read_bytes(), name
        for image in parent["artifacts"]:
            old = image["path"]
            if old.startswith("artifacts/logger-ack_pacing/"):
                relative = old.replace("logger-ack_pacing", "fixed-logger")
            elif image.get("role") == "rollback-master":
                relative = "artifacts/rollback-master/bodaqs_can_master.out"
            elif image.get("role") == "node":
                relative = "artifacts/fixed-node/bodaqs_can_node.out"
            else:
                continue
            copy(args.parent/old, relative, reused_from=str((args.parent/old).resolve()),
                source_commit=parent["source"]["commit"] if "logger-ack_pacing" in old else
                "671384bce93184464c1a248bc5841d72f289394d" if image.get("role")=="rollback-master" else None)
        copy(args.config_reference, "Configurations/B_2imu_adc_off.txt", private=True)
        copy(ROOT/"docs/firmware/IMU_Master_Drain_Round19.md", "RUNBOOK.md")
        copy(ROOT/"firmware/can-fd/master/ticlang/MSPM0G3518_XDS110.ccxml", "MASTER_TARGET.ccxml")
        copy(ROOT/"firmware/tools/export_master_optimization.js", "export_master_optimization.js")
        pinned = [*sorted((ROOT/"analysis/bodaqs_analysis").rglob("*.py")),
            ROOT/"firmware/tools/assess_imu_optimization.py", ROOT/"firmware/tools/assess_master_drain_round.py"]
        for path in pinned:
            copy(path, "assessor-source/"+path.relative_to(ROOT).as_posix())
        run("archive-source", ["git", "archive", "--format=zip", "-o", out/"SOURCE.zip", commit])
        assert git("rev-parse", "HEAD") == commit and not git("status", "--porcelain"), "Source changed during build"
        (out/"Results/01-crc-block/attempt1").mkdir(parents=True)
        (out/"Results/02-can-first/attempt1").mkdir(parents=True)
        (out/"START_HERE.md").write_text("Start with RUNBOOK.md case 01: block-CRC master plus the fixed 600 us logger. Node images/config unchanged. No device has been flashed. Do not install the can-first variant yet.\n", encoding="utf-8")
        manifest["status"] = "passed"
        save()
    except Exception:
        manifest["status"] = "failed"
        save()
        raise
    files = sorted(p for p in out.rglob("*") if p.is_file())
    (out/"SHA256SUMS.txt").write_text("".join(sha(p)+"  "+p.relative_to(out).as_posix()+"\n" for p in files), encoding="utf-8")
    print("Passed source-bound candidate bundle: "+str(out))

if __name__ == "__main__":
    main()
