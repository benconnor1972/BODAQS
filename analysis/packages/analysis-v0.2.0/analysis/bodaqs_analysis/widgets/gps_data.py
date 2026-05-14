from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

_LAT_COLS = ("gps_fit_position_latitude_dom_world [deg]",)
_LON_COLS = ("gps_fit_position_longitude_dom_world [deg]",)
_ALT_COLS = (
    "gps_fit_enhanced_altitude_dom_world [m]",
    "gps_fit_altitude_dom_world [m]",
)
_SPEED_COLS = (
    "gps_fit_enhanced_speed_dom_world [m/s]",
    "gps_fit_speed_dom_world [m/s]",
)
_DISTANCE_COLS = ("gps_fit_distance_dom_world [m]",)
_DEFAULT_ROUTE_COLOR = "#2563eb"
_DEFAULT_SPEED_BIN_EDGES_KMH = (0.0, 10.0, 20.0, 30.0, 40.0)
_DEFAULT_SPEED_BIN_COLORS = (
    "#22c55e",
    "#84cc16",
    "#facc15",
    "#fb923c",
    "#ef4444",
)


@dataclass(frozen=True)
class GPSViewData:
    session_key: str
    source_stream_name: str
    route_df: pd.DataFrame
    has_altitude: bool
    has_speed: bool


@dataclass(frozen=True)
class SpeedColorBin:
    idx: int
    lower_mps: float
    upper_mps: float
    color: str
    label: str


@dataclass(frozen=True)
class LineRun:
    color: str
    label: str
    times_s: tuple[float, ...]
    altitudes_m: tuple[float, ...]
    speeds_mps: tuple[float, ...]
    coordinates: tuple[tuple[float, float], ...]
    point_count: int
    segment_count: int


