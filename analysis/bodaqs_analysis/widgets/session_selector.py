# bodaqs_analysis/widgets/session_selector.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import ipywidgets as W
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore, list_runs, list_sessions
from bodaqs_analysis.widgets.contracts import (
    MutableKeyToRef,
    RebuildFn,
    RefreshHandle,
    RUN_ID_COL,
    SESSION_ID_COL,
    SESSION_KEY_COL,
    SessionKey,
    SessionSelection,
    SessionSelectorHandle,
)


def make_session_key(run_id: str, session_id: str) -> SessionKey:
    return f"{run_id}::{session_id}"


def make_session_selector(
    *,
    artifacts_dir: str | Path = "artifacts",
    default_run_id: str = "__ALL__",
    select_first_by_default: bool = True,
    rows: int = 12,
) -> SessionSelectorHandle:
    """
    Returns dict with:
      ui: widgets container (display this)
      store: ArtifactStore
      run_dd, sessions_sel, out: widgets
      get_selected: callable -> list[{"run_id","session_id"}]
      get_key_to_ref: callable -> dict[session_key]->(run_id, session_id)
      get_events_index_df: callable -> pd.DataFrame with columns session_key, run_id, session_id
    """
    store = ArtifactStore(Path(artifacts_dir))

    def _read_json_safe(path: Path) -> dict[str, Any]:
        try:
            return store.read_json(path)
        except Exception:
            return {}

    def _get_run_meta(run_id: str) -> dict[str, str]:
        m = _read_json_safe(store.path_run_manifest(run_id))
        return {
            "created_at": str(m.get("created_at") or ""),
            "description": str(m.get("description") or "").strip(),
        }

    def _get_session_desc(run_id: str, session_id: str) -> str:
        m = _read_json_safe(store.path_session_manifest(run_id, session_id))
        d = m.get("description")
        return str(d).strip() if d is not None else ""

    def _build_session_index(
        selected_run_id: str | None,
    ) -> tuple[list[str], dict[str, SessionSelection]]:
        run_ids = list_runs(store) if selected_run_id in (None, "__ALL__") else [selected_run_id]

        rows_ = []
        for rid in run_ids:
            run_meta = _get_run_meta(rid)
            created_at = run_meta["created_at"]
            rdesc = run_meta["description"] or "(no description)"

            for sid in list_sessions(store, rid):
                sdesc = _get_session_desc(rid, sid) or "(no description)"
                label = f"{created_at} | {rdesc} | {sid} | {sdesc}"
                rows_.append((label, rid, sid))

        label_counts: dict[str, int] = {}
        options: list[str] = []
        label_to_sel: dict[str, SessionSelection] = {}

        for label, rid, sid in rows_:
            n = label_counts.get(label, 0) + 1
            label_counts[label] = n
            unique_label = label if n == 1 else f"{label} [#{n}]"
            options.append(unique_label)
            label_to_sel[unique_label] = {"run_id": rid, "session_id": sid}

        return options, label_to_sel

    # ---- Widgets
    run_options = [("__All runs__", "__ALL__")] + [(rid, rid) for rid in list_runs(store)]
    run_dd = W.Dropdown(
        options=run_options,
        value=default_run_id if default_run_id in dict(run_options).values() or default_run_id == "__ALL__" else "__ALL__",
        description="Run",
        layout=W.Layout(width="800px"),
    )

    sessions_sel = W.SelectMultiple(
        options=[],
        value=(),
        rows=rows,
        description="Sessions",
        layout=W.Layout(width="800px"),
    )

    out = W.Output()
    
    # state (closed over)
    _label_to_sel: dict[str, SessionSelection] = {}
    _selected: list[SessionSelection] = []
    _key_to_ref: MutableKeyToRef = {}
    _events_index_df = pd.DataFrame(columns=[SESSION_KEY_COL, RUN_ID_COL, SESSION_ID_COL])

    def _refresh_sessions(*_):
        nonlocal _label_to_sel
        options, _label_to_sel = _build_session_index(run_dd.value)
        sessions_sel.options = options
        if select_first_by_default and options:
            sessions_sel.value = (options[0],)
        else:
            sessions_sel.value = ()
        _update_selected()

    def _update_selected(*_):
        nonlocal _selected, _key_to_ref, _events_index_df
        _selected = [_label_to_sel[lbl] for lbl in sessions_sel.value]

        _key_to_ref = {
            make_session_key(s["run_id"], s["session_id"]): (s["run_id"], s["session_id"])
            for s in _selected
        }

        _events_index_df = pd.DataFrame(
            [
                {SESSION_KEY_COL: k, RUN_ID_COL: rid, SESSION_ID_COL: sid}
                for k, (rid, sid) in _key_to_ref.items()
            ]
        )

#        with out:
#            out.clear_output()
#            print("SELECTED =")
#            for s in _selected:
#                print(" ", s)

    run_dd.observe(_refresh_sessions, names="value")
    sessions_sel.observe(_update_selected, names="value")

    _refresh_sessions()

    ui = W.VBox([W.HBox([run_dd]), sessions_sel, out])

    def get_selected() -> list[SessionSelection]:
        return list(_selected)

    def get_key_to_ref() -> MutableKeyToRef:
        return dict(_key_to_ref)

    def get_events_index_df() -> pd.DataFrame:
        return _events_index_df.copy()

    return {
        "ui": ui,
        "store": store,
        "run_dd": run_dd,
        "sessions_sel": sessions_sel,
        "out": out,
        "get_selected": get_selected,
        "get_key_to_ref": get_key_to_ref,
        "get_events_index_df": get_events_index_df,
    }

def attach_refresh(
    sel: Mapping[str, Any],
    rebuild_fns: list[RebuildFn],
) -> RefreshHandle:
    """
    Attach selector observers and call rebuild functions immediately when run/sessions change.
    (No threads; reliable in Jupyter.)
    """
    run_dd = sel.get("run_dd")
    sessions_sel = sel.get("sessions_sel")
    if run_dd is None or sessions_sel is None:
        raise ValueError("selector handle must include 'run_dd' and 'sessions_sel'")

    in_fire = False  # re-entrancy guard

    def _fire(*_):
        nonlocal in_fire
        if in_fire:
            return
        in_fire = True
        try:
            for fn in rebuild_fns:
                try:
                    fn()
                except Exception as e:
                    print(f"[attach_refresh] rebuild failed: {e!r}")
        finally:
            in_fire = False

    run_dd.observe(_fire, names="value")
    sessions_sel.observe(_fire, names="value")

    def detach():
        try:
            run_dd.unobserve(_fire, names="value")
        except Exception:
            pass
        try:
            sessions_sel.unobserve(_fire, names="value")
        except Exception:
            pass

    return {"detach": detach, "trigger": _fire}
