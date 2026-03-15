from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import ipywidgets as W
import pandas as pd
from IPython.display import display

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.library.aggregations import (
    AggregationStore,
    CanonicalAggregationStore,
    build_aggregation_catalog_df,
)
from bodaqs_analysis.session_notes import build_session_catalog_df
from bodaqs_analysis.widgets.entity_scope import (
    resolve_event_schema_sets_for_sessions,
    validate_registry_policy_for_sessions,
)
from bodaqs_analysis.widgets.loaders import make_session_loader


def _format_session_label(row: Mapping[str, Any], *, show_ids: bool) -> str:
    created_at = str(row.get("created_at") or "").strip()
    run_id = str(row.get("run_id") or "").strip()
    session_id = str(row.get("session_id") or "").strip()
    run_desc = str(row.get("run_description") or "").strip()
    session_desc = str(row.get("session_description") or "").strip()

    if show_ids:
        run_part = f"run_id={run_id} | run_desc={run_desc or '(none)'}"
        session_part = f"session_id={session_id} | session_desc={session_desc or '(none)'}"
    else:
        run_part = run_desc or run_id
        session_part = session_desc or session_id

    parts = [p for p in (created_at, run_part, session_part) if p]
    return " | ".join(parts)


def _format_aggregation_label(row: Mapping[str, Any]) -> str:
    title = str(row.get("title") or "").strip()
    key = str(row.get("aggregation_key") or "").strip()
    n_members = int(row.get("n_members") or 0)
    missing = int(row.get("missing_member_count") or 0)
    suffix = f" | missing={missing}" if missing else ""
    return f"{title or key} ({n_members}){suffix}"


