from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from .timebase import register_stream_metadata

GPS_SOURCES_SCHEMA = "bodaqs.gps_sources"
GPS_SOURCES_VERSION = 1
DEFAULT_LOGGER_GPS_STREAM_NAME = "gps_logger"

_LATITUDE_QUANTITIES = {"position_latitude", "latitude", "position_lat", "lat"}
_LONGITUDE_QUANTITIES = {"position_longitude", "longitude", "position_long", "lon", "long"}
_ALTITUDE_QUANTITIES = {"altitude", "elevation"}
_SPEED_QUANTITIES = {"speed", "enhanced_speed"}
_HEADING_QUANTITIES = {"heading", "course"}
_DISTANCE_QUANTITIES = {"distance"}
_VALID_QUANTITIES = {"valid", "fix_valid"}
_AGE_QUANTITIES = {"age", "snapshot_age"}
_SEQ_QUANTITIES = {"seq", "sequence", "sequence_id"}
_FRESH_QUANTITIES = {"fresh", "new_fix"}
_FIX_TYPE_QUANTITIES = {"fix_type"}
_SATELLITES_QUANTITIES = {"satellites", "sats"}
_HACC_QUANTITIES = {"horizontal_accuracy", "hacc", "horizontal_accuracy_m"}
_VACC_QUANTITIES = {"vertical_accuracy", "vacc", "vertical_accuracy_m"}


