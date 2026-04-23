# in bodaqs_analysis/widgets/event_browser.py

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import itertools
from collections import OrderedDict

import ipywidgets as W
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from IPython.display import clear_output, display

from bodaqs_analysis.sensor_aliases import sensors_match
from bodaqs_analysis.segment import extract_segments, SegmentRequest, WindowSpec, RoleSpec
from bodaqs_analysis.widgets.loaders import (
    load_all_events_for_selected,
    load_all_metrics_for_selected,
    make_session_loader,
)
from bodaqs_analysis.widgets.contracts import (
    RegistryPolicy,
    RebuilderHandle,
    SESSION_KEY_COL,
    SessionLoader,
    SessionSelectorHandle,
    WidgetHandle,
    selection_snapshot_from_handle,
)
from bodaqs_analysis.widgets.registry_scope import validate_registry_policy
from bodaqs_analysis.widgets.event_browser_options import (
    build_event_labels,
    build_event_type_options,
    build_sensor_options,
    parse_event_label,
)
from bodaqs_analysis.widgets.event_browser_render import (
    choose_active_sensor,
    set_ylim_zero_at_frac,
)
from bodaqs_analysis.widgets.event_browser_scope import (
    ScopeConfig,
    ScopeResolution,
    filter_events,
    get_registry_from_session_meta,
    infer_event_sensor,
    rebuild_scope_resolution,
    resolve_sensor_for_row,
)
from bodaqs_analysis.widgets.event_semantics import (
    registry_signal_options_for_sensor,
    role_spec_from_semantic_tuple,
)

SemanticKey = tuple[str, str, str, str]
SelectedRole = tuple[str, str, SemanticKey, str | None]
ExtractedSeries = tuple[str, np.ndarray, SemanticKey]


def _coerce_list(x):
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    if isinstance(x, str):
        return [p.strip() for p in x.split(",") if p.strip()]
    return [x]


def _secondary_time_cols(row: pd.Series):
    """Return list of (name, t_abs_s) for any *_time_s columns other than canonical ones."""
    out = []
    if row is None:
        return out
    for c in row.index:
        if not isinstance(c, str):
            continue
        if not c.endswith("_time_s"):
            continue
        if c in ("start_time_s", "end_time_s", "trigger_time_s"):
            continue
        v = row.get(c, np.nan)
        if pd.notna(v) and np.isfinite(float(v)):
            out.append((c, float(v)))
    return out


def _series_stats(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"n": 0, "min": np.nan, "max": np.nan, "mean": np.nan, "median": np.nan}
    return {
        "n": int(len(x)),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
    }


def _metric_items(row: pd.Series) -> list[tuple[str, str]]:
    if row is None:
        return []

    items: list[tuple[str, str]] = []
    for c in sorted(row.index):
        if not isinstance(c, str) or not c.startswith("m_"):
            continue
        v = row.get(c, np.nan)
        if pd.isna(v):
            continue
        if isinstance(v, (float, np.floating, int, np.integer)):
            items.append((c, f"{float(v):.6g}"))
        else:
            items.append((c, str(v)))
    return items


def _merge_event_metrics(
    *,
    events_df: pd.DataFrame,
    metrics_df: pd.DataFrame | None,
    session_key_col: str,
) -> pd.DataFrame:
    if events_df is None or events_df.empty:
        return pd.DataFrame()
    if metrics_df is None or metrics_df.empty:
        return events_df.copy()

    join_keys = []
    for col in (session_key_col, "event_id", "schema_id"):
        if col in events_df.columns and col in metrics_df.columns:
            join_keys.append(col)

    if session_key_col not in join_keys or "event_id" not in join_keys:
        return events_df.copy()

    metric_cols = [c for c in metrics_df.columns if c not in join_keys]
    if not metric_cols:
        return events_df.copy()

    return events_df.merge(
        metrics_df[join_keys + metric_cols],
        on=join_keys,
        how="left",
        suffixes=("", "_m"),
    )


