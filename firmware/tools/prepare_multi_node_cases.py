"""Prepare private polling bench configurations from the tested r15 export."""
import argparse
import hashlib
import json
from pathlib import Path
import re

CASES = (("A_1imu_adc_off", 1, (), 500), ("B_2imu_adc_off", 2, (), 500),
         ("C_4imu_adc_off", 4, (), 500), ("D_4imu_2adc_500", 4, (0, 4), 500),
         ("E_4imu_4adc_200", 4, (0, 1, 4, 5), 200), ("F_4imu_4adc_500", 4, (0, 1, 4, 5), 500))


def prepare(source: Path, output: Path):
    original = source.read_bytes()
    lines = original.decode("utf-8-sig").splitlines(keepends=True)
    values, positions = {}, {}
    for i, line in enumerate(lines):
        match = re.match(r"^\s*([^#;\s=]+)\s*=(.*?)(?:\r?\n)?$", line)
        if not match:
            continue
        key, value = match.groups()
        if key in values:
            raise ValueError("duplicate configuration key: " + key)
        values[key] = value.split("#", 1)[0].strip();positions[key] = i
    if values.get("sensor_count") != "5" or values.get("sample_rate_hz") != "500" or values.get("log_format") != "bodaqs_multi_stream_binary":
        raise ValueError("require the tested r15 five-sensor 500Hz multistream export")
    if any(values.get(f"sensor{i}.muted", "false").lower() not in ("false", "0", "no") for i in range(5)):
        raise ValueError("baseline sensors must all be enabled")
    if any(values.get("sensor0."+key) != value for key, value in
           {"type": "lsm6dso32x_imu", "provider": "can:0", "endpoint": "imu", "profile": "imu6_3333_32g_2000dps_v1"}.items()):
        raise ValueError("require the tested can:0 IMU profile")
    for i, ain in enumerate((0, 1, 4, 5), 1):
        if values.get(f"sensor{i}.type") != "analog_pot" or values.get(f"sensor{i}.ain") != str(ain):
            raise ValueError("require analog pots on AIN0/1/4/5 in tested order")
        if values.get(f"sensor{i}.include_raw", "false").lower() not in ("false", "0", "no") or values.get(f"sensor{i}.output_mode", "1") not in ("0", "1"):
            raise ValueError("retain RAW/LINEAR without an extra raw column")
    if any(re.match(r"sensor(?:[5-9]|[1-9][0-9]+)\.", key) for key in values):
        raise ValueError("unexpected additional sensor keys")
    if output.exists():
        raise ValueError("preserve prior outputs; choose a fresh directory")
    newline = "\r\n" if original.count(b"\r\n") else "\n"
    generated = []
    for name, count, ains, rate in CASES:
        overrides = {"sensor_count": "8", "sample_rate_hz": str(rate), "sensor0.muted": "false"}
        overrides.update({f"sensor{i}.muted": "false" if ain in ains else "true" for i, ain in enumerate((0, 1, 4, 5), 1)})
        changed = list(lines)
        for key, value in overrides.items():
            if key not in positions:
                raise ValueError("missing explicit baseline key: " + key)
            old = changed[positions[key]]
            ending = "\r\n" if old.endswith("\r\n") else "\n" if old.endswith("\n") else ""
            changed[positions[key]] = f"{key}={value}{ending}"
        text = "".join(changed).rstrip("\r\n") + newline
        for node in range(1, 4):
            index = 4+node
            # Copy the profile, clear installation-specific pose/calibration.
            fields = {key.removeprefix("sensor0."): value for key, value in values.items() if key.startswith("sensor0.")}
            fields.update(name=f"bench_imu{node}", imu_id=f"bench_imu_{node}", provider=f"can:{node}",
                          muted="false" if node < count else "true", orient_valid="false",
                          mount_point="", calibration_ref="", domain="frame", end="none",
                          orient_qw="1", orient_qx="0", orient_qy="0", orient_qz="0")
            text += newline + "".join(f"sensor{index}.{key}={value}{newline}" for key, value in fields.items())
        encoded = (b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8")
        assert all(changed[i] == lines[i] for i in range(len(lines)) if i not in {positions[k] for k in overrides})
        generated.append((name, count, ains, rate, encoded))
    output.mkdir(parents=True)
    (output / "restore-r15-working-private.txt").write_bytes(original)
    result = {"schema": "bodaqs.multi-node-cases.v1", "source_sha256": hashlib.sha256(original).hexdigest(),
              "private_configs": True, "cases": []}
    for name, count, ains, rate, encoded in generated:
        path = output / (name + ".txt");path.write_bytes(encoded)
        result["cases"].append({"id": name, "configuration": path.name, "expected_nodes": list(range(count)),
                                "active_ains": list(ains), "requested_hz": rate, "record_seconds": 60,
                                "sha256": hashlib.sha256(encoded).hexdigest()})
    (output / "cases.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.config, args.output_dir)
    print("Created six private configuration files, exact restore copy and case hashes; no device accessed.")
