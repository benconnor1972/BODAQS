"""BYB binary recording reader. Physical calibration belongs in byb.py."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

import numpy as np
import pandas as pd

BYB_READER_VERSION = "byb.v1.2"
BYB_TIMING_VERSION = "byb.counter_grid.v1"
RECORD_DTYPE = np.dtype([
    ("counter", "<u4"), ("front_counts", "<u2"), ("rear_counts", "<u2"),
    ("accel_x_counts", "<i2"), ("accel_y_counts", "<i2"), ("accel_z_counts", "<i2"),
    ("gyro_x_counts", "<i2"), ("gyro_y_counts", "<i2"), ("gyro_z_counts", "<i2"),
    ("brake_1_counts", "<u2"), ("brake_2_counts", "<u2"), ("wheel_speed_counts", "<u2"),
    ("unused", "<u2"), ("latitude_e7", "<i4"), ("longitude_e7", "<i4"),
    ("altitude_m", "<f4"), ("gps_speed_kmh", "<f4"), ("marker", "<u4"),
])


class BYBFormatError(ValueError):
    """A corrupt or unsupported recording, rather than a setup problem."""


def is_byb_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() == ".byb"


@dataclass
class BYBRecording:
    started_local: datetime
    raw: pd.DataFrame
    analysis: pd.DataFrame
    gps: pd.DataFrame
    travel: dict[str, float]
    qc: dict


def _read_trailer(trailer: bytes) -> tuple[dict[str, float], dict, list[str]]:
    """Decode known fixed-width fields before considering the compact layout.

    Hardware recordings include extra fields after wheel travel. Those fields
    cannot be used to locate travel by counting backwards from the file end.
    """
    slots = [trailer[i:i + 30] for i in range(2, len(trailer), 30)]
    padded = len(slots) == 67 and all(
        len(slot) == 30 and (b"\0" not in slot or not any(slot.split(b"\0", 1)[1]))
        for slot in slots
    )
    fields = [slot.split(b"\0", 1)[0].decode("ascii", errors="replace").strip() for slot in slots]
    names = ("front_suspension_mm", "rear_suspension_mm", "rear_wheel_mm")
    metadata = {}
    if padded and any(fields[7:13]):
        values = fields[10:13]
        metadata = {
            "layout": "fixed_30_byte_fields",
            "bike": fields[7], "frame_size": fields[8], "wheel_size": fields[9],
            "raw_travel_fields": dict(zip(names, values)),
        }
    else:
        # The reference also describes a compact layout with travel at the end.
        runs = re.findall(rb"[\x20-\x7e]+", trailer[2:])
        values = [value.decode("ascii") for value in runs[-3:]] if len(runs) >= 3 else [""] * 3
        metadata = {"layout": "compact_trailing_travel", "raw_travel_fields": dict(zip(names, values))}
    travel, warnings = {}, []
    for name, value in zip(names, values):
        try:
            number = float(value)
            if not np.isfinite(number) or number <= 0:
                raise ValueError("non-positive travel")
            travel[name] = number
        except ValueError:
            warnings.append(f"missing_trailer_travel:{name}")
    return travel, metadata, warnings


def _timebase(counters: np.ndarray) -> tuple[np.ndarray, float, dict]:
    ticks = counters.astype(np.int64)
    delta = np.diff(ticks)
    wraps = (delta < 0) & (ticks[:-1] > 0xF0000000) & (ticks[1:] < 0x0FFFFFFF)
    if np.any((delta < 0) & ~wraps):
        raise BYBFormatError("BYB counter reset: elapsed time cannot be recovered; export separate recordings")
    ticks += np.r_[0, np.cumsum(wraps, dtype=np.int64)] * (2 ** 32)
    t = (ticks - ticks[0]).astype(np.float64) / 1000.0
    positive = np.diff(t)
    positive = positive[positive > 0]
    if not len(positive):
        raise BYBFormatError("BYB recording needs at least two distinct counter times")
    # Millisecond integer counters: quantize the estimate to the source clock.
    dt = max(1, round(float(np.median(positive)) * 1000)) / 1000.0
    return t, dt, {
        "policy": BYB_TIMING_VERSION, "initial_counter": int(counters[0]),
        "duplicate_counters": int(np.count_nonzero(np.diff(t) == 0)),
        "counter_wraps": int(np.count_nonzero(wraps)), "nominal_dt_s": dt,
        "gap_threshold_s": 8 * dt,
    }


def _regularize(raw: pd.DataFrame, dt: float) -> pd.DataFrame:
    # Only suspension is interpolated. All original records remain in raw.
    unique = raw.groupby("time_s", sort=False)[["front_counts", "rear_counts"]].mean()
    t = unique.index.to_numpy(dtype=float)
    cuts = np.r_[0, np.flatnonzero(np.diff(t) > 8 * dt + 1e-9) + 1, len(t)]
    frames = []
    for segment_id, (a, b) in enumerate(zip(cuts[:-1], cuts[1:])):
        source_t = t[a:b]
        grid = source_t[0] + np.arange(int(np.floor((source_t[-1] - source_t[0]) / dt + 1e-7)) + 1) * dt
        frame = pd.DataFrame({"time_s": grid, "segment_id": segment_id})
        for col in ("front_counts", "rear_counts"):
            y = unique[col].to_numpy(dtype=float)[a:b]
            # Do not bridge invalid observations. Interpolate only finite runs.
            result = np.full(len(grid), np.nan)
            edges = np.flatnonzero(np.diff(np.r_[False, np.isfinite(y), False]))
            for left, right in zip(edges[::2], edges[1::2]):
                mask = (grid >= source_t[left] - 1e-10) & (grid <= source_t[right - 1] + 1e-10)
                result[mask] = np.interp(grid[mask], source_t[left:right], y[left:right])
            frame[col] = result
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def read_byb(path: str | Path) -> BYBRecording:
    data = Path(path).read_bytes()
    trailer_offset = len(data) - 2012
    if trailer_offset < 72 + 44 or data[trailer_offset:trailer_offset + 2] != b"\xf0\xf0":
        raise BYBFormatError("BYB trailer sentinel missing at file_size - 2012; file may be incomplete")
    if (trailer_offset - 72 - 44) % 48:
        raise BYBFormatError("BYB trailer does not overlap a record marker at the expected alignment")
    n = (trailer_offset - 72 - 44) // 48 + 1
    records = np.frombuffer(data, dtype=RECORD_DTYPE, offset=72, count=n)
    if np.any(records["marker"][:-1] != 0xFFFF):
        raise BYBFormatError("BYB data marker failed before the trailer; recording is corrupt")
    try:
        started = datetime(2000 + data[0], data[2], data[3], data[4], data[5], data[6])
    except ValueError as exc:
        raise BYBFormatError(f"Invalid BYB header date: {exc}") from exc
    t, dt, timing = _timebase(records["counter"])
    raw = pd.DataFrame({name: records[name].astype(records.dtype[name].newbyteorder("=")) for name in records.dtype.names}, copy=False)
    raw.insert(0, "time_s", t)
    # Inspect source values before masking invalid counts for interpolation.
    working = raw[["time_s", "front_counts", "rear_counts"]].copy()
    invalid = {}
    for col in ("front_counts", "rear_counts"):
        bad = working[col] > 4095
        invalid[col] = int(bad.sum())
        working.loc[bad, col] = np.nan
    analysis = _regularize(working, dt)
    fixes = raw.iloc[::100]
    gps = pd.DataFrame({
        "time_s": fixes.time_s.to_numpy(),
        "latitude_deg": fixes.latitude_e7.to_numpy(dtype=float) / 1e7,
        "longitude_deg": fixes.longitude_e7.to_numpy(dtype=float) / 1e7,
        "altitude_m": fixes.altitude_m.to_numpy(dtype=float),
        "speed_mps": fixes.gps_speed_kmh.to_numpy(dtype=float) / 3.6,
    })
    good = gps.latitude_deg.between(-90, 90) & gps.longitude_deg.between(-180, 180)
    good &= ~((gps.latitude_deg == 0) & (gps.longitude_deg == 0))
    gps.loc[~good, ["latitude_deg", "longitude_deg", "altitude_m", "speed_mps"]] = np.nan
    gps.loc[~np.isfinite(gps.speed_mps) | (gps.speed_mps < 0), "speed_mps"] = np.nan
    gps.loc[~np.isfinite(gps.altitude_m), "altitude_m"] = np.nan
    travel, trailer_metadata, warnings = _read_trailer(data[trailer_offset:])
    timing.update({"segment_count": int(analysis.segment_id.nunique()), "analysis_rows": len(analysis)})
    return BYBRecording(started, raw, analysis, gps, travel, {
        "reader_version": BYB_READER_VERSION, "timing": timing, "raw_rows": n,
        "invalid_counts": invalid, "warnings": warnings,
        "trailer": trailer_metadata,
        "header_mode": data[0x16:0x20].split(b"\0")[0].decode("ascii", errors="replace"),
        "declared_rate": data[0x20:0x2A].split(b"\0")[0].decode("ascii", errors="replace"),
        "sampling_mode": data[0x2A:72].split(b"\0")[0].decode("ascii", errors="replace"),
    })
