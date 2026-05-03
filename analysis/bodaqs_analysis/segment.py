"""
BODAQS Segment Extractor (skeleton)

This version includes:
- Semantic binding per event row (bind from each event row's signal_col via the registry)
- op_chain token normalization inside the resolver: 'op_zeroed' == 'zeroed', etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import logging

from .sensor_aliases import canonical_end

logger = logging.getLogger(__name__)

AnchorField = Literal[
    "start_time_s",
    "trigger_time_s",
    "end_time_s",
    "start_idx",
    "trigger_idx",
    "end_idx",
]

PadMode = Literal["nan", "edge", "drop"]
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
    include_primary_signal: bool = True
    dtype: Any = np.float32


@dataclass(frozen=True)
class GridSpec:
    mode: GridMode = "native"
    dt_s: Optional[float] = None


@dataclass(frozen=True)
class RoleSpec:
    role: str
    prefer: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentRequest:
    """Runtime request. Typically you select events (filter) then optionally override schema defaults."""

    event_name: Optional[str] = None
    schema_id: Optional[str] = None
    tags_any: Optional[Sequence[str]] = None

    anchor: Optional[AnchorField] = None
    window: Optional[WindowSpec] = None
    roles: Optional[Sequence[RoleSpec]] = None
    grid: Optional[GridSpec] = None
    output: OutputSpec = field(default_factory=OutputSpec)


SegmentBundle = Dict[str, Any]


def extract_segments(
    df: pd.DataFrame,
    events: pd.DataFrame,
    *,
    meta: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
    request: Optional[SegmentRequest] = None,
) -> SegmentBundle:
    _validate_df_timebase(df)

    req = request or SegmentRequest()
    events_sel = _filter_events(events, req)

    if events_sel is None or len(events_sel) == 0:
        return {
            "data": {},
            "spec": {"anchor": None, "window": None, "grid": None, "role_to_col": {}, "role_to_col_mode": "none"},
            "segments": pd.DataFrame([{"valid": False, "reason": "no selected events"}]),
            "events": events_sel if events_sel is not None else pd.DataFrame(),
            "qc": meta.get("qc") if isinstance(meta, dict) else None,
        }

    resolved = _resolve_effective_spec(schema, events_sel, req)

    role_to_col_by_eventrow = _resolve_roles_to_columns_per_eventrow(
        meta_signals=meta.get("signals", {}),
        roles=resolved["roles"],
        df_columns=df.columns,
        include_primary=req.output.include_primary_signal,
        events_df=events_sel,
    )

    seg_df, n_expected = _compute_segment_indices(
        df_time_s=df["time_s"].to_numpy(),
        events_df=events_sel,
        anchor=resolved["anchor"],
        window=resolved["window"],
        pad=req.output.pad,
        grid=resolved["grid"],
    )

    seg_df = seg_df.copy()
    seg_df["role_to_col"] = seg_df["event_row"].map(lambda i: role_to_col_by_eventrow.get(int(i), {}))

    data = _materialize_arrays_per_event(
        df=df,
        segments_df=seg_df,
        role_to_col_by_eventrow=role_to_col_by_eventrow,
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
            "role_to_col": None,
            "role_to_col_mode": "per_event_row",
            "output": req.output,
        },
        "events": events_sel,
        "segments": seg_df,
        "data": data,
        "qc": qc,
    }


def _filter_events(events: pd.DataFrame, req: SegmentRequest) -> pd.DataFrame:
    out = events.copy()

    if req.schema_id is not None and "schema_id" in out.columns:
        out = out[out["schema_id"] == req.schema_id]
    elif req.event_name is not None and "event_name" in out.columns:
        out = out[out["event_name"] == req.event_name]

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
    anchor: AnchorField = "trigger_time_s"
    window = WindowSpec(mode="time", pre_s=0.0, post_s=0.0)
    grid = GridSpec(mode="native", dt_s=None)
    roles: List[RoleSpec] = []

    event_key = None
    if schema is not None:
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

            g = seg_def.get("grid", {})
            if isinstance(g, dict):
                grid = GridSpec(
                    mode=str(g.get("mode", grid.mode)),  # type: ignore
                    dt_s=g.get("dt_s", grid.dt_s),
                )

            r = seg_def.get("roles")
            if r is not None:
                if not isinstance(r, list) or not r:
                    raise ValueError("schema segment_defaults.roles must be a non-empty list in strict mode")

                parsed: List[RoleSpec] = []
                for x in r:
                    if not isinstance(x, dict):
                        raise ValueError(
                            "schema segment_defaults.roles entries must be dicts in strict mode; "
                            f"got {type(x)} entry {x!r}"
                        )

                    role = str(x.get("role", "")).strip()
                    prefer = x.get("prefer", None)

                    if not role:
                        raise ValueError(f"schema role dict missing/empty 'role': {x!r}")
                    if not isinstance(prefer, dict) or not prefer:
                        raise ValueError(f"schema role {role!r} must include non-empty prefer dict; got {prefer!r}")
                    if not str(prefer.get("quantity", "")).strip():
                        raise ValueError(f"schema role {role!r} prefer must include non-empty 'quantity'")

                    parsed.append(RoleSpec(role=role, prefer=dict(prefer)))

                roles = parsed

    if req.anchor is not None:
        anchor = req.anchor
    if req.window is not None:
        window = req.window
    if req.grid is not None:
        grid = req.grid

    if req.roles is not None:
        parsed: List[RoleSpec] = []
        for rs in req.roles:
            if not isinstance(rs, RoleSpec):
                raise ValueError(f"req.roles must contain RoleSpec objects; got {type(rs)}")
            prefer = getattr(rs, "prefer", None)
            if not isinstance(prefer, Mapping) or not prefer:
                raise ValueError(f"RoleSpec {rs.role!r} missing prefer (strict mode)")
            if not str(prefer.get("quantity", "")).strip():
                raise ValueError(f"RoleSpec {rs.role!r} prefer must include non-empty 'quantity'")
            parsed.append(rs)
        roles = parsed

    if not roles:
        raise ValueError(
            "No roles resolved. In strict mode (Option B), roles must be specified in schema "
            "segment_defaults.roles as dicts with prefer{quantity,...}, or in SegmentRequest.roles."
        )

    if window.mode == "time":
        if window.pre_s < 0 or window.post_s < 0:
            raise ValueError("window pre_s/post_s must be >= 0")
    else:
        if window.pre_n < 0 or window.post_n < 0:
            raise ValueError("window pre_n/post_n must be >= 0")

    return {"anchor": anchor, "window": window, "grid": grid, "roles": tuple(roles)}


def _schema_segment_defaults(schema: Mapping[str, Any], event_key: str | None) -> Optional[Mapping[str, Any]]:
    if schema is None or event_key is None:
        return None

    events = schema.get("events")
    if isinstance(events, list):
        for ev in events:
            if not isinstance(ev, dict):
                continue
            ev_id = ev.get("id")
            ev_name = ev.get("event_name") or ev.get("name")
            if str(ev_id) == str(event_key) or str(ev_name) == str(event_key):
                seg = ev.get("segment_defaults")
                return seg if isinstance(seg, dict) else None

    seg_defaults = schema.get("segment_defaults")
    if isinstance(seg_defaults, dict):
        seg = seg_defaults.get(str(event_key))
        return seg if isinstance(seg, dict) else None

    return None


def _resolve_roles_to_columns_per_eventrow(
    *,
    meta_signals: Mapping[str, Any],
    roles: Sequence[RoleSpec],
    df_columns: Iterable[str],
    include_primary: bool,
    events_df: pd.DataFrame,
) -> Dict[int, Dict[str, str]]:
    df_cols = set(df_columns)
    out: Dict[int, Dict[str, str]] = {}

    if events_df is None or len(events_df) == 0:
        return out
    if "signal_col" not in events_df.columns:
        raise ValueError("events_df missing required 'signal_col' for semantic role binding")

    for i, ev in events_df.iterrows():
        role_to_col: Dict[str, str] = {}

        primary_col = None
        sigcol = ev.get("signal_col", None)
        if isinstance(sigcol, str) and sigcol in df_cols:
            primary_col = sigcol
            if include_primary:
                role_to_col["primary"] = sigcol

        event_context: Dict[str, str] = {}
        if isinstance(sigcol, str):
            info = meta_signals.get(sigcol)
            if isinstance(info, dict):
                for key in ("end", "domain"):
                    value = info.get(key)
                    if isinstance(value, str) and value.strip():
                        event_context[key] = value.strip()


        for rs in roles:
            col = _pick_column_for_role(
                meta_signals,
                rs.role,
                rs.prefer,
                primary_signal_col=primary_col,
                event_context=event_context,
            )
            if col is None:
                raise ValueError(
                    f"Could not resolve role {rs.role!r} for event_row={int(i)} "
                    f"(schema_id={ev.get('schema_id')!r}, signal_col={sigcol!r}, "
                    f"event_context={event_context!r}) "
                    f"via meta['signals']"
                )
            if col not in df_cols:
                raise ValueError(f"Resolved role '{rs.role}' -> '{col}', but column not in df")
            role_to_col[rs.role] = col

        out[int(i)] = role_to_col

    return out


def _pick_column_for_role(meta_signals, role, prefer, primary_signal_col=None, *, event_context=None):
    """Registry-first role resolution with op_chain normalization."""

    def _get_pref(p, k, default=None):
        if p is None:
            return default
        if isinstance(p, dict):
            return p.get(k, default)
        return getattr(p, k, default)

    def _has_pref_key(p, k: str) -> bool:
        if p is None:
            return False
        if isinstance(p, Mapping):
            return k in p
        return hasattr(p, k)

    def _norm_str(x):
        if x is None:
            return None
        s = str(x).strip()
        return s if s else None

    def _norm_kind(x):
        s = _norm_str(x)
        return s or ""

    def _norm_unit(x):
        return _norm_str(x)

    def _norm_op_token(tok: Any) -> str:
        t = str(tok).strip()
        if t.startswith("op_"):
            t = t[3:]
        return t

    def _norm_op_chain(x):
        if x is None:
            return ()
        if isinstance(x, (list, tuple)):
            return tuple(_norm_op_token(v) for v in x if str(v).strip())
        s = str(x).strip()
        if not s:
            return ()
        if "|" in s:
            return tuple(_norm_op_token(p) for p in s.split("|") if p)
        return (_norm_op_token(s),)

    pref_quantity = _norm_str(_get_pref(prefer, "quantity"))
    pref_kind = _norm_kind(_get_pref(prefer, "kind"))
    pref_unit = _norm_unit(_get_pref(prefer, "unit"))
    pref_domain = _norm_str(_get_pref(prefer, "domain"))
    pref_end_raw = _norm_str(_get_pref(prefer, "end"))
    pref_end = canonical_end(pref_end_raw) if pref_end_raw else None
    pref_processing_role = _norm_str(_get_pref(prefer, "processing_role"))
    pref_motion_source_id = _norm_str(_get_pref(prefer, "motion_source_id"))
    pref_motion_profile_id = _norm_str(_get_pref(prefer, "motion_profile_id"))
    pref_has_op_chain = _has_pref_key(prefer, "op_chain")
    pref_op_chain = _norm_op_chain(_get_pref(prefer, "op_chain"))

    event_context = event_context if isinstance(event_context, Mapping) else {}
    if pref_end is None:
        pref_end = canonical_end(event_context.get("end")) or None
    if pref_domain is None:
        pref_domain = _norm_str(event_context.get("domain"))

    if pref_quantity is None and isinstance(role, str) and role.strip():
        pref_quantity = role.strip()

    candidates = []
    for col, info in (meta_signals or {}).items():
        if not isinstance(col, str):
            continue
        if not isinstance(info, dict):
            continue

        quantity = _norm_str(info.get("quantity"))
        kind = _norm_kind(info.get("kind"))
        unit = _norm_unit(info.get("unit"))
        domain = _norm_str(info.get("domain"))
        actual_end = canonical_end(info.get("end"))
        processing_role = _norm_str(info.get("processing_role"))
        motion_source_id = _norm_str(info.get("motion_source_id"))
        motion_profile_id = _norm_str(info.get("motion_profile_id"))
        op_chain = _norm_op_chain(info.get("op_chain"))

        if pref_end is not None and actual_end != pref_end:
            continue
        if pref_quantity is not None and quantity != pref_quantity:
            continue
        if pref_kind and kind != pref_kind:
            continue
        if pref_unit is not None and unit != pref_unit:
            continue
        if pref_domain is not None and domain != pref_domain:
            continue
        if pref_processing_role is not None and processing_role != pref_processing_role:
            continue
        if pref_motion_source_id is not None and motion_source_id != pref_motion_source_id:
            continue
        if pref_motion_profile_id is not None and motion_profile_id != pref_motion_profile_id:
            continue
        # prefer.op_chain present and non-empty means "these ops must be present".
        # prefer.op_chain explicitly [] means "base/no-op signal only".
        if pref_op_chain:
            have = set(op_chain)
            need = set(pref_op_chain)
            if not need.issubset(have):
                continue
        elif pref_has_op_chain:
            if len(op_chain) != 0:
                continue

        candidates.append((col, info))

    logger.debug("role=%r pref_end=%r pref_domain=%r pref_quantity=%r pref_unit=%r pref_kind=%r pref_op_chain=%r",
                 role, pref_end, pref_domain, pref_quantity, pref_unit, pref_kind, pref_op_chain)
                 
    if not candidates:
        if isinstance(role, str) and role.strip().lower() == "primary" and primary_signal_col:
            return primary_signal_col
        return None

    def _score(col_info):
        col, info = col_info
        score = 0
        op_chain = _norm_op_chain(info.get("op_chain"))
        op_len = len(op_chain)
        if info.get("quantity") is not None:
            score += 2
        if info.get("unit") is not None:
            score += 1
        if (info.get("kind") or "") != "":
            score += 1
        role = str(info.get("processing_role") or "").strip().lower()
        if role == "primary_analysis":
            score += 100
        elif role == "secondary_analysis":
            score += 20
        # Prefer cleaner (fewer-op) variants unless schema explicitly asks for ops.
        if pref_op_chain:
            # Fewer extras beyond requested ops wins.
            score -= max(0, op_len - len(pref_op_chain))
        elif pref_has_op_chain:
            # Explicit [] preference already filters to op_len==0.
            score -= op_len
        else:
            score -= op_len
        if primary_signal_col and col == primary_signal_col:
            score += 10
        return score

    candidates.sort(key=_score, reverse=True)

    best_score = _score(candidates[0])
    tied = [c for c in candidates if _score(c) == best_score]
    tied_cols = [c[0] for c in tied]
    if len(set(tied_cols)) > 1:
        raise ValueError(f"Ambiguous role resolution for role={role!r} prefer={prefer!r}: candidates={tied_cols}")

    return candidates[0][0]

def _compute_segment_indices(
    *,
    df_time_s: np.ndarray,
    events_df: pd.DataFrame,
    anchor: AnchorField,
    window: WindowSpec,
    pad: PadMode,
    grid: GridSpec,
) -> Tuple[pd.DataFrame, int]:
    if df_time_s.ndim != 1:
        raise ValueError("df_time_s must be 1D")
    if len(df_time_s) == 0:
        raise ValueError("df_time_s is empty")

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

        if valid:
            if window.mode == "samples":
                req_start_idx = int(trigger_idx - window.pre_n)
                req_end_idx_excl = int(trigger_idx + window.post_n)
            else:
                t0 = trigger_time_s - float(window.pre_s)
                t1 = trigger_time_s + float(window.post_s)
                req_start_idx = int(np.searchsorted(df_time_s, t0, side="left"))
                req_end_idx_excl = int(np.searchsorted(df_time_s, t1, side="right"))
        else:
            req_start_idx = req_end_idx_excl = -1

        if valid:
            start_idx = max(0, req_start_idx)
            end_idx_excl = min(len(df_time_s), req_end_idx_excl)
            n_here = end_idx_excl - start_idx
            if n_here <= 0:
                valid = False
                reason = "empty segment after clipping"
        else:
            start_idx = end_idx_excl = -1
            n_here = 0

        rows.append(
            {
                "event_row": int(i),
                "valid": bool(valid),
                "reason": reason,
                "trigger_time_s": float(trigger_time_s) if valid else np.nan,
                "trigger_idx": int(trigger_idx) if valid else -1,
                "req_start_idx": int(req_start_idx),
                "req_end_idx_excl": int(req_end_idx_excl),
                "start_idx": int(start_idx),
                "end_idx_excl": int(end_idx_excl),
                "n_expected": int(n_here),
            }
        )

    seg_df = pd.DataFrame(rows)
    n_expected_out = int(seg_df["n_expected"].max()) if len(seg_df) else 0
    return seg_df, n_expected_out

def _materialize_arrays_per_event(
    *,
    df: pd.DataFrame,
    segments_df: pd.DataFrame,
    role_to_col_by_eventrow: Mapping[int, Mapping[str, str]],
    n_expected: int,
    output: OutputSpec,
) -> Dict[str, np.ndarray]:
    valid_mask = segments_df["valid"].to_numpy(dtype=bool) if "valid" in segments_df.columns else np.ones(len(segments_df), bool)
    n_seg = int(valid_mask.sum())

    role_keys: List[str] = []
    for _, m in role_to_col_by_eventrow.items():
        role_keys = list(m.keys())
        break

    data: Dict[str, np.ndarray] = {}

    def _alloc() -> np.ndarray:
        if output.pad == "nan":
            return np.full((n_seg, n_expected), np.nan, dtype=output.dtype)
        return np.zeros((n_seg, n_expected), dtype=output.dtype)

    for role in role_keys:
        data[role] = _alloc()

    if output.include_time_s:
        data["time_s"] = _alloc()
    if output.include_t_rel_s:
        data["t_rel_s"] = _alloc()

    time_s = df["time_s"].to_numpy(dtype=np.float64)

    # Estimate a global dt from the session timebase (must be positive)
    if len(time_s) < 3:
        raise ValueError("time_s has < 3 samples; cannot build segment grids")
    dt_global = float(np.median(np.diff(time_s)))
    if dt_global <= 0 or not np.isfinite(dt_global):
        raise ValueError(f"Non-positive dt estimated from df.time_s: dt={dt_global}")

    grid_idx = np.arange(n_expected, dtype=np.float64)

    seg_out_i = 0
    for _, seg in segments_df.iterrows():
        if not bool(seg.get("valid", True)):
            continue

        event_row = int(seg["event_row"])
        role_to_col = role_to_col_by_eventrow.get(event_row, None)
        if not isinstance(role_to_col, Mapping) or not role_to_col:
            raise ValueError(f"Missing role_to_col mapping for event_row={event_row}")

        start_idx = int(seg["start_idx"])
        end_idx_excl = int(seg["end_idx_excl"])
        anchor_t = float(seg["trigger_time_s"])

        sl = slice(start_idx, end_idx_excl)
        have = end_idx_excl - start_idx

        req_start_idx = int(seg.get("req_start_idx", start_idx))
        left_pad = max(0, start_idx - req_start_idx)

        copy_n = min(have, n_expected - left_pad)

        # --- Build full finite grids first (no NaNs in t_rel_s) ---
        if output.include_time_s or output.include_t_rel_s:
            # time at column left_pad equals time_s[start_idx]
            base_time0 = float(time_s[start_idx]) - left_pad * dt_global
            if output.include_time_s:
                data["time_s"][seg_out_i, :] = (base_time0 + grid_idx * dt_global).astype(output.dtype, copy=False)

            if output.include_t_rel_s:
                base_rel0 = (float(time_s[start_idx]) - anchor_t) - left_pad * dt_global
                data["t_rel_s"][seg_out_i, :] = (base_rel0 + grid_idx * dt_global).astype(output.dtype, copy=False)

            # Optionally overwrite the “have” region with exact timestamps (keeps perfect fidelity)
            if copy_n > 0:
                t_slice = time_s[sl][:copy_n]
                if output.include_time_s:
                    data["time_s"][seg_out_i, left_pad:left_pad + copy_n] = t_slice.astype(output.dtype, copy=False)
                if output.include_t_rel_s:
                    data["t_rel_s"][seg_out_i, left_pad:left_pad + copy_n] = (t_slice - anchor_t).astype(output.dtype, copy=False)

        # --- Copy signal roles (still padded with NaN if requested) ---
        for role, col in role_to_col.items():
            x = df[col].to_numpy(dtype=output.dtype, copy=False)[sl][:copy_n]
            data[role][seg_out_i, left_pad:left_pad + copy_n] = x

        seg_out_i += 1

    return data



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


if __name__ == "__main__":
    pass
