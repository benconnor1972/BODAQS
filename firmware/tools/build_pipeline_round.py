"""Build a source-bound r20 diagnostic pair without connecting to devices."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from bench_profiles import review_result
from build_master_drain_round import ROOT, CONFIG_SHA, git, parent_inputs, sha

LOGGER_ENV = "bodaqs_s3_mini_n4r2_imu_pipeline"
BASE = "772f8010741a92c9d49c65abe634e0a0f76a2ecd"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parent", required=True, type=Path)
    p.add_argument("--config-reference", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--review", required=True, type=Path)
    p.add_argument("--jobs", type=int, default=6)
    args = p.parse_args()
    out = args.output.resolve()
    if out.exists() or out == ROOT or ROOT in out.parents or args.jobs < 1:
        p.error("Use a fresh output outside source, and positive jobs")
    if sys.flags.optimize or os.environ.get("PYTHONOPTIMIZE"):
        p.error("Acceptance requires Python assertions enabled")
    parent = parent_inputs(args.parent, args.config_reference)
    commit = git("rev-parse", "HEAD")
    if git("status", "--porcelain"):
        p.error("Requires clean committed source")
    review = review_result(json.loads(args.review.read_text(encoding="utf-8")), BASE, commit)
    for evidence in review["evidence"]:
        if sha(Path(evidence["path"])) != evidence["sha256"]:
            p.error("Review evidence checksum mismatch")
    make = "C:/ti/ccs2101/ccs/utils/bin/gmake.exe"
    cxx, cc = "C:/msys64/ucrt64/bin/g++.exe", "C:/msys64/ucrt64/bin/gcc.exe"
    pio = str(Path.home() / ".platformio/penv/Scripts/pio.exe")
    sdk = "C:/ti/mspm0_sdk_2_11_00_07"
    ti = "C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS"
    sysconfig = "C:/ti/ccs2101/ccs/utils/sysconfig_1.28.1/sysconfig_cli.bat"
    for path in (make, cxx, cc, pio, ti + "/bin/tiarmclang.exe", sysconfig, sdk + "/.metadata/product.json"):
        if not Path(path).is_file():
            p.error("Missing prerequisite: " + path)
    out.mkdir(parents=True)
    (out / "logs").mkdir()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONPATH=str(ROOT / "analysis"))
    env["PATH"] = str(Path(cxx).parent) + os.pathsep + env["PATH"]
    manifest = dict(schema="bodaqs.pipeline_round.v1", status="building", source_commit=commit,
        created_utc=datetime.now(timezone.utc).isoformat(), reviewed_base=BASE,
        parent_bundle=str(args.parent.resolve()), parent_manifest_sha256=sha(args.parent / "BUILD_MANIFEST.json"),
        configuration_sha256=CONFIG_SHA, expected_nodes=[0, 1], minimum_start_spacing_us=600,
        master_boundary_reserve=2, master_optimization_info=[1, 0, 0], logger_env=LOGGER_ENV,
        commands=[], artifacts=[], qualification="unqualified; physical capture pending",
        flash_offsets={"bootloader.bin":"0x0", "partitions.bin":"0x8000", "boot_app0.bin":"0xe000", "firmware.bin":"0x10000"},
        source_archive_scope=["firmware", "analysis/bodaqs_analysis", "docs", "AGENTS.md", "GLOSSARY.md", ".agents"],
        node_provenance="Exact previously tested image retained; original node source commit unknown")

    def save():
        (out / "BUILD_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def run(name, command):
        print(name, flush=True)
        log = out / "logs" / (name + ".txt")
        began = time.monotonic()
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(list(map(str, command)), cwd=ROOT, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT)
        manifest["commands"].append(dict(name=name, argv=list(map(str, command)), exit_code=result.returncode,
            seconds=round(time.monotonic()-began, 3), log=log.relative_to(out).as_posix(), log_sha256=sha(log)))
        save()
        if result.returncode:
            raise RuntimeError(name + " failed; see " + str(log))

    def copy(source, name, **identity):
        dest = out / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        record = dict(path=name, sha256=sha(dest), bytes=dest.stat().st_size, **identity)
        manifest["artifacts"].append(record)
        return record

    try:
        copy(args.review, "review/REVIEW.json")
        for i, evidence in enumerate(review["evidence"]):
            copy(Path(evidence["path"]), "review/evidence-" + str(i) + ".md")
        py = [sys.executable, "-B"]
        for label in ("bodaqs_s3_mini_n4r2", LOGGER_ENV):
            run("deps-" + label, [pio, "pkg", "install", "-d", "firmware", "-e", label])
        for label, folder in (("common-host", "firmware/can-fd/common/test"),
                              ("master-host", "firmware/can-fd/master/test"), ("logger-host", "firmware/test")):
            run(label, [make, "-B", "-C", folder, "test", "CXX="+cxx, "CC="+cc, "PYTHON="+sys.executable])
        run("master-boundary-reserve", [make, "-B", "-C", "firmware/can-fd/master/ticlang",
            "MSPM0_SDK_INSTALL_DIR="+sdk, "TICLANG_ARMCOMPILER="+ti, "SYSCONFIG_TOOL="+sysconfig,
            "CAN_LINK_PROFILE=acquisition", "SPI_MEASUREMENT_PROFILE=first-recording", "SPI_RX_CAPACITY=2",
            "SPI_PHASE_TIMING=1", "SPI_QUEUE_TIMING=1", "SPI_TX_PRIME=1", "SPI_DISABLED_INIT=1",
            "SPI_BOUNDARY_TRACE=0", "SPI_BENCH_MODE=0", "MASTER_BLOCK_CRC=0", "MASTER_CAN_FIRST=0",
            "MASTER_BOUNDARY_RESERVE=2", "CFLAGS_EXTRA=-fstack-usage"])
        folder = ROOT / "firmware/can-fd/master/ticlang"
        for name in ("bodaqs_can_master.out", "bodaqs_can_master.map", "ti_msp_dl_config.c", "ti_msp_dl_config.h", "device.opt", "device_linker.cmd"):
            copy(folder / name, "artifacts/master-boundary-reserve/" + name, source_commit=commit)
        for path in sorted(folder.glob("*.su")):
            copy(path, "artifacts/master-boundary-reserve/stack/" + path.name)
            path.unlink()  # only reports generated by this clean-source build
        run("logger-clean", [pio, "run", "-d", "firmware", "-e", LOGGER_ENV, "-t", "clean"])
        run("logger-pipeline", [pio, "run", "-d", "firmware", "-e", LOGGER_ENV, "-j"+str(args.jobs)])
        folder = ROOT / "firmware/.pio/build" / LOGGER_ENV
        for name in ("firmware.bin", "firmware.elf", "firmware.map", "bootloader.bin", "partitions.bin", "identity/build-recipe.json"):
            copy(folder / name, "artifacts/logger-pipeline/" + name, source_commit=commit)
        copy(Path.home() / ".platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin",
             "artifacts/logger-pipeline/boot_app0.bin")
        manifest["logger_recipe"] = json.loads((folder / "identity/build-recipe.json").read_text(encoding="utf-8"))["id"]
        # Read linked bytes, not just source macros or a symbol-name grep.
        from elftools.elf.elffile import ELFFile
        def symbol_bytes(path, name, size):
            with path.open("rb") as stream:
                elf = ELFFile(stream)
                sym = elf.get_section_by_name(".symtab").get_symbol_by_name(name)[0]
                section = elf.get_section(sym["st_shndx"])
                offset = sym["st_value"] - section["sh_addr"]
                return section.data()[offset:offset+size]
        master = out / "artifacts/master-boundary-reserve/bodaqs_can_master.out"
        if symbol_bytes(master, "gMasterBoundaryReserve", 4) != (2).to_bytes(4, "little") or symbol_bytes(master, "gMasterOptimizationInfo", 12) != b"\1\0\0\0" + bytes(8):
            raise ValueError("Linked master marker mismatch")
        manifest["linked_master_markers_verified"] = True
        for item in parent["artifacts"]:
            old = item["path"]
            if old.startswith("artifacts/logger-ack_pacing/"):
                name = old.replace("logger-ack_pacing", "fixed-logger")
            elif item.get("role") == "rollback-master":
                name = "artifacts/rollback-master/bodaqs_can_master.out"
            elif item.get("role") == "node":
                name = "artifacts/fixed-node/bodaqs_can_node.out"
            else:
                continue
            copy(args.parent / old, name, reused_from=str((args.parent / old).resolve()))
        copy(args.config_reference, "Configurations/B_2imu_adc_off.txt", private=True)
        copy(ROOT / "docs/firmware/IMU_Pipeline_Round20.md", "RUNBOOK.md")
        copy(ROOT / "firmware/can-fd/master/ticlang/MSPM0G3518_XDS110.ccxml", "MASTER_TARGET.ccxml")
        pinned = [*sorted((ROOT / "analysis/bodaqs_analysis").rglob("*.py")),
            *[ROOT / "firmware/tools" / name for name in ("assess_pipeline_round.py", "analyze_pipeline_trace.py",
              "assess_master_drain_round.py", "assess_imu_optimization.py")]]
        for path in pinned:
            copy(path, "assessor-source/" + path.relative_to(ROOT).as_posix())
        run("archive-source", ["git", "archive", "--format=zip", "-o", out / "SOURCE.zip", commit, *manifest["source_archive_scope"]])
        if git("rev-parse", "HEAD") != commit or git("status", "--porcelain"):
            raise ValueError("Source changed during build")
        (out / "Results/01-pipeline/attempt1").mkdir(parents=True)
        (out / "START_HERE.md").write_text("Read RUNBOOK.md. Install the boundary-reserve master and pipeline logger; keep nodes/config unchanged. No devices were accessed or flashed by this build.\n", encoding="utf-8")
        manifest["status"] = "passed"
        save()
    except Exception:
        manifest["status"] = "failed"
        save()
        raise
    (out / "SHA256SUMS.txt").write_text("".join(sha(path) + "  " + path.relative_to(out).as_posix() + "\n"
        for path in sorted(out.rglob("*")) if path.is_file()), encoding="utf-8")
    print("Passed source-bound r20 bundle: " + str(out))


if __name__ == "__main__":
    main()