def make_aggregation_library_manager(
    *,
    artifacts_dir: str | Path = "artifacts",
    aggregation_store: AggregationStore | None = None,
    rows: int = 12,
    show_ids_default: bool = False,
    auto_display: bool = False,
) -> dict[str, Any]:
    artifact_store = ArtifactStore(Path(artifacts_dir))
    agg_store = aggregation_store or CanonicalAggregationStore(artifact_store=artifact_store)
    try:
        agg_store.load()
    except Exception:
        pass

    w_filter = W.Text(
        value="",
        description="Filter",
        placeholder="Search run/session ids or descriptions",
        layout=W.Layout(width="520px"),
    )
    show_ids_cb = W.Checkbox(
        value=bool(show_ids_default),
        description="Show run and session IDs",
        indent=False,
        layout=W.Layout(width="260px"),
    )
    sessions_sel = W.SelectMultiple(
        options=[],
        value=(),
        rows=rows,
        description="Sessions",
        layout=W.Layout(width="860px"),
    )

    w_agg_list = W.Dropdown(
        options=[("(No saved aggregations)", "")],
        value="",
        description="Saved agg",
        layout=W.Layout(width="520px"),
    )
    w_title = W.Text(value="", description="Title", layout=W.Layout(width="520px"))
    w_note = W.Text(value="", description="Note", layout=W.Layout(width="520px"))
    w_registry_policy = W.Dropdown(
        options=[("union", "union"), ("intersection", "intersection"), ("strict", "strict")],
        value="union",
        description="Registry",
        layout=W.Layout(width="220px"),
    )
    w_schema_policy = W.Dropdown(
        options=[("union", "union"), ("intersection", "intersection"), ("strict", "strict")],
        value="union",
        description="Schema",
        layout=W.Layout(width="220px"),
    )

    b_refresh = W.Button(description="Refresh")
    b_create = W.Button(description="Create")
    b_update = W.Button(description="Update")
    b_delete = W.Button(description="Delete")
    b_load = W.Button(description="Load")

    out = W.Output(layout=W.Layout(width="1280px"))

    state: Dict[str, Any] = {
        "catalog_df": pd.DataFrame(),
        "label_to_session_key": {},
        "session_key_to_label": {},
        "catalog_agg_df": pd.DataFrame(),
        "updating": False,
    }

    def _set_status(lines: Sequence[str]) -> None:
        with out:
            out.clear_output()
            for line in lines:
                print(line)

    def _refresh_session_options(*_) -> None:
        catalog_df = build_session_catalog_df(artifacts_dir=artifact_store.root)
        state["catalog_df"] = catalog_df

        label_to_session_key: dict[str, str] = {}
        session_key_to_label: dict[str, str] = {}
        options: list[str] = []
        filter_text = str(w_filter.value or "").strip().lower()
        label_counts: dict[str, int] = {}

        for _, row in catalog_df.iterrows():
            session_key = str(row["session_key"])
            label = _format_session_label(row.to_dict(), show_ids=bool(show_ids_cb.value))
            search_blob = f"{label} {session_key}".lower()
            if filter_text and filter_text not in search_blob:
                continue
            n = label_counts.get(label, 0) + 1
            label_counts[label] = n
            unique_label = label if n == 1 else f"{label} [#{n}]"
            options.append(unique_label)
            label_to_session_key[unique_label] = session_key
            session_key_to_label[session_key] = unique_label

        prev = tuple(map(str, sessions_sel.value or ()))
        sessions_sel.options = options
        sessions_sel.value = tuple(lbl for lbl in prev if lbl in label_to_session_key)
        state["label_to_session_key"] = label_to_session_key
        state["session_key_to_label"] = session_key_to_label

    def _refresh_aggregation_options(*_) -> None:
        try:
            agg_store.load()
        except Exception:
            pass

        catalog_agg_df = build_aggregation_catalog_df(
            aggregation_store=agg_store,
            scope="canonical" if isinstance(agg_store, CanonicalAggregationStore) else "custom",
            artifact_store=artifact_store,
        )
        state["catalog_agg_df"] = catalog_agg_df

        if catalog_agg_df.empty:
            w_agg_list.options = [("(No saved aggregations)", "")]
            w_agg_list.value = ""
            return

        opts = [
            (_format_aggregation_label(row), str(row["aggregation_key"]))
            for _, row in catalog_agg_df.iterrows()
        ]
        prev = str(w_agg_list.value or "")
        valid = {value for _, value in opts}
        w_agg_list.options = opts
        w_agg_list.value = prev if prev in valid else opts[0][1]

    def _refresh_all(*_) -> None:
        _refresh_session_options()
        _refresh_aggregation_options()

    def _selected_session_keys() -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        for label in sessions_sel.value:
            session_key = state["label_to_session_key"].get(str(label))
            if not session_key or session_key in seen:
                continue
            seen.add(session_key)
            selected.append(session_key)
        return selected

    def _validate_members(
        *,
        member_session_keys: Sequence[str],
        registry_policy: str,
        event_schema_policy: str,
    ) -> None:
        if not member_session_keys:
            raise ValueError("Select at least one physical session before saving an aggregation.")

        key_to_ref = {
            str(row["session_key"]): (str(row["run_id"]), str(row["session_id"]))
            for _, row in state["catalog_df"].iterrows()
        }
        missing = [session_key for session_key in member_session_keys if session_key not in key_to_ref]
        if missing:
            raise ValueError(f"Aggregation includes unknown sessions: {', '.join(missing[:3])}")

        session_loader = make_session_loader(store=artifact_store, key_to_ref=key_to_ref)
        validate_registry_policy_for_sessions(
            session_keys=member_session_keys,
            session_loader=session_loader,
            policy=registry_policy,
        )
        resolve_event_schema_sets_for_sessions(
            session_keys=member_session_keys,
            key_to_ref=key_to_ref,
            store=artifact_store,
            session_loader=session_loader,
            policy=event_schema_policy,
        )

    def _on_select(change):
        if state["updating"]:
            return
        key = str(change.get("new") or "")
        if not key:
            return
        agg = agg_store.get(key)
        if agg is None:
            return

        state["updating"] = True
        try:
            w_title.value = agg.title
            w_note.value = agg.note or ""
            w_registry_policy.value = agg.registry_policy
            w_schema_policy.value = agg.event_schema_policy
        finally:
            state["updating"] = False

    def _on_load(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to load."])
            return
        agg = agg_store.get(key)
        if agg is None:
            _set_status([f"Aggregation not found: {key}"])
            return
        labels = [
            state["session_key_to_label"][session_key]
            for session_key in agg.member_session_keys
            if session_key in state["session_key_to_label"]
        ]
        sessions_sel.value = tuple(labels)
        _set_status([f"Loaded {len(labels)} sessions from {key}."])

    def _on_create(_):
        members = _selected_session_keys()
        title = str(w_title.value or "").strip()
        note = str(w_note.value or "").strip() or None
        registry_policy = str(w_registry_policy.value or "union")
        schema_policy = str(w_schema_policy.value or "union")
        try:
            _validate_members(
                member_session_keys=members,
                registry_policy=registry_policy,
                event_schema_policy=schema_policy,
            )
            created = agg_store.create(
                title=(title or f"Aggregation ({len(members)} sessions)"),
                member_session_keys=members,
                registry_policy=registry_policy,
                event_schema_policy=schema_policy,
                note=note,
            )
            agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Created aggregation {created.aggregation_key}."])
        except Exception as exc:
            _set_status([f"Create failed: {exc}"])

    def _on_update(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to update."])
            return
        members = _selected_session_keys()
        title = str(w_title.value or "").strip()
        note = str(w_note.value or "").strip() or None
        registry_policy = str(w_registry_policy.value or "union")
        schema_policy = str(w_schema_policy.value or "union")
        if not title:
            _set_status(["Aggregation title is required for update."])
            return
        try:
            _validate_members(
                member_session_keys=members,
                registry_policy=registry_policy,
                event_schema_policy=schema_policy,
            )
            agg_store.update(
                key,
                patch={
                    "title": title,
                    "member_session_keys": members,
                    "registry_policy": registry_policy,
                    "event_schema_policy": schema_policy,
                    "note": note,
                },
            )
            agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Updated aggregation {key}."])
        except Exception as exc:
            _set_status([f"Update failed: {exc}"])

    def _on_delete(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to delete."])
            return
        try:
            deleted = agg_store.delete(key)
            if deleted:
                agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Deleted aggregation {key}." if deleted else "Aggregation not found."])
        except Exception as exc:
            _set_status([f"Delete failed: {exc}"])

    w_filter.observe(_refresh_session_options, names="value")
    show_ids_cb.observe(_refresh_session_options, names="value")
    w_agg_list.observe(_on_select, names="value")
    b_refresh.on_click(_refresh_all)
    b_load.on_click(_on_load)
    b_create.on_click(_on_create)
    b_update.on_click(_on_update)
    b_delete.on_click(_on_delete)

    _refresh_all()

    ui = W.VBox(
        [
            W.HBox([w_filter, show_ids_cb, b_refresh]),
            sessions_sel,
            W.VBox(
                [
                    W.HTML("<b>Canonical Aggregations</b>"),
                    W.HBox([w_agg_list, b_load]),
                    W.HBox([w_title, w_note]),
                    W.HBox([w_registry_policy, w_schema_policy]),
                    W.HBox([b_create, b_update, b_delete]),
                ]
            ),
            out,
        ]
    )

    handle = {
        "ui": ui,
        "store": artifact_store,
        "aggregation_store": agg_store,
        "sessions_sel": sessions_sel,
        "show_ids_cb": show_ids_cb,
        "out": out,
        "refresh": _refresh_all,
        "controls": {
            "filter": w_filter,
            "saved_aggregations": w_agg_list,
            "title": w_title,
            "note": w_note,
            "registry_policy": w_registry_policy,
            "event_schema_policy": w_schema_policy,
            "load": b_load,
            "create": b_create,
            "update": b_update,
            "delete": b_delete,
        },
        "state": state,
    }
    if auto_display:
        display(ui)
    return handle
