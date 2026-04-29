from __future__ import annotations

from typing import Any, Mapping

import ipywidgets as W
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import clear_output, display

from bodaqs_analysis.sensor_aliases import canonical_end
from bodaqs_analysis.signal_selectors import selector_matches_signal
from bodaqs_analysis.widgets.contracts import SCHEMA_ID_COL, entity_snapshot_from_handle
from bodaqs_analysis.widgets.loaders import (
    load_all_events_for_entities,
    load_all_metrics_for_entities,
    make_session_loader,
)
from bodaqs_analysis.widgets.metric_scatter_widget import (
    build_metric_scatter_series,
    filter_metric_scatter_base_df,
    format_metric_scatter_line,
    plot_metric_scatter_series,
    prepare_metric_scatter_consumer_data,
)
from bodaqs_analysis.widgets.session_selector import attach_refresh


TileHandle = dict[str, Any]
DashboardHandle = dict[str, Any]


def _preferred_entity_label(
    snapshot: Any,
    entity: Any,
    store: Any,
    session_desc_cache: dict[str, str],
) -> str:
    entity_key = str(entity.entity_key)
    kind = str(getattr(entity, "kind", "") or "").strip().lower()

    if kind == "session":
        ref = snapshot.key_to_ref.get(entity_key)
        if ref is not None and len(ref) >= 2:
            run_id, session_id = str(ref[0]), str(ref[1])
            cache_key = f"{run_id}::{session_id}"
            if cache_key not in session_desc_cache:
                try:
                    manifest = store.read_json(store.path_session_manifest(run_id, session_id))
                except Exception:
                    manifest = {}
                session_desc_cache[cache_key] = str((manifest or {}).get("description") or "").strip()
            return session_desc_cache[cache_key] or session_id

    label = str(entity.label)
    if kind == "aggregation":
        prefix = "Aggregation | "
        if label.startswith(prefix):
            body = label[len(prefix):]
            if body.startswith("title="):
                body = body[len("title="):]
                return body.split(" | key=", 1)[0].strip() or entity_key
            if " (" in body:
                return body.rsplit(" (", 1)[0].strip() or entity_key
    return label


def _signal_ops(info: Mapping[str, Any]) -> list[str]:
    raw_ops = info.get("op_chain") or []
    if isinstance(raw_ops, (list, tuple)):
        return [str(x).strip().lower() for x in raw_ops if str(x).strip()]
    return [str(raw_ops).strip().lower()] if str(raw_ops).strip() else []


def _processing_role_score(info: Mapping[str, Any]) -> int:
    role = str(info.get("processing_role") or "").strip().lower()
    if role == "primary_analysis":
        return 2
    if role == "secondary_analysis":
        return 1
    return 0


def _signal_root_key(col: str) -> str:
    col_s = str(col).strip().lower()
    head = col_s.split("_op_", 1)[0]
    if " [" in head:
        head = head.split(" [", 1)[0]
    return head


def _signal_info_matches_end(info: Mapping[str, Any], col: str, end: str) -> bool:
    actual = canonical_end(info.get("end"))
    expected = canonical_end(end)
    return bool(actual and expected and actual == expected)


def _selector_with(selector: Mapping[str, Any] | None, **overrides: Any) -> dict[str, Any]:
    out = {str(k): v for k, v in dict(selector or {}).items() if v is not None and str(v).strip()}
    for key, value in overrides.items():
        if value is not None and str(value).strip():
            out[str(key)] = value
    return out


def _signal_matches_selector(info: Mapping[str, Any], col: str, selector: Mapping[str, Any]) -> bool:
    return selector_matches_signal(dict(info), selector)


def _norm_candidates_for_selector(
    signals: Mapping[str, Mapping[str, Any]],
    selector: Mapping[str, Any],
) -> list[str]:
    candidates: list[tuple[tuple[int, int, int, int], str]] = []
    norm_selector = _selector_with(selector, quantity="disp_norm", unit="1")

    for col, info in signals.items():
        if not isinstance(info, Mapping):
            continue
        if str(info.get("kind") or "").strip().lower() == "qc":
            continue

        ops = _signal_ops(info)
        if "norm" not in ops:
            continue

        col_s = str(col)
        if not _signal_matches_selector(info, col_s, norm_selector):
            continue

        quantity = str(info.get("quantity") or "").strip().lower()
        unit = str(info.get("unit") or "").strip().lower()
        score = (
            _processing_role_score(info),
            1 if quantity == "disp_norm" else 0,
            1 if unit == "1" else 0,
            1 if _signal_matches_selector(info, col_s, selector) else 0,
            1 if "zeroed" in ops else 0,
        )
        candidates.append((score, col_s))

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [col for _score, col in candidates]


def _mm_candidates_for_selector(
    signals: Mapping[str, Mapping[str, Any]],
    selector: Mapping[str, Any],
) -> list[str]:
    candidates: list[tuple[tuple[int, int, int, int, int, int], str]] = []
    mm_selector = _selector_with(selector, quantity="disp", unit="mm")

    for col, info in signals.items():
        if not isinstance(info, Mapping):
            continue
        if str(info.get("kind") or "").strip().lower() == "qc":
            continue

        col_s = str(col)
        if not _signal_matches_selector(info, col_s, mm_selector):
            continue

        quantity = str(info.get("quantity") or "").strip().lower()
        ops = _signal_ops(info)
        has_filtered_ops = any(op == "diff" or op.startswith("butterworth_") for op in ops)
        score = (
            _processing_role_score(info),
            1 if quantity == "disp" else 0,
            1 if _signal_matches_selector(info, col_s, selector) else 0,
            1 if not has_filtered_ops else 0,
            1 if ops == [] else 0,
            1 if "zeroed" in ops else 0,
            -len(ops),
        )
        candidates.append((score, col_s))

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [col for _score, col in candidates]


def _match_mm_for_norm(
    signals: Mapping[str, Mapping[str, Any]],
    *,
    norm_col: str,
    selector: Mapping[str, Any],
) -> str | None:
    norm_info = signals.get(norm_col)
    if not isinstance(norm_info, Mapping):
        return None

    mm_selector = _selector_with(selector, quantity="disp", unit="mm")
    norm_root = _signal_root_key(norm_col)
    norm_ops = _signal_ops(norm_info)
    target_ops = [op for op in norm_ops if op != "norm"]

    candidates: list[tuple[tuple[int, int, int, int, int, int, int], str]] = []
    for col, info in signals.items():
        if not isinstance(info, Mapping):
            continue
        if str(info.get("kind") or "").strip().lower() == "qc":
            continue

        col_s = str(col)
        if not _signal_matches_selector(info, col_s, mm_selector):
            continue

        ops = _signal_ops(info)
        has_filtered_ops = any(op == "diff" or op.startswith("butterworth_") for op in ops)
        score = (
            _processing_role_score(info),
            1 if ops == target_ops else 0,
            1 if _signal_root_key(col_s) == norm_root else 0,
            1 if not has_filtered_ops else 0,
            1 if ops == [] else 0,
            1 if target_ops and ops == [x for x in target_ops if x == "zeroed"] else 0,
            -abs(len(ops) - len(target_ops)),
        )
        candidates.append((score, col_s))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][1]


