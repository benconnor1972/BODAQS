# in bodaqs_analysis/widgets/event_browser.py

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as W
from IPython.display import display, clear_output
from collections import OrderedDict
import matplotlib.ticker as mticker
import itertools

from bodaqs_analysis.segment import extract_segments, SegmentRequest, WindowSpec, RoleSpec
from IPython.display import clear_output
from bodaqs_analysis.widgets.loaders import make_session_loader, load_all_events_for_selected

# ---- internal helpers (paste this whole block near the top of event_browser.py) ----
# Put it AFTER your imports (numpy/pandas/etc.) but BEFORE make_event_browser_widget_for_loader()

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


def _get_registry(meta: dict) -> dict:
    sigs = (meta or {}).get("signals")
    if not isinstance(sigs, dict) or not sigs:
        raise ValueError("session['meta']['signals'] missing/empty (required for segment extraction)")
    return sigs


def _infer_event_sensor(registry: dict, ev_row: pd.Series) -> Optional[str]:
    """Infer sensor from the event's anchor signal column."""
    if ev_row is None:
        return None
    for k in ("signal_col", "anchor_col", "primary_col"):
        v = ev_row.get(k, None)
        if isinstance(v, str) and v.strip():
            info = registry.get(v.strip())
            if isinstance(info, dict):
                s = info.get("sensor")
                if isinstance(s, str) and s.strip():
                    return s.strip()
    return None


def _opkey(op_chain) -> str:
    if op_chain is None:
        return ""
    if isinstance(op_chain, (list, tuple)):
        return "|".join(str(x) for x in op_chain)
    return str(op_chain)


def _registry_signal_options_for_sensor(
    registry: dict,
    sensor: Optional[str],
) -> List[Tuple[str, Tuple[str, str, str, str]]]:
    """
    Build SelectMultiple options from registry entries for a given sensor.

    Each option value is a tuple:
      (quantity, unit, kind, op_chain_key)

    Label is human-friendly.
    """
    if not sensor:
        return []

    opts: List[Tuple[str, Tuple[str, str, str, str]]] = []
    seen = set()

    for col, info in registry.items():
        if not isinstance(info, dict):
            continue
        if info.get("sensor") != sensor:
            continue

        kind = (info.get("kind") or "").strip()
        if kind == "qc":
            continue  # keep QC out of plotting roles by default

        quantity = info.get("quantity")
        if not isinstance(quantity, str) or not quantity.strip():
            continue
        quantity = quantity.strip()

        unit = info.get("unit") or ""
        unit = str(unit)

        opk = _opkey(info.get("op_chain") or [])

        key = (quantity, unit, kind, opk)
        if key in seen:
            continue
        seen.add(key)

        unit_s = f" [{unit}]" if unit else ""
        kind_s = f" ({kind})" if kind else ""
        op_s = f" ⟶{opk}" if opk else ""
        label = f"{quantity}{unit_s}{kind_s}{op_s}"
        opts.append((label, key))

    order = {"disp": 0, "disp_norm": 1, "vel": 2, "acc": 3, "raw": 4}
    opts.sort(key=lambda kv: (order.get(kv[1][0], 99), kv[0]))
    return opts

def _role_spec_from_semantic_tuple(
    RoleSpecCls,
    *,
    role: str,
    sensor: Optional[str],
    semantic: Tuple[str, str, str, str],
):
    """
    semantic = (quantity, unit, kind, opk)

    Construct RoleSpec in the most compatible way possible, then
    *force-populate* rs.prefer post-construction (because some RoleSpec
    constructors in segment.py do not accept prefer=...).
    """
    quantity, unit, kind, opk = semantic
    op_chain = [p for p in opk.split("|") if p] if opk else []

    prefer = {
        "sensor": sensor,
        "quantity": quantity,
        "unit": (unit or None),
        "kind": (kind or None),
        "op_chain": op_chain,
    }

    # 1) Try direct prefer (if supported)
    try:
        rs = RoleSpecCls(role=role, prefer=prefer)
    except TypeError:
        # 2) Fall back to minimal constructor
        rs = RoleSpecCls(role=role)
    return rs


