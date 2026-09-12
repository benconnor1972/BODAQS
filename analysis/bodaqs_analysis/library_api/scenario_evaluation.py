"""Synchronous evaluation of Scenario predicates into session Episodes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore

from .activity_index import activity_regions, build_activity_index, sample_cell_intervals
from .cache import stable_cache_digest
from .errors import InvalidRequestError, LibraryApiError
from .ids import make_session_key, make_session_ref_id
from .scenarios import normalize_scenario
from .timeseries import _parquet_columns, _read_json_object, _resolve_signal_requests, _resolve_time_column


SCENARIO_EVALUATION_SCHEMA = "bodaqs.scenario_evaluation"
SCENARIO_EVALUATION_VERSION = 1
SCENARIO_EVALUATION_ALGORITHM_VERSION = 1
MAX_SESSIONS = 32
MAX_EPISODES = 10_000
Interval = tuple[float, float]


def scenario_evaluation_cache_key(
    request: Mapping[str, Any],
    *,
    scenario: Mapping[str, Any],
    library_root: Callable[[str], Path],
) -> str:
    sessions = request.get("sessions") if isinstance(request, Mapping) else None
    if not isinstance(sessions, list) or not sessions:
        raise InvalidRequestError("Scenario evaluation requires at least one session.")
    if len(sessions) > MAX_SESSIONS:
        raise InvalidRequestError(
            f"Synchronous Scenario evaluation supports at most {MAX_SESSIONS} sessions.",
            details={"requested": len(sessions), "maximum": MAX_SESSIONS},
        )
    effective = normalize_scenario(scenario, scenario_id=_text_or_none(scenario.get("scenario_id")))
    refs = [_session_ref(raw_ref) for raw_ref in sessions]
    artifacts = [
        artifact
        for ref in refs
        for artifact in _input_artifacts(library_root(ref["library_id"]), ref, effective)
    ]
    options = request.get("options") if isinstance(request.get("options"), Mapping) else {}
    return stable_cache_digest(
        {
            "schema": SCENARIO_EVALUATION_SCHEMA,
            "version": SCENARIO_EVALUATION_VERSION,
            "algorithm_version": SCENARIO_EVALUATION_ALGORITHM_VERSION,
            "scenario": effective,
            "sessions": refs,
            "input_artifacts": artifacts,
            "options": options,
        }
    )


def evaluate_scenario(
    request: Mapping[str, Any],
    *,
    scenario: Mapping[str, Any],
    library_root: Callable[[str], Path],
    activity_index_loader: Callable[[Path, Mapping[str, str]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise InvalidRequestError("Scenario evaluation request must be an object.")
    if request.get("schema") not in (None, "bodaqs.scenario_evaluation_request"):
        raise InvalidRequestError("Scenario evaluation request schema is not supported.")
    if request.get("version") not in (None, 1):
        raise InvalidRequestError("Scenario evaluation request version is not supported.")
    sessions = request.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise InvalidRequestError("Scenario evaluation requires at least one session.")
    if len(sessions) > MAX_SESSIONS:
        raise InvalidRequestError(
            f"Synchronous Scenario evaluation supports at most {MAX_SESSIONS} sessions.",
            details={"requested": len(sessions), "maximum": MAX_SESSIONS},
        )
    effective = normalize_scenario(scenario, scenario_id=_text_or_none(scenario.get("scenario_id")))
    digest = stable_cache_digest(effective)
    refs = [_session_ref(raw_ref) for raw_ref in sessions]
    roots = [library_root(ref["library_id"]) for ref in refs]
    input_artifacts = [
        artifact
        for root, ref in zip(roots, refs)
        for artifact in _input_artifacts(root, ref, effective)
    ]
    evaluation_id = f"scenario-eval-{stable_cache_digest({'scenario': digest, 'sessions': refs, 'input_artifacts': input_artifacts})[:12]}"
    include_diagnostics = bool((request.get("options") or {}).get("include_criterion_diagnostics", True)) if isinstance(request.get("options"), Mapping) else True

    results: list[dict[str, Any]] = []
    for root, ref in zip(roots, refs):
        try:
            result = _evaluate_session(
                root,
                ref,
                effective,
                evaluation_id,
                include_diagnostics,
                activity_index_loader,
            )
        except LibraryApiError as exc:
            result = {
                "session_ref": ref,
                "status": "unavailable",
                "episode_count": 0,
                "matched_duration_s": 0.0,
                "matched_distance_m": None,
                "episodes": [],
                "criteria": [],
                "warnings": [{"code": exc.code, "message": exc.message, "details": exc.details}],
            }
        results.append(result)
        if sum(item["episode_count"] for item in results) > MAX_EPISODES:
            raise InvalidRequestError(
                f"Scenario evaluation exceeded the {MAX_EPISODES} Episode limit.",
                details={"maximum": MAX_EPISODES},
            )
    return _scenario_evaluation_response(
        effective=effective,
        digest=digest,
        input_artifacts=input_artifacts,
        evaluation_id=evaluation_id,
        results=results,
    )


def compose_scenario_evaluation(
    request: Mapping[str, Any],
    *,
    scenario: Mapping[str, Any],
    library_root: Callable[[str], Path],
    session_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compose a public evaluation response from independently cached sessions."""

    # Reuse the canonical key validation so composition observes the same request
    # limits and input-artifact identity as direct evaluation.
    scenario_evaluation_cache_key(request, scenario=scenario, library_root=library_root)
    sessions = request.get("sessions")
    assert isinstance(sessions, list)
    if len(session_results) != len(sessions):
        raise InvalidRequestError(
            "Scenario session result count does not match the requested scope.",
            details={"requested": len(sessions), "received": len(session_results)},
        )
    effective = normalize_scenario(scenario, scenario_id=_text_or_none(scenario.get("scenario_id")))
    digest = stable_cache_digest(effective)
    refs = [_session_ref(raw_ref) for raw_ref in sessions]
    input_artifacts = [
        artifact
        for ref in refs
        for artifact in _input_artifacts(library_root(ref["library_id"]), ref, effective)
    ]
    evaluation_id = (
        "scenario-eval-"
        f"{stable_cache_digest({'scenario': digest, 'sessions': refs, 'input_artifacts': input_artifacts})[:12]}"
    )
    results = [dict(result) for result in session_results]
    if sum(int(item.get("episode_count") or 0) for item in results) > MAX_EPISODES:
        raise InvalidRequestError(
            f"Scenario evaluation exceeded the {MAX_EPISODES} Episode limit.",
            details={"maximum": MAX_EPISODES},
        )
    return _scenario_evaluation_response(
        effective=effective,
        digest=digest,
        input_artifacts=input_artifacts,
        evaluation_id=evaluation_id,
        results=results,
    )