def _resolve_displacement_sources_by_session(
    *,
    session_loader: Any,
    session_keys: list[str],
    selector: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], list[str], list[str]]:
    norm_by_session: dict[str, str] = {}
    mm_by_session: dict[str, str] = {}
    missing_norm: list[str] = []
    missing_mm: list[str] = []

    for session_key in map(str, session_keys):
        sess = session_loader(session_key)
        meta = (sess or {}).get("meta") or {}
        signals = meta.get("signals") or {}
        if not isinstance(signals, Mapping):
            signals = {}

        norm_candidates = _norm_candidates_for_selector(signals, selector)
        norm_col = norm_candidates[0] if norm_candidates else None
        if norm_col:
            norm_by_session[session_key] = norm_col
        else:
            missing_norm.append(session_key)

        mm_col = _match_mm_for_norm(signals, norm_col=norm_col, selector=selector) if norm_col else None
        if mm_col is None:
            mm_candidates = _mm_candidates_for_selector(signals, selector)
            mm_col = mm_candidates[0] if mm_candidates else None
        if mm_col:
            mm_by_session[session_key] = mm_col
        else:
            missing_mm.append(session_key)

    return norm_by_session, mm_by_session, missing_norm, missing_mm


def _extract_series(df: pd.DataFrame, col: str, *, include_inactive: bool = False) -> np.ndarray:
    if col not in df.columns:
        return np.array([], dtype=float)
    s = pd.to_numeric(df[col], errors="coerce")
    if (not include_inactive) and ("active_mask_qc" in df.columns):
        s = s[df["active_mask_qc"].astype(bool)]
    vals = s.to_numpy(dtype=float, copy=False)
    vals = vals[np.isfinite(vals)]
    return vals


