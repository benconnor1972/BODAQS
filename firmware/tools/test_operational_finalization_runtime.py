"""Exercise the actual bounded production footer with ArduinoJson 7."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--arduinojson", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    library = args.arduinojson or root / ".pio/libdeps/bodaqs_a8_production/ArduinoJson/src"
    source = (root / "src/StorageManager.cpp").read_text()
    fixture = (root / "test/operational_finalization_runtime_fixture.cpp").read_text()
    fixture = fixture.replace("// PRODUCTION", source[source.index("static size_t buildOperationalSummary_("):source.index("\n#endif\n\nstatic __attribute__((noinline)) void finalizeBdqV2_")])
    with tempfile.TemporaryDirectory(prefix="bodaqs-operational-footer-") as directory:
        cpp, exe = Path(directory)/"fixture.cpp", Path(directory)/"fixture.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler,"-std=c++17","-Wall","-Wextra","-Werror",
                        "-I",str(library),"-I",str(root/"src"),str(cpp),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__ == "__main__":
    main()
