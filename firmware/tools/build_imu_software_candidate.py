"""Build a local, source-pinned IMU software candidate without accessing devices.

Run after committing the candidate source. Outputs must be outside this worktree.
The bundle contains source, command logs, both TI link profiles, the explicit A8
image, independently verified scenario files, and a SHA-256 inventory. It makes
no physical qualification claim. A failed command leaves a failed manifest.
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


ROOT = Path(__file__).resolve().parents[2]
DEFERRED = {
    "175": ["FIFO/DRDY/SYNC association", "SPI rearm and mutex timing",
            "measured four-node throughput and mixed ADC load",
            "clock phase/drift and 10 us alignment", "stack/heap watermarks"],
    "176": ["physical disconnect/reconnect", "CCS halt/resume",
            "node/master reset and electrical fault qualification"],
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--make", default="C:/ti/ccs2101/ccs/utils/bin/gmake.exe")
    parser.add_argument("--cxx", default="C:/msys64/ucrt64/bin/g++.exe")
    parser.add_argument("--cc", default="C:/msys64/ucrt64/bin/gcc.exe")
    parser.add_argument("--sdk", type=Path, default=Path("C:/ti/mspm0_sdk_2_11_00_07"))
    parser.add_argument("--ti-compiler", type=Path, default=Path(
        "C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS"))
    parser.add_argument("--sysconfig", type=Path, default=Path(
        "C:/ti/ccs2101/ccs/utils/sysconfig_1.28.1/sysconfig_cli.bat"))
    parser.add_argument("--pio", default="C:/Users/benco/.platformio/penv/Scripts/pio.exe")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--list-commands", action="store_true",
                        help="Print command plan without running or creating files")
    return parser.parse_args()


def plan(args: argparse.Namespace, output: Path) -> list[dict]:
    def step(name: str, argv: list[str], artifacts: list[tuple[str, str]] | None = None,
             cwd: Path = ROOT) -> dict:
        return {"name": name, "argv": argv, "cwd": str(cwd),
                "artifacts": artifacts or []}

    make = [args.make, "-B"]
    commands = [
        step("a8-dependencies", [args.pio, "pkg", "install", "-d", "firmware", "-e",
             "bodaqs_s3_mini_n4r2"]),
        step("firmware-host", [*make, "-C", "firmware/test", "test",
             f"CXX={args.cxx}", f"PYTHON={Path(sys.executable).as_posix()}"]),
        step("common-host", [*make, "-C", "firmware/can-fd/common/test", "test",
             f"CXX={args.cxx}"]),
        step("master-host", [*make, "-C", "firmware/can-fd/master/test", "test",
             f"CC={args.cc}", f"PYTHON={Path(sys.executable).as_posix()}"]),
        step("node-host", [*make, "-C", "firmware/can-fd/node/test", "test",
             f"CC={args.cc}"]),
        step("control-apply-regression", [sys.executable,
             "firmware/tools/test_control_apply_runtime.py", "--compiler", args.cxx]),
        step("integrated-recording", [sys.executable,
             "firmware/tools/test_integrated_imu_recording_runtime.py",
             "--compiler", args.cxx, "--cc", args.cc,
             "--output-dir", str(output / "scenarios")]),
        step("analysis", [sys.executable, "-m", "pytest", "-q"], cwd=ROOT / "analysis"),
    ]
    for profile in ("bringup", "acquisition"):
        for target in ("node", "master"):
            folder = f"firmware/can-fd/{target}/ticlang"
            basename = f"bodaqs_can_{target}"
            artifacts = [(f"{folder}/{basename}.{suffix}",
                          f"artifacts/{target}-{profile}/{basename}.{suffix}")
                         for suffix in ("out", "map")]
            commands.append(step(f"{target}-{profile}", [*make, "-C", folder,
                f"MSPM0_SDK_INSTALL_DIR={args.sdk.as_posix()}",
                f"TICLANG_ARMCOMPILER={args.ti_compiler.as_posix()}",
                f"SYSCONFIG_TOOL={args.sysconfig.as_posix()}",
                f"CAN_LINK_PROFILE={profile}"], artifacts))
    a8 = "firmware/.pio/build/bodaqs_s3_mini_n4r2"
    commands.append(step("a8-clean", [args.pio, "run", "-d", "firmware", "-e",
        "bodaqs_s3_mini_n4r2", "-t", "clean"]))
    commands.append(step("a8-build", [args.pio, "run", "-d", "firmware", "-e",
        "bodaqs_s3_mini_n4r2", f"-j{args.jobs}"],
        [(f"{a8}/{name}", f"artifacts/a8-bodaqs_s3_mini_n4r2/{name}") for name in
         ("firmware.elf", "firmware.bin", "bootloader.bin", "partitions.bin")]))
    return commands


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(output: Path, manifest: dict) -> None:
    (output / "BUILD_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = arguments()
    output = args.output_dir.resolve()
    if args.jobs < 1:
        raise SystemExit("--jobs must be positive")
    if sys.flags.optimize or os.environ.get("PYTHONOPTIMIZE"):
        raise SystemExit("Run acceptance with Python assertions enabled (no PYTHONOPTIMIZE or -O)")
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("Candidate output must be outside the source worktree")
    commands = plan(args, output)
    if args.list_commands:
        print(json.dumps(commands, indent=2))
        return 0
    if output.exists():
        raise SystemExit("Output already exists; select a fresh candidate directory")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise SystemExit("Commit or preserve tracked changes before building a source-pinned candidate")
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    # Integration-local handoff/evidence is deliberately outside committed code.
    unexpected = [name for name in untracked if not name.startswith(".scratch/")]
    if unexpected:
        raise SystemExit("Untracked files could affect the build: " + ", ".join(unexpected))

    output.mkdir(parents=True)
    (output / "logs").mkdir()
    env = os.environ.copy()
    env["PATH"] = str(Path(args.cxx).resolve().parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = str(ROOT / "analysis")
    manifest = {
        "kind": "local-software-candidate", "status": "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
                   "tracked_dirty_before": False, "untracked_before": untracked},
        "targets": {"node": "MSPM0G3507", "master": "MSPM0G3518",
                    "logger": "bodaqs_s3_mini_n4r2"},
        "link_profiles": {"bringup": [500000, 2000000], "acquisition": [1000000, 4000000]},
        "sdk": str(args.sdk.resolve()), "qualification": "physical qualification deferred",
        "build_environment": {key: env.get(key) for key in (
            "PATH", "PYTHONPATH", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "MAKEFLAGS",
            "PLATFORMIO_BUILD_FLAGS", "PLATFORMIO_BUILD_SRC_FLAGS")},
        "production_remote_admission": "unqualified/unsupported until measured bounds supplied",
        "deferred": DEFERRED, "commands": [], "artifacts": [],
    }
    # These are observations, not inferred versions from installation folder names.
    versions = [["git", "--version"], [sys.executable, "--version"],
                [sys.executable, "-c", "import importlib.metadata as m; "
                 "print('\\n'.join(sorted(str(d.metadata['Name'])+'=='+d.version for d in m.distributions())))"],
                [args.cxx, "--version"], [args.cc, "--version"], [args.make, "--version"],
                [args.pio, "--version"],
                [str(args.ti_compiler / "bin/tiarmclang.exe"), "--version"],
                [str(args.sysconfig), "--version"]]
    runner_path = ROOT / "firmware/test/test_runner.exe"
    runner_bytes = runner_path.read_bytes() if runner_path.exists() else None
    try:
        subprocess.run(["git", "archive", "--format=zip", "--output", str(output / "SOURCE.zip"),
                        manifest["source"]["commit"]], cwd=ROOT, check=True)
        sdk_metadata = args.sdk / ".metadata/product.json"
        shutil.copyfile(sdk_metadata, output / "MSPM0_SDK_PRODUCT.json")
        for index, argv in enumerate(versions):
            log = output / "logs" / f"tool-{index}.txt"
            with log.open("wb") as stream:
                result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, check=False)
            manifest.setdefault("tools", []).append(
                {"argv": argv, "exit_code": result.returncode, "log": log.relative_to(output).as_posix()})
            if result.returncode:
                raise RuntimeError(f"Tool identity command failed: {argv}")
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
        # Existing toolchains create these optional diagnostics on some versions.
        a8_folder = ROOT / "firmware/.pio/build/bodaqs_s3_mini_n4r2"
        for optional in ("firmware.map", "idedata.json"):
            source = a8_folder / optional
            if source.exists():
                shutil.copyfile(source, output / "artifacts/a8-bodaqs_s3_mini_n4r2" / optional)
        manifest["status"] = "passed"
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        print(error, file=sys.stderr)
    finally:
        # This tracked historical executable is a test output, never source input.
        if runner_bytes is not None:
            runner_path.write_bytes(runner_bytes)
        elif runner_path.exists():
            runner_path.unlink()
        manifest["source"]["tracked_changes_after"] = git("status", "--porcelain", "--untracked-files=no")
        manifest["source"]["commit_after"] = git("rev-parse", "HEAD")
        if (manifest["source"]["tracked_changes_after"] or
                manifest["source"]["commit_after"] != manifest["source"]["commit"]):
            manifest["status"] = "failed"
            manifest["error"] = "Source changed during acceptance; candidate is not a fixed-source pass"
        write_manifest(output, manifest)
        (output / "README.txt").write_text(
            "Local IMU software candidate. No devices were accessed.\n"
            "Inspect BUILD_MANIFEST.json status and logs before using artifacts.\n"
            "Both TI profiles are separate artifacts; both endpoints must match.\n"
            "A8 images are separate bootloader/partition/application outputs, not a merged flash image.\n"
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
