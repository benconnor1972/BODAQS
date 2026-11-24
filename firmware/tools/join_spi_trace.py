"""Join a finalized r8 BDQ with its frozen master trace; no device access."""
from pathlib import Path
import argparse
import json
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"analysis"))
from bodaqs_analysis.first_imu_recording import assess_first_imu_recording
from bodaqs_analysis.spi_boundary_trace import correlate

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("bdq",type=Path);p.add_argument("trace",type=Path)
    p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    try:
        report,_=assess_first_imu_recording(args.bdq)
        if report["file_errors"] or not report["file_cleanly_closed"]:raise ValueError("BDQ must be intact and finalized")
        result=correlate(args.trace.read_bytes(),report["final_summary"],report["source"])
    except (ValueError,KeyError,OSError) as error:
        result={"schema":"bodaqs.spi-boundary-join.v1","same_exchange_proven":False,"classification":"inconclusive","reason":str(error)}
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(result["classification"])
    return 0 if result["same_exchange_proven"] else 1

if __name__=="__main__":raise SystemExit(main())
