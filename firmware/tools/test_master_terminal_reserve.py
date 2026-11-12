"""Actual master ingress/retention/wire replay of STOP arriving at a full queue."""
import argparse
from pathlib import Path
import subprocess
import tempfile

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler",default="g++")
    parser.add_argument("--baseline",action="store_true")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    common=root/"can-fd/common/protocol"
    with tempfile.TemporaryDirectory(prefix="bodaqs-terminal-reserve-") as tmp:
        exe=Path(tmp)/"terminal.exe"
        subprocess.run([args.compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror",
            "-DBODAQS_SPI_MEASUREMENT_V2=1",f"-DBODAQS_MASTER_BOUNDARY_RESERVE={0 if args.baseline else 2}",
            "-I",str(common),str(root/"test/master_terminal_reserve_fixture.cpp"),
            *[str(common/n) for n in ("bodaqs_master_service.c","bodaqs_master_protocol.c","bodaqs_control.c","bodaqs_control_exchange.c")],
            "-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
        if not args.baseline:
            for case in ("malformed","transaction-low","transaction-high","exhaustion"):
                subprocess.run([str(exe),case],check=True)

if __name__=="__main__":
    main()