def _registry_has_semantic(
    *,
    registry: Mapping[str, Mapping[str, Any]],
    sensor: str | None,
    semantic: tuple[str, str, str, str],
) -> bool:
    if not sensor:
        return False

    quantity, unit, kind, opk = semantic
    unit_s = str(unit or "")
    kind_s = str(kind or "")
    opk_s = str(opk or "")

    for info in registry.values():
        if not isinstance(info, Mapping):
            continue
        if not sensors_match(info.get("sensor"), sensor):
            continue
        if str(info.get("quantity", "")).strip() != str(quantity):
            continue
        if str(info.get("unit") or "") != unit_s:
            continue
        if str(info.get("kind") or "").strip() != kind_s:
            continue
        op_chain = info.get("op_chain") or []
        if isinstance(op_chain, (list, tuple)):
            info_opk = "|".join(str(x) for x in op_chain)
        else:
            info_opk = str(op_chain or "")
        if info_opk == opk_s:
            return True
    return False


def _registry_columns_for_semantic(
    *,
    registry: Mapping[str, Mapping[str, Any]],
    sensor: str | None,
    semantic: tuple[str, str, str, str],
) -> list[str]:
    if not sensor:
        return []

    quantity, unit, kind, opk = semantic
    unit_s = str(unit or "")
    kind_s = str(kind or "")
    opk_s = str(opk or "")
    matched: list[str] = []

    for col, info in registry.items():
        if not isinstance(col, str) or not isinstance(info, Mapping):
            continue
        if not sensors_match(info.get("sensor"), sensor):
            continue
        if str(info.get("quantity", "")).strip() != str(quantity):
            continue
        if str(info.get("unit") or "") != unit_s:
            continue
        if str(info.get("kind") or "").strip() != kind_s:
            continue
        op_chain = info.get("op_chain") or []
        if isinstance(op_chain, (list, tuple)):
            info_opk = "|".join(str(x) for x in op_chain)
        else:
            info_opk = str(op_chain or "")
        if info_opk != opk_s:
            continue
        matched.append(col)

    matched.sort(key=lambda c: (len(c), c))
    return matched


def _extract_series_for_selected_roles(
    *,
    session: Mapping[str, Any],
    event_row_df: pd.DataFrame,
    event_type: str,
    schema: Mapping[str, Any],
    window: WindowSpec,
    selected_roles: Sequence[SelectedRole],
) -> tuple[np.ndarray | None, list[ExtractedSeries], dict[str, Any], str | None]:
    series: list[ExtractedSeries] = []
    spec: dict[str, Any] = {}
    t_rel: np.ndarray | None = None
    primary_reason: str | None = None

    for role_name, sensor_name, semantic, anchor_col in selected_roles:
        local_event_df = event_row_df.reset_index(drop=True).copy()
        if anchor_col:
            local_event_df["signal_col"] = anchor_col

        req = SegmentRequest(
            schema_id=str(event_type),
            window=window,
            roles=[
                role_spec_from_semantic_tuple(
                    RoleSpec,
                    role=role_name,
                    sensor=sensor_name,
                    semantic=semantic,
                )
            ],
        )

        bundle = extract_segments(
            session["df"],
            local_event_df,
            meta=session["meta"],
            schema=schema,
            request=req,
        )

        data = bundle.get("data", {})
        spec = bundle.get("spec", {})
        segs = bundle.get("segments", None)
        if segs is None or len(segs) == 0 or not bool(segs.iloc[0].get("valid", False)):
            primary_reason = segs.iloc[0].get("reason") if (segs is not None and len(segs)) else None
            continue

        t_local = data.get("t_rel_s", None)
        if t_local is None:
            continue
        if t_rel is None:
            t_rel = np.asarray(t_local)[0]

        if role_name not in data:
            continue

        quantity, unit, kind, opk = semantic
        y = np.asarray(data[role_name])[0]
        unit_s = f" [{unit}]" if unit else ""
        kind_s = f" ({kind})" if kind else ""
        op_s = f" -> {opk}" if opk else ""
        series.append((f"{sensor_name} | {quantity}{unit_s}{kind_s}{op_s}", y, semantic))

    return t_rel, series, spec, primary_reason