def _to_numeric_series(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def _first_existing(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return str(col)
    return None


def _iter_candidate_frames(
    session: Mapping[str, Any],
    *,
    preferred_stream_name: str = "gps_fit",
) -> list[tuple[str, pd.DataFrame]]:
    frames: list[tuple[str, pd.DataFrame]] = []
    stream_dfs = session.get("stream_dfs")
    if isinstance(stream_dfs, Mapping):
        preferred = stream_dfs.get(preferred_stream_name)
        if isinstance(preferred, pd.DataFrame):
            frames.append((str(preferred_stream_name), preferred))
        for stream_name, df in stream_dfs.items():
            if str(stream_name) == str(preferred_stream_name):
                continue
            if isinstance(df, pd.DataFrame):
                frames.append((str(stream_name), df))

    primary_df = session.get("df")
    if isinstance(primary_df, pd.DataFrame):
        frames.append(("primary", primary_df))
    return frames


def _interpolate_primary_col(
    primary_df: pd.DataFrame,
    *,
    target_time_s: np.ndarray,
    source_col: str,
    time_col: str = "time_s",
) -> np.ndarray:
    if time_col not in primary_df.columns or source_col not in primary_df.columns:
        return np.full(len(target_time_s), np.nan, dtype=float)

    src_t = _to_numeric_series(primary_df, time_col).to_numpy(dtype=float)
    src_v = _to_numeric_series(primary_df, source_col).to_numpy(dtype=float)
    mask = np.isfinite(src_t) & np.isfinite(src_v)
    if int(mask.sum()) == 0:
        return np.full(len(target_time_s), np.nan, dtype=float)
    if int(mask.sum()) == 1:
        return np.full(len(target_time_s), float(src_v[mask][0]), dtype=float)

    x = src_t[mask]
    y = src_v[mask]
    order = np.argsort(x, kind="stable")
    x = x[order]
    y = y[order]
    x, unique_idx = np.unique(x, return_index=True)
    y = y[unique_idx]
    if len(x) == 1:
        return np.full(len(target_time_s), float(y[0]), dtype=float)
    return np.interp(target_time_s, x, y, left=np.nan, right=np.nan)


def _time_bounds(df: pd.DataFrame, *, time_col: str = "time_s") -> Optional[tuple[float, float]]:
    if time_col not in df.columns:
        return None

    time_s = _to_numeric_series(df, time_col).to_numpy(dtype=float)
    mask = np.isfinite(time_s)
    if not mask.any():
        return None

    return float(np.min(time_s[mask])), float(np.max(time_s[mask]))


def extract_gps_view_data(
    session: Mapping[str, Any],
    *,
    session_key: str = "",
    preferred_stream_name: str = "gps_fit",
    time_col: str = "time_s",
) -> Optional[GPSViewData]:
    primary_df = session.get("df")
    primary_df = primary_df if isinstance(primary_df, pd.DataFrame) else pd.DataFrame()

    chosen_name = None
    chosen_df: Optional[pd.DataFrame] = None
    for stream_name, df in _iter_candidate_frames(session, preferred_stream_name=preferred_stream_name):
        lat_col = _first_existing(df, _LAT_COLS)
        lon_col = _first_existing(df, _LON_COLS)
        if lat_col and lon_col and time_col in df.columns:
            chosen_name = stream_name
            chosen_df = df.copy()
            break

    if chosen_df is None or chosen_name is None:
        return None

    lat_col = _first_existing(chosen_df, _LAT_COLS)
    lon_col = _first_existing(chosen_df, _LON_COLS)
    if lat_col is None or lon_col is None or time_col not in chosen_df.columns:
        return None

    route_df = pd.DataFrame(
        {
            "time_s": _to_numeric_series(chosen_df, time_col).to_numpy(dtype=float),
            "latitude_deg": _to_numeric_series(chosen_df, lat_col).to_numpy(dtype=float),
            "longitude_deg": _to_numeric_series(chosen_df, lon_col).to_numpy(dtype=float),
        }
    )

    alt_col = _first_existing(chosen_df, _ALT_COLS)
    speed_col = _first_existing(chosen_df, _SPEED_COLS)
    distance_col = _first_existing(chosen_df, _DISTANCE_COLS)

    if alt_col is not None:
        route_df["altitude_m"] = _to_numeric_series(chosen_df, alt_col).to_numpy(dtype=float)
    else:
        route_df["altitude_m"] = np.nan

    if speed_col is not None:
        route_df["speed_mps"] = _to_numeric_series(chosen_df, speed_col).to_numpy(dtype=float)
    else:
        route_df["speed_mps"] = np.nan

    if distance_col is not None:
        route_df["distance_m"] = _to_numeric_series(chosen_df, distance_col).to_numpy(dtype=float)
    else:
        route_df["distance_m"] = np.nan

    mask = (
        np.isfinite(route_df["time_s"].to_numpy(dtype=float))
        & np.isfinite(route_df["latitude_deg"].to_numpy(dtype=float))
        & np.isfinite(route_df["longitude_deg"].to_numpy(dtype=float))
    )
    route_df = route_df.loc[mask].copy()
    if route_df.empty:
        return None

    route_df = route_df.sort_values("time_s", kind="stable")
    route_df = route_df.loc[~route_df["time_s"].duplicated(keep="first")].reset_index(drop=True)

    primary_time_bounds = None
    if primary_df is not None and not primary_df.empty:
        primary_time_bounds = _time_bounds(primary_df, time_col=time_col)
    if primary_time_bounds is not None:
        session_t0_s, session_t1_s = primary_time_bounds
        route_df = route_df.loc[
            (route_df["time_s"] >= session_t0_s) & (route_df["time_s"] <= session_t1_s)
        ].copy()
        if route_df.empty:
            return None
        route_df = route_df.reset_index(drop=True)

    target_time_s = route_df["time_s"].to_numpy(dtype=float)
    if primary_df is not None and not primary_df.empty:
        if not np.isfinite(route_df["altitude_m"].to_numpy(dtype=float)).any():
            primary_alt = _first_existing(primary_df, _ALT_COLS)
            if primary_alt is not None:
                route_df["altitude_m"] = _interpolate_primary_col(
                    primary_df,
                    target_time_s=target_time_s,
                    source_col=primary_alt,
                    time_col=time_col,
                )

        if not np.isfinite(route_df["speed_mps"].to_numpy(dtype=float)).any():
            primary_speed = _first_existing(primary_df, _SPEED_COLS)
            if primary_speed is not None:
                route_df["speed_mps"] = _interpolate_primary_col(
                    primary_df,
                    target_time_s=target_time_s,
                    source_col=primary_speed,
                    time_col=time_col,
                )

    return GPSViewData(
        session_key=str(session_key),
        source_stream_name=str(chosen_name),
        route_df=route_df.reset_index(drop=True),
        has_altitude=bool(np.isfinite(route_df["altitude_m"].to_numpy(dtype=float)).any()),
        has_speed=bool(np.isfinite(route_df["speed_mps"].to_numpy(dtype=float)).any()),
    )


def build_route_segments(route_df: pd.DataFrame) -> pd.DataFrame:
    if route_df is None or route_df.empty or len(route_df.index) < 2:
        return pd.DataFrame()

    time_s = pd.to_numeric(route_df["time_s"], errors="coerce").to_numpy(dtype=float)
    lat = pd.to_numeric(route_df["latitude_deg"], errors="coerce").to_numpy(dtype=float)
    lon = pd.to_numeric(route_df["longitude_deg"], errors="coerce").to_numpy(dtype=float)
    alt = pd.to_numeric(route_df.get("altitude_m", pd.Series(np.nan, index=route_df.index)), errors="coerce").to_numpy(dtype=float)
    speed = pd.to_numeric(route_df.get("speed_mps", pd.Series(np.nan, index=route_df.index)), errors="coerce").to_numpy(dtype=float)

    rows: list[dict[str, Any]] = []
    for i in range(len(route_df.index) - 1):
        if not (
            np.isfinite(time_s[i])
            and np.isfinite(time_s[i + 1])
            and np.isfinite(lat[i])
            and np.isfinite(lat[i + 1])
            and np.isfinite(lon[i])
            and np.isfinite(lon[i + 1])
        ):
            continue
        if float(time_s[i + 1]) <= float(time_s[i]):
            continue

        speed_vals = [x for x in (speed[i], speed[i + 1]) if np.isfinite(x)]
        speed_value = float(np.mean(speed_vals)) if speed_vals else np.nan
        rows.append(
            {
                "time_start_s": float(time_s[i]),
                "time_end_s": float(time_s[i + 1]),
                "lat0_deg": float(lat[i]),
                "lon0_deg": float(lon[i]),
                "lat1_deg": float(lat[i + 1]),
                "lon1_deg": float(lon[i + 1]),
                "alt0_m": float(alt[i]) if np.isfinite(alt[i]) else np.nan,
                "alt1_m": float(alt[i + 1]) if np.isfinite(alt[i + 1]) else np.nan,
                "speed_mps": speed_value,
            }
        )

    return pd.DataFrame(rows)


def build_speed_color_bins(
    values: Sequence[float],
    *,
    n_bins: int = 8,
    colorscale: str = "Viridis",
) -> list[SpeedColorBin]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return []

    edges_kmh = tuple(float(x) for x in _DEFAULT_SPEED_BIN_EDGES_KMH)
    n_bins = len(edges_kmh)
    colors = tuple(str(x) for x in _DEFAULT_SPEED_BIN_COLORS)
    out: list[SpeedColorBin] = []
    for idx in range(n_bins):
        lo_kmh = float(edges_kmh[idx])
        lo = lo_kmh / 3.6
        if idx == (n_bins - 1):
            hi = float(np.inf)
            label = f"{int(lo_kmh)}+ km/h"
        else:
            hi_kmh = float(edges_kmh[idx + 1])
            hi = hi_kmh / 3.6
            label = f"{int(lo_kmh)}-{int(hi_kmh)} km/h"
        out.append(
            SpeedColorBin(
                idx=idx,
                lower_mps=lo,
                upper_mps=hi,
                color=colors[idx],
                label=label,
            )
        )
    return out


def _color_bin_index(value: float, bins: Sequence[SpeedColorBin]) -> Optional[int]:
    if not np.isfinite(value) or not bins:
        return None
    value_f = float(value)
    if value_f < float(bins[0].lower_mps):
        return 0
    for idx, item in enumerate(bins):
        is_last = idx == (len(bins) - 1)
        in_bin = (
            item.lower_mps <= value_f <= item.upper_mps
            if is_last
            else item.lower_mps <= value_f < item.upper_mps
        )
        if in_bin:
            return idx
    return len(bins) - 1


def build_line_runs_from_segments(
    segment_df: pd.DataFrame,
    *,
    color_by_speed: bool,
    n_bins: int = 8,
    default_color: str = _DEFAULT_ROUTE_COLOR,
) -> tuple[list[LineRun], list[SpeedColorBin]]:
    if segment_df is None or segment_df.empty:
        return [], []

    bins = build_speed_color_bins(segment_df.get("speed_mps", pd.Series(dtype=float)).to_numpy(dtype=float), n_bins=n_bins)
    rows = segment_df.reset_index(drop=True)
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    for _, row in rows.iterrows():
        speed_value = float(row.get("speed_mps", np.nan))
        if color_by_speed and bins:
            bin_idx = _color_bin_index(speed_value, bins)
            color = bins[bin_idx].color if bin_idx is not None else default_color
            label = bins[bin_idx].label if bin_idx is not None else "speed unavailable"
        else:
            color = default_color
            label = "route"

        p0 = (float(row["lat0_deg"]), float(row["lon0_deg"]))
        p1 = (float(row["lat1_deg"]), float(row["lon1_deg"]))
        t0 = float(row["time_start_s"])
        t1 = float(row["time_end_s"])
        a0 = float(row["alt0_m"]) if np.isfinite(float(row.get("alt0_m", np.nan))) else np.nan
        a1 = float(row["alt1_m"]) if np.isfinite(float(row.get("alt1_m", np.nan))) else np.nan

        key = (str(color), str(label))
        bucket = groups.get(key)
        if bucket is None:
            bucket = {
                "color": color,
                "label": label,
                "times_s": [],
                "altitudes_m": [],
                "speeds_mps": [],
                "coordinates": [],
                "segment_count": 0,
            }
            groups[key] = bucket
        elif bucket["times_s"]:
            bucket["times_s"].append(np.nan)
            bucket["altitudes_m"].append(np.nan)
            bucket["speeds_mps"].append(np.nan)
            bucket["coordinates"].append((np.nan, np.nan))

        bucket["times_s"].extend([t0, t1])
        bucket["altitudes_m"].extend([a0, a1])
        bucket["speeds_mps"].extend([speed_value, speed_value])
        bucket["coordinates"].extend([p0, p1])
        bucket["segment_count"] += 1

    runs: list[LineRun] = []
    for bucket in groups.values():
        runs.append(
            LineRun(
                color=str(bucket["color"]),
                label=str(bucket["label"]),
                times_s=tuple(float(x) if np.isfinite(x) else np.nan for x in bucket["times_s"]),
                altitudes_m=tuple(float(x) if np.isfinite(x) else np.nan for x in bucket["altitudes_m"]),
                speeds_mps=tuple(float(x) if np.isfinite(x) else np.nan for x in bucket["speeds_mps"]),
                coordinates=tuple(
                    (
                        float(lat) if np.isfinite(lat) else np.nan,
                        float(lon) if np.isfinite(lon) else np.nan,
                    )
                    for lat, lon in bucket["coordinates"]
                ),
                point_count=int(sum(1 for lat, lon in bucket["coordinates"] if np.isfinite(lat) and np.isfinite(lon))),
                segment_count=int(bucket["segment_count"]),
            )
        )
    return runs, bins


def subset_segments_by_window(
    segment_df: pd.DataFrame,
    *,
    t0_s: Optional[float],
    t1_s: Optional[float],
) -> pd.DataFrame:
    if segment_df is None or segment_df.empty:
        return pd.DataFrame()
    if t0_s is None or t1_s is None:
        return segment_df.copy()
    a = float(min(t0_s, t1_s))
    b = float(max(t0_s, t1_s))
    return segment_df.loc[
        (pd.to_numeric(segment_df["time_end_s"], errors="coerce") >= a)
        & (pd.to_numeric(segment_df["time_start_s"], errors="coerce") <= b)
    ].copy()


def nearest_route_point(route_df: pd.DataFrame, *, time_s: Optional[float]) -> Optional[dict[str, float]]:
    if route_df is None or route_df.empty or time_s is None:
        return None

    t = pd.to_numeric(route_df["time_s"], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(t)
    if not mask.any():
        return None

    idx_candidates = np.flatnonzero(mask)
    nearest_idx = int(idx_candidates[np.argmin(np.abs(t[mask] - float(time_s)))])
    row = route_df.iloc[nearest_idx]
    return {
        "time_s": float(row["time_s"]),
        "latitude_deg": float(row["latitude_deg"]),
        "longitude_deg": float(row["longitude_deg"]),
        "altitude_m": float(row["altitude_m"]) if np.isfinite(float(row.get("altitude_m", np.nan))) else np.nan,
        "speed_mps": float(row["speed_mps"]) if np.isfinite(float(row.get("speed_mps", np.nan))) else np.nan,
    }


def route_bounds(route_df: pd.DataFrame) -> Optional[list[list[float]]]:
    if route_df is None or route_df.empty:
        return None

    lat = pd.to_numeric(route_df["latitude_deg"], errors="coerce").to_numpy(dtype=float)
    lon = pd.to_numeric(route_df["longitude_deg"], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(lat) & np.isfinite(lon)
    if not mask.any():
        return None

    return [
        [float(np.min(lat[mask])), float(np.min(lon[mask]))],
        [float(np.max(lat[mask])), float(np.max(lon[mask]))],
    ]
