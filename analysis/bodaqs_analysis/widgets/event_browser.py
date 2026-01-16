# in bodaqs_analysis/widgets/event_browser.py

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as W
from IPython.display import display, clear_output

from bodaqs_analysis.segment import extract_segments, SegmentRequest, WindowSpec, RoleSpec

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

    # 3) FORCE populate prefer, regardless of constructor signature
    if hasattr(rs, "prefer"):
        try:
            # replace entirely to avoid stale empty dicts
            rs.prefer = dict(prefer)
        except Exception:
            # last resort: update in place
            try:
                rs.prefer.update(prefer)
            except Exception:
                pass

    # 4) Optional: also set explicit attrs if they exist on this RoleSpec version
    for k, v in prefer.items():
        if hasattr(rs, k):
            try:
                setattr(rs, k, v)
            except Exception:
                pass

    return rs


def make_event_browser_widget_for_loader(
    schema: dict,
    events_df: pd.DataFrame,
    *,
    session_loader: Callable[[str], dict],
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

    _require_cols(events_df, ("session_id", "event_id", "signal_col", "trigger_time_s"), name="events_df")
    et_col = _event_type_col(events_df)
    _require_cols(events_df, (et_col,), name="events_df")

    # ---- Controls (NOTE: session selector is now multi-select + active session)
    all_sessions = sorted(events_df["session_id"].dropna().astype(str).unique().tolist())

    # multi-select for "scope"
    w_sessions = W.SelectMultiple(
        options=all_sessions,
        value=(all_sessions[0],) if all_sessions else (),
        description="Sessions:",
        layout=W.Layout(width="380px", height="120px"),
    )

    # single active session used for extraction (can be changed by the user)
    w_active_session = W.Dropdown(
        options=all_sessions,
        value=all_sessions[0] if all_sessions else None,
        description="Active:",
        layout=W.Layout(width="380px"),
    )

    w_event_type = W.Dropdown(options=[], description="Event type:", layout=W.Layout(width="380px"))
    w_event = W.Dropdown(options=[], description="Event:", layout=W.Layout(width="520px"))

    w_pre = W.FloatText(value=float(default_pre_s), description="Pre (s):", layout=W.Layout(width="160px"))
    w_post = W.FloatText(value=float(default_post_s), description="Post (s):", layout=W.Layout(width="160px"))

    # Sensor + signals are derived from the *active session's* registry
    w_sensor = W.Dropdown(options=[""], value="", description="Sensor:", layout=W.Layout(width="320px"))
    w_auto_sensor = W.Checkbox(value=True, description="Auto (from event)")

    w_signals = W.SelectMultiple(
        options=[],
        value=(),
        description="Signals:",
        layout=W.Layout(width="520px", height="140px"),
    )

    w_show_secondary = W.Checkbox(value=True, description="Show secondary triggers")
    w_show_grid = W.Checkbox(value=True, description="Grid")
    w_show_stats = W.Checkbox(value=True, description="Stats")
    w_show_resolve = W.Checkbox(value=False, description="Resolve info")

    out = W.Output()

    # ---- Session cache (avoid re-loading repeatedly)
    _session_cache: Dict[str, dict] = {}

    def _get_session(session_id: str) -> dict:
        sid = str(session_id)
        if sid not in _session_cache:
            _session_cache[sid] = session_loader(sid)
        return _session_cache[sid]

    def _active_session_id() -> Optional[str]:
        sid = w_active_session.value
        if sid is None:
            return None
        sid = str(sid)
        return sid if sid else None

    def _active_registry() -> dict:
        sid = _active_session_id()
        if not sid:
            raise ValueError("No active session selected")
        sess = _get_session(sid)
        return _get_registry(sess.get("meta") or {})

    def _filtered_events() -> pd.DataFrame:
        # Scope by selected sessions + event type
        scope = set(map(str, _coerce_list(w_sessions.value)))
        if not scope:
            return events_df.iloc[0:0]

        sub = events_df[events_df["session_id"].astype(str).isin(scope)].copy()
        if w_event_type.value:
            sub = sub[sub[et_col].astype(str) == str(w_event_type.value)].copy()
        return sub

    def _rebuild_active_session_options(*_):
        # When scope changes, update active session dropdown to only those sessions
        scope = list(map(str, _coerce_list(w_sessions.value)))
        w_active_session.options = scope
        if scope:
            if w_active_session.value not in scope:
                w_active_session.value = scope[0]
        else:
            w_active_session.value = None
        _rebuild_event_type()

    def _rebuild_event_type(*_):
        sub = _filtered_events()
        etypes = sorted(sub[et_col].dropna().astype(str).unique().tolist())
        w_event_type.options = etypes
        if etypes:
            if w_event_type.value not in etypes:
                w_event_type.value = etypes[0]
        else:
            w_event_type.value = None
        _rebuild_events()

    def _rebuild_events(*_):
        sub = _filtered_events()
        if len(sub) == 0:
            w_event.options = []
            return

        # Show only events that belong to the scope; include session_id in label now
        labels = []
        for _, r in sub.sort_values(["session_id", "trigger_time_s"]).iterrows():
            labels.append(
                f"{r['session_id']} :: {r['event_id']}  |  t={float(r['trigger_time_s']):.3f}s  |  {r.get('signal_col','')}"
            )
        w_event.options = labels
        if labels:
            w_event.value = labels[0]

        _rebuild_sensor_and_signals()

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

    def _rebuild_sensor_and_signals(*_):
        # Update sensor list from active session's registry
        try:
            registry = _active_registry()
        except Exception:
            w_sensor.options = [""]
            w_sensor.value = ""
            w_signals.options = []
            w_signals.value = ()
            return

        sensors = sorted({info.get("sensor") for info in registry.values() if isinstance(info, dict) and info.get("sensor")})
        sensors = [s for s in sensors if isinstance(s, str) and s.strip()]
        w_sensor.options = (sensors or [""])
        if sensors and (w_sensor.value not in sensors):
            w_sensor.value = sensors[0]
        if not sensors:
            w_sensor.value = ""

        # Auto sensor from event anchor when enabled
        ev_df, ev_row = _selected_event_row()
        inferred = _infer_event_sensor(registry, ev_row) if ev_row is not None else None
        active_sensor = inferred if (w_auto_sensor.value and inferred) else (w_sensor.value or None)
        active_sensor = active_sensor.strip() if isinstance(active_sensor, str) else None

        opts = _registry_signal_options_for_sensor(registry, active_sensor)
        w_signals.options = opts

        # Default by quantity
        desired = set(_coerce_list(default_quantities))
        selected = [key for (_, key) in opts if key[0] in desired]
        w_signals.value = tuple(selected) if selected else ()

    def _render(*_):
        with out:
            clear_output(wait=True)

            ev_row_df, ev_row = _selected_event_row()
            if ev_row is None:
                print("No event selected.")
                return

            # Use the event's session_id for extraction (this is the big win vs passing `session` in)
            event_session_id = str(ev_row["session_id"])
            session = _get_session(event_session_id)
            registry = _get_registry(session.get("meta") or {})

            # Determine active sensor for the event
            inferred = _infer_event_sensor(registry, ev_row)
            sensor = inferred if (w_auto_sensor.value and inferred) else (w_sensor.value or None)
            sensor = sensor.strip() if isinstance(sensor, str) else None

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

            fig, ax = plt.subplots(figsize=(9.5, 4.2))
            for name, y in series:
                ax.plot(t_rel, y, label=name)

            ax.axvline(0.0, linestyle="--", linewidth=1.0)
            ax.text(0.0, 0.98, "trigger", transform=ax.get_xaxis_transform(), ha="left", va="top")

            if w_show_secondary.value:
                t0 = float(ev_row["trigger_time_s"])
                for col, t_abs in _secondary_time_cols(ev_row):
                    tsec = float(t_abs) - t0
                    ax.axvline(tsec, linestyle=":", linewidth=1.0)
                    ax.text(tsec, 0.98, col.replace("_time_s", ""), transform=ax.get_xaxis_transform(),
                            rotation=90, ha="right", va="top", fontsize=8)

            ax.set_title(f"Event browser — {event_session_id} | {ev_row[et_col]} | {ev_row['event_id']} | {sensor or ''}".strip())
            ax.set_xlabel("t_rel_s (s)")
            ax.set_ylabel("value")

            if w_show_grid.value:
                ax.grid(True, which="both", axis="both", alpha=0.3)
            ax.legend(loc="best")
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
                print("  active session:", _active_session_id())
                print("  event_type_col:", et_col)
                print("  event type:", ev_row.get(et_col))
                print("  event signal_col:", ev_row.get("signal_col"))
                print("  inferred sensor:", inferred)
                print("  sensor used:", sensor)
                print("  selected quantities:", [k[0] for k in _coerce_list(w_signals.value)])
                print("\nResolved spec:")
                print("  role_to_col:", spec.get("role_to_col"))

    # ---- Wire up
    w_sessions.observe(_rebuild_active_session_options, names="value")
    w_active_session.observe(_rebuild_sensor_and_signals, names="value")
    w_event_type.observe(_rebuild_events, names="value")
    w_event.observe(_rebuild_sensor_and_signals, names="value")
    w_auto_sensor.observe(_rebuild_sensor_and_signals, names="value")
    w_sensor.observe(_rebuild_sensor_and_signals, names="value")

    for w in (w_event, w_pre, w_post, w_signals, w_show_secondary, w_show_grid, w_show_stats, w_show_resolve):
        w.observe(_render, names="value")

    # ---- Init
    _rebuild_active_session_options()
    ui = W.VBox(
        [
            W.HBox([w_sessions, W.VBox([w_active_session, w_event_type])]),
            W.HBox([w_auto_sensor, w_sensor]),
            W.HBox([w_event]),
            W.HBox([w_pre, w_post, w_show_secondary, w_show_grid, w_show_stats, w_show_resolve]),
            W.HBox([w_signals]),
            out,
        ]
    )

    display(ui)
    _render()

    return {
        "ui": ui,
        "out": out,
        "controls": {
            "sessions": w_sessions,
            "active_session": w_active_session,
            "event_type": w_event_type,
            "sensor": w_sensor,
            "auto_sensor": w_auto_sensor,
            "event": w_event,
            "signals": w_signals,
        },
        "cache": _session_cache,
    }