def make_event_browser_widget_for_loader(
    schema: dict,
    events_df: pd.DataFrame,
    *,
    session_loader: Callable[[str], dict],
    session_key_col: str = "session_id",
    default_quantities: Sequence[str] = ("disp", "vel"),
    default_pre_s: float = 0.8,
    default_post_s: float = 0.8,
):
    """
    Same widget, but session is selected in the UI and loaded lazily via session_loader(session_id)->session dict.
    The loaded session must include: {"df": DataFrame, "meta": {"signals": ...}, ...}
    """
    if events_df is None or len(events_df) == 0:
        raise ValueError("events_df is empty")

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
        rows=min(8, max(3, len(all_sessions))),
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
        options=["All"],   # will be replaced dynamically once registry is available
        value="All",
        description="Sensor:",
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
        session = _get_session(str(ev_row[session_key_col]))
        return _get_registry(session.get("meta") or {})

    def _filtered_events() -> pd.DataFrame:
        scope = list(map(str, _coerce_list(w_sessions.value)))
        if not scope:
            return events_df.iloc[0:0]

        sub = events_df[events_df[session_key_col].astype(str).isin(scope)].copy()

        # Apply event type filter
        if w_event_type.value:
            sub = sub[sub[et_col].astype(str) == str(w_event_type.value)].copy()

        # Apply sensor filter ONLY if scope is unambiguous
        sel_sensor = w_sensor.value
        if sel_sensor and str(sel_sensor) != "All" and len(scope) == 1:
            sess = _get_session(scope[0])
            registry = _get_registry(sess.get("meta") or {})

            sel_sensor = str(sel_sensor).strip()
            mask = []
            for _, r in sub.iterrows():
                col = r.get("signal_col", None)
                if not isinstance(col, str) or not col.strip():
                    mask.append(False)
                    continue
                info = registry.get(col.strip())
                mask.append(isinstance(info, dict) and info.get("sensor") == sel_sensor)

            sub = sub.loc[pd.Series(mask, index=sub.index)].copy()

        return sub


    def _rebuild_event_type(*_):
        scope = set(map(str, _coerce_list(w_sessions.value)))
        if not scope:
            w_event_type.options = []
            w_event_type.value = None
            w_event.options = []
            w_event.value = None
            _update_nav_buttons()
            return

        # scope-only (no event type / sensor filtering here)
        sub = events_df[events_df[session_key_col].astype(str).isin(scope)].copy()
        etypes = sorted(sub[et_col].dropna().astype(str).unique().tolist())

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
            w_sensor.options = ["All"]
            w_sensor.value = "All"
            return

        # Pick a stable session for sensor universe (first in scope)
        sess = _get_session(scope[0])
        registry = _get_registry(sess.get("meta") or {})

        sensors = sorted({
            info.get("sensor")
            for info in registry.values()
            if isinstance(info, dict) and isinstance(info.get("sensor"), str)
        })
        sensors = [s for s in sensors if s and s != "active"]

        current = w_sensor.value
        opts = ["All"] + sensors
        w_sensor.options = opts
        w_sensor.value = current if current in opts else "All"

    def _rebuild_events(*_):
        sub = _filtered_events()
        if len(sub) == 0:
            w_event.options = []
            return

        # Show only events that belong to the scope; include session_id in label now
        labels = []
        for _, r in sub.sort_values(["session_id", "trigger_time_s"]).iterrows():
            labels.append(
                f"{r['session_id']} :: {r['event_id']}  |  t={float(r['trigger_time_s']):.3f}s"
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

        # Parse session_id and event_id from label
        left, rest = str(w_event.value).split(" :: ", 1)
        event_id = rest.split("  |  ", 1)[0].strip()
        session_id = left.strip()

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
        inferred = _infer_event_sensor(registry, ev_row) if ev_row is not None else None
        active_sensor = None if (w_sensor.value in (None, "", "All")) else str(w_sensor.value).strip()
        if not active_sensor and inferred:
            active_sensor = inferred  # implicit “auto” when All
        active_sensor = active_sensor.strip() if isinstance(active_sensor, str) else None

        # --- Remember current selection (before we replace options) ---
        prev = tuple(w_signals.value) if w_signals.value is not None else ()

        opts = _registry_signal_options_for_sensor(registry, active_sensor)
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
        
        def _set_ylim_zero_at_frac(ax_i, data_min, data_max, frac0, pad=0.05):
            """
            Choose y-lims [ymin, ymax] that contain [data_min, data_max] and place y=0 at frac0.
            frac0 in (0,1): 0 at ymin + frac0*(ymax-ymin).
            """
            # If data range is degenerate, make a small span
            if not np.isfinite(data_min) or not np.isfinite(data_max):
                return
            if data_min == data_max:
                span = abs(data_min) if data_min != 0 else 1.0
                data_min -= 0.5 * span
                data_max += 0.5 * span

            # Required range so that ymin <= data_min and ymax >= data_max
            req = []
            if data_min < 0:
                req.append((-data_min) / max(frac0, 1e-6))
            if data_max > 0:
                req.append((data_max) / max(1.0 - frac0, 1e-6))
            if not req:
                # All data on one side of 0; still make a reasonable range
                req.append(max(abs(data_min), abs(data_max), 1.0))

            rng = max(req) * (1.0 + pad)
            ymin = -frac0 * rng
            ymax = (1.0 - frac0) * rng
            ax_i.set_ylim(ymin, ymax)

        with out:
            clear_output(wait=True)

            ev_row_df, ev_row = _selected_event_row()
            if ev_row is None:
                print("No event selected.")
                return

            # Loader key (unique across runs) + display id (friendly)
            event_session_key = str(ev_row[session_key_col])
            event_session_id  = str(ev_row["session_id"])
            session = _get_session(event_session_key)

            registry = _get_registry(session.get("meta") or {})

            # Determine active sensor for the event
            inferred = _infer_event_sensor(registry, ev_row) if ev_row is not None else None
            sensor = None if (w_sensor.value in (None, "", "All")) else str(w_sensor.value).strip()
            if not sensor and inferred:
                sensor = inferred  # implicit “auto” when All


            # Build RoleSpecs from selected semantic tuples
            role_specs = []
            for semantic in _coerce_list(w_signals.value):
                qty = str(semantic[0])
                role_specs.append(
                    _role_spec_from_semantic_tuple(RoleSpec, role=qty, sensor=sensor, semantic=semantic)
                )

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
                _set_ylim_zero_at_frac(ax_i, float(y_all.min()), float(y_all.max()), frac0, pad=0.05)


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

    display(ui)
    _rebuild_event_type()
    _render()

    return {
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
    }

def make_event_browser_rebuilder(
    *,
    sel: Dict[str, Any],
    schema: dict,
    out: Optional[W.Output] = None,
    session_key_col: str = "session_key",
    **kwargs,
) -> Dict[str, Any]:
    """
    Rebuild helper for the event browser widget (recreates the widget on selector change).
    """

    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None}

    def rebuild() -> None:
        store = sel["store"]
        key_to_ref = sel["get_key_to_ref"]()
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
                **kwargs,
            )

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