def _extract_paired_series(
    df: pd.DataFrame,
    *,
    norm_col: str,
    mm_col: str,
    include_inactive: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    if norm_col not in df.columns or mm_col not in df.columns:
        return np.array([], dtype=float), np.array([], dtype=float)

    s_norm = pd.to_numeric(df[norm_col], errors="coerce")
    s_mm = pd.to_numeric(df[mm_col], errors="coerce")
    if (not include_inactive) and ("active_mask_qc" in df.columns):
        mask_active = df["active_mask_qc"].astype(bool)
        s_norm = s_norm[mask_active]
        s_mm = s_mm[mask_active]

    a_norm = s_norm.to_numpy(dtype=float, copy=False)
    a_mm = s_mm.to_numpy(dtype=float, copy=False)
    mask = np.isfinite(a_norm) & np.isfinite(a_mm)
    return a_norm[mask], a_mm[mask]


def _paired_disp_metrics(norm_vals: np.ndarray, mm_vals: np.ndarray, trim_cutoff: float = 0.05) -> dict[str, float | bool]:
    n = np.asarray(norm_vals, dtype=float)
    m = np.asarray(mm_vals, dtype=float)
    paired_ok = np.isfinite(n) & np.isfinite(m)
    n = n[paired_ok]
    m = m[paired_ok]

    if n.size == 0:
        return {
            "insufficient": True,
            "q50_n": np.nan,
            "q95_n": np.nan,
            "q100_n": np.nan,
            "iqr_n": np.nan,
            "skew_n": np.nan,
            "q50_mm": np.nan,
            "q95_mm": np.nan,
            "q100_mm": np.nan,
            "iqr_mm": np.nan,
            "skew_mm": np.nan,
        }

    keep = n >= float(trim_cutoff)
    n = n[keep]
    m = m[keep]
    if n.size == 0:
        return {
            "insufficient": True,
            "q50_n": np.nan,
            "q95_n": np.nan,
            "q100_n": np.nan,
            "iqr_n": np.nan,
            "skew_n": np.nan,
            "q50_mm": np.nan,
            "q95_mm": np.nan,
            "q100_mm": np.nan,
            "iqr_mm": np.nan,
            "skew_mm": np.nan,
        }

    q25_n, q50_n, q75_n, q95_n, q100_n = np.quantile(n, [0.25, 0.5, 0.75, 0.95, 1.0])
    q25_mm, q50_mm, q75_mm, q95_mm, q100_mm = np.quantile(m, [0.25, 0.5, 0.75, 0.95, 1.0])
    iqr_n = float(q75_n - q25_n)
    iqr_mm = float(q75_mm - q25_mm)
    skew_n = np.nan if iqr_n <= 0 else float((q75_n + q25_n - (2.0 * q50_n)) / iqr_n)
    skew_mm = np.nan if iqr_mm <= 0 else float((q75_mm + q25_mm - (2.0 * q50_mm)) / iqr_mm)
    return {
        "insufficient": False,
        "q50_n": float(q50_n),
        "q95_n": float(q95_n),
        "q100_n": float(q100_n),
        "iqr_n": float(iqr_n),
        "skew_n": float(skew_n),
        "q50_mm": float(q50_mm),
        "q95_mm": float(q95_mm),
        "q100_mm": float(q100_mm),
        "iqr_mm": float(iqr_mm),
        "skew_mm": float(skew_mm),
    }


def _fmt_pct_mm(norm_v: float, mm_v: float) -> str:
    if np.isnan(norm_v) or np.isnan(mm_v):
        return "nan"
    return f"{(100.0 * float(norm_v)):.1f}% ({float(mm_v):.1f} mm)"

def _velocity_candidates_for_selector(
    signals: Mapping[str, Mapping[str, Any]],
    selector: Mapping[str, Any],
) -> list[str]:
    candidates: list[tuple[tuple[int, int, int, int], str]] = []
    vel_selector = _selector_with(selector, quantity="vel", unit="mm/s")

    for col, info in signals.items():
        if not isinstance(info, Mapping):
            continue
        if str(info.get("kind") or "").strip().lower() == "qc":
            continue

        col_s = str(col)
        col_l = col_s.lower()
        if not _signal_matches_selector(info, col_s, vel_selector):
            continue

        quantity = str(info.get("quantity") or "").strip().lower()
        unit = str(info.get("unit") or "").strip().lower()

        score = (
            _processing_role_score(info),
            1 if quantity == "vel" else 0,
            1 if unit == "mm/s" else 0,
            1 if _signal_matches_selector(info, col_s, selector) else 0,
            1 if "_vel_" in col_l or col_l.endswith("_vel") else 0,
        )
        candidates.append((score, col_s))

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [col for _score, col in candidates]


def _resolve_velocity_source_by_session(
    *,
    session_loader: Any,
    session_keys: list[str],
    selector: Mapping[str, Any],
) -> tuple[dict[str, str], list[str]]:
    source_by_session: dict[str, str] = {}
    missing: list[str] = []
    for session_key in map(str, session_keys):
        sess = session_loader(session_key)
        meta = (sess or {}).get("meta") or {}
        signals = meta.get("signals") or {}
        if not isinstance(signals, Mapping):
            signals = {}
        candidates = _velocity_candidates_for_selector(signals, selector)
        if not candidates:
            missing.append(session_key)
            continue
        source_by_session[session_key] = candidates[0]
    return source_by_session, missing


def _phase_stats(vals: np.ndarray) -> dict[str, float]:
    arr = np.asarray(vals, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"n": 0.0, "mean": np.nan, "max_abs": np.nan, "p95_abs": np.nan}
    abs_arr = np.abs(arr)
    return {
        "n": float(arr.size),
        "mean": float(np.mean(arr)),
        "max_abs": float(np.max(abs_arr)),
        "p95_abs": float(np.quantile(abs_arr, 0.95)),
    }


def _fmt_one(v: float) -> str:
    if np.isnan(v):
        return "nan"
    return f"{v:.1f}"


def _velocity_hist_proportions(vals: np.ndarray, *, bins: int, x_abs_limit: float) -> tuple[np.ndarray, np.ndarray]:
    clean = np.asarray(vals, dtype=float)
    clean = clean[np.isfinite(clean)]

    core_edges = np.linspace(-float(x_abs_limit), float(x_abs_limit), int(bins) + 1)
    core_width = float(core_edges[1] - core_edges[0]) if core_edges.size > 1 else max(1.0, float(x_abs_limit) / 25.0)
    overflow_width = max(core_width, float(x_abs_limit) * 0.10)
    right_edge = float(x_abs_limit) + overflow_width
    edges = np.concatenate((core_edges, [right_edge]))

    if clean.size == 0:
        return np.zeros(edges.size - 1, dtype=float), edges

    clipped = np.clip(clean, float(core_edges[0]) + 1e-9, right_edge - 1e-9)
    counts, _ = np.histogram(clipped, bins=edges)
    total = int(counts.sum())
    props = counts.astype(float) / float(total if total > 0 else 1)
    return props, edges


def _event_side_mask(events_df: pd.DataFrame, side: str) -> pd.Series:
    if events_df is None or events_df.empty:
        return pd.Series(dtype=bool)
    end_s = events_df["end"] if "end" in events_df.columns else pd.Series("", index=events_df.index, dtype="object")
    meta_s = events_df["meta"] if "meta" in events_df.columns else pd.Series({}, index=events_df.index, dtype="object")
    expected = canonical_end(side)

    def _meta_end(value: Any) -> str:
        if isinstance(value, Mapping):
            expansion = value.get("input_expansion")
            if isinstance(expansion, Mapping):
                return canonical_end(expansion.get("end"))
        return ""

    return end_s.map(lambda v: bool(canonical_end(v) and canonical_end(v) == expected)) | meta_s.map(
        lambda v: bool(_meta_end(v) and _meta_end(v) == expected)
    )


def _event_schema_id_series(events_df: pd.DataFrame) -> pd.Series:
    for col in ("schema_id", "event_type", "event_name", "event_id"):
        if col in events_df.columns:
            vals = events_df[col].astype(str).str.strip()
            if vals.str.len().gt(0).any():
                return vals
    return pd.Series(["(unknown event)"] * len(events_df), index=events_df.index, dtype="object")


def _build_event_entity_summaries(
    snapshot: Any,
    events_df: pd.DataFrame,
    side: str,
    store: Any,
    session_desc_cache: dict[str, str],
) -> list[dict[str, Any]]:
    selected_entities = list(snapshot.selected_entities)
    if events_df is None or events_df.empty:
        return [
            {
                "entity_key": str(entity.entity_key),
                "label": _preferred_entity_label(snapshot, entity, store, session_desc_cache),
                "total_count": 0,
                "counts_df": pd.DataFrame(columns=["Event", "Count"]),
            }
            for entity in selected_entities
        ]

    sub = events_df.loc[_event_side_mask(events_df, side)].copy()
    if sub.empty:
        return [
            {
                "entity_key": str(entity.entity_key),
                "label": _preferred_entity_label(snapshot, entity, store, session_desc_cache),
                "total_count": 0,
                "counts_df": pd.DataFrame(columns=["Event", "Count"]),
            }
            for entity in selected_entities
        ]

    entity_keys = sub["entity_key"].astype(str) if "entity_key" in sub.columns else pd.Series(["(selection)"] * len(sub), index=sub.index, dtype="object")
    sub["_entity_key"] = entity_keys
    sub["_event_label"] = _event_schema_id_series(sub)

    summaries: list[dict[str, Any]] = []
    for entity in selected_entities:
        entity_key = str(entity.entity_key)
        label = _preferred_entity_label(snapshot, entity, store, session_desc_cache)
        part = sub.loc[sub["_entity_key"] == entity_key].copy()
        if part.empty:
            counts_df = pd.DataFrame(columns=["Event", "Count"])
            total_count = 0
        else:
            counts_df = (
                part.groupby("_event_label", dropna=False)
                .size()
                .reset_index(name="Count")
                .rename(columns={"_event_label": "Event"})
                .sort_values(["Count", "Event"], ascending=[False, True])
                .reset_index(drop=True)
            )
            counts_df["Count"] = counts_df["Count"].astype(int)
            total_count = int(len(part))
        summaries.append(
            {
                "entity_key": entity_key,
                "label": label,
                "total_count": total_count,
                "counts_df": counts_df,
            }
        )
    return summaries


def _events_summary_html(summaries: list[dict[str, Any]]) -> str:
    if not summaries:
        return "<div>No entities selected.</div>"

    parts: list[str] = []
    show_entity_labels = len(summaries) > 1
    for summary in summaries:
        label = str(summary["label"])
        total_count = int(summary["total_count"])
        counts_df = summary["counts_df"] if isinstance(summary["counts_df"], pd.DataFrame) else pd.DataFrame(columns=["Event", "Count"])
        if show_entity_labels:
            parts.append(
                "<div style='margin-top:8px'>"
                f"<b>{label}</b><br>"
                f"Events detected: {total_count}"
                "</div>"
            )
        else:
            parts.append(f"<div style='margin-top:8px'>Events detected: {total_count}</div>")
        if counts_df.empty:
            parts.append("<div style='margin-left:12px'>No events detected.</div>")
            continue
        for _, row in counts_df.iterrows():
            parts.append(f"<div style='margin-left:12px'>{str(row['Event'])}: {int(row['Count'])}</div>")
    return "".join(parts)


def _make_metric_scatter_tile(
    *,
    sel: Mapping[str, Any],
    title: str,
    event_type: str,
    x_metric: str,
    y_metric: str,
    session_desc_cache: dict[str, str],
    signal_selector: Mapping[str, Any] | None = None,
    sensor: str | None = None,
    overlay_fit_cache: dict[str, list[dict[str, Any]]] | None = None,
    overlay_self_key: str | None = None,
    overlay_other_key: str | None = None,
) -> TileHandle:
    out = W.Output(layout=W.Layout(border="1px solid #d9d9d9", padding="8px", width="100%"))
    state: dict[str, Any] = {}

    def rebuild() -> None:
        snapshot = entity_snapshot_from_handle(sel)
        selected_entities = list(snapshot.selected_entities)
        with out:
            clear_output(wait=True)
            display(W.HTML(f"<h3 style='margin:0 0 8px 0;'>{title}</h3>"))
            if not selected_entities:
                print("No entities selected.")
                return

            key_to_ref = dict(snapshot.key_to_ref)
            session_loader = make_session_loader(store=sel["store"], key_to_ref=key_to_ref)
            events_df = load_all_events_for_entities(sel["store"], snapshot=snapshot)
            metrics_df = load_all_metrics_for_entities(sel["store"], snapshot=snapshot)
            try:
                scatter_data = prepare_metric_scatter_consumer_data(
                    events_df=events_df,
                    metrics_df=metrics_df,
                    session_keys=list(map(str, snapshot.expanded_session_keys)),
                    session_loader=session_loader,
                    schema=None,
                    event_type_col=SCHEMA_ID_COL,
                    registry_policy="union",
                    require_schema=False,
                )
            except Exception as exc:
                print(str(exc))
                return

            if str(event_type) not in set(map(str, scatter_data["event_types"])):
                print(f"No events found for {event_type!r} in the current selection.")
                return
            if str(x_metric) not in set(map(str, scatter_data["metrics"])):
                print(f"Metric {x_metric!r} is not available in the current selection.")
                return
            if str(y_metric) not in set(map(str, scatter_data["metrics"])):
                print(f"Metric {y_metric!r} is not available in the current selection.")
                return
            if signal_selector is None:
                if not sensor or str(sensor) not in set(map(str, scatter_data["sensors"])):
                    print(f"No end/context resolved as {sensor!r} in the current selection.")
                    return

            entity_keys = [str(entity.entity_key) for entity in selected_entities]
            entity_labels = {
                str(entity.entity_key): _preferred_entity_label(snapshot, entity, sel["store"], session_desc_cache)
                for entity in selected_entities
            }
            selectors = [signal_selector] if isinstance(signal_selector, Mapping) and signal_selector else None
            sensors = [sensor] if sensor else []
            base = filter_metric_scatter_base_df(
                viz_df=scatter_data["viz_df"],
                event_type_col=SCHEMA_ID_COL,
                scope_entity_col=str(scatter_data["scope_entity_col"]),
                event_value=event_type,
                entity_values=entity_keys,
                sensor_values=sensors,
                signal_selectors=selectors,
            )
            if len(base) == 0:
                target = dict(signal_selector) if isinstance(signal_selector, Mapping) else sensor
                print(f"No rows after filtering for event={event_type!r} and signal={target!r}.")
                return

            series = build_metric_scatter_series(
                viz_df=scatter_data["viz_df"],
                event_type_col=SCHEMA_ID_COL,
                scope_entity_col=str(scatter_data["scope_entity_col"]),
                event_value=event_type,
                entity_values=entity_keys,
                sensor_values=sensors,
                signal_selectors=selectors,
                x_metric=x_metric,
                y_metric=y_metric,
                series_labeler=lambda entity_key, _sensor: entity_labels.get(entity_key, entity_key),
            )

            fig, ax = plt.subplots(figsize=(4.8, 2.52))
            results = plot_metric_scatter_series(
                ax,
                series,
                alpha=0.6,
                size=18,
                grid=True,
                equal_axes=False,
                diag_line=False,
                regression=True,
            )
            ax.set_title("")
            ax.set_xlabel(x_metric)
            ax.set_ylabel(y_metric)

            if overlay_fit_cache is not None and overlay_self_key:
                overlay_fit_cache[str(overlay_self_key)] = [
                    {"label": result.label, "fit": result.fit}
                    for result in results
                    if result.fit is not None
                ]

            overlay_palette = ["#d95f02", "#1b9e77", "#7570b3", "#e7298a"]
            overlay_results = []
            if overlay_fit_cache is not None and overlay_other_key:
                overlay_results = list(overlay_fit_cache.get(str(overlay_other_key), []))
            if overlay_results:
                xlo, xhi = ax.get_xlim()
                for idx, overlay in enumerate(overlay_results):
                    fit = overlay.get("fit")
                    if fit is None:
                        continue
                    xs = np.array([xlo, xhi], dtype=float)
                    ys = float(fit.slope) * xs + float(fit.intercept)
                    ax.plot(
                        xs,
                        ys,
                        linestyle="--",
                        linewidth=1.8,
                        alpha=0.95,
                        color=overlay_palette[idx % len(overlay_palette)],
                    )

            chart_out = W.Output(layout=W.Layout(width="60%"))
            with chart_out:
                plt.show()

            metric_lines = [
                (
                    "<div style='font-size:1.1em;font-weight:600;'>"
                    f"{event_type} | {dict(signal_selector) if isinstance(signal_selector, Mapping) else sensor}"
                    "</div>"
                )
            ]
            show_entity_labels = len(selected_entities) > 1
            stats_by_label: dict[str, dict[str, Any]] = {}
            for result in results:
                fit = result.fit
                stats_by_label[result.label] = {
                    "n": int(result.n),
                    "equation": (format_metric_scatter_line(fit) if fit is not None else None),
                    "r_squared": (float(fit.r_squared) if fit is not None else np.nan),
                }
                label_prefix = f"<b>{result.label}</b><br>" if show_entity_labels else ""
                if result.n <= 0:
                    metric_lines.append(
                        "<div style='margin-top:8px'>"
                        f"{label_prefix}"
                        "n: 0<br>"
                        "Regression: n/a<br>"
                        "R^2: n/a"
                        "</div>"
                    )
                    continue
                if fit is None:
                    metric_lines.append(
                        "<div style='margin-top:8px'>"
                        f"{label_prefix}"
                        f"n: {result.n}<br>"
                        "Regression: n/a (need >=2 points)<br>"
                        "R^2: n/a"
                        "</div>"
                    )
                    continue
                metric_lines.append(
                    "<div style='margin-top:8px'>"
                    f"{label_prefix}"
                    f"n: {result.n}<br>"
                    f"Regression: {format_metric_scatter_line(fit)}<br>"
                    f"R^2: {fit.r_squared:.6g}"
                    "</div>"
                )

            metrics_html = W.HTML("".join(metric_lines), layout=W.Layout(width="40%"))
            display(
                W.HBox(
                    [chart_out, metrics_html],
                    layout=W.Layout(
                        width="100%",
                        align_items="flex-start",
                        justify_content="space-between",
                    ),
                )
            )
            state["scatter_data"] = scatter_data
            state["stats"] = stats_by_label

    return {"out": out, "rebuild": rebuild, "state": state}

def _make_displacement_tile(
    *,
    sel: Mapping[str, Any],
    title: str,
    signal_selector: Mapping[str, Any],
    bins: int,
    trim_cutoff: float,
    y_shared: dict[str, float],
    y_key: str,
    session_desc_cache: dict[str, str],
    show_engineering_getter: Any,
) -> TileHandle:
    out = W.Output(layout=W.Layout(border="1px solid #d9d9d9", padding="8px", width="100%"))
    state: dict[str, Any] = {}
    selector = dict(signal_selector)

    def rebuild() -> None:
        snapshot = entity_snapshot_from_handle(sel)
        selected_entities = list(snapshot.selected_entities)
        show_engineering = bool(show_engineering_getter()) if callable(show_engineering_getter) else False

        with out:
            clear_output(wait=True)
            display(W.HTML(f"<h3 style='margin:0 0 8px 0;'>{title}</h3>"))
            if not selected_entities:
                print("No entities selected.")
                return

            key_to_ref = dict(snapshot.key_to_ref)
            base_loader = make_session_loader(store=sel["store"], key_to_ref=key_to_ref)
            session_keys = list(map(str, snapshot.expanded_session_keys))
            norm_by_session, mm_by_session, missing_norm, missing_mm = _resolve_displacement_sources_by_session(
                session_loader=base_loader,
                session_keys=session_keys,
                selector=selector,
            )

            if show_engineering and (not mm_by_session):
                print(f"No matching engineering-unit displacement signal found for selector={selector!r} in the current selection.")
                return
            if (not show_engineering) and (not norm_by_session):
                print(f"No matching normalized displacement signal found for selector={selector!r} in the current selection.")
                return

            notes: list[str] = []
            if missing_norm:
                notes.append(f"norm missing in {len(missing_norm)} session(s)")
            if missing_mm:
                notes.append(f"mm missing in {len(missing_mm)} session(s)")
            if notes:
                display(W.HTML(f"<small><b>Note:</b> {'; '.join(notes)}.</small>"))

            hist_values_by_entity: dict[str, np.ndarray] = {}
            paired_norm_by_entity: dict[str, np.ndarray] = {}
            paired_mm_by_entity: dict[str, np.ndarray] = {}

            for entity in selected_entities:
                entity_key = str(entity.entity_key)
                label = _preferred_entity_label(snapshot, entity, sel["store"], session_desc_cache)
                members = snapshot.entity_to_effective_members.get(entity_key, [entity_key])
                hist_chunks: list[np.ndarray] = []
                norm_chunks: list[np.ndarray] = []
                mm_chunks: list[np.ndarray] = []

                for session_key in map(str, members):
                    sess = base_loader(session_key)
                    df = (sess or {}).get("df")
                    if not isinstance(df, pd.DataFrame):
                        continue
                    norm_col = norm_by_session.get(session_key)
                    mm_col = mm_by_session.get(session_key)
                    if show_engineering:
                        if mm_col:
                            vals = _extract_series(df, mm_col, include_inactive=False)
                            if vals.size:
                                hist_chunks.append(vals)
                    else:
                        if norm_col:
                            vals = _extract_series(df, norm_col, include_inactive=False)
                            if vals.size:
                                hist_chunks.append(vals)
                    if norm_col and mm_col:
                        n_vals, m_vals = _extract_paired_series(df, norm_col=norm_col, mm_col=mm_col, include_inactive=False)
                        if n_vals.size:
                            norm_chunks.append(n_vals)
                            mm_chunks.append(m_vals)

                hist_values_by_entity[label] = np.concatenate(hist_chunks) if hist_chunks else np.array([], dtype=float)
                paired_norm_by_entity[label] = np.concatenate(norm_chunks) if norm_chunks else np.array([], dtype=float)
                paired_mm_by_entity[label] = np.concatenate(mm_chunks) if mm_chunks else np.array([], dtype=float)

            fig, ax = plt.subplots(figsize=(4.8, 2.52))
            plotted = 0
            local_y_max = 0.0
            if show_engineering:
                all_vals = [v for v in hist_values_by_entity.values() if v.size]
                if all_vals:
                    merged = np.concatenate(all_vals)
                    merged = merged[np.isfinite(merged)]
                    lo = float(np.min(merged)) if merged.size else 0.0
                    hi = float(np.max(merged)) if merged.size else 1.0
                    lo = min(0.0, lo)
                    if hi <= lo:
                        hi = lo + 1.0
                    hist_range = (lo, hi)
                else:
                    hist_range = (0.0, 1.0)
            else:
                hist_range = (0.0, 1.0)

            for label, vals in hist_values_by_entity.items():
                clean = np.asarray(vals, dtype=float)
                clean = clean[np.isfinite(clean)]
                if clean.size == 0:
                    continue
                hist, edges = np.histogram(clean, bins=int(bins), range=hist_range)
                props = hist.astype(float) / float(max(clean.size, 1))
                ax.stairs(props, edges, label=label, linewidth=1.4)
                if props.size:
                    local_y_max = max(local_y_max, float(np.max(props)))
                plotted += 1

            y_shared[str(y_key)] = max(local_y_max, 0.0)
            target_y = max([local_y_max] + [float(v) for v in y_shared.values()]) if y_shared else local_y_max
            if show_engineering:
                ax.set_title("")
                ax.set_xlabel("Displacement (mm)")
            else:
                ax.set_title("")
                ax.set_xlabel("Normalized displacement")
                ax.set_xlim(0.0, 1.0)
            ax.set_ylabel("Proportion")
            if target_y > 0:
                ax.set_ylim(0.0, target_y * 1.05)
            ax.grid(True, alpha=0.3)
            if plotted > 1:
                ax.legend(fontsize=9)
            if plotted == 0:
                ax.text(0.5, 0.5, "No numeric values after filtering", ha="center", va="center", transform=ax.transAxes)
                ax.set_axis_off()
            chart_out = W.Output(layout=W.Layout(width="60%"))
            with chart_out:
                plt.show()

            metric_lines = [
                (
                    f"<div style='font-size:1.1em;font-weight:600;'>"
                    f"Metrics (trim cutoff = {trim_cutoff:.2f})"
                    f"</div>"
                )
            ]
            stats_by_label: dict[str, dict[str, float | bool]] = {}
            show_entity_labels = len(selected_entities) > 1
            for label in sorted(set(paired_norm_by_entity.keys()) | set(paired_mm_by_entity.keys())):
                n_vals = paired_norm_by_entity.get(label, np.array([], dtype=float))
                m_vals = paired_mm_by_entity.get(label, np.array([], dtype=float))
                metrics = _paired_disp_metrics(n_vals, m_vals, trim_cutoff=float(trim_cutoff))
                stats_by_label[label] = metrics
                if bool(metrics["insufficient"]):
                    prefix = f"<b>{label}</b><br>" if show_entity_labels else ""
                    metric_lines.append(f"<div style='margin-top:8px'>{prefix}insufficient paired norm/mm data</div>")
                    continue
                label_prefix = f"<b>{label}</b><br>" if show_entity_labels else ""
                metric_lines.append(
                    "<div style='margin-top:8px'>"
                    f"{label_prefix}"
                    f"Dynamic sag: {_fmt_pct_mm(float(metrics['q50_n']), float(metrics['q50_mm']))}<br>"
                    f"95th percentile: {_fmt_pct_mm(float(metrics['q95_n']), float(metrics['q95_mm']))}<br>"
                    f"Maximum travel: {_fmt_pct_mm(float(metrics['q100_n']), float(metrics['q100_mm']))}<br>"
                    f"Interquartile range: {_fmt_pct_mm(float(metrics['iqr_n']), float(metrics['iqr_mm']))}<br>"
                    f"Skew: {_fmt_pct_mm(float(metrics['skew_n']), float(metrics['skew_mm']))}"
                    "</div>"
                )
            metrics_html = W.HTML(
                "".join(metric_lines),
                layout=W.Layout(width="40%"),
            )
            display(
                W.HBox(
                    [chart_out, metrics_html],
                    layout=W.Layout(
                        width="100%",
                        align_items="flex-start",
                        justify_content="space-between",
                    ),
                )
            )
            state["stats"] = stats_by_label
            state["norm_by_session"] = dict(norm_by_session)
            state["mm_by_session"] = dict(mm_by_session)
            state["signal_selector"] = dict(selector)

    return {"out": out, "rebuild": rebuild, "state": state}

def _make_velocity_tile(
    *,
    sel: Mapping[str, Any],
    title: str,
    signal_selector: Mapping[str, Any],
    bins: int,
    x_abs_limit: float,
    y_shared: dict[str, float],
    y_key: str,
    session_desc_cache: dict[str, str],
) -> TileHandle:
    out = W.Output(layout=W.Layout(border="1px solid #d9d9d9", padding="8px", width="100%"))
    state: dict[str, Any] = {}
    selector = dict(signal_selector)

    def rebuild() -> None:
        snapshot = entity_snapshot_from_handle(sel)
        selected_entities = list(snapshot.selected_entities)
        with out:
            clear_output(wait=True)
            display(W.HTML(f"<h3 style='margin:0 0 8px 0;'>{title}</h3>"))
            if not selected_entities:
                print("No entities selected.")
                return

            key_to_ref = dict(snapshot.key_to_ref)
            base_loader = make_session_loader(store=sel["store"], key_to_ref=key_to_ref)
            session_keys = list(map(str, snapshot.expanded_session_keys))
            source_by_session, missing = _resolve_velocity_source_by_session(
                session_loader=base_loader,
                session_keys=session_keys,
                selector=selector,
            )
            if not source_by_session:
                print(f"No matching velocity signal found for selector={selector!r} in the current selection.")
                return
            if missing:
                sample = ", ".join(missing[:3])
                display(W.HTML(f"<small><b>Note:</b> {len(missing)} session(s) had no selector={selector!r} velocity signal (examples: {sample}).</small>"))

            entity_values: dict[str, np.ndarray] = {}
            for entity in selected_entities:
                entity_key = str(entity.entity_key)
                label = _preferred_entity_label(snapshot, entity, sel["store"], session_desc_cache)
                members = snapshot.entity_to_effective_members.get(entity_key, [entity_key])
                chunks: list[np.ndarray] = []
                for session_key in map(str, members):
                    source = source_by_session.get(session_key)
                    if not source:
                        continue
                    sess = base_loader(session_key)
                    df = (sess or {}).get("df")
                    if not isinstance(df, pd.DataFrame) or source not in df.columns:
                        continue
                    s = pd.to_numeric(df[source], errors="coerce")
                    if "active_mask_qc" in df.columns:
                        s = s[df["active_mask_qc"].astype(bool)]
                    vals = s.to_numpy(dtype=float, copy=False)
                    vals = vals[np.isfinite(vals)]
                    if vals.size:
                        chunks.append(vals)
                entity_values[label] = np.concatenate(chunks) if chunks else np.array([], dtype=float)

            fig, ax = plt.subplots(figsize=(4.8, 2.52))
            plotted = 0
            stats_by_label: dict[str, dict[str, dict[str, float]]] = {}
            last_edges: np.ndarray | None = None
            local_y_max = 0.0

            for label, vals in entity_values.items():
                clean = np.asarray(vals, dtype=float)
                clean = clean[np.isfinite(clean)]
                if clean.size == 0:
                    stats_by_label[label] = {
                        "rebound": _phase_stats(np.array([], dtype=float)),
                        "compression": _phase_stats(np.array([], dtype=float)),
                    }
                    continue
                props, edges = _velocity_hist_proportions(clean, bins=int(bins), x_abs_limit=float(x_abs_limit))
                ax.stairs(props, edges, label=label, linewidth=1.4)
                if props.size:
                    local_y_max = max(local_y_max, float(np.max(props)))
                last_edges = edges
                plotted += 1
                stats_by_label[label] = {
                    "rebound": _phase_stats(clean[clean < 0]),
                    "compression": _phase_stats(clean[clean > 0]),
                }

            y_shared[str(y_key)] = max(local_y_max, 0.0)
            target_y = max([local_y_max] + [float(v) for v in y_shared.values()]) if y_shared else local_y_max
            ax.set_title("")
            ax.set_xlabel("Velocity (mm/s)")
            ax.set_ylabel("Proportion")
            if target_y > 0:
                ax.set_ylim(0.0, target_y * 1.05)
            ax.grid(True, alpha=0.3)
            if last_edges is not None:
                ax.set_xlim(float(last_edges[0]), float(last_edges[-1]))
                ax.set_xticks([-float(x_abs_limit), 0.0, float(x_abs_limit), float(last_edges[-1])])
                ax.set_xticklabels([f"{-int(x_abs_limit)}", "0", f"{int(x_abs_limit)}", ""])
                ax.axvline(-float(x_abs_limit), color="#999999", linestyle=":", linewidth=1.0, alpha=0.9)
                ax.axvline(0.0, color="#777777", linestyle="--", linewidth=1.0, alpha=0.9)
                ax.axvline(float(x_abs_limit), color="#999999", linestyle=":", linewidth=1.0, alpha=0.9)
            if plotted > 1:
                ax.legend(fontsize=9)
            if plotted == 0:
                ax.text(0.5, 0.5, "No numeric values after filtering", ha="center", va="center", transform=ax.transAxes)
                ax.set_axis_off()
            chart_out = W.Output(layout=W.Layout(width="60%"))
            with chart_out:
                plt.show()

            rebound_lines = [
                (
                    '<div style="font-size:1.1em;font-weight:600;">'
                    'Rebound (v &lt; 0)'
                    '</div>'
                )
            ]
            compression_lines = [
                (
                    '<div style="font-size:1.1em;font-weight:600;">'
                    'Compression (v &gt; 0)'
                    '</div>'
                )
            ]
            show_entity_labels = len(selected_entities) > 1
            for label, phases in stats_by_label.items():
                rebound = phases["rebound"]
                compression = phases["compression"]
                if rebound["n"] <= 0:
                    prefix = f"<b>{label}</b><br>" if show_entity_labels else ""
                    rebound_lines.append(f"<div style='margin-top:8px'>{prefix}no rebound samples</div>")
                else:
                    label_prefix = f"<b>{label}</b><br>" if show_entity_labels else ""
                    rebound_lines.append(
                        "<div style='margin-top:8px'>"
                        f"{label_prefix}"
                        f"mean: {_fmt_one(rebound['mean'])} mm/s<br>"
                        f"max |v|: {_fmt_one(rebound['max_abs'])} mm/s<br>"
                        f"p95 |v|: {_fmt_one(rebound['p95_abs'])} mm/s"
                        "</div>"
                    )
                if compression["n"] <= 0:
                    prefix = f"<b>{label}</b><br>" if show_entity_labels else ""
                    compression_lines.append(f"<div style='margin-top:8px'>{prefix}no compression samples</div>")
                else:
                    label_prefix = f"<b>{label}</b><br>" if show_entity_labels else ""
                    compression_lines.append(
                        "<div style='margin-top:8px'>"
                        f"{label_prefix}"
                        f"mean: {_fmt_one(compression['mean'])} mm/s<br>"
                        f"max |v|: {_fmt_one(compression['max_abs'])} mm/s<br>"
                        f"p95 |v|: {_fmt_one(compression['p95_abs'])} mm/s"
                        "</div>"
                    )
            metrics_column = W.VBox(
                [
                    W.HTML("".join(rebound_lines)),
                    W.HTML("".join(compression_lines)),
                ],
                layout=W.Layout(width="40%", gap="10px"),
            )
            metrics_row = W.HBox(
                [chart_out, metrics_column],
                layout=W.Layout(width="100%", align_items="flex-start", justify_content="space-between"),
            )
            display(metrics_row)
            state["stats"] = stats_by_label
            state["source_by_session"] = dict(source_by_session)
            state["signal_selector"] = dict(selector)

    return {"out": out, "rebuild": rebuild, "state": state}


def _make_event_tile(
    *,
    sel: Mapping[str, Any],
    side: str,
    title: str,
    session_desc_cache: dict[str, str],
) -> TileHandle:
    out = W.Output(layout=W.Layout(border="1px solid #d9d9d9", padding="8px", width="100%"))
    state: dict[str, Any] = {}
    side_l = str(side).strip().lower()

    def rebuild() -> None:
        snapshot = entity_snapshot_from_handle(sel)
        selected_entities = list(snapshot.selected_entities)
        with out:
            clear_output(wait=True)
            display(W.HTML(f"<h3 style='margin:0 0 8px 0;'>{title}</h3>"))
            if not selected_entities:
                print("No entities selected.")
                return
            events_df = load_all_events_for_entities(sel["store"], snapshot=snapshot)
            summaries = _build_event_entity_summaries(snapshot, events_df, side_l, sel["store"], session_desc_cache)
            display(W.HTML(_events_summary_html(summaries)))
            state["events_df"] = events_df.copy() if isinstance(events_df, pd.DataFrame) else pd.DataFrame()
            state["summaries"] = summaries

    return {"out": out, "rebuild": rebuild, "state": state}


def _make_two_column_row(left: W.Widget, right: W.Widget) -> W.HBox:
    left.layout = W.Layout(width="49%")
    right.layout = W.Layout(width="49%")
    return W.HBox(
        [left, right],
        layout=W.Layout(width="100%", align_items="flex-start", justify_content="space-between"),
    )

def make_simple_suspension_metrics_dashboard(
    sel: Mapping[str, Any],
    *,
    compression_event_type: str = "compressions_all>25",
    rebound_event_type: str = "rebounds_all>25",
    scatter_x_metric: str = "m_peak_disp_max",
    compression_y_metric: str = "m_interval_vel_max",
    rebound_y_metric: str = "m_interval_vel_min",
    front_signal_selector: Mapping[str, Any] | None = None,
    rear_signal_selector: Mapping[str, Any] | None = None,
    front_displacement_selector: Mapping[str, Any] | None = None,
    rear_displacement_selector: Mapping[str, Any] | None = None,
    front_velocity_selector: Mapping[str, Any] | None = None,
    rear_velocity_selector: Mapping[str, Any] | None = None,
    front_event_signal_selector: Mapping[str, Any] | None = None,
    rear_event_signal_selector: Mapping[str, Any] | None = None,
    auto_display: bool = False,
) -> DashboardHandle:
    session_desc_cache: dict[str, str] = {}
    row1_shared_y: dict[str, float] = {}
    row2_shared_y: dict[str, float] = {}
    compression_overlay_fits: dict[str, list[dict[str, Any]]] = {}
    rebound_overlay_fits: dict[str, list[dict[str, Any]]] = {}

    w_show_engineering = W.Checkbox(
        value=False,
        description="Show engineering units (mm)",
        indent=False,
    )

    def _show_engineering() -> bool:
        return bool(w_show_engineering.value)

    front_base_selector = dict(front_signal_selector or {"end": "front", "domain": "suspension"})
    rear_base_selector = dict(rear_signal_selector or {"end": "rear", "domain": "wheel"})
    front_disp_selector = dict(front_displacement_selector or front_base_selector)
    rear_disp_selector = dict(rear_displacement_selector or rear_base_selector)
    front_vel_selector = dict(front_velocity_selector or front_disp_selector)
    rear_vel_selector = dict(rear_velocity_selector or rear_disp_selector)
    front_event_selector = dict(front_event_signal_selector or {"end": "front", "domain": "suspension"})
    rear_event_selector = dict(rear_event_signal_selector or {"end": "rear", "domain": "suspension"})

    front_disp = _make_displacement_tile(
        sel=sel,
        title="Front Suspension: Displacement",
        signal_selector=front_disp_selector,
        bins=50,
        trim_cutoff=0.05,
        y_shared=row1_shared_y,
        y_key="front",
        session_desc_cache=session_desc_cache,
        show_engineering_getter=_show_engineering,
    )
    rear_disp = _make_displacement_tile(
        sel=sel,
        title="Rear Suspension: Displacement",
        signal_selector=rear_disp_selector,
        bins=50,
        trim_cutoff=0.05,
        y_shared=row1_shared_y,
        y_key="rear",
        session_desc_cache=session_desc_cache,
        show_engineering_getter=_show_engineering,
    )
    front_vel = _make_velocity_tile(
        sel=sel,
        title="Front Suspension: Velocity",
        signal_selector=front_vel_selector,
        bins=100,
        x_abs_limit=2000.0,
        y_shared=row2_shared_y,
        y_key="front",
        session_desc_cache=session_desc_cache,
    )
    rear_vel = _make_velocity_tile(
        sel=sel,
        title="Rear Suspension: Velocity",
        signal_selector=rear_vel_selector,
        bins=100,
        x_abs_limit=2000.0,
        y_shared=row2_shared_y,
        y_key="rear",
        session_desc_cache=session_desc_cache,
    )
    front_evt = _make_event_tile(
        sel=sel,
        side="front",
        title="Front Suspension: Events",
        session_desc_cache=session_desc_cache,
    )
    rear_evt = _make_event_tile(
        sel=sel,
        side="rear",
        title="Rear Suspension: Events",
        session_desc_cache=session_desc_cache,
    )
    front_comp_scatter = _make_metric_scatter_tile(
        sel=sel,
        title="Front Suspension: Compressions >25%",
        event_type=compression_event_type,
        signal_selector=front_event_selector,
        x_metric=scatter_x_metric,
        y_metric=compression_y_metric,
        session_desc_cache=session_desc_cache,
        overlay_fit_cache=compression_overlay_fits,
        overlay_self_key="front",
        overlay_other_key="rear",
    )
    rear_comp_scatter = _make_metric_scatter_tile(
        sel=sel,
        title="Rear Suspension: Compressions >25%",
        event_type=compression_event_type,
        signal_selector=rear_event_selector,
        x_metric=scatter_x_metric,
        y_metric=compression_y_metric,
        session_desc_cache=session_desc_cache,
        overlay_fit_cache=compression_overlay_fits,
        overlay_self_key="rear",
        overlay_other_key="front",
    )
    front_rebound_scatter = _make_metric_scatter_tile(
        sel=sel,
        title="Front Suspension: Rebounds >25%",
        event_type=rebound_event_type,
        signal_selector=front_event_selector,
        x_metric=scatter_x_metric,
        y_metric=rebound_y_metric,
        session_desc_cache=session_desc_cache,
        overlay_fit_cache=rebound_overlay_fits,
        overlay_self_key="front",
        overlay_other_key="rear",
    )
    rear_rebound_scatter = _make_metric_scatter_tile(
        sel=sel,
        title="Rear Suspension: Rebounds >25%",
        event_type=rebound_event_type,
        signal_selector=rear_event_selector,
        x_metric=scatter_x_metric,
        y_metric=rebound_y_metric,
        session_desc_cache=session_desc_cache,
        overlay_fit_cache=rebound_overlay_fits,
        overlay_self_key="rear",
        overlay_other_key="front",
    )

    rows = {
        "displacement": _make_two_column_row(front_disp["out"], rear_disp["out"]),
        "velocity": _make_two_column_row(front_vel["out"], rear_vel["out"]),
        "events": _make_two_column_row(front_evt["out"], rear_evt["out"]),
        "compression_scatter": _make_two_column_row(front_comp_scatter["out"], rear_comp_scatter["out"]),
        "rebound_scatter": _make_two_column_row(front_rebound_scatter["out"], rear_rebound_scatter["out"]),
    }

    root = W.VBox(
        [
            W.HBox([w_show_engineering], layout=W.Layout(width="100%", justify_content="flex-start")),
            rows["displacement"],
            rows["velocity"],
            rows["events"],
            rows["compression_scatter"],
            rows["rebound_scatter"],
        ],
        layout=W.Layout(width="100%", gap="12px"),
    )

    def refresh() -> None:
        row1_shared_y.clear()
        front_disp["rebuild"]()
        rear_disp["rebuild"]()
        front_disp["rebuild"]()

        row2_shared_y.clear()
        front_vel["rebuild"]()
        rear_vel["rebuild"]()
        front_vel["rebuild"]()

        front_evt["rebuild"]()
        rear_evt["rebuild"]()

        compression_overlay_fits.clear()
        front_comp_scatter["rebuild"]()
        rear_comp_scatter["rebuild"]()
        front_comp_scatter["rebuild"]()

        rebound_overlay_fits.clear()
        front_rebound_scatter["rebuild"]()
        rear_rebound_scatter["rebuild"]()
        front_rebound_scatter["rebuild"]()

    def _on_show_engineering_change(*_: Any) -> None:
        refresh()

    w_show_engineering.observe(_on_show_engineering_change, names="value")
    refresh_handle = attach_refresh(sel, rebuild_fns=[refresh])
    refresh()

    def detach() -> None:
        try:
            w_show_engineering.unobserve(_on_show_engineering_change, names="value")
        except Exception:
            pass
        try:
            refresh_handle["detach"]()
        except Exception:
            pass

    handle: DashboardHandle = {
        "ui": root,
        "controls": {"show_engineering": w_show_engineering},
        "rows": rows,
        "tiles": {
            "front_displacement": front_disp,
            "rear_displacement": rear_disp,
            "front_velocity": front_vel,
            "rear_velocity": rear_vel,
            "front_events": front_evt,
            "rear_events": rear_evt,
            "front_compression_scatter": front_comp_scatter,
            "rear_compression_scatter": rear_comp_scatter,
            "front_rebound_scatter": front_rebound_scatter,
            "rear_rebound_scatter": rear_rebound_scatter,
        },
        "state": {
            "row1_shared_y": row1_shared_y,
            "row2_shared_y": row2_shared_y,
            "session_desc_cache": session_desc_cache,
            "compression_overlay_fits": compression_overlay_fits,
            "rebound_overlay_fits": rebound_overlay_fits,
            "front_signal_selector": front_base_selector,
            "rear_signal_selector": rear_base_selector,
            "front_displacement_selector": front_disp_selector,
            "rear_displacement_selector": rear_disp_selector,
            "front_velocity_selector": front_vel_selector,
            "rear_velocity_selector": rear_vel_selector,
            "front_event_signal_selector": front_event_selector,
            "rear_event_signal_selector": rear_event_selector,
            "compression_event_type": compression_event_type,
            "rebound_event_type": rebound_event_type,
            "scatter_x_metric": scatter_x_metric,
            "compression_y_metric": compression_y_metric,
            "rebound_y_metric": rebound_y_metric,
        },
        "refresh": refresh,
        "detach": detach,
    }

    if auto_display:
        display(root)
    return handle