def _require_cols(df: pd.DataFrame, cols: Sequence[str], *, name: str):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required columns: {missing}")


def _event_type_col(events_df: pd.DataFrame) -> str:
    """
    Determine which column represents the event type.

    Prefer explicit 'event_type' if present; otherwise fall back to 'schema_id'.
    """
    return "event_type" if "event_type" in events_df.columns else "schema_id"



def make_event_browser_widget_for_loader(
    schema: Mapping[str, Any],
    events_df: pd.DataFrame,
    *,
    session_loader: SessionLoader,
    metrics_df: pd.DataFrame | None = None,
    session_key_col: str = SESSION_KEY_COL,
    registry_policy: RegistryPolicy = "union",
    default_quantities: Sequence[str] = ("disp", "vel"),
    default_pre_s: float = 0.8,
    default_post_s: float = 0.8,
    auto_display: bool = False,
) -> WidgetHandle:
    """
    Same widget, but session is selected in the UI and loaded lazily via session_loader(session_id)->session dict.
    The loaded session must include: {"df": DataFrame, "meta": {"signals": ...}, ...}
    """
    if events_df is None or len(events_df) == 0:
        raise ValueError("events_df is empty")
    validate_registry_policy(registry_policy)

    _require_cols(
    events_df,
    (session_key_col, "session_id", "event_id", "signal_col", "trigger_time_s"),
    name="events_df",
    )
    et_col = _event_type_col(events_df)
    _require_cols(events_df, (et_col,), name="events_df")
    events_viz_df = _merge_event_metrics(
        events_df=events_df,
        metrics_df=metrics_df,
        session_key_col=session_key_col,
    )

    # ---- Controls (NOTE: session selector is now multi-select)
    all_sessions = sorted(events_viz_df[session_key_col].dropna().astype(str).unique().tolist())

    # multi-select for "scope"
    sessions_label = W.Label("Sessions:")
    w_sessions = W.SelectMultiple(
        options=all_sessions,
        value=tuple(all_sessions),
        description="",
        rows=min(8, max(5, len(all_sessions))),
        layout=W.Layout(width="380px"),
    )

    dummy_label = W.Label(" ")
    event_label = W.Label("Event:")
    w_event_type = W.Dropdown(options=[], description="Event type:", layout=W.Layout(width="380px"))
    w_event = W.Dropdown(options=[], description="", layout=W.Layout(width="450px"))
   
    # --- Prev/Next buttons for event navigation ---
    w_prev = W.Button(description="", icon="arrow-left", tooltip="Previous event", layout=W.Layout(width="36px"))
    w_next = W.Button(description="", icon="arrow-right", tooltip="Next event", layout=W.Layout(width="36px"))

    def _event_labels() -> List[str]:
        # Dropdown options are labels (strings)
        return list(w_event.options) if w_event.options else []

    def _event_index() -> int:
        labels = _event_labels()
        try:
            return labels.index(w_event.value)
        except Exception:
            return -1

    def _update_nav_buttons(*_):
        labels = _event_labels()
        idx = _event_index()
        w_prev.disabled = (not labels) or (idx <= 0)
        w_next.disabled = (not labels) or (idx == -1) or (idx >= len(labels) - 1)

    def _go_delta(delta: int):
        labels = _event_labels()
        if not labels:
            return
        idx = _event_index()
        if idx == -1:
            w_event.value = labels[0]
            return
        j = max(0, min(len(labels) - 1, idx + delta))
        if labels[j] != w_event.value:
            w_event.value = labels[j]  # triggers downstream observers

    def _on_prev(_btn):
        _go_delta(-1)

    def _on_next(_btn):
        _go_delta(+1)

    w_prev.on_click(_on_prev)
    w_next.on_click(_on_next)

    # keep enabled/disabled state in sync
    w_event.observe(_update_nav_buttons, names="value")

    w_pre = W.FloatText(value=float(default_pre_s), description="Pre (s):", layout=W.Layout(width="160px"))
    w_post = W.FloatText(value=float(default_post_s), description="Post (s):", layout=W.Layout(width="160px"))

    # Sensor + signals are derived from the registry
    w_sensor = W.Dropdown(
        options=[],              # populated by _rebuild_sensor_options
        value=None,
        description="Sensors:",
        layout=W.Layout(width="380px"),
    )

    signals_label = W.Label("Signals:")
    w_signals = W.SelectMultiple(
        options=[],
        value=(),
        description="",
        layout=W.Layout(width="380px", height="140px"),
    )

    w_show_secondary = W.Checkbox(value=True, description="Sec. triggers")
    w_show_all_sensors = W.Checkbox(value=False, description="Show all sensors")
    w_show_grid = W.Checkbox(value=True, description="Grid")
    w_show_metrics = W.Checkbox(value=False, description="Show metrics")
    w_show_stats = W.Checkbox(value=False, description="Stats")
    w_show_resolve = W.Checkbox(value=False, description="Info")

    out = W.Output()

    # ---- Session cache (avoid re-loading repeatedly)
    _session_cache: Dict[str, dict] = {}

    def _get_session(session_key: str) -> dict:
        sk = str(session_key)
        if sk not in _session_cache:
            _session_cache[sk] = session_loader(sk)
        return _session_cache[sk]

    def _event_registry() -> dict:
        ev_df, ev_row = _selected_event_row()
        if ev_row is None:
            raise ValueError("No event selected")
        sk = str(ev_row.get(session_key_col))
        reg = _scope_resolution.registries_by_session.get(sk)
        if isinstance(reg, dict) and reg:
            return reg
        session = _get_session(sk)
        return get_registry_from_session_meta(session)

    # ----------------------------
    # Schema-mediated sensor resolver (session-aware)
    # ----------------------------
    scope_config = ScopeConfig(
        session_key_col=session_key_col,
        event_type_col=et_col,
        signal_col="signal_col",
        registry_policy=registry_policy,
    )
    _scope_resolution = ScopeResolution({}, {}, None)

    def _rebuild_scope_resolution(scope: List[str]) -> None:
        nonlocal _scope_resolution
        _scope_resolution = rebuild_scope_resolution(
            scope_sessions=scope,
            get_session=_get_session,
            schema=schema,
            config=scope_config,
        )

    def _resolve_sensor_for_session(
        *,
        session_key: object,
        schema_id_val: object,
        token_val: object,
    ) -> str:
        return resolve_sensor_for_row(
            session_key=session_key,
            schema_id_val=schema_id_val,
            token_val=token_val,
            resolution=_scope_resolution,
        )

    def _infer_event_sensor_for_row(ev_row: pd.Series) -> Optional[str]:
        return infer_event_sensor(
            ev_row=ev_row,
            candidate_token_cols=("signal_col", "anchor_col", "primary_col"),
            config=scope_config,
            resolution=_scope_resolution,
        )

    def _filtered_events() -> pd.DataFrame:
        scope = list(map(str, _coerce_list(w_sessions.value)))
        _rebuild_scope_resolution(scope)
        selected_sensor = str(w_sensor.value).strip() if w_sensor.value else ""
        return filter_events(
            events_df=events_viz_df,
            scope_sessions=scope,
            selected_event_type=(str(w_event_type.value) if w_event_type.value else None),
            selected_sensors=((selected_sensor,) if selected_sensor else ()),
            config=scope_config,
            resolution=_scope_resolution,
        )



    def _rebuild_event_type(*_):
        scope = set(map(str, _coerce_list(w_sessions.value)))
        if not scope:
            _scope_resolution.error = None
            w_event_type.options = []
            w_event_type.value = None
            w_event.options = []
            w_event.value = None
            _update_nav_buttons()
            return

        # scope-only (no event type / sensor filtering here)
        etypes = build_event_type_options(
            events_df=events_viz_df,
            scope_sessions=list(scope),
            session_key_col=session_key_col,
            event_type_col=et_col,
        )

        prev = w_event_type.value  # remember user choice

        w_event_type.options = etypes

        # restore if still valid, else choose a sensible default
        if prev in etypes:
            w_event_type.value = prev
        else:
            w_event_type.value = etypes[0] if etypes else None

        _rebuild_events()
        _rebuild_sensor_options()



    def _rebuild_sensor_options(*_):
        scope = list(map(str, _coerce_list(w_sessions.value)))
        if not scope:
            w_sensor.options = []
            w_sensor.value = None
            return

        _rebuild_scope_resolution(scope)
        if _scope_resolution.error:
            w_sensor.options = []
            w_sensor.value = None
            return

        sensors = build_sensor_options(
            events_df=events_viz_df,
            scope_sessions=scope,
            selected_event_type=(str(w_event_type.value) if w_event_type.value else None),
            session_key_col=session_key_col,
            event_type_col=et_col,
            resolve_sensor_for_row_fn=lambda r: _resolve_sensor_for_session(
                session_key=r.get(session_key_col),
                schema_id_val=r.get(et_col),
                token_val=r.get("signal_col"),
            ),
        )

        current = str(w_sensor.value) if w_sensor.value else None

        opts = sensors
        w_sensor.options = opts

        if current in opts:
            w_sensor.value = current
        elif opts:
            w_sensor.value = opts[0]
        else:
            w_sensor.value = None


    def _rebuild_events(*_):
        sub = _filtered_events()
        if len(sub) == 0:
            w_event.options = []
            w_event.value = None
            return

        labels = build_event_labels(
            filtered_events_df=sub,
            session_id_col="session_id",
            event_id_col="event_id",
            trigger_time_col="trigger_time_s",
            session_key_col=session_key_col,
        )

        current = w_event.value
        w_event.options = labels

        if current in labels:
            w_event.value = current
        elif labels:
            w_event.value = labels[0]

        _update_nav_buttons()


    def _selected_event_row() -> Tuple[Optional[pd.DataFrame], Optional[pd.Series]]:
        if not w_event.value:
            return None, None

        session_id, event_id, session_key = parse_event_label(str(w_event.value))

        sub = _filtered_events()
        if session_key:
            ev = sub[
                (sub[session_key_col].astype(str) == str(session_key))
                & (sub["event_id"].astype(str) == str(event_id))
            ].copy()
        else:
            ev = sub[
                (sub["session_id"].astype(str) == session_id)
                & (sub["event_id"].astype(str) == str(event_id))
            ].copy()

        if len(ev) != 1:
            return None, None
        return ev, ev.iloc[0]

    def _rebuild_signals_only(*_):
        # Update sensor list from event's registry
        try:
            registry = _event_registry()
        except Exception:
            w_signals.options = []
            w_signals.value = ()
            return

        # Auto sensor from event anchor when enabled
        ev_df, ev_row = _selected_event_row()
        inferred = _infer_event_sensor_for_row(ev_row) if ev_row is not None else None

        selected_sensor = str(w_sensor.value).strip() if w_sensor.value else ""
        active_sensor = selected_sensor or inferred


        # --- Remember current selection (before we replace options) ---
        prev = tuple(w_signals.value) if w_signals.value is not None else ()

        opts = registry_signal_options_for_sensor(registry=registry, sensor=active_sensor)
        w_signals.options = opts
        avail = {key for (_, key) in opts}

        # 1) Restore remembered selection if still valid
        kept = tuple(k for k in prev if k in avail)
        if kept:
            w_signals.value = kept
            return

        mm_keys = [key for (_, key) in opts if key and str(key[1] or "") == "mm"]
        if mm_keys:
            w_signals.value = (mm_keys[0],)
            return

        # Helper: choose "best" single key among candidates
        def _pick_best(cands):
            if not cands:
                return None

            # Prefer: kind == "" (not raw/qc), then opk == "" (no op chain)
            def score(k):
                quantity, unit, kind, opk = k
                return (
                    0 if (kind == "" or kind is None) else 1,
                    0 if (opk == "" or opk is None) else 1,
                    str(unit),
                    str(k),
                )

            return sorted(cands, key=score)[0]

        # 3) Default to trigger role for the selected event (single series)
        trigger_role = None
        if ev_row is not None:
            trigger_role = ev_row.get("signal", None)
            trigger_role = trigger_role.strip() if isinstance(trigger_role, str) else None

        if trigger_role:
            trig_cands = [key for (_, key) in opts if key and key[0] == trigger_role]
            best = _pick_best(trig_cands)
            if best is not None:
                w_signals.value = (best,)
                return

        # 4) Fall back to default_quantities (same behavior as before)
        desired = set(_coerce_list(default_quantities))
        selected = [key for (_, key) in opts if key and key[0] in desired]
        w_signals.value = tuple(selected) if selected else ()

    def _render(*_):
        with out:
            clear_output(wait=True)

            if _scope_resolution.error:
                print(_scope_resolution.error)
                return

            ev_row_df, ev_row = _selected_event_row()
            if ev_row is None:
                print("No event selected.")
                return

            # Loader key (unique across runs) + display id (friendly)
            event_session_key = str(ev_row[session_key_col])
            event_session_id  = str(ev_row["session_id"])
            session = _get_session(event_session_key)

            registry = get_registry_from_session_meta(session)

            # Determine active sensor for the event
            inferred = _infer_event_sensor_for_row(ev_row) if ev_row is not None else None

            selected_sensor = str(w_sensor.value).strip() if w_sensor.value else ""
            sensor = choose_active_sensor(
                inferred_sensor=inferred,
                selected_sensors=((selected_sensor,) if selected_sensor else ()),
            )



            # Build role selection plan
            selected_roles: List[SelectedRole] = []
            sensors_to_plot: List[str] = []
            if bool(w_show_all_sensors.value):
                sensors_to_plot = [str(s) for s in list(w_sensor.options or []) if str(s).strip()]
            elif sensor:
                sensors_to_plot = [str(sensor)]

            if not sensors_to_plot and inferred:
                sensors_to_plot = [str(inferred)]

            for idx, semantic in enumerate(_coerce_list(w_signals.value)):
                qty = str(semantic[0])
                for sensor_name in sensors_to_plot:
                    matched_cols = _registry_columns_for_semantic(
                        registry=registry,
                        sensor=sensor_name,
                        semantic=semantic,
                    )
                    if not matched_cols:
                        continue
                    role_name = f"{qty}__{sensor_name}__sel_{idx}"
                    anchor_col = matched_cols[0] if bool(w_show_all_sensors.value) else None
                    selected_roles.append((role_name, sensor_name, semantic, anchor_col))

            if not selected_roles:
                print("No signals selected. Select at least one signal to plot.")
                return

            req_window = WindowSpec(mode="time", pre_s=float(w_pre.value), post_s=float(w_post.value))
            t_rel, series_raw, spec, primary_reason = _extract_series_for_selected_roles(
                session=session,
                event_row_df=ev_row_df,
                event_type=str(ev_row[et_col]),
                schema=schema,
                window=req_window,
                selected_roles=selected_roles,
            )

            series: list[ExtractedSeries] = []
            for name, y, semantic in series_raw:
                if bool(w_show_all_sensors.value):
                    series.append((name, y, semantic))
                else:
                    quantity, unit, kind, opk = semantic
                    unit_s = f" [{unit}]" if unit else ""
                    kind_s = f" ({kind})" if kind else ""
                    op_s = f" -> {opk}" if opk else ""
                    series.append((f"{quantity}{unit_s}{kind_s}{op_s}", y, semantic))

            if not series:
                print("Segment invalid:" if primary_reason else "No series available to plot.", primary_reason or "")
                return

            if t_rel is None:
                print("Bundle missing t_rel_s")
                return

            # group series by unit
            by_unit = OrderedDict()
            for plot_label, y, semantic in series:
                quantity, unit, kind, opk = semantic
                unit_key = unit or ""  # empty string = unitless
                by_unit.setdefault(unit_key, []).append((plot_label, y))

            if not by_unit:
                print("No plotted series resolved for the selected signals.")
                return


            chart_out = W.Output(layout=W.Layout(width="780px" if bool(w_show_metrics.value) else "980px"))
            metrics_out = W.Output(layout=W.Layout(width="340px"))

            with chart_out:
                fig, ax = plt.subplots(figsize=(9.5, 4.2))

                axes = [ax]
                unit_to_ax = {list(by_unit.keys())[0]: ax}

                # create additional y-axes if needed
                for i, unit in enumerate(list(by_unit.keys())[1:], start=1):
                    ax_i = ax.twinx()
                    ax_i.spines["right"].set_position(("outward", 60 * (i - 1)))
                    axes.append(ax_i)
                    unit_to_ax[unit] = ax_i

                colors = itertools.cycle(plt.rcParams["axes.prop_cycle"].by_key()["color"])
                for unit, items in by_unit.items():
                    ax_i = unit_to_ax[unit]
                    for plot_label, y in items:
                        ax_i.plot(t_rel, y, label=plot_label, color=next(colors))

                fmt = mticker.ScalarFormatter(useMathText=True)
                fmt.set_powerlimits((-4, 4))
                for ax_i in axes:
                    ax_i.yaxis.set_major_formatter(fmt)

                ymin0, ymax0 = ax.get_ylim()
                frac0 = (0.0 - ymin0) / (ymax0 - ymin0) if ymax0 != ymin0 else 0.5
                frac0 = float(np.clip(frac0, 0.05, 0.95))

                for ax_i in axes:
                    lines = ax_i.get_lines()
                    if not lines:
                        continue
                    y_all = np.concatenate([ln.get_ydata() for ln in lines if ln.get_ydata() is not None])
                    y_all = y_all[np.isfinite(y_all)]
                    if y_all.size == 0:
                        continue
                    set_ylim_zero_at_frac(ax_i, float(y_all.min()), float(y_all.max()), frac0, pad=0.05)

                handles = []
                labels = []
                for ax_i in axes:
                    h, l = ax_i.get_legend_handles_labels()
                    handles.extend(h)
                    labels.extend(l)

                ax.legend(handles, labels, loc="best")

                for ax_i in axes:
                    ax_i.axvline(
                        0.0,
                        linestyle="--",
                        linewidth=1.2,
                        color="0.25",
                        zorder=3,
                    )

                ax.axvline(0.0, linestyle="--", linewidth=1.0, color="0.25", zorder=3)
                ax.text(0.0, 0.98, "trigger", transform=ax.get_xaxis_transform(), ha="left", va="top")

                if w_show_secondary.value:
                    t0 = float(ev_row["trigger_time_s"])
                    for col, t_abs in _secondary_time_cols(ev_row):
                        tsec = float(t_abs) - t0
                        ax.axvline(tsec, linestyle=":", linewidth=1.0)
                        ax.text(
                            tsec, 0.98, col.replace("_time_s", ""),
                            transform=ax.get_xaxis_transform(),
                            rotation=90, ha="right", va="top", fontsize=8
                        )

                title_sensor = sensor or ""
                if bool(w_show_all_sensors.value):
                    title_sensor = "all sensors"
                ax.set_title(
                    f"Event browser - {event_session_id} | {ev_row[et_col]} | {ev_row['event_id']} | {title_sensor}".strip()
                )
                ax.set_xlabel("t_rel_s (s)")
                for unit, ax_i in unit_to_ax.items():
                    if unit:
                        ax_i.set_ylabel(unit)
                    else:
                        ax_i.set_ylabel("")

                if w_show_grid.value:
                    ax.grid(True, which="both", axis="both", alpha=0.3)
                plt.show()

            if bool(w_show_metrics.value):
                with metrics_out:
                    metric_items = _metric_items(ev_row)
                    if metric_items:
                        print("Metrics:")
                        for key, val in metric_items:
                            print(f"  {key}: {val}")
                    else:
                        print("No event metrics available.")
                display(W.HBox([chart_out, metrics_out]))
            else:
                display(chart_out)

            if w_show_stats.value or w_show_resolve.value:
                aux_out = W.Output()
                with aux_out:
                    if w_show_stats.value:
                        print("Series stats (finite only):")
                        for name, y, _semantic in series:
                            st = _series_stats(y)
                            print(
                                f"  {name:16s}  n={st['n']:4d}  "
                                f"min={st['min']:+.4g}  max={st['max']:+.4g}  "
                                f"mean={st['mean']:+.4g}  median={st['median']:+.4g}"
                            )

                    if w_show_resolve.value:
                        print("\nResolve info:")
                        print("  scope sessions:", list(_coerce_list(w_sessions.value)))
                        print("  event session:", event_session_id)
                        print("  event session key:", event_session_key)
                        print("  event_type_col:", et_col)
                        print("  event type:", ev_row.get(et_col))
                        print("  event signal_col:", ev_row.get("signal_col"))
                        print("  inferred sensor:", inferred)
                        print("  sensor used:", sensor)
                        print("  plotting sensors:", sensors_to_plot)
                        print("  selected signals:", list(_coerce_list(w_signals.value)))
                        print("\nResolved spec:")
                        print("  role_to_col:", spec.get("role_to_col"))
                display(aux_out)


    # ---- Wire up
    w_sessions.observe(_rebuild_event_type, names="value")
    w_event_type.observe(_rebuild_events, names="value")
    w_event.observe(_rebuild_signals_only, names="value")
    w_sensor.observe(_rebuild_events, names="value")
    w_sensor.observe(_rebuild_signals_only, names="value")


    for w in (
        w_event,
        w_pre,
        w_post,
        w_signals,
        w_show_secondary,
        w_show_all_sensors,
        w_show_grid,
        w_show_metrics,
        w_show_stats,
        w_show_resolve,
    ):
        w.observe(_render, names="value")

    # ---- Init
    ui = W.VBox(
        [
            W.HBox([W.VBox([sessions_label, w_sessions]), W.VBox([dummy_label, w_event_type, w_sensor])]),
            W.HBox([W.VBox([event_label, w_event]), W.VBox([dummy_label,W.HBox([w_prev, w_next])])]),

            W.HBox([W.VBox([signals_label, w_signals]),W.VBox([dummy_label, W.HBox([w_pre, w_post]), W.HBox([w_show_secondary, w_show_all_sensors]), W.HBox([w_show_grid, w_show_metrics]), W.HBox([w_show_stats, w_show_resolve])])]),
            out,
        ]
    )

    def refresh() -> None:
        _rebuild_event_type()
        _render()

    refresh()
    if auto_display:
        display(ui)

    return {
        "root": ui,
        "ui": ui,
        "out": out,
        "controls": {
            "sessions": w_sessions,
            "event_type": w_event_type,
            "sensor": w_sensor,
            "event": w_event,
            "signals": w_signals,
            "show_all_sensors": w_show_all_sensors,
            "show_metrics": w_show_metrics,
        },
        "cache": _session_cache,
        "refresh": refresh,
    }