@dataclass(frozen=True)
class GPSColumnSet:
    latitude: str
    longitude: str
    altitude: Optional[str] = None
    speed: Optional[str] = None
    heading: Optional[str] = None
    distance: Optional[str] = None
    valid: Optional[str] = None
    age: Optional[str] = None
    seq: Optional[str] = None
    fresh: Optional[str] = None
    fix_type: Optional[str] = None
    satellites: Optional[str] = None
    horizontal_accuracy: Optional[str] = None
    vertical_accuracy: Optional[str] = None
    sensor: Optional[str] = None
    source: Optional[str] = None
    source_kind: str = "unknown"

    @property
    def quality_columns(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in (
            "valid",
            "age",
            "seq",
            "fresh",
            "fix_type",
            "satellites",
            "horizontal_accuracy",
            "vertical_accuracy",
        ):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out


def normalize_gps_source_policy(value: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    policy = dict(value or {})
    preference = str(policy.get("preferred_source") or "logger_then_fit").strip().lower()
    if preference not in {
        "logger_then_fit",
        "fit_then_logger",
        "best_coverage",
        "logger",
        "logger_sensor",
        "fit",
        "fit_enrichment",
    }:
        preference = "logger_then_fit"
    return {
        "preferred_source": preference,
        "preserve_all_sources": bool(policy.get("preserve_all_sources", True)),
        "build_logger_stream": bool(policy.get("build_logger_stream", True)),
        "logger_stream_name": _nonempty_text(policy.get("logger_stream_name")) or DEFAULT_LOGGER_GPS_STREAM_NAME,
    }


def resolve_gps_columns(
    metadata: Mapping[str, Any],
    *,
    known_columns: Optional[set[str]] = None,
    require_logger_source: bool = False,
) -> Optional[GPSColumnSet]:
    column_info = _metadata_column_info(metadata, known_columns=known_columns)
    if not column_info:
        return None

    latitude_candidates = _matching_columns(column_info, known_columns, _is_latitude_column)
    longitude_candidates = _matching_columns(column_info, known_columns, _is_longitude_column)
    if require_logger_source:
        latitude_candidates = [
            col for col in latitude_candidates if _source_kind_for_column(col, column_info.get(col, {})) == "logger_sensor"
        ]
        longitude_candidates = [
            col for col in longitude_candidates if _source_kind_for_column(col, column_info.get(col, {})) == "logger_sensor"
        ]
    if not latitude_candidates or not longitude_candidates:
        return None

    paired = _paired_position_columns(latitude_candidates, longitude_candidates, column_info)
    if paired is None:
        return None
    latitude, longitude = paired
    lat_info = column_info.get(latitude, {})
    group_key = _gps_group_key(latitude, lat_info) or _gps_group_key(longitude, column_info.get(longitude, {}))
    source_kind = _source_kind_for_column(latitude, lat_info)

    def pick(predicate: Any) -> Optional[str]:
        candidates = _matching_columns(column_info, known_columns, predicate)
        if require_logger_source:
            candidates = [
                col for col in candidates if _source_kind_for_column(col, column_info.get(col, {})) == "logger_sensor"
            ]
        same_group = [
            col for col in candidates
            if group_key is not None and _gps_group_key(col, column_info.get(col, {})) == group_key
        ]
        if same_group:
            return same_group[0]
        # A sole ungrouped legacy column is safe only when the selected
        # position pair is also ungrouped. Never borrow QC or motion fields
        # from a different explicitly identified GPS source.
        if group_key is None and len(candidates) == 1 and _gps_group_key(
            candidates[0], column_info.get(candidates[0], {})
        ) is None:
            return candidates[0]
        return None

    return GPSColumnSet(
        latitude=latitude,
        longitude=longitude,
        altitude=pick(_is_altitude_column),
        speed=pick(_is_speed_column),
        heading=pick(_is_heading_column),
        distance=pick(_is_distance_column),
        valid=pick(_is_valid_column),
        age=pick(_is_age_column),
        seq=pick(_is_seq_column),
        fresh=pick(_is_fresh_column),
        fix_type=pick(_is_fix_type_column),
        satellites=pick(_is_satellites_column),
        horizontal_accuracy=pick(_is_hacc_column),
        vertical_accuracy=pick(_is_vacc_column),
        sensor=_nonempty_text(lat_info.get("sensor")),
        source=_nonempty_text(lat_info.get("source")),
        source_kind=source_kind,
    )


def build_logger_gps_route_stream(
    session: dict[str, Any],
    *,
    gps_source_policy: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    policy = normalize_gps_source_policy(gps_source_policy)
    if not policy["build_logger_stream"]:
        return session

    df = session.get("df")
    if not isinstance(df, pd.DataFrame) or "time_s" not in df.columns:
        return session

    meta = session.get("meta") if isinstance(session.get("meta"), Mapping) else {}
    columns = resolve_gps_columns(meta, known_columns=set(map(str, df.columns)), require_logger_source=True)
    if columns is None:
        return session

    stream_name = str(policy["logger_stream_name"])
    route_df, route_meta = _logger_route_dataframe(df, columns)
    if route_df.empty:
        _set_gps_qc(session, stream_name, columns, route_meta, status="empty")
        return session

    stream_dfs = session.setdefault("stream_dfs", {})
    if not isinstance(stream_dfs, dict):
        stream_dfs = {}
        session["stream_dfs"] = stream_dfs
    stream_dfs[stream_name] = route_df

    register_stream_metadata(
        session,
        stream_name=stream_name,
        kind="intermittent",
        time_col="time_s",
        notes="Logger GPS route reconstructed from primary-row async snapshots",
    )

    secondary_streams = session.setdefault("meta", {}).setdefault("secondary_streams", {})
    if not isinstance(secondary_streams, dict):
        secondary_streams = {}
        session["meta"]["secondary_streams"] = secondary_streams
    secondary_streams[stream_name] = _logger_stream_metadata(stream_name, columns, route_meta)
    _set_gps_qc(session, stream_name, columns, route_meta, status="succeeded")
    return session


def refresh_gps_source_metadata(
    session: dict[str, Any],
    *,
    gps_source_policy: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    policy = normalize_gps_source_policy(gps_source_policy)
    sources: list[dict[str, Any]] = []

    stream_dfs = session.get("stream_dfs")
    secondary_streams = session.get("meta", {}).get("secondary_streams") if isinstance(session.get("meta"), Mapping) else {}
    if isinstance(stream_dfs, Mapping):
        for stream_name, stream_df in stream_dfs.items():
            if not isinstance(stream_name, str) or not isinstance(stream_df, pd.DataFrame):
                continue
            stream_meta = {}
            if isinstance(secondary_streams, Mapping):
                candidate_meta = secondary_streams.get(stream_name)
                if isinstance(candidate_meta, Mapping):
                    stream_meta = dict(candidate_meta)
            source = _source_summary_from_frame(
                source_id=stream_name,
                stream_name=stream_name,
                df=stream_df,
                metadata=stream_meta,
            )
            if source is not None:
                sources.append(source)

    if not sources:
        df = session.get("df")
        meta = session.get("meta") if isinstance(session.get("meta"), Mapping) else {}
        if isinstance(df, pd.DataFrame):
            source = _source_summary_from_frame(
                source_id="primary",
                stream_name="primary",
                df=df,
                metadata=meta,
            )
            if source is not None:
                sources.append(source)

    preferred = _choose_preferred_source(sources, policy)
    gps_meta = {
        "schema": GPS_SOURCES_SCHEMA,
        "version": GPS_SOURCES_VERSION,
        "policy": policy,
        "preferred_source": preferred.get("source_id") if preferred else None,
        "preferred_source_kind": preferred.get("kind") if preferred else None,
        "sources": sources,
    }
    session.setdefault("meta", {})["gps_sources"] = gps_meta
    return session


def preferred_gps_source_name(
    session: Mapping[str, Any],
    *,
    fallback: Optional[str] = None,
) -> Optional[str]:
    meta = session.get("meta") if isinstance(session.get("meta"), Mapping) else {}
    gps_sources = meta.get("gps_sources") if isinstance(meta, Mapping) else None
    if isinstance(gps_sources, Mapping):
        preferred = _nonempty_text(gps_sources.get("preferred_source"))
        if preferred:
            return preferred
    return _nonempty_text(fallback)


def gps_source_kind(source_id: str, metadata: Mapping[str, Any], *, latitude_col: Optional[str] = None) -> str:
    explicit = _nonempty_text(metadata.get("source_kind"))
    if explicit in {"logger_sensor", "fit_enrichment"}:
        return explicit
    if latitude_col is not None:
        return _source_kind_for_column(latitude_col, _metadata_column_info(metadata).get(latitude_col, {}))
    text_parts = [source_id]
    for key in ("source", "sensor", "origin", "filename", "fit_filename", "stream_name"):
        value = metadata.get(key)
        if value is not None:
            text_parts.append(str(value))
    text = " ".join(text_parts).lower()
    if "fit" in text:
        return "fit_enrichment"
    if "gps" in text:
        return "logger_sensor"
    return "unknown"


def _logger_route_dataframe(df: pd.DataFrame, columns: GPSColumnSet) -> tuple[pd.DataFrame, dict[str, Any]]:
    route = pd.DataFrame(
        {
            "time_s": _numeric_array(df, "time_s"),
            "latitude_deg": _numeric_array(df, columns.latitude),
            "longitude_deg": _numeric_array(df, columns.longitude),
        }
    )
    if columns.altitude:
        route["altitude_m"] = _numeric_array(df, columns.altitude)
    if columns.speed:
        route["speed_mps"] = _numeric_array(df, columns.speed)
    if columns.heading:
        route["heading_deg"] = _numeric_array(df, columns.heading)
    if columns.distance:
        route["distance_m"] = _numeric_array(df, columns.distance)

    for qc_name, source_col in columns.quality_columns.items():
        route[_route_qc_column_name(qc_name)] = _numeric_array(df, source_col)

    initial_rows = int(len(route.index))
    finite_position = (
        np.isfinite(route["time_s"].to_numpy(dtype=float))
        & np.isfinite(route["latitude_deg"].to_numpy(dtype=float))
        & np.isfinite(route["longitude_deg"].to_numpy(dtype=float))
    )
    valid_filtered = False
    if "valid" in route.columns:
        valid_values = pd.to_numeric(route["valid"], errors="coerce").fillna(0)
        finite_position &= valid_values.astype(float).to_numpy() == 1.0
        valid_filtered = True
    route = route.loc[finite_position].copy()

    duplicate_snapshot_rows = 0
    dedupe_method = None
    if "seq" in route.columns:
        before = int(len(route.index))
        route = route.loc[~route["seq"].duplicated(keep="first")].copy()
        duplicate_snapshot_rows = before - int(len(route.index))
        dedupe_method = "seq"
    elif "fresh" in route.columns:
        fresh_values = pd.to_numeric(route["fresh"], errors="coerce").fillna(0)
        before = int(len(route.index))
        route = route.loc[fresh_values.astype(float).to_numpy() == 1.0].copy()
        duplicate_snapshot_rows = before - int(len(route.index))
        dedupe_method = "fresh"

    route = route.sort_values("time_s", kind="stable")
    route = route.loc[~route["time_s"].duplicated(keep="first")].reset_index(drop=True)

    ages = route["age_ms"].to_numpy(dtype=float) if "age_ms" in route.columns else np.array([], dtype=float)
    finite_ages = ages[np.isfinite(ages)]
    gaps = np.diff(route["time_s"].to_numpy(dtype=float)) if len(route.index) >= 2 else np.array([], dtype=float)
    finite_gaps = gaps[np.isfinite(gaps) & (gaps > 0)]
    meta = {
        "input_rows": initial_rows,
        "output_points": int(len(route.index)),
        "finite_position_rows": int(np.count_nonzero(finite_position)),
        "valid_filter_applied": valid_filtered,
        "dedupe_method": dedupe_method,
        "duplicate_snapshot_rows_removed": int(duplicate_snapshot_rows),
        "cached_async_snapshots": bool(dedupe_method is None),
        "age_ms_median": float(np.median(finite_ages)) if finite_ages.size else None,
        "age_ms_max": float(np.max(finite_ages)) if finite_ages.size else None,
        "gap_s_median": float(np.median(finite_gaps)) if finite_gaps.size else None,
        "gap_s_max": float(np.max(finite_gaps)) if finite_gaps.size else None,
    }
    return route, meta


def _logger_stream_metadata(stream_name: str, columns: GPSColumnSet, route_meta: Mapping[str, Any]) -> dict[str, Any]:
    channel_info = {
        "latitude_deg": {
            "unit": "deg",
            "domain": "world",
            "quantity": "position_latitude",
            "sensor": columns.sensor,
            "source": "logger_gps",
            "source_columns": [columns.latitude],
        },
        "longitude_deg": {
            "unit": "deg",
            "domain": "world",
            "quantity": "position_longitude",
            "sensor": columns.sensor,
            "source": "logger_gps",
            "source_columns": [columns.longitude],
        },
    }
    optional_specs = {
        "altitude_m": (columns.altitude, "altitude", "m"),
        "speed_mps": (columns.speed, "speed", "m/s"),
        "heading_deg": (columns.heading, "heading", "deg"),
        "distance_m": (columns.distance, "distance", "m"),
    }
    for output_col, (source_col, quantity, unit) in optional_specs.items():
        if source_col:
            channel_info[output_col] = {
                "unit": unit,
                "domain": "world",
                "quantity": quantity,
                "sensor": columns.sensor,
                "source": "logger_gps",
                "source_columns": [source_col],
            }
    for qc_name, source_col in columns.quality_columns.items():
        output_col = _route_qc_column_name(qc_name)
        channel_info[output_col] = {
            "kind": "qc",
            "quantity": qc_name,
            "processing_role": "qc_metric",
            "semantic_selection_excluded": True,
            "sensor": columns.sensor,
            "source": "logger_gps",
            "source_columns": [source_col],
        }
    return {
        "stream_name": stream_name,
        "kind": "intermittent",
        "source_kind": "logger_sensor",
        "source": "logger_gps",
        "sensor": columns.sensor,
        "time_col": "time_s",
        "position_columns": {
            "latitude": "latitude_deg",
            "longitude": "longitude_deg",
        },
        "source_position_columns": {
            "latitude": columns.latitude,
            "longitude": columns.longitude,
        },
        "quality_columns": columns.quality_columns,
        "channel_info": channel_info,
        "route_reconstruction": dict(route_meta),
    }


def _set_gps_qc(
    session: dict[str, Any],
    stream_name: str,
    columns: GPSColumnSet,
    route_meta: Mapping[str, Any],
    *,
    status: str,
) -> None:
    qc = session.setdefault("qc", {})
    gps_qc = qc.setdefault("gps", {})
    gps_qc[stream_name] = {
        "status": status,
        "source_kind": "logger_sensor",
        "sensor": columns.sensor,
        "position_columns": {
            "latitude": columns.latitude,
            "longitude": columns.longitude,
        },
        "quality_columns": columns.quality_columns,
        "route_reconstruction": dict(route_meta),
    }


def _source_summary_from_frame(
    *,
    source_id: str,
    stream_name: str,
    df: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    columns = resolve_gps_columns(metadata, known_columns=set(map(str, df.columns)))
    if columns is None:
        return None
    lat = pd.to_numeric(df[columns.latitude], errors="coerce")
    lon = pd.to_numeric(df[columns.longitude], errors="coerce")
    valid = lat.notna() & lon.notna()
    if "time_s" in df.columns:
        valid &= pd.to_numeric(df["time_s"], errors="coerce").notna()
    point_count = int(valid.sum())
    return {
        "source_id": source_id,
        "kind": gps_source_kind(source_id, metadata, latitude_col=columns.latitude),
        "stream_name": stream_name,
        "position_columns": {
            "latitude": columns.latitude,
            "longitude": columns.longitude,
        },
        "quality_columns": columns.quality_columns,
        "point_count": point_count,
        "sensor": columns.sensor,
        "_coverage_score": point_count,
    }


def _choose_preferred_source(sources: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    if not sources:
        return None
    preference = str(policy.get("preferred_source") or "logger_then_fit")
    if preference == "best_coverage":
        return max(sources, key=lambda source: int(source.get("_coverage_score") or 0))
    if preference in {"fit", "fit_enrichment", "fit_then_logger"}:
        kind_order = ("fit_enrichment", "logger_sensor", "unknown")
    else:
        kind_order = ("logger_sensor", "fit_enrichment", "unknown")
    order = {kind: index for index, kind in enumerate(kind_order)}
    return sorted(
        sources,
        key=lambda source: (
            order.get(str(source.get("kind") or "unknown"), len(order)),
            -int(source.get("_coverage_score") or 0),
            str(source.get("source_id") or ""),
        ),
    )[0]


def _metadata_column_info(
    metadata: Mapping[str, Any],
    *,
    known_columns: Optional[set[str]] = None,
) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for key in ("channel_info", "signals"):
        raw = metadata.get(key)
        if isinstance(raw, Mapping):
            for column, info in raw.items():
                out[str(column)] = info if isinstance(info, Mapping) else {}
    if known_columns is not None:
        for column in known_columns:
            out.setdefault(str(column), {})
    return out


def _matching_columns(
    column_info: Mapping[str, Mapping[str, Any]],
    known_columns: Optional[set[str]],
    predicate: Any,
) -> list[str]:
    candidates: list[str] = []
    for column, info in column_info.items():
        if known_columns is not None and column not in known_columns:
            continue
        if predicate(column, info):
            candidates.append(column)
    return sorted(candidates, key=_column_sort_key)


def _paired_position_columns(
    latitude_candidates: Sequence[str],
    longitude_candidates: Sequence[str],
    column_info: Mapping[str, Mapping[str, Any]],
) -> Optional[tuple[str, str]]:
    for lat in latitude_candidates:
        lat_group = _gps_group_key(lat, column_info.get(lat, {}))
        if not lat_group:
            continue
        for lon in longitude_candidates:
            if _gps_group_key(lon, column_info.get(lon, {})) == lat_group:
                return lat, lon
    if len(latitude_candidates) == 1 and len(longitude_candidates) == 1:
        lat = latitude_candidates[0]
        lon = longitude_candidates[0]
        lat_group = _gps_group_key(lat, column_info.get(lat, {}))
        lon_group = _gps_group_key(lon, column_info.get(lon, {}))
        if not lat_group or not lon_group:
            return lat, lon
    return None


def _column_sort_key(column: str) -> tuple[int, str]:
    lower = column.lower()
    if "gps_logger" in lower:
        return (0, lower)
    if "gps_fit" in lower:
        return (2, lower)
    return (1, lower)


def _is_latitude_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _LATITUDE_QUANTITIES or _text_matches(column, info, ("position_latitude", "latitude", "_lat"))


def _is_longitude_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _LONGITUDE_QUANTITIES or _text_matches(column, info, ("position_longitude", "longitude", "_lon"))


def _is_altitude_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _ALTITUDE_QUANTITIES or _text_matches(column, info, ("altitude", "elevation"))


def _is_speed_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _SPEED_QUANTITIES or _text_matches(column, info, ("speed",))


def _is_heading_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _HEADING_QUANTITIES or _text_matches(column, info, ("heading", "course"))


def _is_distance_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _DISTANCE_QUANTITIES or _text_matches(column, info, ("distance",))


def _is_valid_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _VALID_QUANTITIES or _text_matches(column, info, ("valid",))


def _is_age_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _AGE_QUANTITIES or _text_matches(column, info, ("age",))


def _is_seq_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _SEQ_QUANTITIES or _text_matches(column, info, ("seq",))


def _is_fresh_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _FRESH_QUANTITIES or _text_matches(column, info, ("fresh",))


def _is_fix_type_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _FIX_TYPE_QUANTITIES or _text_matches(column, info, ("fix_type",))


def _is_satellites_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _SATELLITES_QUANTITIES or _text_matches(column, info, ("satellites", "_sats"))


def _is_hacc_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _HACC_QUANTITIES or _text_matches(column, info, ("horizontal_accuracy", "_hacc"))


def _is_vacc_column(column: str, info: Mapping[str, Any]) -> bool:
    return _quantity(info) in _VACC_QUANTITIES or _text_matches(column, info, ("vertical_accuracy", "_vacc"))


def _text_matches(column: str, info: Mapping[str, Any], needles: Sequence[str]) -> bool:
    text = _semantic_text(column, info)
    return any(needle in text for needle in needles)


def _semantic_text(column: str, info: Mapping[str, Any]) -> str:
    parts = [column]
    for key in ("role", "quantity", "domain", "sensor", "origin", "source", "display_name", "processing_role"):
        value = info.get(key)
        if value is not None:
            parts.append(str(value))
    return " ".join(parts).replace("-", "_").lower()


def _quantity(info: Mapping[str, Any]) -> str:
    for key in ("quantity", "role"):
        value = _nonempty_text(info.get(key))
        if value:
            return value.replace("-", "_").lower()
    return ""


def _gps_group_key(column: str, info: Mapping[str, Any]) -> Optional[str]:
    for key in ("sensor", "source_id", "stream_name"):
        value = _nonempty_text(info.get(key))
        if value:
            return f"{key}:{value.lower()}"
    prefix = _gps_column_prefix(column)
    if prefix:
        return f"column:{prefix}"
    source_columns = info.get("source_columns")
    if isinstance(source_columns, Sequence) and not isinstance(source_columns, (str, bytes)):
        for value in source_columns:
            text = _nonempty_text(value)
            if text:
                source_prefix = _gps_column_prefix(text)
                if source_prefix:
                    return f"column:{source_prefix}"
    return None


def _gps_column_prefix(column: str) -> Optional[str]:
    lower = str(column).replace("-", "_").lower()
    markers = (
        "_position_latitude",
        "_position_longitude",
        "_latitude",
        "_longitude",
        "_lat",
        "_lon",
        "_alt",
        "_speed",
        "_heading",
        "_valid",
        "_age",
        "_seq",
        "_fresh",
        "_fix_type",
        "_sats",
        "_hacc",
        "_vacc",
    )
    positions = [lower.find(marker) for marker in markers]
    positions = [position for position in positions if position > 0]
    if not positions:
        return None
    return lower[: min(positions)]


def _source_kind_for_column(column: str, info: Mapping[str, Any]) -> str:
    explicit = _nonempty_text(info.get("source_kind"))
    if explicit in {"logger_sensor", "fit_enrichment"}:
        return explicit
    text = _semantic_text(column, info)
    if "fit" in text:
        return "fit_enrichment"
    if "gps" in text or _nonempty_text(info.get("origin")) == "logger":
        return "logger_sensor"
    return "unknown"


def _route_qc_column_name(qc_name: str) -> str:
    return "age_ms" if qc_name == "age" else qc_name


def _numeric_array(df: pd.DataFrame, column: str) -> np.ndarray:
    return pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)


def _nonempty_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None
