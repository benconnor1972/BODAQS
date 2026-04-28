# -*- coding: utf-8 -*-
"""
BODAQS signal-sample histogram widget (loader-based).

Public APIs:
    make_signal_histogram_widget_for_loader(...)
    make_signal_histogram_rebuilder(...)
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import ipywidgets as W
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import clear_output, display

from bodaqs_analysis.widgets.contracts import (
    RebuilderHandle,
    RegistryPolicy,
    SESSION_ID_COL,
    SESSION_KEY_COL,
    SessionLoader,
    SessionSelectorHandle,
    WidgetHandle,
    entity_snapshot_from_handle,
    selection_snapshot_from_handle,
)
from bodaqs_analysis.widgets.histogram_core import (
    compute_trimmed_quantile_metrics,
    format_metric,
    parse_optional_float,
    plot_hist_or_cdf,
)
from bodaqs_analysis.widgets.loaders import make_session_loader
from bodaqs_analysis.widgets.registry_scope import validate_registry_policy
from bodaqs_analysis.widgets.signal_histogram_scope import (
    resolve_scope_signal_options,
    signal_values,
)


# -------------------------
# Widget
# -------------------------


def make_signal_histogram_widget_for_loader(
    events_df: pd.DataFrame,
    *,
    session_loader: SessionLoader,
    session_key_col: str = SESSION_KEY_COL,
    entity_to_members: Optional[Dict[str, List[str]]] = None,
    entity_labels: Optional[Dict[str, str]] = None,
    registry_policy: RegistryPolicy = "union",
    default_bins: int = 50,
    max_bins: int = 500,
    auto_display: bool = False,
    loader_key_resolver: Optional[Callable[[str], str]] = None,
) -> WidgetHandle:
    """
    Signal histogram / CDF widget using session_loader.

    Entities are discovered from events_df[session_key_col].
    Signals are resolved per-session from each session registry/df and then
    combined by registry_policy: "union", "intersection", or "strict".
    """
    if session_key_col not in events_df.columns:
        raise ValueError(f"events_df must contain {session_key_col!r} column")
    validate_registry_policy(registry_policy)

    entity_ids = sorted(events_df[session_key_col].dropna().astype(str).unique().tolist())
    if not entity_ids:
        raise ValueError("No entities available in events_df for signal histogram")

    entity_to_members = {
        str(k): list(map(str, v))
        for k, v in dict(entity_to_members or {}).items()
    }
    for entity_id in entity_ids:
        entity_to_members.setdefault(str(entity_id), [str(entity_id)])
    entity_labels = {str(k): str(v) for k, v in dict(entity_labels or {}).items()}

    session_cache: Dict[str, Dict[str, Any]] = {}

    def _resolve_loader_key(session_id: str) -> str:
        if loader_key_resolver is None:
            return str(session_id)
        return str(loader_key_resolver(str(session_id)))

    def _get_session(session_id: str) -> Dict[str, Any]:
        sid = str(session_id)
        if sid not in session_cache:
            sess = session_loader(_resolve_loader_key(sid))
            if not isinstance(sess, dict):
                raise ValueError("session_loader must return a dict-like object")
            if "df" not in sess:
                raise ValueError("session_loader result missing required key 'df'")
            if not isinstance(sess["df"], pd.DataFrame):
                raise ValueError("session_loader result['df'] must be a pandas DataFrame")
            session_cache[sid] = sess
        return session_cache[sid]

    def _resolve_signals_for_scope(scope_sessions: list[str]) -> tuple[list[str], dict[str, list[str]]]:
        resolved = resolve_scope_signal_options(
            scope_sessions=scope_sessions,
            get_session=_get_session,
            registry_policy=registry_policy,
            primary_only=bool(w_primary_only.value),
        )
        return resolved.options, resolved.by_session

    # --- UI ---
    sessions_label = W.Label("Entities:")
    w_sessions = W.SelectMultiple(
        options=entity_ids,
        value=tuple(entity_ids),
        description="",
        rows=min(8, max(3, len(entity_ids))),
        layout=W.Layout(width="450px"),
    )

    signals_label = W.Label("Signals:")
    w_signals = W.SelectMultiple(
        options=[],
        value=(),
        description="",
        rows=min(8, max(3, len(entity_ids))),
        layout=W.Layout(width="450px"),
    )
    w_primary_only = W.Checkbox(value=True, description="Primary signals only")

    w_bins = W.BoundedIntText(value=default_bins, min=1, max=max_bins, description="Bins:", layout=W.Layout(width="150px"))
    w_cdf = W.Checkbox(value=False, description="CDF")
    w_norm = W.Checkbox(value=True, description="Normalize")
    w_dropna = W.Checkbox(value=True, description="Drop NaN/inf")
    w_include_inactive = W.Checkbox(value=False, description="Include inactive")
    w_show_metrics = W.Checkbox(value=False, description="Show metrics")
    w_trim_a = W.Text(
        value="",
        description="Trim cutoff (a):",
        placeholder="blank = no trimming",
        layout=W.Layout(width="240px"),
    )
    w_trim_help = W.HTML("<small>Exclude values &lt; a from metric computation.</small>")
    for w in (w_cdf, w_norm, w_dropna, w_include_inactive, w_show_metrics):
        w.layout = W.Layout(width="auto")

    out = W.Output()

    state: Dict[str, Any] = {
        "signal_policy_error": None,
        "session_signal_cols": {},
        "session_cache": session_cache,
    }

    def _toggle_trim_input(*_):
        enabled = bool(w_show_metrics.value)
        w_trim_a.disabled = not enabled
        w_trim_help.layout = W.Layout(display="block" if enabled else "none")

    def _rebuild_signal_options(*_):
        sel_entities = list(map(str, w_sessions.value or ()))
        prev = list(map(str, w_signals.value or ()))

        if not sel_entities:
            w_signals.options = []
            w_signals.value = ()
            state["signal_policy_error"] = None
            state["session_signal_cols"] = {}
            return

        scope_sessions = sorted(
            {
                sk
                for entity_id in sel_entities
                for sk in entity_to_members.get(str(entity_id), [str(entity_id)])
            }
        )

        try:
            options, by_session = _resolve_signals_for_scope(scope_sessions)
            state["signal_policy_error"] = None
            state["session_signal_cols"] = by_session
        except Exception as exc:
            options = []
            state["signal_policy_error"] = str(exc)
            state["session_signal_cols"] = {}

        w_signals.options = options
        kept = tuple([s for s in prev if s in options])
        if kept:
            w_signals.value = kept
            return

        # Prefer a signal present in all selected entities, so compare mode
        # shows multiple entity series by default.
        common_by_entity: list[set[str]] = []
        for entity_id in sel_entities:
            members = entity_to_members.get(str(entity_id), [str(entity_id)])
            entity_signal_set: set[str] = set()
            for sk in members:
                entity_signal_set.update(map(str, by_session.get(str(sk), [])))
            if entity_signal_set:
                common_by_entity.append(entity_signal_set)

        common_options: set[str] = set(options)
        if common_by_entity:
            common_options = common_options.intersection(*common_by_entity)

        preferred = [opt for opt in options if opt in common_options]
        w_signals.value = (tuple(preferred[:1]) if preferred else (tuple(options[:1]) if options else ()))

    _toggle_trim_input()

    # --- render ---
    def _render(*_):
        with out:
            clear_output(wait=True)

            signal_policy_error = state.get("signal_policy_error")
            if signal_policy_error:
                print(signal_policy_error)
                return

            sel_entities = list(map(str, w_sessions.value or ()))
            sel_signals = list(map(str, w_signals.value or ()))

            if not sel_entities or not sel_signals:
                print("Select at least one entity and one signal.")
                return

            series: List[Tuple[str, np.ndarray]] = []

            def get_vals_for_entity(entity_id: str, sig: str) -> np.ndarray:
                parts = []
                for sid in entity_to_members.get(str(entity_id), [str(entity_id)]):
                    session = _get_session(str(sid))
                    parts.append(
                        signal_values(
                            session["df"],
                            sig,
                            dropna=bool(w_dropna.value),
                            include_inactive=bool(w_include_inactive.value),
                        )
                    )
                return np.concatenate(parts) if parts else np.array([], dtype=float)

            for entity_id in sel_entities:
                display_entity = entity_labels.get(str(entity_id), str(entity_id))
                for sig in sel_signals:
                    series.append((f"{display_entity} | {sig}", get_vals_for_entity(entity_id, sig)))

            fig, ax = plt.subplots(figsize=(8.3, 4.2))
            any_plotted = False
            no_data_series: list[str] = []

            for name, vals in series:
                clean = np.asarray(vals, dtype=float)
                clean = clean[np.isfinite(clean)]
                if clean.size == 0:
                    no_data_series.append(str(name))
                    continue

                any_plotted = True
                plot_hist_or_cdf(
                    ax,
                    clean,
                    int(w_bins.value),
                    cdf=bool(w_cdf.value),
                    norm=bool(w_norm.value),
                    label=name,
                )

            ax.set_title("Signal sample distribution")
            ax.set_xlabel("Signal value")
            ax.set_ylabel(
                "Cumulative proportion"
                if w_cdf.value
                else ("Proportion" if w_norm.value else "Count")
            )
            ax.grid(True, alpha=0.3)

            if len(series) > 1:
                ax.legend(fontsize=9)

            if not any_plotted:
                ax.text(
                    0.5,
                    0.5,
                    "No numeric values after filtering",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
                ax.set_axis_off()

            plt.show()

            if no_data_series:
                print("No numeric values for:", ", ".join(no_data_series))

            if w_show_metrics.value:
                a = parse_optional_float(w_trim_a.value)
                rows: List[Dict[str, str]] = []

                for name, vals in series:
                    metrics = compute_trimmed_quantile_metrics(vals, a)
                    row = {
                        "Group": str(name),
                        "n_trim / n_total": f"{metrics.n_trim} / {metrics.n_total}",
                    }

                    if metrics.insufficient:
                        row.update(
                            {
                                "Q25": "insufficient data",
                                "Q50": "insufficient data",
                                "Q75": "insufficient data",
                                "IQR": "insufficient data",
                                "Q90": "insufficient data",
                                "Q95": "insufficient data",
                                "skew_Q": "insufficient data",
                            }
                        )
                    else:
                        row.update(
                            {
                                "Q25": format_metric(metrics.q25),
                                "Q50": format_metric(metrics.q50),
                                "Q75": format_metric(metrics.q75),
                                "IQR": format_metric(metrics.iqr),
                                "Q90": format_metric(metrics.q90),
                                "Q95": format_metric(metrics.q95),
                                "skew_Q": format_metric(metrics.skew_q),
                            }
                        )
                    rows.append(row)

                trim_label = "none" if a is None else format_metric(a)
                print(f"Trimmed quantile metrics (a={trim_label})")
                display(pd.DataFrame(rows))

    def _on_scope_change(*_):
        _rebuild_signal_options()
        _render()

    for w in (
        w_signals,
        w_bins,
        w_cdf,
        w_norm,
        w_dropna,
        w_include_inactive,
        w_show_metrics,
        w_trim_a,
    ):
        w.observe(_render, names="value")

    w_sessions.observe(_on_scope_change, names="value")
    w_primary_only.observe(_on_scope_change, names="value")
    w_show_metrics.observe(_toggle_trim_input, names="value")

    controls = W.VBox(
        [
            W.HBox(
                [w_bins, w_cdf, w_norm, w_dropna, w_include_inactive, w_show_metrics, w_trim_a],
                layout=W.Layout(
                    justify_content="flex-start",
                    align_items="center",
                    gap="6px",
                    flex_flow="row wrap",
                ),
            ),
            w_trim_help,
            W.HBox(
                [
                    W.VBox([sessions_label, w_sessions]),
                    W.VBox([signals_label, w_primary_only, w_signals]),
                ]
            ),
        ]
    )

    root = W.VBox([controls, out])

    def refresh() -> None:
        _rebuild_signal_options()
        _render()

    refresh()

    if auto_display:
        display(root)

    return {
        "root": root,
        "out": out,
        "entity_ids": entity_ids,
        "session_ids": entity_ids,  # backward-compatible alias
        "signal_cols": list(map(str, w_signals.options)),
        "state": state,
        "controls": {
            "sessions": w_sessions,
            "signals": w_signals,
            "primary_only": w_primary_only,
            "bins": w_bins,
            "cdf": w_cdf,
            "normalize": w_norm,
            "dropna": w_dropna,
            "include_inactive": w_include_inactive,
            "show_metrics": w_show_metrics,
            "trim_cutoff": w_trim_a,
        },
        "refresh": refresh,
    }


def make_signal_histogram_rebuilder(
    *,
    sel: SessionSelectorHandle,
    out: Optional[W.Output] = None,
    session_key_col: str = SESSION_KEY_COL,
    **kwargs,
) -> RebuilderHandle:
    """
    Rebuild helper for the signal histogram widget (recreates the widget on selector change).
    """
    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None}

    def rebuild() -> None:
        snapshot = selection_snapshot_from_handle(sel)
        entity_snapshot = entity_snapshot_from_handle(sel)
        store = sel["store"]
        key_to_ref = snapshot.key_to_ref
        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

        loader_key_resolver: Optional[Callable[[str], str]] = None
        entity_ids = [str(e.entity_key) for e in entity_snapshot.selected_entities]
        if session_key_col == SESSION_KEY_COL:
            session_values = entity_ids
        elif session_key_col == SESSION_ID_COL:
            sid_to_key: Dict[str, str] = {}
            for sk, (_rid, sid) in entity_snapshot.key_to_ref.items():
                sid_s = str(sid)
                if sid_s in sid_to_key and sid_to_key[sid_s] != sk:
                    raise ValueError(
                        "session_id values are not unique across selected runs; "
                        "use session_key-based wiring instead."
                    )
                sid_to_key[sid_s] = str(sk)
            session_values = sorted(sid_to_key.keys())
            loader_key_resolver = lambda sid, m=sid_to_key: m[str(sid)]
        else:
            session_values = [str(k) for k in key_to_ref.keys()]

        events_df_sel = pd.DataFrame({session_key_col: session_values})

        with out:
            clear_output(wait=True)
            state["handles"] = make_signal_histogram_widget_for_loader(
                events_df_sel,
                session_loader=session_loader,
                session_key_col=session_key_col,
                entity_to_members=entity_snapshot.entity_to_effective_members,
                entity_labels={
                    str(entity.entity_key): str(entity.label)
                    for entity in entity_snapshot.selected_entities
                },
                loader_key_resolver=loader_key_resolver,
                auto_display=False,
                **kwargs,
            )
            h = state["handles"]
            root = h.get("root") or h.get("ui")
            if root is not None:
                display(root)

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