def make_event_browser_rebuilder(
    *,
    sel: SessionSelectorHandle,
    schema: Mapping[str, Any],
    out: Optional[W.Output] = None,
    session_key_col: str = SESSION_KEY_COL,
    registry_policy: RegistryPolicy = "union",
    **kwargs,
) -> RebuilderHandle:
    """
    Rebuild helper for the event browser widget (recreates the widget on selector change).
    """

    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None}

    def rebuild() -> None:
        snapshot = selection_snapshot_from_handle(sel)
        store = sel["store"]
        key_to_ref = snapshot.key_to_ref
        if not key_to_ref:
            with out:
                clear_output(wait=True)
                print("No sessions available for the current selector scope.")
            state["handles"] = None
            return

        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)
        events_df_sel = load_all_events_for_selected(store, key_to_ref=key_to_ref)
        metrics_df_sel = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)

        with out:
            clear_output(wait=True)
            state["handles"] = make_event_browser_widget_for_loader(
                schema,
                events_df_sel,
                session_loader=session_loader,
                metrics_df=metrics_df_sel,
                session_key_col=session_key_col,
                registry_policy=registry_policy,
                auto_display=False,
                **kwargs,
            )
            h = state["handles"]
            root = h.get("root") or h.get("ui")
            if root is not None:
                display(root)

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}


