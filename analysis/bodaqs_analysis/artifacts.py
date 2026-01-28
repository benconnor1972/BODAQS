from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, List

import pandas as pd
import shutil
import hashlib

@dataclass(frozen=True)
class ArtifactStore:
    root: Path = Path("artifacts")

    def run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def session_dir(self, run_id: str, session_id: str) -> Path:
        return self.run_dir(run_id) / "sessions" / session_id

    def ensure_dir(self, p: Path) -> None:
        p.mkdir(parents=True, exist_ok=True)

    # ---------- JSON ----------
    def write_json(self, path: Path, obj: Dict[str, Any]) -> None:
        self.ensure_dir(path.parent)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def read_json(self, path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    # ---------- Parquet ----------
    def write_df(self, path: Path, df: pd.DataFrame, *, compression: str = "zstd") -> None:
        self.ensure_dir(path.parent)
        df.to_parquet(path, index=False, compression=compression)

    def read_df(self, path: Path, *, columns: Optional[list[str]] = None) -> pd.DataFrame:
        return pd.read_parquet(path, columns=columns)

    # ---------- Canonical locations ----------
    def path_run_manifest(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"

    def path_session_manifest(self, run_id: str, session_id: str) -> Path:
        return self.session_dir(run_id, session_id) / "manifest.json"

    def path_session_df(self, run_id: str, session_id: str) -> Path:
        return self.session_dir(run_id, session_id) / "session" / "df.parquet"

    def path_session_meta(self, run_id: str, session_id: str) -> Path:
        return self.session_dir(run_id, session_id) / "session" / "meta.json"

    def path_events_df(self, run_id: str, session_id: str, event_type: str) -> Path:
        return self.session_dir(run_id, session_id) / "events" / event_type / "events.parquet"

    def path_metrics_df(self, run_id: str, session_id: str, event_type: str) -> Path:
        return self.session_dir(run_id, session_id) / "metrics" / event_type / "metrics.parquet"

def make_run_id(*, tz_label: str = "AWST", git_sha: Optional[str] = None) -> str:
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    base = f"run_{ts}_{tz_label}"
    return f"{base}__{git_sha}" if git_sha else base


# --- Discovery helpers ---

def list_runs(store: "ArtifactStore") -> List[str]:
    """
    Return run_ids available under artifacts/runs/, sorted newest-first if names are timestamped.
    """
    runs_dir = store.root / "runs"
    if not runs_dir.exists():
        return []
    out: List[str] = []
    for p in runs_dir.iterdir():
        if p.is_dir():
            out.append(p.name)
    # If your run_ids are like run_YYYY-MM-DD..., reverse sort gives newest first
    return sorted(out, reverse=True)


def list_sessions(store: "ArtifactStore", run_id: str) -> List[str]:
    """
    Return session_ids available under artifacts/runs/<run_id>/sessions/, sorted.
    """
    sessions_dir = store.run_dir(run_id) / "sessions"
    if not sessions_dir.exists():
        return []
    out: List[str] = []
    for p in sessions_dir.iterdir():
        if p.is_dir():
            out.append(p.name)
    return sorted(out)

def list_all_sessions(store) -> List[Dict[str, Any]]:
    """
    Returns a list of entries:
      {run_id, session_id, run_description, session_description, created_at}
    Safe if manifests are missing fields.
    """
    out: List[Dict[str, Any]] = []
    for run_id in list_runs(store):
        run_manifest = {}
        try:
            run_manifest = store.read_json(store.path_run_manifest(run_id))
        except Exception:
            pass

        run_desc = run_manifest.get("description")
        created_at = run_manifest.get("created_at")

        for session_id in list_sessions(store, run_id):
            sess_manifest = {}
            try:
                sess_manifest = store.read_json(store.path_session_manifest(run_id, session_id))
            except Exception:
                pass

            out.append({
                "run_id": run_id,
                "session_id": session_id,
                "created_at": created_at,
                "run_description": run_desc,
                "session_description": sess_manifest.get("description"),
            })
    return out

def list_event_types(store: "ArtifactStore", run_id: str, session_id: str) -> List[str]:
    """
    Return event types present under events/ for the given session.
    Only returns directories that contain events.parquet.
    """
    events_dir = store.session_dir(run_id, session_id) / "events"
    if not events_dir.exists():
        return []

    out: List[str] = []
    for p in events_dir.iterdir():
        if not p.is_dir():
            continue
        if (p / "events.parquet").exists():
            out.append(p.name)

    return sorted(out)


def list_metric_event_types(store: "ArtifactStore", run_id: str, session_id: str) -> List[str]:
    """
    Return event types present under metrics/ for the given session.
    Only returns directories that contain metrics.parquet.
    """
    metrics_dir = store.session_dir(run_id, session_id) / "metrics"
    if not metrics_dir.exists():
        return []

    out: List[str] = []
    for p in metrics_dir.iterdir():
        if not p.is_dir():
            continue
        if (p / "metrics.parquet").exists():
            out.append(p.name)

    return sorted(out)

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



def save_session_artifacts(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    session_df: pd.DataFrame,
    session_meta: Mapping[str, Any],
) -> None:
    store.write_df(store.path_session_df(run_id, session_id), session_df)
    store.write_json(store.path_session_meta(run_id, session_id), dict(session_meta))

def load_session_artifacts(store: ArtifactStore, *, run_id: str, session_id: str) -> Dict[str, Any]:
    df = store.read_df(store.path_session_df(run_id, session_id))
    meta = store.read_json(store.path_session_meta(run_id, session_id))
    return {"df": df, "meta": meta}

def write_run_manifest(
    store: ArtifactStore,
    *,
    run_id: str,
    session_ids: list[str],
    git_sha: Optional[str] = None,
    timezone_label: str = "AWST",
    description: str | None = None,
    pipeline_config: Optional[Mapping[str, Any]] = None,
) -> None:
    obj: Dict[str, Any] = {
        "artifact_layout_version": "0.2",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "timezone": timezone_label,
        "description": description,
        "sessions": session_ids,
    }
    if git_sha:
        obj["git_sha"] = git_sha
    if pipeline_config:
        obj["pipeline_config"] = dict(pipeline_config)

    store.write_json(store.path_run_manifest(run_id), obj)

def write_session_manifest(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    description: str | None = None,
    contracts: Optional[Mapping[str, str]] = None,
    source: Optional[Mapping[str, Any]] = None,
    summary: Optional[Mapping[str, Any]] = None,
) -> None:
    obj: Dict[str, Any] = {
        "session_id": session_id,
        "description": description,  # always present (may be None)
    }
    if contracts:
        obj["contracts"] = dict(contracts)
    if source:
        obj["source"] = dict(source)
    if summary:
        obj["summary"] = dict(summary)

    store.write_json(store.path_session_manifest(run_id, session_id), obj)


def _freeze_schema_yaml_for_event_type(*, run_id: str, session_id: str, event_type: str) -> None:
    """
    Copy the exact schema YAML file used into the canonical artifact location.
    This preserves comments/ordering and avoids YAML re-serialization issues.
    """
    dst = store.session_dir(run_id, session_id) / "events" / event_type / "schema.yaml"
    store.ensure_dir(dst.parent)
    shutil.copy2(SCHEMA_PATH, dst)

def _safe_folder_name(x) -> str:
    s = "null" if x is None else str(x)
    # Keep folder names stable + filesystem-safe
    return "".join(ch if (ch.isalnum() or ch in ("_", "-")) else "_" for ch in s)

def write_events_partitioned_by_schema_id(
    *,
    store,
    run_id: str,
    session_id: str,
    events_df: pd.DataFrame,
    schema_path: Path | str,
) -> list[str]:
    """
    Write events artifacts partitioned by schema_id.

    Produces:
      sessions/<session_id>/events/<schema_id>/events.parquet
      sessions/<session_id>/events/<schema_id>/schema.yaml

    Returns list of schema_ids written.
    """
    if not isinstance(events_df, pd.DataFrame) or events_df.empty:
        return []

    required = {"session_id", "event_id", "schema_id"}
    missing = required - set(events_df.columns)
    if missing:
        raise ValueError(f"events_df missing required columns: {sorted(missing)}")

    schema_ids_written: list[str] = []

    for sid_key, g0 in events_df.groupby("schema_id", dropna=False):
        schema_id = _safe_folder_name(sid_key)

        g = g0.reset_index(drop=True)
        out_path = store.path_events_df(run_id, session_id, schema_id)
        store.write_df(out_path, g)

        # Freeze the exact YAML file used (preserve comments/order)
        dst = store.session_dir(run_id, session_id) / "events" / schema_id / "schema.yaml"
        store.ensure_dir(dst.parent)
        shutil.copy2(str(schema_path), dst)

        schema_ids_written.append(schema_id)

    return sorted(set(schema_ids_written))


def write_metrics_partitioned_by_schema_id(
    *,
    store,
    run_id: str,
    session_id: str,
    metrics_df: pd.DataFrame,
) -> list[str]:
    """
    Write metrics artifacts partitioned by schema_id.

    Produces:
      sessions/<session_id>/metrics/<schema_id>/metrics.parquet

    Returns list of schema_ids written.
    """
    if not isinstance(metrics_df, pd.DataFrame) or metrics_df.empty:
        return []

    required = {"session_id", "event_id", "schema_id"}
    missing = required - set(metrics_df.columns)
    if missing:
        raise ValueError(f"metrics_df missing required columns: {sorted(missing)}")

    schema_ids_written: list[str] = []

    for sid_key, g0 in metrics_df.groupby("schema_id", dropna=False):
        schema_id = _safe_folder_name(sid_key)

        g = g0.reset_index(drop=True)
        out_path = store.path_metrics_df(run_id, session_id, schema_id)
        store.write_df(out_path, g)

        schema_ids_written.append(schema_id)

    return sorted(set(schema_ids_written))


def copy_raw_csv_to_source(
    *,
    store,
    run_id: str,
    session_id: str,
    csv_path: Path,
) -> str:
    """
    Copy the raw input CSV into the canonical source/ directory
    and compute its SHA-256 hash.

    Returns
    -------
    sha256 : str
        Hex digest of the copied file.
    """
    dst = store.session_dir(run_id, session_id) / "source" / "input.csv"
    store.ensure_dir(dst.parent)

    shutil.copy2(csv_path, dst)

    sha256 = _sha256_file(dst)

    # Write hash sidecar
    hash_path = dst.with_suffix(".sha256")
    hash_path.write_text(sha256 + "\n", encoding="utf-8")

    return sha256

def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """
    Compute SHA-256 hash of a file in a streaming manner.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()
    
class ArtifactOverwriteError(FileExistsError):
    """Raised when an artifact write would overwrite existing outputs."""


def ensure_run_is_new(
    store,
    *,
    run_id: str,
    force: bool = False,
) -> None:
    """
    Run-level overwrite guard.

    If the run directory exists and is non-empty, raise unless force=True.
    """
    run_dir = store.run_dir(run_id)
    if not run_dir.exists():
        return

    # If empty, allow (e.g., created but nothing written yet)
    try:
        next(run_dir.iterdir())
        non_empty = True
    except StopIteration:
        non_empty = False

    if non_empty and not force:
        raise ArtifactOverwriteError(
            f"Run directory already exists and is non-empty: {run_dir}. "
            f"Refusing to overwrite. Pass force=True to allow."
        )


def ensure_session_is_new(
    store,
    *,
    run_id: str,
    session_id: str,
    force: bool = False,
) -> None:
    """
    Session-level overwrite guard.

    If key session outputs already exist for this session, raise unless force=True.

    We check the canonical session dataframe path as the primary indicator.
    You can extend this to include meta/events/metrics if desired.
    """
    df_path = store.path_session_df(run_id, session_id)
    if df_path.exists() and not force:
        raise ArtifactOverwriteError(
            f"Session artifacts already exist for run_id={run_id!r}, session_id={session_id!r} "
            f"({df_path}). Refusing to overwrite. Pass force=True to allow."
        )
        
def update_manifest_description(path: Path, description: str | None) -> None:
    obj = store.read_json(path)
    obj["description"] = description
    store.write_json(path, obj)
    
def set_run_description(
    store,
    *,
    run_id: str,
    description: Optional[str],
) -> None:
    """
    Update the run manifest's description field in-place.
    Leaves all other fields untouched.
    """
    if description is not None and not str(description).strip():
        description = None

    path = store.path_run_manifest(run_id)
    obj = store.read_json(path)
    obj["description"] = description
    store.write_json(path, obj)


def set_session_description(
    store,
    *,
    run_id: str,
    session_id: str,
    description: Optional[str],
) -> None:
    """
    Update a session manifest's description field in-place.
    Leaves all other fields untouched.
    """
    if description is not None and not str(description).strip():
        description = None

    path = store.path_session_manifest(run_id, session_id)
    obj = store.read_json(path)
    obj["description"] = description
    store.write_json(path, obj)