# bodaqs_analysis/widgets/loaders.py
from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd

from bodaqs_analysis.artifacts import load_session_artifacts


def make_session_loader(*, store, key_to_ref: Dict[str, Tuple[str, str]]):
    """
    Returns session_loader(session_key) -> {"df": ..., "meta": ...}

    This is the standard "consumer" contract used by widgets.
    """
    def session_loader(session_key: str) -> dict:
        run_id, session_id = key_to_ref[str(session_key)]
        return load_session_artifacts(store, run_id=run_id, session_id=session_id)
    return session_loader


def load_all_events_for_selected(store, *, key_to_ref: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """
    Loads and concatenates events across all selected sessions, adding:
      - session_key (run_id::session_id)
      - run_id, session_id
    Assumes your artifacts are partitioned by schema_id under:
      events/<schema_id>/events.parquet
    """
    dfs = []

    for session_key, (run_id, session_id) in key_to_ref.items():
        # Discover schema_id folders by scanning events dir
        events_root = store.session_dir(run_id, session_id) / "events"
        if not events_root.exists():
            continue

        for schema_dir in events_root.iterdir():
            if not schema_dir.is_dir():
                continue
            p = schema_dir / "events.parquet"
            if not p.exists():
                continue

            df = store.read_df(p)
            if df.empty:
                continue

            # Add cross-run identity columns
            df = df.copy()
            df["session_key"] = session_key
            df["run_id"] = run_id
            df["session_id"] = session_id  # keep for convenience
            dfs.append(df)

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    
def load_all_metrics_for_selected(store, *, key_to_ref: Dict[str, Tuple[str, str]]) -> pd.DataFrame:
    """
    Load + concat metrics for the selected sessions.

    Looks for:
        <session_dir>/metrics/<schema_id>/metrics.parquet

    Adds identity columns:
        session_key, run_id, session_id
    """
    dfs = []

    for session_key, (run_id, session_id) in key_to_ref.items():
        metrics_root = store.session_dir(run_id, session_id) / "metrics"
        if not metrics_root.exists():
            continue

        for schema_dir in metrics_root.iterdir():
            if not schema_dir.is_dir():
                continue

            p = schema_dir / "metrics.parquet"
            if not p.exists():
                continue

            df = store.read_df(p)
            if df is None or df.empty:
                continue

            df = df.copy()
            df["session_key"] = session_key
            df["run_id"] = run_id
            df["session_id"] = session_id
            dfs.append(df)

    return pd.concat(dfs, ignore_index=True, sort=False) if dfs else pd.DataFrame()
