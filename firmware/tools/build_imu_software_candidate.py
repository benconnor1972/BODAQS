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
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


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
    parser.add_argument("--profile", choices=("production", "first-recording"), default="production",
                        help="Select restricted single-IMU v2 candidate explicitly")
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
    logger_env = "bodaqs_s3_mini_n4r2_imu_smoke" if args.profile=="first-recording" else "bodaqs_s3_mini_n4r2"
    commands = [
        step("a8-dependencies", [args.pio, "pkg", "install", "-d", "firmware", "-e",
             logger_env]),
        step("firmware-host", [*make, "-C", "firmware/test", "test",
             f"CXX={args.cxx}", f"CC={args.cc}", f"PYTHON={Path(sys.executable).as_posix()}"]),
        step("common-host", [*make, "-C", "firmware/can-fd/common/test", "test",
             f"CC={args.cc}", f"CXX={args.cxx}", f"PYTHON={Path(sys.executable).as_posix()}"]),
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
    if args.profile=="first-recording":
        commands.append(step("integrated-first-recording", [sys.executable,
            "firmware/tools/test_integrated_imu_recording_runtime.py", "--first-recording",
            "--compiler", args.cxx, "--cc", args.cc,
            "--output-dir", str(output / "scenarios-first-recording")]))
    if args.mode == "host":
        return commands
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
                f"CAN_LINK_PROFILE={profile}",
                *([f"SPI_MEASUREMENT_PROFILE={args.profile if args.profile=='first-recording' else 'legacy'}",
                   "CFLAGS_EXTRA=-fstack-usage"] if target=="master" else [])], artifacts))
    a8 = f"firmware/.pio/build/{logger_env}"
    commands.append(step("a8-clean", [args.pio, "run", "-d", "firmware", "-e",
        logger_env, "-t", "clean"]))
    commands.append(step("a8-build", [args.pio, "run", "-d", "firmware", "-e",
        logger_env, f"-j{args.jobs}"],
        [(f"{a8}/{name}", f"artifacts/a8-{logger_env}/{name}") for name in
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
    env["PYTHONPATH"] = str(ROOT / "analysis")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def main() -> int:
    args = arguments()
    if args.jobs < 1:
        raise SystemExit("--jobs must be positive")
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
    try:
        tools = preflight(args)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.mode == "preflight":
        print("Tool, Python dependency and SDK preflight passed; no output, builds or device access.")
        return 0

    output.mkdir(parents=True)
    (output / "logs").mkdir()
    env = build_environment(args)
    manifest = {
        "kind": "local-software-candidate" if args.mode == "candidate" else "host-validation", "status": "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
                   "tracked_dirty_before": bool(dirty), "untracked_before": untracked},
        "targets": {"node": "MSPM0G3507", "master": "MSPM0G3518",
                    "logger": "bodaqs_s3_mini_n4r2_imu_smoke" if args.profile=="first-recording" else "bodaqs_s3_mini_n4r2"},
        "candidate_profile": args.profile,
        "measurement": {"version": 2, "physical_bytes":256,"requested_hz":16000000,"guard_us":25,"publication":"boundary_only"} if args.profile=="first-recording" else {"version":1},
        "acquisition": {"lease_ms":5000,"renewal_ms":1000,"challenge_ms":300},
        "link_profiles": {"bringup": [500000, 2000000], "acquisition": [1000000, 4000000]},
        "sdk": str(args.sdk.resolve()) if args.mode == "candidate" else None,
        "validation_mode": args.mode, "qualification": "physical qualification deferred",
        "build_environment": {key: env.get(key) for key in (
            "PATH", "PYTHONPATH", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "MAKEFLAGS",
            "PLATFORMIO_BUILD_FLAGS", "PLATFORMIO_BUILD_SRC_FLAGS")},
        "production_remote_admission": "unqualified/unsupported until measured bounds supplied",
        "deferred": DEFERRED, "commands": [], "artifacts": [],
    }
    try:
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
        # Existing toolchains create these optional diagnostics on some versions.
        logger_env=manifest["targets"]["logger"]
        a8_folder = ROOT / f"firmware/.pio/build/{logger_env}"
        for optional in ("firmware.map", "idedata.json"):
            source = a8_folder / optional
            if args.mode == "candidate" and source.exists():
                shutil.copyfile(source, output / f"artifacts/a8-{logger_env}" / optional)
        if args.mode == "candidate" and args.profile=="first-recording":
            extras=[(ROOT / "docs/firmware/CAN-FD_First_Recording_Runbook.md", "RUNBOOK.md"),
                    (Path.home() / ".platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin",
                     f"artifacts/a8-{logger_env}/boot_app0.bin")]
            for source,destination in extras:
                target=output / destination;shutil.copyfile(source,target)
                manifest["artifacts"].append({"path":destination,"bytes":target.stat().st_size,"sha256":sha256(target)})
        if args.mode == "candidate":
            if git("status", "--porcelain", "--untracked-files=no") or git("rev-parse", "HEAD") != manifest["source"]["commit"]:
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
        if args.mode == "candidate" and (manifest["source"]["tracked_changes_after"] or
                manifest["source"]["commit_after"] != manifest["source"]["commit"]):
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
            ("Both TI profiles are separate artifacts; both endpoints must match.\n"
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