def _scenario_evaluation_response(
    *,
    effective: Mapping[str, Any],
    digest: str,
    input_artifacts: Sequence[Mapping[str, Any]],
    evaluation_id: str,
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    results = _episodes_for_evaluation(results, evaluation_id)
    evaluated = [item for item in results if item["status"] != "unavailable"]
    status = "succeeded" if len(evaluated) == len(results) and all(item["status"] == "succeeded" for item in results) else ("unavailable" if not evaluated else "partial")
    distance_values = [item["matched_distance_m"] for item in results]
    return {
        "schema": SCENARIO_EVALUATION_SCHEMA,
        "version": SCENARIO_EVALUATION_VERSION,
        "evaluation_id": evaluation_id,
        "status": status,
        "scenario": {
            "scenario_id": effective.get("scenario_id"),
            "revision": effective.get("revision"),
            "display_name": effective["display_name"],
        },
        "algorithm_version": SCENARIO_EVALUATION_ALGORITHM_VERSION,
        "sessions": results,
        "summary": {
            "requested_session_count": len(results),
            "evaluated_session_count": len(evaluated),
            "matched_session_count": sum(item["episode_count"] > 0 for item in results),
            "episode_count": sum(item["episode_count"] for item in results),
            "matched_duration_s": sum(float(item["matched_duration_s"]) for item in results),
            "matched_distance_m": sum(float(value) for value in distance_values if value is not None) if any(value is not None for value in distance_values) else None,
        },
        "provenance": {
            "scenario_definition_digest": f"sha256:{digest}",
            "input_artifacts": input_artifacts,
            "intervalisation": "conservative_sample_cells",
            "evaluated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "warnings": [],
    }


def _episodes_for_evaluation(
    results: Sequence[Mapping[str, Any]],
    evaluation_id: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for result in results:
        item = dict(result)
        ref = item.get("session_ref") if isinstance(item.get("session_ref"), Mapping) else {}
        session_key = str(
            ref.get("session_key")
            or make_session_key(str(ref.get("run_id") or ""), str(ref.get("session_id") or ""))
        )
        episodes: list[dict[str, Any]] = []
        for index, raw_episode in enumerate(item.get("episodes") or []):
            episode = dict(raw_episode)
            ordinal = int(episode.get("ordinal") or index + 1)
            episode["episode_id"] = (
                "episode-"
                f"{stable_cache_digest([evaluation_id, session_key, episode.get('start_time_s'), episode.get('end_time_s'), ordinal])[:12]}"
            )
            episodes.append(episode)
        item["episodes"] = episodes
        normalized.append(item)
    return normalized


def _evaluate_session(
    root: Path,
    ref: dict[str, str],
    scenario: Mapping[str, Any],
    evaluation_id: str,
    include_diagnostics: bool,
    activity_index_loader: Callable[[Path, Mapping[str, str]], Mapping[str, Any]] | None,
) -> dict[str, Any]:
    store = ArtifactStore(root)
    if not store.session_dir(ref["run_id"], ref["session_id"]).exists():
        raise InvalidRequestError("Scenario session was not found.", details=ref)
    diagnostics: list[dict[str, Any]] = []
    truth, known = _evaluate_node(store, ref, scenario["predicate"], diagnostics)
    activity = scenario["eligibility_policy"]["activity"]
    if activity == "require_active":
        activity_index = (
            activity_index_loader(root, ref)
            if activity_index_loader is not None
            else build_activity_index(root, ref)
        )
        active_truth, active_known, active_diag = activity_regions(activity_index)
        diagnostics.append(active_diag)
        truth, known = _and_states([(truth, known), (active_truth, active_known)])

    policy = scenario["episode_policy"]
    mapper = _distance_mapper(store, ref)
    truth = _bridge_known_false_gaps(
        truth,
        known,
        maximum_gap_s=policy.get("bridge_gap_s"),
        maximum_gap_m=policy.get("bridge_gap_m"),
        distance_mapper=mapper,
    )
    minimum_duration = float(policy.get("minimum_duration_s") or 0.0)
    truth = [interval for interval in truth if interval[1] - interval[0] >= minimum_duration]
    episodes: list[dict[str, Any]] = []
    minimum_distance = policy.get("minimum_distance_m")
    for start, end in truth:
        start_distance = mapper(start) if mapper else None
        end_distance = mapper(end) if mapper else None
        distance = (
            max(0.0, end_distance - start_distance)
            if start_distance is not None and end_distance is not None
            else None
        )
        if minimum_distance is not None and (distance is None or distance < float(minimum_distance)):
            continue
        ordinal = len(episodes) + 1
        episodes.append(
            {
                "episode_id": f"episode-{stable_cache_digest([evaluation_id, ref['session_key'], start, end, ordinal])[:12]}",
                "ordinal": ordinal,
                "start_time_s": start,
                "end_time_s": end,
                "duration_s": end - start,
                "start_distance_m": start_distance,
                "end_distance_m": end_distance,
                "distance_m": distance,
                "continuity": {"intervalisation": "conservative_sample_cells"},
            }
        )
    unavailable = [item for item in diagnostics if item["status"] == "unavailable"]
    status = "unavailable" if not known and unavailable else ("partial" if unavailable else "succeeded")
    distances = [item["distance_m"] for item in episodes]
    return {
        "session_ref": ref,
        "status": status,
        "episode_count": len(episodes),
        "matched_duration_s": sum(item["duration_s"] for item in episodes),
        "matched_distance_m": sum(value for value in distances if value is not None) if any(value is not None for value in distances) else None,
        "episodes": episodes,
        "criteria": diagnostics if include_diagnostics else [],
        "warnings": [],
    }


def _evaluate_node(
    store: ArtifactStore,
    ref: Mapping[str, str],
    node: Mapping[str, Any],
    diagnostics: list[dict[str, Any]],
) -> tuple[list[Interval], list[Interval]]:
    if node.get("op") in {"and", "or"}:
        states = [_evaluate_node(store, ref, child, diagnostics) for child in node["children"]]
        return _and_states(states) if node["op"] == "and" else _or_states(states)
    try:
        frame, metadata, coordinate_column, time_column, stream_kind = _load_series(store, ref, node["series"])
        spec = _resolve_signal_requests(
            [{key: node["series"][key]} for key in ("column", "selector") if key in node["series"]],
            meta=metadata,
            available_columns=list(frame.columns),
        )[0]
        values = frame[spec["column"]]
        times = pd.to_numeric(frame[time_column], errors="coerce").to_numpy(dtype=float)
        coords = pd.to_numeric(frame[coordinate_column], errors="coerce").to_numpy(dtype=float)
        known_mask, true_mask = _criterion_masks(values, times, coords, node)
        if stream_kind == "spatial_context":
            if "distance_support_fraction" in frame:
                known_mask &= pd.to_numeric(frame["distance_support_fraction"], errors="coerce").fillna(0).to_numpy() > 0
            if "active_mask_qc" in frame:
                known_mask &= pd.to_numeric(frame["active_mask_qc"], errors="coerce").fillna(0).to_numpy() > 0
            true_mask &= known_mask
        known = sample_cell_intervals(times, known_mask)
        truth = sample_cell_intervals(times, true_mask)
        info = spec.get("info") if isinstance(spec.get("info"), Mapping) else {}
        diagnostics.append(
            {
                "criterion_id": node["criterion_id"],
                "status": "succeeded",
                "resolved_series": {
                    "stream_name": node["series"]["stream_name"],
                    "column": spec["column"],
                    "unit": info.get("unit"),
                    "coordinate_column": coordinate_column,
                    "coordinate_unit": "m" if stream_kind == "spatial_context" else "s",
                },
                "true_duration_s": _duration(truth),
                "unknown_duration_s": None,
                "warnings": [],
            }
        )
        return truth, known
    except LibraryApiError as exc:
        diagnostics.append(
            {
                "criterion_id": node["criterion_id"],
                "status": "unavailable",
                "resolved_series": None,
                "true_duration_s": 0.0,
                "unknown_duration_s": None,
                "warnings": [{"code": exc.code, "message": exc.message}],
            }
        )
        return [], []


def _load_series(
    store: ArtifactStore, ref: Mapping[str, str], series: Mapping[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any], str, str, str]:
    run_id, session_id = ref["run_id"], ref["session_id"]
    stream_name = str(series["stream_name"])
    session_metadata = _read_json_object(store.path_session_meta(run_id, session_id))
    if stream_name == "primary":
        path = store.path_session_df(run_id, session_id)
        metadata = session_metadata
        kind = "primary"
    elif stream_name == "spatial_context":
        path = store.path_session_stream_df(run_id, session_id, stream_name)
        metadata = _read_json_object(store.path_session_stream_meta(run_id, session_id, stream_name))
        kind = "spatial_context"
    else:
        secondary = session_metadata.get("secondary_streams")
        registered = secondary.get(stream_name) if isinstance(secondary, Mapping) else None
        if not isinstance(registered, Mapping):
            raise InvalidRequestError(
                "Scenario source stream is not registered for this session.",
                details={"stream_name": stream_name},
            )
        path = store.path_session_stream_df(run_id, session_id, stream_name)
        disk_metadata = _read_json_object(store.path_session_stream_meta(run_id, session_id, stream_name))
        metadata = _merge_stream_metadata(registered, disk_metadata)
        kind = "time_series"
    if not path.exists():
        raise InvalidRequestError("Scenario source stream is unavailable.", details={"stream_name": stream_name})
    columns = _parquet_columns(path)
    specs = _resolve_signal_requests(
        [{key: series[key]} for key in ("column", "selector") if key in series],
        meta=metadata,
        available_columns=columns,
    )
    if kind == "spatial_context":
        coordinate = metadata.get("coordinate") if isinstance(metadata.get("coordinate"), Mapping) else {}
        mapping = metadata.get("time_mapping") if isinstance(metadata.get("time_mapping"), Mapping) else {}
        coordinate_column = str(coordinate.get("column") or "distance_m")
        time_column = str(mapping.get("column") or "representative_time_s")
    else:
        time_column, _ = _resolve_time_column(metadata, columns)
        coordinate_column = time_column
    read_columns = [specs[0]["column"], coordinate_column, time_column]
    if kind == "spatial_context":
        read_columns.extend(column for column in ("distance_support_fraction", "active_mask_qc") if column in columns)
    return pd.read_parquet(path, columns=list(dict.fromkeys(read_columns))), metadata, coordinate_column, time_column, kind


def _merge_stream_metadata(
    registered: Mapping[str, Any],
    materialized: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(registered)
    merged.update(materialized)
    registered_signals = registered.get("signals")
    materialized_signals = materialized.get("signals")
    if isinstance(registered_signals, Mapping) or isinstance(materialized_signals, Mapping):
        signals = dict(registered_signals) if isinstance(registered_signals, Mapping) else {}
        if isinstance(materialized_signals, Mapping):
            signals.update(materialized_signals)
        merged["signals"] = signals
    return merged


def _criterion_masks(
    values: pd.Series, times: np.ndarray, coordinates: np.ndarray, criterion: Mapping[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    op = criterion["op"]
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    if op in {"lt", "lte", "gt", "gte", "between", "outside"}:
        known = np.isfinite(times) & np.isfinite(coordinates) & np.isfinite(numeric)
        if op == "lt": true = numeric < float(criterion["value"])
        elif op == "lte": true = numeric <= float(criterion["value"])
        elif op == "gt": true = numeric > float(criterion["value"])
        elif op == "gte": true = numeric >= float(criterion["value"])
        else:
            bounds = criterion["range"]
            lower = numeric >= bounds["lower"] if bounds["include_lower"] else numeric > bounds["lower"]
            upper = numeric <= bounds["upper"] if bounds["include_upper"] else numeric < bounds["upper"]
            inside = lower & upper
            true = inside if op == "between" else ~inside
    else:
        known = np.isfinite(times) & np.isfinite(coordinates) & values.notna().to_numpy()
        if op == "present": true = known.copy()
        elif op == "eq": true = values.to_numpy() == criterion["value"]
        else: true = values.isin(criterion["value"]).to_numpy()
    return known, known & np.asarray(true, dtype=bool)


def _distance_mapper(store: ArtifactStore, ref: Mapping[str, str]) -> Callable[[float], float | None] | None:
    path = store.path_session_stream_df(ref["run_id"], ref["session_id"], "spatial_context")
    if not path.exists():
        return None
    try:
        available = _parquet_columns(path)
        read_columns = ["representative_time_s", "distance_m"]
        if "distance_support_fraction" in available:
            read_columns.append("distance_support_fraction")
        frame = pd.read_parquet(path, columns=read_columns)
    except Exception:
        return None
    times = pd.to_numeric(frame["representative_time_s"], errors="coerce").to_numpy(dtype=float)
    distances = pd.to_numeric(frame["distance_m"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(times) & np.isfinite(distances)
    if "distance_support_fraction" in frame:
        valid &= pd.to_numeric(frame["distance_support_fraction"], errors="coerce").fillna(0).to_numpy() > 0
    rows = np.flatnonzero(valid)
    if len(rows) < 2:
        return None
    valid_diffs = np.diff(times[rows])
    positive = valid_diffs[valid_diffs > 1e-9]
    nominal = float(np.median(positive)) if positive.size else 0.0
    split_at = np.flatnonzero((np.diff(rows) > 1) | (valid_diffs <= 0) | (valid_diffs > max(3.0 * nominal, nominal + 1e-6))) + 1
    segments = [segment for segment in np.split(rows, split_at) if len(segment) >= 2]
    if not segments:
        return None
    def map_time(value: float) -> float | None:
        for segment in segments:
            segment_times = times[segment]
            segment_distances = distances[segment]
            local_diffs = np.diff(segment_times)
            local_nominal = float(np.median(local_diffs[local_diffs > 0]))
            start_edge = max(0.0, float(segment_times[0]) - local_nominal / 2.0)
            end_edge = float(segment_times[-1]) + local_nominal / 2.0
            if start_edge <= value <= end_edge:
                if value < segment_times[0]:
                    slope = (segment_distances[1] - segment_distances[0]) / (segment_times[1] - segment_times[0])
                    return float(segment_distances[0] + slope * (value - segment_times[0]))
                if value > segment_times[-1]:
                    slope = (segment_distances[-1] - segment_distances[-2]) / (segment_times[-1] - segment_times[-2])
                    return float(segment_distances[-1] + slope * (value - segment_times[-1]))
                return float(np.interp(value, segment_times, segment_distances))
        return None
    return map_time


def _and_states(states: Sequence[tuple[list[Interval], list[Interval]]]) -> tuple[list[Interval], list[Interval]]:
    truth = states[0][0]
    for child_truth, _ in states[1:]: truth = _intersect(truth, child_truth)
    false: list[Interval] = []
    for child_truth, child_known in states: false = _union([*false, *_subtract(child_known, child_truth)])
    return truth, _union([*truth, *false])


def _or_states(states: Sequence[tuple[list[Interval], list[Interval]]]) -> tuple[list[Interval], list[Interval]]:
    truth = _union([interval for state, _ in states for interval in state])
    false = _subtract(states[0][1], states[0][0])
    for child_truth, child_known in states[1:]: false = _intersect(false, _subtract(child_known, child_truth))
    return truth, _union([*truth, *false])


def _bridge_known_false_gaps(
    truth: list[Interval],
    known: list[Interval],
    *,
    maximum_gap_s: float | None,
    maximum_gap_m: float | None,
    distance_mapper: Callable[[float], float | None] | None,
) -> list[Interval]:
    if len(truth) < 2 or (maximum_gap_s is None and maximum_gap_m is None):
        return truth
    result = [truth[0]]
    for current in truth[1:]:
        previous = result[-1]
        gap = (previous[1], current[0])
        time_ok = maximum_gap_s is None or gap[1] - gap[0] <= float(maximum_gap_s)
        if maximum_gap_m is None:
            distance_ok = True
        else:
            start_distance = distance_mapper(gap[0]) if distance_mapper else None
            end_distance = distance_mapper(gap[1]) if distance_mapper else None
            distance_ok = (
                start_distance is not None
                and end_distance is not None
                and abs(end_distance - start_distance) <= float(maximum_gap_m)
            )
        if time_ok and distance_ok and _covered(gap, known): result[-1] = (previous[0], current[1])
        else: result.append(current)
    return result


def _union(intervals: Sequence[Interval]) -> list[Interval]:
    ordered = sorted((float(a), float(b)) for a, b in intervals if b > a)
    out: list[Interval] = []
    for start, end in ordered:
        if out and start <= out[-1][1] + 1e-9: out[-1] = (out[-1][0], max(out[-1][1], end))
        else: out.append((start, end))
    return out


def _intersect(left: Sequence[Interval], right: Sequence[Interval]) -> list[Interval]:
    out: list[Interval] = []
    i = j = 0
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if end > start: out.append((start, end))
        if left[i][1] <= right[j][1]: i += 1
        else: j += 1
    return _union(out)


def _subtract(left: Sequence[Interval], right: Sequence[Interval]) -> list[Interval]:
    result: list[Interval] = []
    for start, end in left:
        pieces = [(start, end)]
        for cut_start, cut_end in right:
            next_pieces: list[Interval] = []
            for a, b in pieces:
                if cut_end <= a or cut_start >= b: next_pieces.append((a, b))
                else:
                    if cut_start > a: next_pieces.append((a, min(b, cut_start)))
                    if cut_end < b: next_pieces.append((max(a, cut_end), b))
            pieces = next_pieces
        result.extend(pieces)
    return _union(result)


def _covered(interval: Interval, coverage: Sequence[Interval]) -> bool:
    return any(start <= interval[0] + 1e-9 and end >= interval[1] - 1e-9 for start, end in coverage)


def _duration(intervals: Sequence[Interval]) -> float:
    return sum(end - start for start, end in intervals)


def _input_artifacts(
    root: Path,
    ref: Mapping[str, str],
    scenario: Mapping[str, Any],
) -> list[dict[str, Any]]:
    streams = {"primary"} if scenario["eligibility_policy"]["activity"] == "require_active" else set()
    stack = [scenario["predicate"]]
    while stack:
        node = stack.pop()
        if node.get("op") in {"and", "or"}:
            stack.extend(node["children"])
        else:
            streams.add(str(node["series"]["stream_name"]))

    store = ArtifactStore(root)
    paths: list[tuple[str, Path]] = []
    for stream in sorted(streams):
        if stream == "primary":
            paths.extend(
                [
                    ("primary.data", store.path_session_df(ref["run_id"], ref["session_id"])),
                    ("primary.metadata", store.path_session_meta(ref["run_id"], ref["session_id"])),
                ]
            )
        else:
            paths.extend(
                [
                    (
                        f"{stream}.data",
                        store.path_session_stream_df(ref["run_id"], ref["session_id"], stream),
                    ),
                    (
                        f"{stream}.metadata",
                        store.path_session_stream_meta(ref["run_id"], ref["session_id"], stream),
                    ),
                ]
            )
    out: list[dict[str, Any]] = []
    for role, path in paths:
        stat = path.stat() if path.exists() else None
        out.append(
            {
                "library_id": ref["library_id"],
                "session_key": ref["session_key"],
                "role": role,
                "path": str(path),
                "exists": stat is not None,
                "size_bytes": stat.st_size if stat is not None else None,
                "modified_ns": stat.st_mtime_ns if stat is not None else None,
            }
        )
    return out


def _session_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise InvalidRequestError("Each Scenario evaluation session must be an object.")
    library_id = _required_text(value.get("library_id"), "session.library_id")
    run_id = _required_text(value.get("run_id"), "session.run_id")
    session_id = _required_text(value.get("session_id"), "session.session_id")
    key = _text_or_none(value.get("session_key")) or make_session_key(run_id, session_id)
    if key != make_session_key(run_id, session_id):
        raise InvalidRequestError("session_key does not match run_id/session_id.")
    return {"library_id": library_id, "session_key": key, "session_ref_id": make_session_ref_id(library_id, key), "run_id": run_id, "session_id": session_id}


def _required_text(value: Any, field: str) -> str:
    result = _text_or_none(value)
    if result is None: raise InvalidRequestError(f"{field} is required.")
    return result


def _text_or_none(value: Any) -> str | None:
    if value is None: return None
    text = str(value).strip()
    return text or None
