"""Source-derived identity; PlatformIO pre-script and standalone helper."""
from hashlib import sha256
from pathlib import Path
import subprocess


def source_identity(firmware):
    firmware = Path(firmware).resolve()
    digest = sha256()
    # Git excludes ignored TI/SCons/PIO generated C and H files while retaining
    # new project sources. An extracted source archive contains canonical files.
    try:
        names = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
            cwd=firmware, stderr=subprocess.DEVNULL).split(b"\0")
        candidates = [firmware / name.decode("utf-8") for name in names if name]
    except (OSError, subprocess.CalledProcessError):
        candidates = list(firmware.rglob("*"))
    paths = [p for p in candidates if p.is_file()
             and not any(part in {".pio", ".build", "__pycache__", ".git"}
                         for part in p.relative_to(firmware).parts)
             and p.suffix.lower() in {".c", ".cpp", ".h", ".ino", ".py", ".ini", ".json", ".csv"}]
    for path in sorted(paths):
        digest.update(path.relative_to(firmware).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=firmware,
                                           text=True, stderr=subprocess.DEVNULL).strip()[:12]
    except (OSError, subprocess.CalledProcessError):
        revision = "unversioned"
    return f"spi-probe-v6-{revision}-{digest.hexdigest()[:20]}"


if "Import" in globals():
    Import("env")
    identity = source_identity(env.subst("$PROJECT_DIR"))
    env.Append(CPPDEFINES=[("BODAQS_SPI_PROBE_BUILD", env.StringifyMacro(identity))])
