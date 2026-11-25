"""Offline copies from a fresh working export; never access or configure a device.

Generated full configs may contain private Wi-Fi settings. Keep the output local.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

CASES = (("A_split_500",500,4,500,30), ("B_concentrated_500",500,1,500,30),
         ("C_concentrated_700",700,1,700,30), ("D_requested_1000",1000,1,700,15))


def prepare(source: Path, output: Path):
    original=source.read_bytes()
    text=original.decode("utf-8-sig")
    lines=text.splitlines(keepends=True)
    values={}; positions={}
    for i,line in enumerate(lines):
        match=re.match(r"^\s*([^#;\s=]+)\s*=(.*?)(?:\r?\n)?$",line)
        if not match: continue
        key,value=match.groups()
        if key in values: raise ValueError("Duplicate configuration key: "+key)
        values[key]=value.split('#',1)[0].strip();positions[key]=i
    def active(i): return values.get(f"sensor{i}.muted","false").lower() not in ("true","1","yes")
    count=int(values["sensor_count"])
    live=[i for i in range(count) if active(i)]
    imu=[i for i in live if values.get(f"sensor{i}.type")=="lsm6dso32x_imu"]
    analog=[i for i in live if values.get(f"sensor{i}.type")=="analog_pot"]
    if len(live)!=3 or len(imu)!=1 or len(analog)!=2:
        raise ValueError("Use a fresh working export with one active IMU and two active analog pots")
    if values.get(f"sensor{imu[0]}.provider")!="can:0" or values.get(f"sensor{imu[0]}.endpoint")!="imu":
        raise ValueError("Require the existing can:0/imu endpoint")
    if values.get(f"sensor{imu[0]}.profile")!="imu6_3333_32g_2000dps_v1":
        raise ValueError("Keep the tested IMU profile")
    if values.get("sample_rate_hz")!="500" or values.get("log_format") not in ("bodaqs_multi_stream_binary","bodaqs_multistream_binary","multi_stream_binary"):
        raise ValueError("Baseline must be the working 500Hz multistream configuration")
    if {values.get(f"sensor{i}.ain") for i in analog}!={"0","4"}:
        raise ValueError("Baseline analog inputs must be AIN0 and AIN4")
    for i in analog:
        if values.get(f"sensor{i}.include_raw","false").lower() not in ("false","0","no") or values.get(f"sensor{i}.output_mode","1") not in ("0","1"):
            raise ValueError("Keep r13 RAW or LINEAR mode without an extra raw column")
    moved=next(i for i in analog if values[f"sensor{i}.ain"]=="4")
    if output.exists(): raise ValueError("Refuse existing output directory")
    output.mkdir(parents=True)
    (output/"baseline-private.txt").write_bytes(original)
    result={"schema":"bodaqs.adc-channel-cases.v1","source_sha256":hashlib.sha256(original).hexdigest(),
            "private_configs":True,"moved_sensor_index":moved,"cases":[]}
    for name,requested,ain,effective,duration in CASES:
        changed=list(lines);overrides={"sample_rate_hz":str(requested),f"sensor{moved}.ain":str(ain)}
        for key,value in overrides.items():
            old=changed[positions[key]];ending="\r\n" if old.endswith("\r\n") else "\n" if old.endswith("\n") else ""
            changed[positions[key]]=f"{key}={value}{ending}"
        encoded="".join(changed).encode("utf-8")
        if original.startswith(b'\xef\xbb\xbf'): encoded=b'\xef\xbb\xbf'+encoded
        path=output/(name+".txt");path.write_bytes(encoded)
        assert all(changed[i]==lines[i] for i in range(len(lines)) if i not in {positions[k] for k in overrides})
        result["cases"].append({"id":name,"configuration":path.name,"sha256":hashlib.sha256(encoded).hexdigest(),
                               "requested_hz":requested,"expected_effective_hz":effective,"active_ains":[0,ain],
                               "record_seconds":duration,"overrides":overrides})
    (output/"cases.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    result=prepare(args.config,args.output_dir)
    print("Created four local configuration copies and exact hashes; no device accessed.")
