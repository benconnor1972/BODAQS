"""Build and load the compact real-data spatial-context regression corpus."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .artifacts import ArtifactStore, load_session_artifacts
from .spatial_context import DEFAULT_SPATIAL_CONTEXT_CONFIG, derive_spatial_context


CORPUS_SCHEMA = "bodaqs.spatial_context_regression_corpus"
CORPUS_VERSION = 1
SOURCE_RUN_ID = "ben-stevo-rc3001_260830_171848"

PRIMARY_COLUMNS = (
    "time_s",
    "active_mask_qc",
    "front_wheel_disp_dom_wheel [mm]",
    "rear_wheel_disp_dom_wheel [mm]",
)
GPS_COLUMNS = (
    "time_s",
    "latitude_deg",
    "longitude_deg",
    "altitude_m",
    "valid",
    "fresh",
    "seq",
    "horizontal_accuracy",
)

REAL_CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "case_id": "pipenhot_full",
        "session_id": "260830_112024_282b52292710",
        "tags": ["full_session", "gps_zigzag", "inactivity", "known_track_alignment_case"],
    },
    {
        "case_id": "sendit2_full",
        "session_id": "260830_141913_e482381b666b",
        "tags": ["full_session", "return_excursion", "inactivity", "continuity_boundary"],
    },
    {
        "case_id": "rapid_activity_boundaries",
        "session_id": "260830_132810_c6d6d57b9470",
        "time_range_s": [1038.0, 1090.0],
        "tags": ["short_extract", "rapid_activity_boundaries", "full_rate_suspension"],
    },
)

VARIANT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "case_id": "rapid_activity_boundaries_gps_1hz",
        "base_case_id": "rapid_activity_boundaries",
        "mutations": [{"kind": "gps_decimate", "factor": 5}],
        "tags": ["synthetic_fault", "minimum_nominal_gps_rate"],
    },
    {
        "case_id": "rapid_activity_boundaries_gps_outage",
        "base_case_id": "rapid_activity_boundaries",
        "mutations": [{"kind": "gps_remove_time_range", "start_s": 20.0, "end_s": 35.0}],
        "tags": ["synthetic_fault", "gps_outage", "continuity_boundary"],
    },
    {
        "case_id": "rapid_activity_boundaries_no_rear_wheel",
        "base_case_id": "rapid_activity_boundaries",
        "mutations": [{"kind": "omit_rear_wheel"}],
        "tags": ["synthetic_fault", "missing_rear_wheel"],
    },
    {
        "case_id": "rapid_activity_boundaries_no_active_mask",
        "base_case_id": "rapid_activity_boundaries",
        "mutations": [{"kind": "omit_active_mask"}],
        "tags": ["synthetic_fault", "missing_active_mask"],
    },
)

CANONICAL_CONFIG_OVERRIDES: dict[str, Any] = {}

_EARTH_RADIUS_M = 6_371_000.0


def corpus_config() -> dict[str, Any]:
    """Return the canonical configuration used to generate corpus expectations."""

    config = copy.deepcopy(DEFAULT_SPATIAL_CONTEXT_CONFIG)
    _deep_update(config, CANONICAL_CONFIG_OVERRIDES)
    return config


def load_corpus_manifest(corpus_root: str | Path) -> dict[str, Any]:
    return json.loads((Path(corpus_root) / "manifest.json").read_text(encoding="utf-8"))


def load_corpus_case(
    corpus_root: str | Path,
    case_id: str,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load one physical or virtual corpus case as a derive-compatible session."""

    root = Path(corpus_root)
    corpus = dict(manifest or load_corpus_manifest(root))
    cases = {case["case_id"]: case for case in corpus["cases"]}
    if case_id not in cases:
        raise KeyError(f"Unknown spatial-context corpus case: {case_id}")
    case = cases[case_id]
    base_case_id = str(case.get("base_case_id") or case_id)
    base_case = cases[base_case_id]
    case_dir = root / "cases" / base_case_id
    session = {
        "session_id": case_id,
        "source": {"type": "spatial_context_regression_corpus"},
        "df": pd.read_parquet(case_dir / "primary.parquet"),
        "meta": json.loads((case_dir / "metadata.json").read_text(encoding="utf-8")),
        "stream_dfs": {"gps_logger": pd.read_parquet(case_dir / "gps.parquet")},
    }
    for mutation in case.get("mutations", []):
        _apply_mutation(session, mutation)
    return session


