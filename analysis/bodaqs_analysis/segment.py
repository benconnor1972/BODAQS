"""
BODAQS Segment Extractor (skeleton)

Purpose
-------
Extract aligned sample windows ("segments") around detected events, using:
- df timebase contract: numeric, monotonic df["time_s"]
- event table contract: start/trigger/end fields (idx + time_s)
- signal registry: session["meta"]["signals"] mapping column -> semantics
- schema-level segment_defaults (optional) + runtime overrides

This module is intentionally:
- independent of detection (consumes events_df)
- independent of metrics (produces SegmentBundle intermediate)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


# -------------------------
# Types / Contracts
# -------------------------

AnchorField = Literal[
    "start_time_s",
    "trigger_time_s",
    "end_time_s",
    "start_idx",
    "trigger_idx",
    "end_idx",
]

PadMode = Literal["nan", "edge", "drop"]  # edge = clamp indices + pad (future: edge-fill)
GridMode = Literal["native", "resample"]


@dataclass(frozen=True)
class WindowSpec:
    mode: Literal["time", "samples"] = "time"
    pre_s: float = 0.0
    post_s: float = 0.0
    pre_n: int = 0
    post_n: int = 0


@dataclass(frozen=True)
class OutputSpec:
    pad: PadMode = "nan"
    include_time_s: bool = True
    include_t_rel_s: bool = True
    include_primary_signal: bool = True  # include event.signal_col as role="primary"
    dtype: Any = np.float32


@dataclass(frozen=True)
class GridSpec:
    mode: GridMode = "native"
    dt_s: Optional[float] = None  # required for resample
    # future: interpolation method, anti-alias, etc.


@dataclass(frozen=True)
class RoleSpec:
    role: str
    prefer: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentDefaults:
    # Defaults that can be attached to schema per event (optional)
    anchor: AnchorField = "trigger_time_s"
    window: WindowSpec = field(default_factory=WindowSpec)
    roles: Tuple[RoleSpec, ...] = field(default_factory=tuple)
    grid: GridSpec = field(default_factory=GridSpec)


@dataclass(frozen=True)
class SegmentRequest:
    """
    Runtime request. Typically you select events (filter) then optionally override schema defaults.
    """
    # Selector
    event_name: Optional[str] = None
    schema_id: Optional[str] = None
    tags_any: Optional[Sequence[str]] = None

    # Overrides (optional)
    anchor: Optional[AnchorField] = None
    window: Optional[WindowSpec] = None
    roles: Optional[Sequence[RoleSpec]] = None
    grid: Optional[GridSpec] = None
    output: OutputSpec = field(default_factory=OutputSpec)


# SegmentBundle: returned intermediate
# - events: filtered events used
# - segments: per-row extraction metadata (indices, validity)
# - data: role -> (n_seg, n_samples) arrays (+ time arrays)
# - qc: summary
SegmentBundle = Dict[str, Any]


# -------------------------
# Public API
# -------------------------

def extract_segments(
    df: pd.DataFrame,
    events: pd.DataFrame,
    *,
    meta: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
    request: Optional[SegmentRequest] = None,
) -> SegmentBundle:
    """
    Extract aligned windows around events.

    Parameters
    ----------
    df:
        Session dataframe, must contain numeric monotonic 'time_s'.
    events:
        Detected events table per your contract (must include start/trigger/end idx/time fields).
    meta:
        Session meta dict, must include meta["signals"] registry mapping df column -> semantics.
    schema:
        Event schema dict (optional). If provided, schema defaults are used (segment_defaults).
    request:
        SegmentRequest selecting events & overriding schema defaults.

    Returns
    -------
    SegmentBundle dict:
        {
          "spec": {...resolved...},
          "events": events_df,
          "segments": segments_df,
          "data": {role: array, "time_s": array?, "t_rel_s": array?},
          "qc": {...}
        }
    """
    _validate_df_timebase(df)

    req = request or SegmentRequest()
    events_sel = _filter_events(events, req)
    
    #debug
    print("events total:", len(events))
    print("events schema_id counts:\n", events["schema_id"].value_counts())
    print("request:", req)
    events_sel = _filter_events(events, req)
    print("events selected:", len(events_sel))
    print("selected schema_id unique:", sorted(events_sel["schema_id"].dropna().unique().tolist()))
    print("selected event_name unique:", sorted(events_sel["event_name"].dropna().unique().tolist())[:5])
    #debug


    # Resolve defaults per-event_name (or schema_id) from schema, then apply request overrides.
    resolved = _resolve_effective_spec(schema, events_sel, req)

    #debug
    print("resolved anchor:", resolved["anchor"])
    print("resolved window:", resolved["window"])
    print("resolved grid:", resolved["grid"])
    print("resolved roles:", [r.role for r in resolved["roles"]])
    #debug

    # Resolve roles -> df columns (registry aware)
    role_to_col = _resolve_roles_to_columns(
        meta_signals=meta.get("signals", {}),
        roles=resolved["roles"],
        df_columns=df.columns,
        include_primary=(req.output.include_primary_signal),
        events_df=events_sel,
    )

    # Compute extraction indices per event row
    seg_df, n_expected = _compute_segment_indices(
        df_time_s=df["time_s"].to_numpy(),
        events_df=events_sel,
        anchor=resolved["anchor"],
        window=resolved["window"],
        pad=req.output.pad,
        grid=resolved["grid"],
    )

    # Materialize arrays
    data = _materialize_arrays(
        df=df,
        segments_df=seg_df,
        role_to_col=role_to_col,
        n_expected=n_expected,
        output=req.output,
    )

    qc = _qc_summary(seg_df)

    return {
        "spec": {
            "anchor": resolved["anchor"],
            "window": resolved["window"],
            "grid": resolved["grid"],
            "roles": list(resolved["roles"]),
            "role_to_col": role_to_col,
            "output": req.output,
        },
        "events": events_sel,
        "segments": seg_df,
        "data": data,
        "qc": qc,
    }


# -------------------------
# Filtering / Spec resolution
# -------------------------

def _filter_events(events: pd.DataFrame, req: SegmentRequest) -> pd.DataFrame:
    out = events.copy()

    # Prefer schema_id (canonical, stable)
    if req.schema_id is not None and "schema_id" in out.columns:
        out = out[out["schema_id"] == req.schema_id]

    # Fallback to event_name (human label) ONLY if schema_id not supplied
    elif req.event_name is not None and "event_name" in out.columns:
        out = out[out["event_name"] == req.event_name]

    # Optional tags filter (applies after primary selection)
    if req.tags_any and "tags" in out.columns:
        want = set(req.tags_any)

        def _has_any(x: Any) -> bool:
            if x is None or (isinstance(x, float) and np.isnan(x)):  # type: ignore
                return False
            if isinstance(x, str):
                parts = [p.strip() for p in x.split(",") if p.strip()]
                return bool(want.intersection(parts))
            if isinstance(x, (list, tuple, set)):
                return bool(want.intersection(set(x)))
            return False

        out = out[out["tags"].map(_has_any)]

    return out.reset_index(drop=True)



def _resolve_effective_spec(
    schema: Optional[Mapping[str, Any]],
    events_df: pd.DataFrame,
    req: SegmentRequest,
) -> Dict[str, Any]:
    """
    Resolve: schema segment_defaults (optional) + request overrides.
    For v0, we use:
      - one effective spec for the whole selection (assumes homogeneous event types)
    """
    # ---- base defaults ----
    anchor: AnchorField = "trigger_time_s"
    window = WindowSpec(mode="time", pre_s=0.0, post_s=0.0)
    grid = GridSpec(mode="native", dt_s=None)
    roles: List[RoleSpec] = [RoleSpec("disp")]

    # ---- schema-derived defaults (optional) ----
    if schema is not None:
        # Choose schema event key. Prefer schema_id (stable), fallback to event_name (legacy).
        event_key = None

        if "schema_id" in events_df.columns and len(events_df) > 0:
            ids = sorted(set(events_df["schema_id"].dropna().astype(str).tolist()))
            if len(ids) == 1:
                event_key = ids[0]
            elif len(ids) > 1:
                raise ValueError(
                    f"extract_segments v0 expects one schema_id at a time; got {ids}. "
                    "Filter with SegmentRequest(schema_id=...)."
                )

        if event_key is None and "event_name" in events_df.columns and len(events_df) > 0:
            names = sorted(set(events_df["event_name"].dropna().astype(str).tolist()))
            if len(names) == 1:
                event_key = names[0]
            elif len(names) > 1:
                raise ValueError(
                    f"extract_segments v0 expects one event_name at a time; got {names}. "
                    "Filter with SegmentRequest(event_name=...)."
                )

        #debug
        print("event_key:", event_key)
        print("schema keys:", list(schema.keys()))
        #debug

        seg_def = _schema_segment_defaults(schema, event_key)
        if seg_def is not None:
            anchor = seg_def.get("anchor", anchor)  # type: ignore
            w = seg_def.get("window", {})
            if isinstance(w, dict):
                window = WindowSpec(
                    mode="time",
                    pre_s=float(w.get("pre_s", window.pre_s)),
                    post_s=float(w.get("post_s", window.post_s)),
                )
            r = seg_def.get("roles")
            if isinstance(r, list) and r:
                roles = [RoleSpec(role=str(x)) if not isinstance(x, dict)
                         else RoleSpec(role=str(x.get("role")), prefer=dict(x.get("prefer", {})))
                         for x in r]
            g = seg_def.get("grid", {})
            if isinstance(g, dict):
                grid = GridSpec(
                    mode=str(g.get("mode", grid.mode)),  # type: ignore
                    dt_s=g.get("dt_s", grid.dt_s),
                )

    # ---- request overrides ----
    if req.anchor is not None:
        anchor = req.anchor
    if req.window is not None:
        window = req.window
    if req.grid is not None:
        grid = req.grid
    if req.roles is not None:
        roles = list(req.roles)

    # Basic sanity
    if window.mode == "time":
        if window.pre_s < 0 or window.post_s < 0:
            raise ValueError("window pre_s/post_s must be >= 0")
    else:
        if window.pre_n < 0 or window.post_n < 0:
            raise ValueError("window pre_n/post_n must be >= 0")

    return {"anchor": anchor, "window": window, "grid": grid, "roles": tuple(roles)}


def _schema_segment_defaults(schema: Mapping[str, Any], event_key: Optional[str]) -> Optional[Mapping[str, Any]]:
    """
    Supports schemas where schema["events"] is either:
      A) dict keyed by event id/schema_id
      B) list of event dicts containing an 'id' (or 'schema_id') field
    Returns the event's 'segment_defaults' dict if present.
    """
    if not event_key:
        return None

    try:
        events = schema.get("events", None)

        # A) Mapping form: events[event_key]
        if isinstance(events, Mapping):
            ev = events.get(event_key)
            if isinstance(ev, Mapping):
                sd = ev.get("segment_defaults")
                return sd if isinstance(sd, Mapping) else None
            return None

        # B) List form: find dict with matching id/schema_id
        if isinstance(events, list):
            for ev in events:
                if not isinstance(ev, Mapping):
                    continue
                eid = ev.get("id", None)
                if eid is None:
                    eid = ev.get("schema_id", None)
                if isinstance(eid, str) and eid == event_key:
                    sd = ev.get("segment_defaults")
                    return sd if isinstance(sd, Mapping) else None
            return None

        return None
    except Exception:
        return None



# -------------------------
# Registry role resolution
# -------------------------

def _resolve_roles_to_columns(
    *,
    meta_signals: Mapping[str, Any],
    roles: Sequence[RoleSpec],
    df_columns: Iterable[str],
    include_primary: bool,
    events_df: pd.DataFrame,
) -> Dict[str, str]:
    """
    Resolve each role to a concrete df column name using meta["signals"] registry.
    Also optionally includes a role "primary" mapped to events_df["signal_col"].
    """
    df_cols = set(df_columns)
    role_to_col: Dict[str, str] = {}

    # Fast path: include primary signal from event table if present.
    if include_primary and "signal_col" in events_df.columns and len(events_df) > 0:
        # If mixed, require consistent
        cols = sorted(set(events_df["signal_col"].dropna().astype(str).tolist()))
        if len(cols) == 1 and cols[0] in df_cols:
            role_to_col["primary"] = cols[0]

    # --- Prefer the detected event's concrete signal column ---
    primary_signal_col = None
    if events_df is not None and "signal_col" in events_df.columns:
        uniq = [x for x in events_df["signal_col"].dropna().unique().tolist() if isinstance(x, str)]
        if len(uniq) == 1:
            primary_signal_col = uniq[0]
        
    # Resolve additional roles via registry
    # Registry format: column -> {kind, unit, domain, op_chain, base, ...}
    for rs in roles:
        col = _pick_column_for_role(meta_signals, rs.role, rs.prefer, primary_signal_col=primary_signal_col)
        if col is None:
            raise ValueError(f"Could not resolve role '{rs.role}' via meta['signals']")
        if col not in df_cols:
            raise ValueError(f"Resolved role '{rs.role}' -> '{col}', but column not in df")
        role_to_col[rs.role] = col

    return role_to_col


def _pick_column_for_role(meta_signals: dict, role: str, prefer: list[str] | None,
                          *, primary_signal_col: str | None = None) -> str | None:
    role = (role or "").strip().lower()

    # Helper: ensure candidate exists in registry
    def has(col: str) -> bool:
        return isinstance(col, str) and col in meta_signals

    # 1) If events told us the concrete signal column, use it as disp.
    if role == "disp" and primary_signal_col and has(primary_signal_col):
        return primary_signal_col

    # 2) Derive related columns from the disp prefix when possible.
    # disp col example: "rear_shock_dom_suspension [mm]"
    # vel col:         "rear_shock_vel [mm/s]"
    # acc col:         "rear_shock_acc [mm/s^2]"
    # norm col:        "rear_shock_norm [1]"
    # zeroed col:      "rear_shock_dom_suspension [mm]_op_zeroed"
    if primary_signal_col:
        prefix = primary_signal_col.split("_", 1)[0]  # "rear" would be wrong; use better:
        # Better prefix extraction: take token before first "_" is too short.
        # Use first two tokens if present: "rear_shock"
        parts = primary_signal_col.split("_")
        prefix = "_".join(parts[:2]) if len(parts) >= 2 else parts[0]

        if role == "vel":
            cand = f"{prefix}_vel [mm/s]"
            if has(cand): return cand

        if role == "acc":
            cand = f"{prefix}_acc [mm/s^2]"
            if has(cand): return cand

        if role in ("disp_norm", "norm"):
            cand = f"{prefix}_norm [1]"
            if has(cand): return cand

        if role in ("disp_zeroed", "zeroed"):
            cand = f"{primary_signal_col}_op_zeroed"
            if has(cand): return cand

    # 3) Fallback: scan registry by unit/op_chain (kind is blank for engineered signals)
    want = {
        "disp":        {"unit": "mm",     "op": None},
        "vel":         {"unit": "mm/s",   "op": None},
        "acc":         {"unit": "mm/s^2", "op": None},
        "disp_norm":   {"unit": "1",      "name_contains": "_norm"},
        "disp_zeroed": {"unit": "mm",     "op": "zeroed"},
    }.get(role)

    if not want:
        return None

    best = None
    best_score = -1

    for col, info in meta_signals.items():
        if not isinstance(info, dict):
            continue

        unit = info.get("unit")
        kind = info.get("kind")
        op_chain = info.get("op_chain") or []

        if kind == "raw":
            continue

        if unit != want.get("unit"):
            continue

        if want.get("op") is not None:
            if want["op"] not in op_chain:
                continue

        if want.get("name_contains"):
            if want["name_contains"] not in col:
                continue

        # Prefer suspension domain if present (your disp has domain='suspension')
        score = 0
        if info.get("domain") == "suspension":
            score += 2
        if primary_signal_col and col.startswith(primary_signal_col.split("[", 1)[0].strip()):
            score += 2

        if score > best_score:
            best = col
            best_score = score

    return best



def _role_semantics(role: str) -> Dict[str, Any]:
    role = role.strip().lower()

    # Normalize common unit spellings
    def u(*alts: str) -> List[str]:
        return [a for a in alts if a]

    if role in ("disp", "displacement"):
        return {"kind_any": ["disp", "displacement", "position"], "unit_any": u("[mm]", "mm")}
    if role in ("vel", "velocity"):
        return {"kind_any": ["vel", "velocity"], "unit_any": u("[mm/s]", "mm/s")}
    if role in ("acc", "accel", "acceleration"):
        return {"kind_any": ["acc", "accel", "acceleration"], "unit_any": u("[mm/s^2]", "mm/s^2")}
    if role in ("disp_norm", "norm"):
        return {"kind_any": ["disp", "displacement", "position"], "unit_any": u("[1]", "1"), "op_contains": ["norm"]}
    if role in ("disp_zeroed", "zeroed"):
        return {"kind_any": ["disp", "displacement", "position"], "unit_any": u("[mm]", "mm"), "op_contains": ["op_zeroed"]}

    return {}



# -------------------------
# Index computation
# -------------------------

def _compute_segment_indices(
    *,
    df_time_s: np.ndarray,
    events_df: pd.DataFrame,
    anchor: AnchorField,
    window: WindowSpec,
    pad: PadMode,
    grid: GridSpec,
) -> Tuple[pd.DataFrame, int]:
    """
    Returns:
      segments_df: per-event extraction metadata
      n_expected: expected samples per segment (for native grid)
    """
    if df_time_s.ndim != 1:
        raise ValueError("df_time_s must be 1D")
    if len(df_time_s) == 0:
        raise ValueError("df_time_s is empty")

    # Estimate dt for native fixed-length extraction
    dt_est = float(np.median(np.diff(df_time_s))) if len(df_time_s) >= 3 else float(df_time_s[-1] - df_time_s[0])
    if dt_est <= 0:
        raise ValueError("Non-positive dt estimate from df_time_s; ensure monotonic increasing time_s")

    if grid.mode == "resample":
        if grid.dt_s is None or grid.dt_s <= 0:
            raise ValueError("grid.dt_s must be set and >0 for resample mode")
        dt_use = float(grid.dt_s)
    else:
        dt_use = dt_est

    if window.mode == "time":
        span = float(window.pre_s + window.post_s)
        n_expected = int(round(span / dt_use)) + 1
    else:
        n_expected = int(window.pre_n + window.post_n + 1)

    rows: List[Dict[str, Any]] = []

    for i, ev in events_df.iterrows():

        # -------------------------------------------------
        # 1) Resolve anchor for THIS event
        # -------------------------------------------------
        if anchor.endswith("_idx"):
            trigger_idx = int(ev[anchor])
            if trigger_idx < 0 or trigger_idx >= len(df_time_s):
                valid = False
                reason = "anchor idx out of bounds"
                trigger_time_s = np.nan
            else:
                trigger_time_s = float(df_time_s[trigger_idx])
                valid = True
                reason = ""
        else:
            trigger_time_s = float(ev[anchor])
            trigger_idx = int(np.searchsorted(df_time_s, trigger_time_s, side="left"))
            if trigger_idx < 0 or trigger_idx >= len(df_time_s):
                valid = False
                reason = "anchor time out of bounds"
            else:
                valid = True
                reason = ""

        # -------------------------------------------------
        # 2) Compute requested window indices
        # -------------------------------------------------
        if valid:
            if window.mode == "samples":
                req_start_idx = int(trigger_idx - window.pre_n)
                req_end_idx_excl = int(trigger_idx + window.post_n)
            else:
                # time mode: convert seconds to indices using df_time_s
                t0 = trigger_time_s - float(window.pre_s)
                t1 = trigger_time_s + float(window.post_s)
                req_start_idx = int(np.searchsorted(df_time_s, t0, side="left"))
                req_end_idx_excl = int(np.searchsorted(df_time_s, t1, side="right"))
        else:
            req_start_idx = req_end_idx_excl = -1


        # -------------------------------------------------
        # 3) Apply padding / clipping
        # -------------------------------------------------
        if valid:
            start_idx = max(0, req_start_idx)
            end_idx_excl = min(len(df_time_s), req_end_idx_excl)
            n_expected = end_idx_excl - start_idx
            if n_expected <= 0:
                valid = False
                reason = "empty segment after clipping"
        else:
            start_idx = end_idx_excl = -1
            n_expected = 0

        # -------------------------------------------------
        # 4) NOW build the row (all variables exist)
        # -------------------------------------------------
        row = {
            "event_row": int(i),
            "valid": bool(valid),
            "reason": reason,
            "trigger_time_s": float(trigger_time_s) if valid else np.nan,
            "trigger_idx": int(trigger_idx) if valid else -1,
            "req_start_idx": int(req_start_idx),
            "req_end_idx_excl": int(req_end_idx_excl),
            "start_idx": int(start_idx),
            "end_idx_excl": int(end_idx_excl),
            "n_expected": int(n_expected),
        }

        rows.append(row)


    seg_df = pd.DataFrame(rows)
    n_expected_out = int(seg_df["n_expected"].max()) if len(seg_df) else 0
    return seg_df, n_expected


# -------------------------
# Materialization
# -------------------------

def _materialize_arrays(
    *,
    df: pd.DataFrame,
    segments_df: pd.DataFrame,
    role_to_col: Mapping[str, str],
    n_expected: int,
    output: OutputSpec,
) -> Dict[str, np.ndarray]:
    valid_mask = segments_df["valid"].to_numpy(dtype=bool) if "valid" in segments_df.columns else np.ones(len(segments_df), bool)
    n_seg = int(valid_mask.sum())

    # Allocate
    data: Dict[str, np.ndarray] = {}

    def _alloc() -> np.ndarray:
        if output.pad == "nan":
            arr = np.full((n_seg, n_expected), np.nan, dtype=output.dtype)
        else:
            arr = np.zeros((n_seg, n_expected), dtype=output.dtype)
        return arr

    # Pre-allocate per role
    for role in role_to_col.keys():
        data[role] = _alloc()

    if output.include_time_s:
        data["time_s"] = _alloc()
    if output.include_t_rel_s:
        data["t_rel_s"] = _alloc()

    # Prepare for fast slicing
    time_s = df["time_s"].to_numpy(dtype=np.float64)

    seg_out_i = 0
    for seg_i, seg in segments_df.iterrows():
        if not bool(seg.get("valid", True)):
            continue

        start_idx = int(seg["start_idx"])
        end_idx_excl = int(seg["end_idx_excl"])
        anchor_t = float(seg["trigger_time_s"])

        # The slice we can take from df
        sl = slice(start_idx, end_idx_excl)
        have = end_idx_excl - start_idx

        # We want to place into a fixed-length window aligned to anchor.
        # For v0, we map the slice into the center by computing the requested start index.
        # Use req_start_idx to determine left padding (when clamped).
        req_start_idx = int(seg.get("req_start_idx", start_idx))
        left_pad = max(0, start_idx - req_start_idx)

        # If the slice is longer than expected due to dt jitter, clamp.
        copy_n = min(have, n_expected - left_pad)

        # Fill time arrays
        if output.include_time_s or output.include_t_rel_s:
            t_slice = time_s[sl][:copy_n]
            if output.include_time_s:
                data["time_s"][seg_out_i, left_pad:left_pad + copy_n] = t_slice.astype(output.dtype, copy=False)
            if output.include_t_rel_s:
                data["t_rel_s"][seg_out_i, left_pad:left_pad + copy_n] = (t_slice - anchor_t).astype(output.dtype, copy=False)

        # Fill signal roles
        for role, col in role_to_col.items():
            x = df[col].to_numpy(dtype=output.dtype, copy=False)[sl][:copy_n]
            data[role][seg_out_i, left_pad:left_pad + copy_n] = x

        seg_out_i += 1

    # Also return a compact index mapping if needed (future)
    return data


# -------------------------
# QC / Validation
# -------------------------

def _validate_df_timebase(df: pd.DataFrame) -> None:
    if "time_s" not in df.columns:
        raise ValueError("df must contain 'time_s'")
    ts = df["time_s"]
    if not np.issubdtype(ts.dtype, np.number):
        raise ValueError("'time_s' must be numeric")
    t = ts.to_numpy()
    if len(t) < 2:
        raise ValueError("'time_s' must have at least 2 samples")
    if not np.all(np.isfinite(t)):
        raise ValueError("'time_s' contains non-finite values")
    if np.any(np.diff(t) < 0):
        raise ValueError("'time_s' must be monotonic non-decreasing (prefer strictly increasing)")


def _qc_summary(segments_df: pd.DataFrame) -> Dict[str, Any]:
    n_total = len(segments_df)
    if n_total == 0:
        return {"n_total": 0, "n_valid": 0, "n_invalid": 0, "reasons": {}}

    valid = segments_df["valid"].to_numpy(dtype=bool) if "valid" in segments_df.columns else np.ones(n_total, bool)
    n_valid = int(valid.sum())
    n_invalid = int(n_total - n_valid)

    reasons: Dict[str, int] = {}
    if "reason" in segments_df.columns:
        for r in segments_df.loc[~valid, "reason"].astype(str).tolist():
            reasons[r] = reasons.get(r, 0) + 1

    return {"n_total": n_total, "n_valid": n_valid, "n_invalid": n_invalid, "reasons": reasons}


# -------------------------
# Example usage (remove in production)
# -------------------------

if __name__ == "__main__":
    # This is only a placeholder; wire into your pipeline:
    # bundle = extract_segments(session["df"], events, meta=session["meta"], schema=schema, request=SegmentRequest(event_name="rebound"))
    pass
