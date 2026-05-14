from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import ipywidgets as W
import pandas as pd

from ..io_fit import find_overlapping_fit_files, load_fit_bindings, select_fit_candidate, upsert_fit_binding


def _session_absolute_bounds(session: Mapping[str, Any]) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
    meta = session.get("meta", {})
    source = session.get("source", {})

    anchor = None
    if isinstance(meta, Mapping):
        anchor = meta.get("t0_datetime")
    if anchor is None and isinstance(source, Mapping):
        anchor = source.get("created_local")
    if not isinstance(anchor, str) or not anchor.strip():
        return None

    df = session.get("df")
    if not isinstance(df, pd.DataFrame) or "time_s" not in df.columns:
        return None

    t = pd.to_numeric(df["time_s"], errors="coerce").dropna()
    if t.empty:
        return None

    start = pd.Timestamp(anchor)
    end = start + pd.to_timedelta(float(t.max()), unit="s")
    return start, end


def _normalize_fit_import(fit_import: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    base = {
        "enabled": False,
        "fit_dir": None,
        "field_allowlist": None,
        "ambiguity_policy": "require_binding",
        "partial_overlap": "allow",
        "bindings_path": None,
    }
    if isinstance(fit_import, Mapping):
        base.update(dict(fit_import))
    return base


def build_fit_candidate_summary(
    sessions_by_id: Mapping[str, Mapping[str, Any]],
    *,
    fit_import: Optional[Mapping[str, Any]],
) -> pd.DataFrame:
    cfg = _normalize_fit_import(fit_import)
    rows: list[dict[str, Any]] = []

    if not bool(cfg.get("enabled")):
        for session_id in sorted(map(str, sessions_by_id.keys())):
            rows.append(
                {
                    "session_id": session_id,
                    "status": "disabled",
                    "n_candidates": 0,
                    "selected_file": None,
                    "candidate_files": [],
                    "reason": "FIT import disabled",
                }
            )
        return pd.DataFrame(rows)

    fit_dir = cfg.get("fit_dir")
    if not isinstance(fit_dir, str) or not fit_dir.strip():
        for session_id in sorted(map(str, sessions_by_id.keys())):
            rows.append(
                {
                    "session_id": session_id,
                    "status": "invalid_config",
                    "n_candidates": 0,
                    "selected_file": None,
                    "candidate_files": [],
                    "reason": "fit_dir missing",
                }
            )
        return pd.DataFrame(rows)

    for session_id, session in sorted(sessions_by_id.items()):
        bounds = _session_absolute_bounds(session)
        if bounds is None:
            rows.append(
                {
                    "session_id": str(session_id),
                    "status": "missing_anchor",
                    "n_candidates": 0,
                    "selected_file": None,
                    "candidate_files": [],
                    "reason": "Session lacks absolute time anchor",
                }
            )
            continue

        session_start, session_end = bounds
        candidates = find_overlapping_fit_files(
            fit_dir=fit_dir,
            session_start_datetime=session_start.isoformat(),
            session_end_datetime=session_end.isoformat(),
            field_allowlist=cfg.get("field_allowlist"),
            partial_overlap=str(cfg.get("partial_overlap", "allow")),
        )

        selected_file = None
        status = "no_match"
        reason = "No overlapping FIT files"
        if candidates:
            status = "auto_match" if len(candidates) == 1 else "ambiguous"
            reason = f"{len(candidates)} overlapping FIT file(s)"
            try:
                selected = select_fit_candidate(
                    session_id=str(session_id),
                    csv_path=session.get("source", {}).get("path") if isinstance(session.get("source"), Mapping) else None,
                    csv_sha256=session.get("source", {}).get("sha256") if isinstance(session.get("source"), Mapping) else None,
                    candidates=candidates,
                    ambiguity_policy=str(cfg.get("ambiguity_policy", "require_binding")),
                    bindings_path=cfg.get("bindings_path"),
                )
                if selected is not None:
                    selected_file = selected.get("filename")
                    status = "bound_match" if len(candidates) > 1 else "auto_match"
                    reason = f"Selected {selected_file}"
            except Exception as exc:
                reason = str(exc)

        rows.append(
            {
                "session_id": str(session_id),
                "status": status,
                "n_candidates": int(len(candidates)),
                "selected_file": selected_file,
                "candidate_files": [str(c.get("filename", c.get("path"))) for c in candidates],
                "reason": reason,
            }
        )

    return pd.DataFrame(rows)


def make_fit_bindings_editor(
    sessions_by_id: Mapping[str, Mapping[str, Any]],
    *,
    fit_import: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    cfg = _normalize_fit_import(fit_import)
    out = W.Output(layout=W.Layout(border="1px solid #ddd", padding="8px"))
    summary_html = W.HTML("")
    session_dd = W.Dropdown(description="Session", layout=W.Layout(width="420px"))
    candidate_dd = W.Dropdown(description="FIT", layout=W.Layout(width="100%"))
    refresh_btn = W.Button(description="Refresh", button_style="info", icon="refresh")
    save_btn = W.Button(description="Save Binding", button_style="success", icon="save")

    state: Dict[str, Any] = {
        "summary_df": pd.DataFrame(),
        "candidates_by_session": {},
    }

    def _refresh(*_args: Any) -> None:
        df = build_fit_candidate_summary(sessions_by_id, fit_import=cfg)
        state["summary_df"] = df

        ambiguous = df[df["status"].isin(["ambiguous", "bound_match", "auto_match"])]
        session_ids = ambiguous["session_id"].astype(str).tolist()
        session_dd.options = session_ids or ["(none)"]
        session_dd.value = session_ids[0] if session_ids else "(none)"

        status_counts = df["status"].value_counts().to_dict() if not df.empty else {}
        summary_html.value = (
            "<b>FIT Binding Summary</b><br>"
            + ", ".join(f"{k}: {v}" for k, v in sorted(status_counts.items()))
        )
        _refresh_candidates()

    def _refresh_candidates(*_args: Any) -> None:
        sid = session_dd.value
        if sid in (None, "(none)"):
            candidate_dd.options = []
            return

        session = sessions_by_id.get(str(sid))
        if not isinstance(session, Mapping):
            candidate_dd.options = []
            return

        bounds = _session_absolute_bounds(session)
        if bounds is None:
            candidate_dd.options = []
            return

        session_start, session_end = bounds
        candidates = find_overlapping_fit_files(
            fit_dir=str(cfg.get("fit_dir")),
            session_start_datetime=session_start.isoformat(),
            session_end_datetime=session_end.isoformat(),
            field_allowlist=cfg.get("field_allowlist"),
            partial_overlap=str(cfg.get("partial_overlap", "allow")),
        )
        state["candidates_by_session"][str(sid)] = candidates
        candidate_dd.options = [
            (f"{c.get('filename')} ({c.get('overlap_s', 0.0):.1f}s overlap)", c.get("path"))
            for c in candidates
        ]

        existing = None
        bindings_path = cfg.get("bindings_path")
        if isinstance(bindings_path, str) and bindings_path.strip() and Path(bindings_path).exists():
            for entry in load_fit_bindings(bindings_path):
                if entry.get("session_id") == str(sid):
                    existing = entry.get("fit_file")
                    break
        if existing:
            for _label, value in candidate_dd.options:
                if value == existing:
                    candidate_dd.value = value
                    break

    def _save_binding(*_args: Any) -> None:
        sid = session_dd.value
        fit_path = candidate_dd.value
        bindings_path = cfg.get("bindings_path")
        if sid in (None, "(none)") or not fit_path:
            with out:
                out.clear_output()
                print("No session/candidate selected.")
            return
        if not isinstance(bindings_path, str) or not bindings_path.strip():
            with out:
                out.clear_output()
                print("fit_import.bindings_path is not configured.")
            return

        session = sessions_by_id[str(sid)]
        source = session.get("source", {})
        entry = upsert_fit_binding(
            bindings_path,
            session_id=str(sid),
            csv_path=source.get("path") if isinstance(source, Mapping) else None,
            csv_sha256=source.get("sha256") if isinstance(source, Mapping) else None,
            fit_file=str(fit_path),
        )
        with out:
            out.clear_output()
            print(f"Saved FIT binding for {sid}: {entry['fit_file']}")
        _refresh()

    session_dd.observe(_refresh_candidates, names="value")
    refresh_btn.on_click(_refresh)
    save_btn.on_click(_save_binding)

    ui = W.VBox(
        [
            summary_html,
            W.HBox([session_dd, refresh_btn, save_btn]),
            candidate_dd,
            out,
        ],
        layout=W.Layout(width="100%"),
    )

    _refresh()
    return {
        "ui": ui,
        "refresh": _refresh,
        "get_summary_df": lambda: state["summary_df"].copy(),
    }
