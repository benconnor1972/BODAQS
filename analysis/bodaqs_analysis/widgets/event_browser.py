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

from bodaqs_analysis.segment import extract_segments, SegmentRequest, WindowSpec, RoleSpec
from bodaqs_analysis.widgets.loaders import make_session_loader, load_all_events_for_selected
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

    # ---- Controls (NOTE: session selector is now multi-select)
    all_sessions = sorted(events_df[session_key_col].dropna().astype(str).unique().tolist())

    # multi-select for "scope"
    sessions_label = W.Label("Sessions:")
    w_sessions = W.SelectMultiple(
        options=all_sessions,
        value=(all_sessions[0],) if all_sessions else (),
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
    w_sensor = W.SelectMultiple(
        options=[],              # populated by _rebuild_sensor_options
        value=(),                # empty = no filtering (equivalent to "All")
        rows=3,
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
    w_show_grid = W.Checkbox(value=True, description="Grid")
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
        return filter_events(
            events_df=events_df,
            scope_sessions=scope,
            selected_event_type=(str(w_event_type.value) if w_event_type.value else None),
            selected_sensors=tuple(map(str, _coerce_list(w_sensor.value))),
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
            events_df=events_df,
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
            w_sensor.value = ()
            return

        _rebuild_scope_resolution(scope)
        if _scope_resolution.error:
            w_sensor.options = []
            w_sensor.value = ()
            return

        sensors = build_sensor_options(
            events_df=events_df,
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

        current = tuple(map(str, _coerce_list(w_sensor.value)))

        opts = sensors
        w_sensor.options = opts

        # Keep selections that still exist
        kept = tuple([s for s in current if s in opts])
        w_sensor.value = kept
        
        if not w_sensor.value and opts:
            w_sensor.value = (opts[0],)


    def _rebuild_events(*_):
        sub = _filtered_events()
        if len(sub) == 0:
            w_event.options = []
            return

        labels = build_event_labels(
            filtered_events_df=sub,
            session_id_col="session_id",
            event_id_col="event_id",
            trigger_time_col="trigger_time_s",
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

        session_id, event_id = parse_event_label(str(w_event.value))

        sub = _filtered_events()
        ev = sub[
            (sub["session_id"].astype(str) == session_id) &
            (sub["event_id"].astype(str) == str(event_id))
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

        sel_sensors = tuple(map(str, _coerce_list(w_sensor.value)))
        sel_sensors = tuple(s.strip() for s in sel_sensors if s and str(s).strip())

        # Empty selection => "All" (auto): use inferred if available, else no sensor filter
        if not sel_sensors:
            active_sensor = inferred
        # Single selection => use it
        elif len(sel_sensors) == 1:
            active_sensor = sel_sensors[0]
        # Multiple selections => prefer inferred if it's among them, else pick first
        else:
            active_sensor = inferred if (inferred and inferred in sel_sensors) else sel_sensors[0]


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

        # 2) Default to trigger role for the selected event (single series)
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

        # 3) Fall back to default_quantities (same behavior as before)
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

            # Determine active sensor for the event (multi-select semantics)
            inferred = _infer_event_sensor_for_row(ev_row) if ev_row is not None else None

            sel_sensors = tuple(map(str, _coerce_list(w_sensor.value)))
            sensor = choose_active_sensor(
                inferred_sensor=inferred,
                selected_sensors=sel_sensors,
            )



            # Build RoleSpecs from selected semantic tuples
            role_specs = []
            
            for semantic in _coerce_list(w_signals.value):
                qty = str(semantic[0])
                role_specs.append(
                    role_spec_from_semantic_tuple(RoleSpec, role=qty, sensor=sensor, semantic=semantic)
                )

            if not role_specs:
                print("No signals selected. Select at least one signal to plot.")
                return
                
            req = SegmentRequest(
                schema_id=str(ev_row[et_col]),
                window=WindowSpec(mode="time", pre_s=float(w_pre.value), post_s=float(w_post.value)),
                roles=role_specs,
            )

            bundle = extract_segments(
                session["df"],
                ev_row_df.reset_index(drop=True),
                meta=session["meta"],
                schema=schema,
                request=req,
            )

            data = bundle.get("data", {})
            spec = bundle.get("spec", {})
            segs = bundle.get("segments", None)

            if segs is None or len(segs) == 0 or not bool(segs.iloc[0].get("valid", False)):
                reason = segs.iloc[0].get("reason") if (segs is not None and len(segs)) else None
                print("Segment invalid:", reason or "no segments")
                return

            t_rel = data.get("t_rel_s", None)
            if t_rel is None:
                print("Bundle missing t_rel_s")
                return
            t_rel = np.asarray(t_rel)[0]

            series = []
            for semantic in _coerce_list(w_signals.value):
                quantity, unit, kind, opk = semantic
                key = str(quantity)
                if key in data:
                    y = np.asarray(data[key])[0]
                    unit_s = f" [{unit}]" if unit else ""
                    series.append((f"{key}{unit_s}", y))

            if not series and "primary" in data:
                series.append(("primary", np.asarray(data["primary"])[0]))

            if not series:
                print("No series available to plot.")
                return

            # group series by unit
            by_unit = OrderedDict()
            for semantic in _coerce_list(w_signals.value):
                quantity, unit, kind, opk = semantic
                key = str(quantity)
                if key not in data:
                    continue
                y = np.asarray(data[key])[0]
                unit_key = unit or ""  # empty string = unitless
                by_unit.setdefault(unit_key, []).append((quantity, y))


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
                for quantity, y in items:
                    ax_i.plot(t_rel, y, label=quantity, color=next(colors))

            # sci notation outside ~1e-4..1e4
            fmt = mticker.ScalarFormatter(useMathText=True)
            fmt.set_powerlimits((-4, 4))  

            for ax_i in axes:
                ax_i.yaxis.set_major_formatter(fmt)

            # Compute desired frac0 from primary axis (based on its current limits)
            ymin0, ymax0 = ax.get_ylim()
            frac0 = (0.0 - ymin0) / (ymax0 - ymin0) if ymax0 != ymin0 else 0.5
            frac0 = float(np.clip(frac0, 0.05, 0.95))

            # Apply aligned 0-position limits to every axis based on that frac0
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

            ax.axvline(0.0, linestyle="--", linewidth=1.0, color="0.25",zorder=3)
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

            ax.set_title(
                f"Event browser — {event_session_id} | {ev_row[et_col]} | {ev_row['event_id']} | {sensor or ''}".strip()
            )
            ax.set_xlabel("t_rel_s (s)")
            for unit, ax_i in unit_to_ax.items():
                if unit:
                    ax_i.set_ylabel(unit)
                else:
                    ax_i.set_ylabel("")  # unitless or leave blank

            if w_show_grid.value:
                ax.grid(True, which="both", axis="both", alpha=0.3)
            plt.show()

            if w_show_stats.value:
                print("Series stats (finite only):")
                for name, y in series:
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
                print("  selected quantities:", [k[0] for k in _coerce_list(w_signals.value)])
                print("\nResolved spec:")
                print("  role_to_col:", spec.get("role_to_col"))


    # ---- Wire up
    w_sessions.observe(_rebuild_event_type, names="value")
    w_event_type.observe(_rebuild_events, names="value")
    w_event.observe(_rebuild_signals_only, names="value")
    w_sensor.observe(_rebuild_events, names="value")


    for w in (w_event, w_pre, w_post, w_signals, w_show_secondary, w_show_grid, w_show_stats, w_show_resolve):
        w.observe(_render, names="value")

    # ---- Init
    ui = W.VBox(
        [
            W.HBox([W.VBox([sessions_label, w_sessions]), W.VBox([dummy_label, w_event_type, w_sensor])]),
            W.HBox([W.VBox([event_label, w_event]), W.VBox([dummy_label,W.HBox([w_prev, w_next])])]),

            W.HBox([W.VBox([signals_label, w_signals]),W.VBox([dummy_label, W.HBox([w_pre, w_post]), W.HBox([w_show_secondary, w_show_grid]), W.HBox([w_show_stats, w_show_resolve])])]),
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
        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

        events_df_sel = load_all_events_for_selected(store, key_to_ref=key_to_ref)
        # Expect events_df_sel already includes a session_key column

        with out:
            clear_output(wait=True)
            state["handles"] = make_event_browser_widget_for_loader(
                schema,
                events_df_sel,
                session_loader=session_loader,
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