def build_spatial_context_corpus(
    source_library_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Build the committed corpus from the nominated private source run."""

    source_store = ArtifactStore(Path(source_library_root))
    output = Path(output_root)
    cases_dir = output / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    for spec in REAL_CASE_SPECS:
        source = load_session_artifacts(
            source_store,
            run_id=SOURCE_RUN_ID,
            session_id=spec["session_id"],
        )
        case_session = _extract_case(source, spec)
        case_dir = cases_dir / spec["case_id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        case_session["df"].to_parquet(
            case_dir / "primary.parquet", index=False, compression="zstd"
        )
        case_session["stream_dfs"]["gps_logger"].to_parquet(
            case_dir / "gps.parquet", index=False, compression="zstd"
        )
        (case_dir / "metadata.json").write_text(
            json.dumps(case_session["meta"], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        case_record = {
            **copy.deepcopy(spec),
            "kind": "real_extract",
            "input_sha256": _case_input_sha256(case_session),
            "primary_rows": len(case_session["df"]),
            "gps_rows": len(case_session["stream_dfs"]["gps_logger"]),
            "expect": _summarize_result(case_session),
        }
        cases.append(case_record)

    physical_cases = {case["case_id"]: case for case in cases}
    for spec in VARIANT_SPECS:
        base_id = spec["base_case_id"]
        base_session = load_corpus_case_from_output(output, physical_cases[base_id])
        for mutation in spec["mutations"]:
            _apply_mutation(base_session, mutation)
        cases.append(
            {
                **copy.deepcopy(spec),
                "kind": "deterministic_variant",
                "expect": _summarize_result(base_session),
            }
        )

    manifest = {
        "schema": CORPUS_SCHEMA,
        "version": CORPUS_VERSION,
        "source": {
            "run_id": SOURCE_RUN_ID,
            "description": "Sunday Collie intel gathering",
            "materialized_session_count_observed": 6,
            "declared_import_session_count": 7,
            "session_count_note": (
                "One spurious, non-useful session was manually deleted after the run completed."
            ),
            "materialization_note": (
                "One spurious session was intentionally deleted after the run completed."
            ),
        },
        "privacy": {
            "coordinates_relocated": True,
            "time_rebased": True,
            "altitude_rebased": True,
            "route_shape_retained": True,
        },
        "config_overrides": copy.deepcopy(CANONICAL_CONFIG_OVERRIDES),
        "numeric_tolerances": {
            "distance_absolute_m": 0.5,
            "metric_relative": 0.02,
            "metric_absolute": 1e-6,
        },
        "cases": cases,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def load_corpus_case_from_output(output_root: Path, case: Mapping[str, Any]) -> dict[str, Any]:
    case_dir = output_root / "cases" / str(case["case_id"])
    return {
        "session_id": str(case["case_id"]),
        "source": {"type": "spatial_context_regression_corpus"},
        "df": pd.read_parquet(case_dir / "primary.parquet"),
        "meta": json.loads((case_dir / "metadata.json").read_text(encoding="utf-8")),
        "stream_dfs": {"gps_logger": pd.read_parquet(case_dir / "gps.parquet")},
    }


def _extract_case(source: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    primary = source["df"]
    gps = source["stream_dfs"]["gps_logger"]
    start_s, end_s = _case_time_bounds(primary, spec.get("time_range_s"))
    primary_out = primary.loc[
        primary["time_s"].between(start_s, end_s),
        [column for column in PRIMARY_COLUMNS if column in primary],
    ].copy()
    gps_out = gps.loc[
        gps["time_s"].between(start_s, end_s),
        [column for column in GPS_COLUMNS if column in gps],
    ].copy()
    if primary_out.empty or gps_out.empty:
        raise ValueError(f"Corpus case {spec['case_id']} has no source data")

    primary_out["time_s"] = primary_out["time_s"].astype(float) - start_s
    gps_out["time_s"] = gps_out["time_s"].astype(float) - start_s
    _relocate_gps(gps_out)

    source_meta = source.get("meta", {})
    registry = source_meta.get("signals") or source_meta.get("channel_info") or {}
    signals = {
        column: copy.deepcopy(registry[column])
        for column in primary_out.columns
        if column in registry
    }
    secondary_source = source.get("secondary_stream_meta", {}).get("gps_logger", {})
    secondary_meta = _minimal_gps_metadata(secondary_source, gps_out.columns)
    meta = {
        "session_id": str(spec["case_id"]),
        "signals": signals,
        "channel_info": copy.deepcopy(signals),
        "secondary_streams": {"gps_logger": secondary_meta},
        "gps_sources": {"preferred_source": "gps_logger"},
        "corpus_provenance": {
            "source_run_id": SOURCE_RUN_ID,
            "source_session_id": str(spec["session_id"]),
            "source_time_range_s": [start_s, end_s],
        },
    }
    return {
        "session_id": str(spec["case_id"]),
        "source": {"type": "spatial_context_regression_corpus"},
        "df": primary_out.reset_index(drop=True),
        "meta": meta,
        "stream_dfs": {"gps_logger": gps_out.reset_index(drop=True)},
    }


def _case_time_bounds(primary: pd.DataFrame, requested: Any) -> tuple[float, float]:
    lower = float(primary["time_s"].min())
    upper = float(primary["time_s"].max())
    if requested is None:
        return lower, upper
    start_s, end_s = map(float, requested)
    return max(lower, start_s), min(upper, end_s)


def _relocate_gps(gps: pd.DataFrame) -> None:
    valid = gps[["latitude_deg", "longitude_deg"]].dropna()
    if valid.empty:
        return
    source_latitude = float(valid.iloc[0]["latitude_deg"])
    source_longitude = float(valid.iloc[0]["longitude_deg"])
    latitude = pd.to_numeric(gps["latitude_deg"], errors="coerce").to_numpy(float)
    longitude = pd.to_numeric(gps["longitude_deg"], errors="coerce").to_numpy(float)
    north_m = np.radians(latitude - source_latitude) * _EARTH_RADIUS_M
    east_m = (
        np.radians(longitude - source_longitude)
        * _EARTH_RADIUS_M
        * math.cos(math.radians(source_latitude))
    )
    gps["latitude_deg"] = np.degrees(north_m / _EARTH_RADIUS_M)
    gps["longitude_deg"] = np.degrees(east_m / _EARTH_RADIUS_M)
    if "altitude_m" in gps:
        altitude = pd.to_numeric(gps["altitude_m"], errors="coerce")
        finite = altitude.dropna()
        if not finite.empty:
            gps["altitude_m"] = altitude - float(finite.iloc[0])


def _minimal_gps_metadata(source: Mapping[str, Any], columns: Sequence[str]) -> dict[str, Any]:
    registry = source.get("signals") or source.get("channel_info") or {}
    signals = {
        column: copy.deepcopy(registry[column])
        for column in columns
        if column in registry
    }
    return {
        "stream_name": "gps_logger",
        "source_kind": "logger_sensor",
        "source": "logger_gps",
        "sensor": "gps",
        "kind": "intermittent",
        "time_col": "time_s",
        "position_columns": {"latitude": "latitude_deg", "longitude": "longitude_deg"},
        "signals": signals,
        "channel_info": copy.deepcopy(signals),
    }


def _apply_mutation(session: dict[str, Any], mutation: Mapping[str, Any]) -> None:
    kind = str(mutation["kind"])
    if kind == "gps_decimate":
        factor = int(mutation["factor"])
        session["stream_dfs"]["gps_logger"] = (
            session["stream_dfs"]["gps_logger"].iloc[::factor].reset_index(drop=True)
        )
        return
    if kind == "gps_remove_time_range":
        gps = session["stream_dfs"]["gps_logger"]
        retained = ~gps["time_s"].between(
            float(mutation["start_s"]), float(mutation["end_s"])
        )
        session["stream_dfs"]["gps_logger"] = gps.loc[retained].reset_index(drop=True)
        return
    if kind == "omit_rear_wheel":
        column = "rear_wheel_disp_dom_wheel [mm]"
        session["df"] = session["df"].drop(columns=[column], errors="ignore")
        session["meta"].get("signals", {}).pop(column, None)
        session["meta"].get("channel_info", {}).pop(column, None)
        return
    if kind == "omit_active_mask":
        column = "active_mask_qc"
        session["df"] = session["df"].drop(columns=[column], errors="ignore")
        session["meta"].get("signals", {}).pop(column, None)
        session["meta"].get("channel_info", {}).pop(column, None)
        return
    raise ValueError(f"Unsupported corpus mutation: {kind}")


def _summarize_result(session: Mapping[str, Any]) -> dict[str, Any]:
    result = derive_spatial_context(session, corpus_config())
    stream = result.stream_df
    selected = result.stream_meta.get("distance_source", {}).get("selected") or {}
    metrics = {}
    for column in (
        "gradient_fraction",
        "twistiness_rad_per_m",
        "front_suspension_activity",
        "rear_suspension_activity",
        "combined_suspension_activity",
    ):
        if column not in stream:
            continue
        values = pd.to_numeric(stream[column], errors="coerce").dropna()
        metrics[column] = {
            "valid_rows": int(len(values)),
            "median": _finite_or_none(values.median()),
            "p95": _finite_or_none(values.quantile(0.95)),
        }
    return {
        "status": result.stream_meta.get("status"),
        "distance_source": selected.get("candidate_kind"),
        "spatial_rows": int(len(stream)),
        "distance_m": _finite_or_none(stream["distance_m"].max()) if not stream.empty else None,
        "warnings": sorted(map(str, result.stream_meta.get("warnings", []))),
        "metrics": metrics,
    }


def _case_input_sha256(session: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    for frame in (session["df"], session["stream_dfs"]["gps_logger"]):
        digest.update(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes())
        digest.update("\0".join(map(str, frame.columns)).encode("utf-8"))
    digest.update(json.dumps(session["meta"], sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _finite_or_none(value: Any) -> float | None:
    number = float(value)
    return number if np.isfinite(number) else None


def _deep_update(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-library-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_spatial_context_corpus(args.source_library_root, args.output_root)
    print(f"Built {len(manifest['cases'])} cases in {args.output_root}")


if __name__ == "__main__":
    _main()
