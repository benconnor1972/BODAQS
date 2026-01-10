from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence, Tuple
from .model import validate_events_df
from .metrics import extract_metrics_df  # contract: metrics live in metrics.py

import math
import numpy as np
import pandas as pd

# Optional SciPy peak finding
try:
    from scipy.signal import find_peaks  # type: ignore
    _HAVE_SCIPY = True
except Exception:
    _HAVE_SCIPY = False

def _require_inputs(df: Optional[pd.DataFrame] = None,
                   meta: Optional[Dict[str, Any]] = None,
                   schema: Optional[Dict[str, Any]] = None):
    """Notebook-compat input resolver.

    In the original notebook, this pulled from globals (df/data_rs + schema dict).
    In the package version, you should pass `df` and `schema` explicitly.

    Returns (df, meta, schema).
    """
    if meta is None:
        meta = {}
    if df is None:
        # Fallback for notebook usage
        if "data_rs" in globals():
            df = globals()["data_rs"]
        elif "data" in globals():
            df = globals()["data"]
        else:
            raise ValueError("No dataframe provided and no global 'data_rs'/'data' found.")
    if schema is None:
        if "schema" in globals():
            schema = globals()["schema"]
        else:
            raise ValueError("No schema provided and no global 'schema' found.")
    return df, meta, schema


def _to_seconds(series: pd.Series) -> np.ndarray:
    """Return time in seconds as float64 from a numeric/Timedelta/Datetime series."""
    s = series
    dt = s.dtype

    # Handle Timedelta64[ns]
    if np.issubdtype(dt, np.timedelta64):
        return s.astype("timedelta64[ns]").view("int64") / 1e9

    # Handle Datetime64[ns]
    if np.issubdtype(dt, np.datetime64):
        base = s.astype("datetime64[ns]").view("int64")[0]
        return (s.astype("datetime64[ns]").view("int64") - base) / 1e9

    # Already numeric → assume seconds
    return pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)

def _robust_dt(df: pd.DataFrame, meta: dict) -> float:
    """Try meta['dt'], else estimate from 't' column."""
    dt_val = float(meta.get("dt", np.nan))
    if np.isfinite(dt_val) and dt_val > 0:
        return dt_val
    if "time_s" in df.columns and len(df) > 1:
        t_sec = _to_seconds(df["time_s"])
        diffs = np.diff(t_sec)
        diffs = diffs[(diffs > 0) & np.isfinite(diffs)]
        if diffs.size:
            return float(np.median(diffs))
    return float("nan")

def _sec_to_samples_opt(s: float | None, dt: float) -> int | None:
    """Seconds → samples; returns None if dt invalid or s is None."""
    if s is None:
        return None
    if not np.isfinite(dt) or dt <= 0:
        return None
    return int(round(float(s) / float(dt)))

def _clip_bounds(n: int, i0: int, i1: int):
    return max(0, i0), min(n, i1)

def _series_get(df: pd.DataFrame, name: str):
    if not name:
        raise KeyError("Series name is None — check trigger.signal and suffix mapping.")
    if name not in df.columns:
        raise KeyError(f"Series '{name}' not found in event_analysis_df columns.")
    return df[name].to_numpy()

def _nan_frac(arr):
    return float(np.mean(np.isnan(arr))) if arr.size else 1.0

def _resolve_search_window(trig: dict, t: np.ndarray, base_t0_sec: float | None):
    """
    Return (i0, i1) index bounds into t for trigger search.

    Semantics:
      - If trig.search is absent/empty and base_t0_sec is None/invalid → whole series [0, n)
      - Otherwise:
          * base time = base_t0_sec (if finite) else t[0]
          * start = base + min_delay_s
          * end   = base + max_delay_s (or last time if max_delay_s missing)
    """
    search = trig.get("search") or {}
    n = len(t)
    if n == 0:
        return 0, 0

    if not search and (base_t0_sec is None or not np.isfinite(base_t0_sec)):
        return 0, n

    min_delay_s = float(search.get("min_delay_s", 0.0))
    max_delay_s = search.get("max_delay_s", None)

    if base_t0_sec is None or not np.isfinite(base_t0_sec):
        base = float(t[0])
    else:
        base = float(base_t0_sec)

    start_sec = base + min_delay_s
    end_sec   = base + float(max_delay_s) if max_delay_s is not None else float(t[-1])

    i0 = int(np.searchsorted(t, start_sec, side="left"))
    i1 = int(np.searchsorted(t, end_sec,   side="right"))
    return _clip_bounds(n, i0, i1)

def _resolve_inputs_for_sensor(sensor: str, schema: dict, meta: dict | None = None) -> dict:

    """
    Resolve schema signal roles (disp/vel/acc/disp_zeroed/disp_norm/...) to concrete df column names.
    Registry-first:
      - Prefer session["meta"]["signals"] if present (canonical, domain-aware).
    Fallback:
      - If schema provides naming.suffixes, use suffix concatenation (legacy support).
    Returns:
      inputs_map: { role -> column_name }
    """

    out: dict[str, str] = {}
    # ---------------- Registry-first resolution ----------------
    signals = None
    if isinstance(meta, dict):
        signals = meta.get("signals")
    if isinstance(signals, dict) and signals:
        # Build quick lookup by base (sensor name) and by derived base names.
        # In your naming contract, base is embedded in column names; we match by parsing names.
        try:
            from .signalname import parse_signal_name  # adjust import path if needed
        except Exception:
            parse_signal_name = None  # fallback below

        # Helper: find a column in registry matching predicate
        def _find_col(pred):
            for col, info in signals.items():
                if pred(col, info):
                    return col
            return None

        # Helper: identify whether registry entry corresponds to a sensor base
        # Prefer parse_signal_name if available; else basic prefix matching.
        def _is_base_match(col: str, base: str) -> bool:
            if parse_signal_name:
                try:
                    parts = parse_signal_name(col)
                    return parts.base == base
                except Exception:
                    return False

            # crude fallback (should rarely be used)
            return col.startswith(base)

        # Engineered displacement for this sensor (domain may be injected)
        disp_col = _find_col(lambda c, info: _is_base_match(c, sensor) and info.get("kind", "") == "" and info.get("unit") == "mm")
        if disp_col:
            out["disp"] = disp_col

        # Velocity & acceleration are derived bases in your implementation: <sensor>_vel / <sensor>_acc
        vel_col = _find_col(lambda c, info: _is_base_match(c, f"{sensor}_vel") and info.get("kind", "") == "" and info.get("unit") == "mm/s")

        if vel_col:
            out["vel"] = vel_col

        acc_col = _find_col(lambda c, info: _is_base_match(c, f"{sensor}_acc") and info.get("kind", "") == "" and info.get("unit") == "mm/s^2")
        if acc_col:
            out["acc"] = acc_col

        # Normalised displacement: <sensor>_norm [1]
        norm_col = _find_col(lambda c, info: _is_base_match(c, f"{sensor}_norm") and info.get("kind", "") == "" and info.get("unit") == "1")
        if norm_col:
            out["disp_norm"] = norm_col

        # Zeroed displacement: op token "zeroed" applied to disp_col
        # Name convention: "<disp_col>_op_zeroed"
        if disp_col:
            zeroed_col = f"{disp_col}_op_zeroed"
            # only include if it exists in registry keys

            if zeroed_col in signals:

                out["disp_zeroed"] = zeroed_col

            else:

                # Some implementations may store op_chain in registry; try to find it that way.

                z2 = _find_col(lambda c, info: _is_base_match(c, sensor) and info.get("unit") == "mm"

                                             and "zeroed" in (info.get("op_chain") or []))

                if z2:

                    out["disp_zeroed"] = z2



        # Raw counts: kind="raw" and unit="counts"

        raw_col = _find_col(lambda c, info: _is_base_match(c, sensor) and info.get("kind") == "raw" and info.get("unit") == "counts")

        if raw_col:

            out["raw"] = raw_col



        # If registry provided anything, we're done (roles not found will be validated elsewhere)

        if out:

            return out



    # ---------------- Legacy suffix-only fallback ----------------

    naming = schema.get("naming", {}) or {}

    suffixes = (naming.get("suffixes") or {})

    for role, suf in suffixes.items():

        if sensor:

            out[role] = f"{sensor}{suf}"

    return out


def _expand_event_by_sensors(ev: dict, schema: dict) -> list[dict]:
    """
    Turn one (multi-sensor) event into a list of per-sensor events,
    each with an explicit 'sensor'. Suffix-only: we no longer support
    legacy single-sensor events without 'sensors'.
    """
    sensors = ev.get("sensors") or []
    if not sensors:
        raise KeyError(f"Event '{ev.get('id','?')}' missing 'sensors' in suffix-only schema.")
    out = []
    for s in sensors:
        ev2 = dict(ev)
        ev2["sensor"] = s
        out.append(ev2)
    return out

def _validate_event_series_with_map(ev: dict, df: pd.DataFrame, inputs_map: dict):
    """
    Validate that trigger/conditions/metrics refer to signals present in `inputs_map`,
    and that the mapped DataFrame columns exist.
    """
    ev_id = ev.get("id", "(unknown)")
    trig = ev.get("trigger", {}) or {}

    # ---- Trigger ----
    sig = trig.get("signal")
    if sig:
        if sig not in inputs_map:
            raise KeyError(
                f"Event '{ev_id}': trigger.signal='{sig}' not found in resolved inputs_map keys {list(inputs_map.keys())}."
            )
        col = inputs_map[sig]
        if col not in df.columns:
            raise KeyError(
                f"Event '{ev_id}': trigger.signal '{sig}' maps to column '{col}', "
                f"which is not in event_analysis_df."
            )

    # ---- Collect referenced signals in conditions & metrics ----
    def _collect_refs(blocks):
        refs = set()
        for blk in (blocks or []):
            for key in ("any_of", "all_of"):
                for test in (blk.get(key) or []):
                    s = test.get("signal")
                    if s:
                        refs.add(s)
        return refs

    cond_refs   = _collect_refs(ev.get("preconditions")) | _collect_refs(ev.get("postconditions"))
    metric_refs = {m.get("signal") for m in (ev.get("metrics") or []) if m.get("signal")}
    needed      = {x for x in (cond_refs | metric_refs) if x}

    # ---- Validate each referenced signal via the resolved mapping ----
    for name in needed:
        if name not in inputs_map:
            raise KeyError(
                f"Event '{ev_id}': a condition/metric references '{name}', "
                f"but resolved inputs_map only has {list(inputs_map.keys())}."
            )
        col = inputs_map[name]
        if col not in df.columns:
            raise KeyError(
                f"Event '{ev_id}': signal '{name}' maps to column '{col}', "
                f"which is not in event_analysis_df."
            )

def _hash_event_params(ev_resolved: dict, *, schema_version: str = "") -> str:
    """
    Contract: params_hash is a hash of the event’s effective schema block.
    We hash a stable JSON serialization of the resolved event dict plus schema_version.
    """
    import json, hashlib
    payload = {"schema_version": str(schema_version), "event": ev_resolved}
    b = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(b).hexdigest()

def _trigger_local_extrema(df, dt, ev, base_t0_sec=None):
    trig = ev["trigger"]
    signal = trig.get("signal")            # 'disp' | 'vel' | 'acc'
    kind = trig.get("kind")                # 'min' | 'max'
    prom = trig.get("prominence")          # units of the chosen series
    dist_s = trig.get("distance_s")
    edge_ignore_s = trig.get("edge_ignore_s")

    series_name = ev["inputs"].get(signal)
    y = _series_get(df, series_name).copy()
    t = _to_seconds(df["time_s"])
    n = len(y)
    if n == 0:
        return []

    # base series (peaks operate on this)
    if kind == "min":
        y_proc = -y
        prom_arg = prom if prom is None else float(prom)
    else:
        y_proc = y
        prom_arg = prom if prom is None else float(prom)

    distance = _sec_to_samples_opt(dist_s, dt)

    # edge ignore in samples
    edge = _sec_to_samples_opt(edge_ignore_s, dt) or 0

    # search window (for secondary vs primary)
    i0, i1 = _resolve_search_window(trig, t, base_t0_sec)
    if i0 >= i1:
        return []

    # clamp window to edge-ignore region
    search_lo = max(edge, i0)
    search_hi = min(n - edge, i1)
    if search_lo >= search_hi:
        return []

    if _HAVE_SCIPY:
        y_sub = y_proc[search_lo:search_hi]
        kwargs = {}
        if prom_arg is not None:
            kwargs["prominence"] = prom_arg
        if (distance is not None) and (distance > 1):
            kwargs["distance"] = int(distance)
        idx_local, props = find_peaks(y_sub, **kwargs)
        prominences = props.get("prominences", np.full_like(idx_local, np.nan, dtype=float)) if props else np.full(0, np.nan)
        idx = idx_local + search_lo
    else:
        idx = np.arange(search_lo + 1, search_hi - 1)
        prominences = []
        kept = []
        if kind == "min":
            cand = idx[(y[idx] < y[idx-1]) & (y[idx] <= y[idx+1])]
            win = max(5, int(distance) if distance else 5)
            for i in cand:
                L = max(0, i-win); R = min(n, i+win+1)
                ref = np.nanmax(y[L:R])
                p = (ref - y[i])
                if prom is None or (p >= prom):
                    kept.append(i); prominences.append(p)
        else:
            cand = idx[(y[idx] > y[idx-1]) & (y[idx] >= y[idx+1])]
            win = max(5, int(distance) if distance else 5)
            for i in cand:
                L = max(0, i-win); R = min(n, i+win+1)
                ref = np.nanmin(y[L:R])
                p = (y[i] - ref)
                if prom is None or (p >= prom):
                    kept.append(i); prominences.append(p)
        idx = np.array(kept, dtype=int)
        prominences = np.array(prominences, dtype=float)

    # Package
    out = []
    for i, p in zip(idx, prominences if len(prominences) else [np.nan]*len(idx)):
        out.append({
            "t0_index": int(i),
            "t0_time": float(t[i]),
            "trigger_strength": float(p) if np.isfinite(p) else None,
            "trigger_value": float(y[i]) if np.isfinite(y[i]) else None,
        })
    return out

def _trigger_threshold_crossing(df, dt, ev, base_t0_sec=None):
    """
    Implements 'simple_threshold_crossing' (and legacy 'threshold_crossing').

    When base_t0_sec is not None and trigger.search is present,
    restricts search to that time window (used for secondary triggers).
    """
    trig = ev["trigger"]
    signal = trig.get("signal")
    if not signal:
        return []

    direction = trig.get("dir", "either")
    value = float(trig.get("value", 0.0))
    hyster = float(trig.get("hysteresis", 0.0))

    series_name = ev["inputs"].get(signal)   # e.g. 'rear_shock [mm]_vel'
    y = _series_get(df, series_name).astype(float)
    t = _to_seconds(df["time_s"])
    n = len(y)
    if n == 0:
        return []

    # optional displacement for scoring
    disp_col = ev["inputs"].get("disp")
    if disp_col:
        x_raw = _series_get(df, disp_col)
        x = np.asarray(x_raw, dtype=float)
    else:
        x = None

    # search window
    i0, i1 = _resolve_search_window(trig, t, base_t0_sec)
    if i0 >= i1:
        return []

    crossings = []
    armed_rising = True
    armed_falling = True

    for i in range(max(1, i0), i1):
        y0, y1 = y[i-1], y[i]

        if direction in ("rising", "either"):
            if armed_rising and (y0 < value) and (y1 >= value):
                crossings.append(i)
                armed_rising = False
            if (y1 <= value - hyster):
                armed_rising = True

        if direction in ("falling", "either"):
            if armed_falling and (y0 > value) and (y1 <= value):
                crossings.append(i)
                armed_falling = False
            if (y1 >= value + hyster):
                armed_falling = True

    crossings = np.unique(np.asarray(crossings, dtype=int))

    out = []
    for i in crossings:
        d = {
            "t0_index": int(i),
            "t0_time": float(t[i]),
            "trigger_value": float(y[i]),
            "trigger_strength": float(abs(y[i] - y[i-1])) if i > 0 and np.isfinite(y[i-1]) else None,
        }
        if x is not None and 0 <= i < len(x) and np.isfinite(x[i]):
            d["disp"] = float(x[i])
        out.append(d)

    return out

def _trigger_zero_crossing(df, dt, ev, base_t0_sec=None):
    trig = ev["trigger"].copy()
    trig.setdefault("value", 0.0)
    ev2 = dict(ev); ev2["trigger"] = trig
    return _trigger_threshold_crossing(df, dt, ev2, base_t0_sec=base_t0_sec)

def _trigger_phased_threshold_crossing(df, dt, ev, base_t0_sec=None):
    """
    Phased threshold crossing trigger.

    Looks for a NEG → ZERO → POS (for dir='rising') or
    POS → ZERO → NEG (for dir='falling') pattern in the chosen signal,
    constrained by:
      - trigger.search.min_delay_s / max_delay_s (resolved via _resolve_search_window)
      - trigger.search.smooth_ms (optional smoothing window)
      - bands.<neg/zero/pos>.{min,max,dwell_samples}
      - cross_samples (minimum dwell in the final band)

    Works for both:
      - primary triggers (base_t0_sec=None → search over whole frame or search window)
      - secondary triggers (base_t0_sec = time of base trigger → windowed after base)
    """
    trig = ev["trigger"]
    signal = trig.get("signal")
    if not signal:
        return []

    # signal → column
    series_name = ev["inputs"].get(signal)
    y = _series_get(df, series_name).astype(float)
    n = len(y)
    if n == 0:
        return []

    t = _to_seconds(df["time_s"])

    value = float(trig.get("value", 0.0))  # currently unused, reserved for future relative semantics
    direction = trig.get("dir", "rising")
    search = trig.get("search", {}) or {}
    bands = trig.get("bands", {}) or {}
    cross_samples = int(trig.get("cross_samples", 1) or 1)

    # --- Search window in index space (shared helper) ---
    i0, i1 = _resolve_search_window(trig, t, base_t0_sec)
    i0, i1 = _clip_bounds(n, i0, i1)
    if i0 >= i1:
        return []

    # --- Optional smoothing ---
    smooth_ms = search.get("smooth_ms")
    if smooth_ms is not None and np.isfinite(dt) and dt > 0:
        win = int(round((smooth_ms / 1000.0) / dt))
        if win > 1:
            kernel = np.ones(win, dtype=float) / win
            y_s = np.convolve(y, kernel, mode="same")
        else:
            y_s = y
    else:
        y_s = y

    # --- Build band masks & dwell requirements ---
    def _band_masks(bands_def):
        def _one(name):
            cfg = bands_def.get(name, {}) or {}
            bmin = cfg.get("min", -np.inf)
            bmax = cfg.get("max", np.inf)
            dwell = int(cfg.get("dwell_samples", 1) or 1)
            mask = (y_s >= bmin) & (y_s <= bmax)
            return mask, dwell

        neg_mask, neg_dwell = _one("neg")
        zero_mask, zero_dwell = _one("zero")
        pos_mask, pos_dwell = _one("pos")
        return (neg_mask, zero_mask, pos_mask,
                neg_dwell, zero_dwell, pos_dwell)

    neg_mask, zero_mask, pos_mask, neg_dwell, zero_dwell, pos_dwell = _band_masks(bands)

    def _scan(neg_m, zero_m, pos_m, neg_dw, zero_dw, pos_dw):
        """Find all NEG→ZERO→POS sequences within [i0, i1)."""
        cands = []
        i = i0
        while i < i1:
            # 1) NEG dwell
            j = i
            while j < i1 and not neg_m[j]:
                j += 1
            if j >= i1:
                break
            k = j
            while k < i1 and neg_m[k]:
                k += 1
            if (k - j) < neg_dw:
                i = j + 1
                continue
            neg_start, neg_end = j, k

            # 2) ZERO band
            j = neg_end
            while j < i1 and not zero_m[j]:
                j += 1
            if j >= i1:
                break
            k = j
            while k < i1 and zero_m[k]:
                k += 1
            if (k - j) < max(zero_dw, 1):
                i = j + 1
                continue
            zero_start, zero_end = j, k

            # 3) POS dwell
            j = zero_end
            while j < i1 and not pos_m[j]:
                j += 1
            if j >= i1:
                break
            k = j
            while k < i1 and pos_m[k]:
                k += 1
            # require final dwell and cross_samples
            if (k - j) < max(pos_dw, cross_samples, 1):
                i = j + 1
                continue
            pos_start, pos_end = j, k

            t0_idx = pos_start
            strength = pos_end - pos_start  # length of final dwell as crude strength
            cands.append({
                "t0_index": int(t0_idx),
                "t0_time": float(t[t0_idx]),
                "trigger_value": float(y[t0_idx]),
                "trigger_strength": float(strength),
            })

            # continue search after this full sequence
            i = pos_end
        return cands

    # --- Direction handling ---
    all_cands = []
    if direction in (None, "rising"):
        # NEG → ZERO → POS in the given bands
        all_cands.extend(_scan(neg_mask, zero_mask, pos_mask,
                               neg_dwell, zero_dwell, pos_dwell))
    elif direction == "falling":
        # POS → ZERO → NEG (swap band roles)
        all_cands.extend(_scan(pos_mask, zero_mask, neg_mask,
                               pos_dwell, zero_dwell, neg_dwell))
    elif direction == "either":
        rising = _scan(neg_mask, zero_mask, pos_mask,
                       neg_dwell, zero_dwell, pos_dwell)
        falling = _scan(pos_mask, zero_mask, neg_mask,
                        pos_dwell, zero_dwell, neg_dwell)
        merged = {}
        for c in rising + falling:
            merged[c["t0_index"]] = c
        all_cands = [merged[k] for k in sorted(merged.keys())]
    else:
        # unknown dir → default to rising semantics
        all_cands.extend(_scan(neg_mask, zero_mask, pos_mask,
                               neg_dwell, zero_dwell, pos_dwell))

    return all_cands


    # --- Direction handling ---
    all_cands = []
    if direction in (None, "rising"):
        all_cands.extend(_scan(neg_mask, zero_mask, pos_mask,
                               neg_dwell, zero_dwell, pos_dwell))
    elif direction == "falling":
        all_cands.extend(_scan(pos_mask, zero_mask, neg_mask,
                               pos_dwell, zero_dwell, neg_dwell))
    elif direction == "either":
        rising = _scan(neg_mask, zero_mask, pos_mask,
                       neg_dwell, zero_dwell, pos_dwell)
        falling = _scan(pos_mask, zero_mask, neg_mask,
                        pos_dwell, zero_dwell, neg_dwell)
        merged = {}
        for c in rising + falling:
            merged[c["t0_index"]] = c
        all_cands = [merged[k] for k in sorted(merged.keys())]
    else:
        all_cands.extend(_scan(neg_mask, zero_mask, pos_mask,
                               neg_dwell, zero_dwell, pos_dwell))

    return all_cands

def _eval_simple_tests(df, t0_idx, t, tests, inputs_map):
    def _sel(name): return df[inputs_map[name]].to_numpy()

    for test in tests:
        typ = test.get("type")
        signal = test.get("signal")
        if signal not in inputs_map:
            return False
        y = _sel(signal)

        w = test.get("_slice")
        seg = y[w[0]:w[1]] if w is not None else y
        if seg.size == 0:
            return False

        if typ == "range":
            lo = test.get("min", -np.inf)
            hi = test.get("max", np.inf)
            if not (np.nanmin(seg) >= lo and np.nanmax(seg) <= hi):
                return False

        elif typ == "delta":
            cmp = test.get("cmp")
            if cmp is None:
                raise ValueError("Condition test missing required key 'cmp' (see schema spec v0.1)")
            val = float(test.get("value", 0.0))
            ref = y[t0_idx]
            dseg = seg - ref
            cond = {
                ">=": np.nanmax(dseg) >= val,
                "<=": np.nanmin(dseg) <= val,
                ">":  np.nanmax(dseg) >  val,
                "<":  np.nanmin(dseg) <  val,
            }.get(cmp, False)
            if not cond:
                return False

        elif typ == "peak":
            kind = test.get("kind", "max")
            cmp = test.get("cmp")
            if cmp is None:
                raise ValueError("Condition test missing required key 'cmp' (see schema spec v0.1)")
            val = float(test.get("value", 0.0))
            peak_val = np.nanmax(seg) if kind == "max" else np.nanmin(seg)
            cond = {
                ">=": peak_val >= val,
                "<=": peak_val <= val,
                ">":  peak_val >  val,
                "<":  peak_val <  val,
            }.get(cmp, False)
            if not cond:
                return False
        else:
            return False
    return True

def _apply_conditions(df, dt, ev, t0_idx, inputs_map):
    """
    Evaluate pre/post conditions for an event candidate using a fully-resolved inputs_map.
    """
    t = _to_seconds(df["time_s"])

    def make_slice(within):
        start_s, end_s = within
        n = len(df)
        def _s2n(sec):
            k = _sec_to_samples_opt(sec, dt)
            return int(k) if (k is not None) else 0
        i0 = t0_idx + _s2n(start_s)
        i1 = t0_idx + _s2n(end_s)
        if i1 < i0:
            i0, i1 = i1, i0
        i0, i1 = _clip_bounds(n, i0, i1)
        if i1 <= i0:
            i1 = min(n, i0 + 1)
        return (i0, i1)

    # --- Preconditions ---
    for block in (ev.get("preconditions") or []):
        w = make_slice(block.get("within_s", [-np.inf, 0.0]))
        any_of = block.get("any_of"); all_of = block.get("all_of")
        if any_of:
            ok_any = False
            for test in any_of:
                test = dict(test); test["_slice"] = w
                if _eval_simple_tests(df, t0_idx, t, [test], inputs_map):
                    ok_any = True; break
            if not ok_any:
                return False
        if all_of:
            tests = []
            for test in all_of:
                test = dict(test); test["_slice"] = w
                tests.append(test)
            if not _eval_simple_tests(df, t0_idx, t, tests, inputs_map):
                return False

    # --- Postconditions ---
    for block in (ev.get("postconditions") or []):
        w = make_slice(block.get("within_s", [0.0, np.inf]))
        any_of = block.get("any_of"); all_of = block.get("all_of")
        if any_of:
            ok_any = False
            for test in (any_of or []):
                t2 = dict(test); t2["_slice"] = w
                if _eval_simple_tests(df, t0_idx, t, [t2], inputs_map):
                    ok_any = True; break
            if not ok_any:
                return False
        if all_of:
            tests = []
            for test in (all_of or []):
                t2 = dict(test); t2["_slice"] = w
                tests.append(t2)
            if tests and (not _eval_simple_tests(df, t0_idx, t, tests, inputs_map)):
                return False

    return True

def _debounce_and_select(
    cands,
    dt,
    min_gap_s,
    prefer_key="trigger_strength",
    prefer_abs=False,
    prefer_max=True,
):
    if not cands:
        return []
    if not min_gap_s or min_gap_s <= 0 or (not np.isfinite(dt) or dt <= 0):
        return cands

    min_gap = _sec_to_samples_opt(min_gap_s, dt)
    if min_gap is None or min_gap <= 0:
        return cands

    cands = sorted(cands, key=lambda d: d["t0_index"])
    out = []
    cluster = [cands[0]]

    def score(c):
        v = c.get(prefer_key)
        if v is None:
            return -np.inf if prefer_max else np.inf
        return abs(v) if prefer_abs else v

    for c in cands[1:]:
        if c["t0_index"] - cluster[-1]["t0_index"] < min_gap:
            cluster.append(c)
        else:
            # choose within-cluster winner according to prefer_max
            best = max(cluster, key=score) if prefer_max else min(cluster, key=score)
            out.append(best)
            cluster = [c]

    # last cluster
    best = max(cluster, key=score) if prefer_max else min(cluster, key=score)
    out.append(best)
    return out

def _resolve_interval_from_triggers(
    df, t, trig_results, metric_cfg, primary_trigger_id, fallback_indices
):
    """
    Resolve an interval [s_i, e_i) and times (s_t, e_t) based on trigger IDs.
    If no end_trigger is provided, or triggers missing, falls back to event window.
    """
    # Trigger IDs
    start_id = metric_cfg.get("start_trigger") or primary_trigger_id or "primary"
    end_id   = metric_cfg.get("end_trigger")

    # Fallback to event window if end trigger missing
    if not end_id:
        s_i, e_i = fallback_indices
        s_t = float(t[s_i])
        e_t = float(t[e_i - 1])
        return s_i, e_i, s_t, e_t

    # Look up trigger results
    s_c = trig_results.get(start_id)
    e_c = trig_results.get(end_id)
    if not s_c or not e_c:
        return None

    s_t = float(s_c.get("t0_time", np.nan))
    e_t = float(e_c.get("t0_time", np.nan))
    if not (np.isfinite(s_t) and np.isfinite(e_t)):
        return None
    if e_t <= s_t:
        return None

    # Enforce minimum delay if requested
    min_delay_s = float(metric_cfg.get("min_delay_s", 0.0))
    if (e_t - s_t) < min_delay_s:
        return None

    # Convert to indices
    s_i = int(s_c.get("t0_index"))
    e_i = int(e_c.get("t0_index"))
    n = len(df)
    s_i, e_i = _clip_bounds(n, s_i, e_i)
    if e_i <= s_i:
        return None

    # Return [start, end_exclusive) + (start_time, end_time)
    return s_i, e_i + 1, s_t, e_t

def _compute_metrics(
    df: pd.DataFrame,
    dt: float,
    ev: dict,
    t0_idx: int,
    start_idx: int,
    end_idx: int,
    trig_results: dict | None = None,
    primary_trigger_id: str | None = None,
):
    t = _to_seconds(df["time_s"])
    seg = df.iloc[start_idx:end_idx]
    metrics = ev.get("metrics", []) or []
    out = {}

    def _arr(name):
        return seg[ev["inputs"][name]].to_numpy() if name in ev["inputs"] else None

    for m in metrics:
        mtype = m.get("type"); signal = m.get("signal")
        if signal and signal not in ev["inputs"]:
            continue
        y = _arr(signal) if signal else None

        if mtype == "integral" and y is not None:
            dx = dt if (np.isfinite(dt) and dt > 0) else 1.0
            val = np.trapezoid(np.abs(y), dx=dx) if m.get("abs", False) else np.trapezoid(y, dx=dx)
            out[f"m_integral_{signal}{'_abs' if m.get('abs', False) else ''}"] = float(val)

        elif mtype == "peak" and y is not None:
            kind = m.get("kind", "max")
            if kind == "max":
                idx_rel = int(np.nanargmax(y)) if len(y) else 0
                val = float(np.nanmax(y)) if len(y) else np.nan
            else:
                idx_rel = int(np.nanargmin(y)) if len(y) else 0
                val = float(np.nanmin(y)) if len(y) else np.nan
            out[f"m_peak_{signal}"] = val
            if m.get("return_time", False):
                out[f"m_peak_{signal}_t"] = float(t[start_idx + idx_rel] - t[t0_idx])

        elif mtype == "time_above" and y is not None:
            thr = float(m.get("threshold", 0.0))
            dx = dt if (np.isfinite(dt) and dt > 0) else 1.0
            mask = y > thr
            val = float(np.sum(mask) * dx)
            out[f"m_time_above_{signal}_{thr:g}"] = val

        # ---------- generic interval-based metrics ----------
        elif mtype == "interval_stats":
            if trig_results is None:
                continue

            # Resolve interval: triggers -> indices & times
            fallback = (start_idx, end_idx)
            interval = _resolve_interval_from_triggers(
                df, t, trig_results, m, primary_trigger_id, fallback
            )
            if interval is None:
                continue

            s_i, e_i, s_t, e_t = interval

            # Which signal?
            signal_name = signal or "vel"
            col = ev["inputs"].get(signal_name)
            if not col or col not in df.columns:
                continue

            y = df[col].to_numpy()[s_i:e_i]
            if y.size == 0:
                continue

            # optional smoothing
            smooth_ms = m.get("smooth_ms", None)
            if smooth_ms is not None and np.isfinite(dt) and dt > 0:
                win = int(round((smooth_ms / 1000.0) / dt))
                if win > 1:
                    kernel = np.ones(win, dtype=float) / win
                    y_s = np.convolve(y, kernel, mode="same")
                else:
                    y_s = y
            else:
                y_s = y

            polarity = m.get("polarity", None)
            ops = m.get("ops") or []

            for op in ops:
                key_base = f"m_int_{signal_name}_{op}"

                if op == "mean":
                    out[key_base] = float(np.nanmean(y_s))

                elif op == "max":
                    out[key_base] = float(np.nanmax(y_s))

                elif op == "min":
                    out[key_base] = float(np.nanmin(y_s))

                elif op == "peak":
                    if polarity == "neg_to_pos":
                        val = float(np.nanmax(y_s))
                    elif polarity == "pos_to_neg":
                        val = float(np.nanmin(y_s))
                    else:
                        val = float(np.nanmax(np.abs(y_s)))
                    out[key_base] = val

                elif op == "delta":
                    out[key_base] = float(y_s[-1] - y_s[0])

                elif op == "integral":
                    dx = dt if (np.isfinite(dt) and dt > 0) else 1.0
                    out[key_base] = float(np.trapezoid(y_s, dx=dx))

                elif op == "time_above":
                    thr = float(m.get("threshold", 0.0))
                    dx = dt if (np.isfinite(dt) and dt > 0) else 1.0
                    mask = y_s > thr
                    out[f"{key_base}_{thr:g}"] = float(np.sum(mask) * dx)

                # Optional: more ops here later (std, RMS, skew, etc.)

            if m.get("return_debug", False):
                out[f"m_int_{signal_name}_t_start"] = float(s_t)
                out[f"m_int_{signal_name}_t_end"]   = float(e_t)


    return out

def _pick_secondary_candidate(st_cands, base_t0_sec, search_cfg):
    """
    Given a list of secondary trigger candidates (each with t0_time),
    select exactly one according to search.{min_delay_s, max_delay_s, direction}.

    - min_delay_s / max_delay_s are relative to base_t0_sec, and may be negative.
    - direction:
        'forward'  -> earliest in time within window
        'backward' -> latest in time within window
        'auto'     -> infer behaviour from delay signs:
                       * both >= 0      -> forward
                       * both <= 0      -> backward
                       * cross zero     -> pick closest in time to base
    """
    if not st_cands:
        return None

    # If base time is missing, fall back to earliest candidate
    if base_t0_sec is None or not np.isfinite(base_t0_sec):
        return min(st_cands, key=lambda d: d["t0_time"])

    search_cfg = search_cfg or {}
    try:
        min_delay = float(search_cfg.get("min_delay_s", 0.0) or 0.0)
    except Exception:
        min_delay = 0.0

    max_delay_raw = search_cfg.get("max_delay_s", None)
    if max_delay_raw is None:
        max_delay = None
    else:
        try:
            max_delay = float(max_delay_raw)
        except Exception:
            max_delay = None

    direction = (search_cfg.get("direction") or "forward").lower()
    if direction not in ("forward", "backward", "auto"):
        direction = "forward"

    # Filter by relative delay window
    filtered = []
    for c in st_cands:
        t = float(c.get("t0_time", np.nan))
        if not np.isfinite(t):
            continue
        rel = t - base_t0_sec  # seconds relative to base trigger
        if rel < min_delay:
            continue
        if (max_delay is not None) and (rel > max_delay):
            continue
        filtered.append((c, rel))

    if not filtered:
        return None

    # Helper choices
    def _earliest(cand_rel_list):
        return min(cand_rel_list, key=lambda cr: cr[0]["t0_time"])[0]

    def _latest(cand_rel_list):
        return max(cand_rel_list, key=lambda cr: cr[0]["t0_time"])[0]

    def _closest(cand_rel_list):
        return min(cand_rel_list, key=lambda cr: abs(cr[1]))[0]

    # Explicit direction overrides any auto logic
    if direction == "forward":
        return _earliest(filtered)
    if direction == "backward":
        return _latest(filtered)

    # direction == "auto"
    if max_delay is None:
        # Open-ended: decide from the sign of min_delay
        if min_delay >= 0:
            return _earliest(filtered)
        else:
            return _latest(filtered)

    # Both window bounds finite
    if max_delay <= 0:
        # Entire window is in the past
        return _latest(filtered)
    if min_delay >= 0:
        # Entire window is in the future
        return _earliest(filtered)

    # Mixed window: spans both sides of base_t0 → pick closest in time
    return _closest(filtered)
        
def detect_events_from_schema(
    df: Optional[pd.DataFrame] = None,
    schema: Optional[Dict[str, Any]] = None,
    *,
    meta: Optional[Dict[str, Any]] = None,
    event_ids=None,
):

    df, meta, schema = _require_inputs(df=df, meta=meta, schema=schema)

    # Optional absolute datetime anchoring (contract-reserved column)
    _t0_dt_raw = meta.get("t0_datetime")
    _t0_ts = pd.to_datetime(_t0_dt_raw, errors="coerce") if _t0_dt_raw is not None else None
    if _t0_ts is not None and pd.isna(_t0_ts):
        _t0_ts = None

    dt = _robust_dt(df, meta)
    if not np.isfinite(dt) or dt <= 0:
        print("[Detect] Warning: invalid dt; skipping time-based distances/edge windows; using prominence-only.")

    defaults = schema.get("defaults", {}) or {}
    def_window = defaults.get("window", {}) or {}
    def_pre   = def_window.get("pre_s", 2.0)
    def_post  = def_window.get("post_s", 1.0)
    def_align = def_window.get("align", "trigger")

    # NEW: debounce defaults live under defaults.debounce
    def_debounce_cfg    = (defaults.get("debounce") or {})
    def_debounce_gap_s  = def_debounce_cfg.get("gap_s", 0.25)
    def_debounce_key    = def_debounce_cfg.get("prefer_key", None)   # may be None → use per-type default
    def_debounce_abs    = def_debounce_cfg.get("prefer_abs", False)
    def_debounce_max   = def_debounce_cfg.get("prefer_max", True)

    raw_events = (schema.get("events") or [])
    expanded = []
    for ev in raw_events:
        if event_ids and ev.get("id") not in set(event_ids):
            continue  # filter early by id if requested
        expanded.extend(_expand_event_by_sensors(ev, schema))

    events = expanded  # concrete events with explicit 'sensor'

    if event_ids:
        keep = set(event_ids)
        events = [e for e in events if e.get("id") in keep]


    rows = []
    n = len(df)
    tvec = df["time_s"].to_numpy()

    # Contract: event_id must be unique per *instance*.
    # We'll generate event_id as "{schema_id}:{occurrence_index}" per contract recommendation.
    # Keying by schema_id + sensor keeps occurrences stable across sensor-expanded events.
    occurrence_ctr: dict[tuple[str, str], int] = {}

    for ev in events:
        ev_id  = ev.get("id")
        if "SKIP_EVENTS" in globals():
            if ev_id in globals()["SKIP_EVENTS"]:
                print(f"[Skip] Event '{ev_id}' skipped per SKIP_EVENTS.")
                continue

        sensor = ev.get("sensor")
        trig   = ev.get("trigger", {}) or {}
        ttype  = trig.get("type")
        primary_id = trig.get("id") or "primary"
        sec_trigs = ev.get("secondary_triggers", []) or []

        # ---- Debounce config: per-trigger, with global defaults ----
        trig_deb = (trig.get("debounce") or {})
        # Primary gap_s: trigger-specific > defaults
        primary_gap_s = trig_deb.get("gap_s", def_debounce_gap_s)

        # prefer_key / prefer_abs:
        #  - per-trigger override wins
        #  - else fall back to defaults.debounce.*
        primary_pref_key = trig_deb.get("prefer_key", def_debounce_key)
        primary_pref_abs = trig_deb.get("prefer_abs", def_debounce_abs)
        primary_pref_max = trig_deb.get("prefer_max", def_debounce_max)
        
        inputs_map = _resolve_inputs_for_sensor(sensor, schema, meta=meta)

        # Quick sanity on trigger series
        sig = (ev.get("trigger") or {}).get("signal")
        col = inputs_map.get(sig) if sig else None
        if sig and col and col in df.columns:
            arr = df[col].to_numpy()
            if not np.isfinite(arr).any():
                print(f"[DEBUG] {ev_id}({sensor}): trigger series '{col}' is all non-finite")
            else:
                vmin, vmax = float(np.nanmin(arr)), float(np.nanmax(arr))
                if np.allclose(vmin, vmax):
                    print(f"[DEBUG] {ev_id}({sensor}): trigger '{col}' is flat (min=max={vmin:.3g})")
        elif sig:
            print(f"[DEBUG] {ev_id}({sensor}): missing trigger series for signal='{sig}' → inputs[{sig!r}]={col!r}")

        # ---- Validate against the resolved inputs map ----
        _validate_event_series_with_map(ev, df, inputs_map)

        # ---- Use a resolved copy of the event for all downstream calls ----
        ev_resolved = dict(ev)
        ev_resolved["inputs"] = inputs_map  # triggers & metrics use this

        # ---- Trigger detection ----
        if ttype == "local_extrema":
            cands = _trigger_local_extrema(df, dt, ev_resolved, base_t0_sec=None)
            prefer_key_default = "t0_index"
        elif ttype in ("simple_threshold_crossing", "threshold_crossing"):
            cands = _trigger_threshold_crossing(df, dt, ev_resolved, base_t0_sec=None)
            prefer_key_default = "t0_index"
        elif ttype == "zero_crossing":
            cands = _trigger_zero_crossing(df, dt, ev_resolved, base_t0_sec=None)
            prefer_key_default = "t0_index"
        elif ttype == "phased_threshold_crossing":
            cands = _trigger_phased_threshold_crossing(df, dt, ev_resolved, base_t0_sec=None)
            prefer_key_default = "t0_index"
        elif ttype == "custom":
            print(f"[WARN] Custom trigger not implemented for '{ev_id}'. Skipping.")
            cands, prefer_key_default = [], "t0_index"
        else:
            print(f"[WARN] Unknown trigger type '{ttype}' for '{ev_id}'. Skipping.")
            cands, prefer_key_default = [], "t0_index"

        # Effective prefer_key / prefer_abs / prefer_max for PRIMARY debouncing
        if primary_pref_key is not None:
            effective_prefer_key = primary_pref_key
        else:
            effective_prefer_key = prefer_key_default

        if primary_pref_abs is not None:
            effective_prefer_abs = bool(primary_pref_abs)
        else:
            effective_prefer_abs = False  # default: no abs() unless requested

        if primary_pref_max is not None:
            effective_prefer_max = bool(primary_pref_max)
        else:
            effective_prefer_max = True  # default: pick max score

        print(f"[DEBUG] {ev_id}({sensor}): raw candidates={len(cands)}")



        # ---- Debounce (once) for primary trigger ----
        debounce_s = primary_gap_s
        cands = _debounce_and_select(
            cands,
            dt,
            debounce_s,
            prefer_key=effective_prefer_key,
            prefer_abs=effective_prefer_abs,
            prefer_max=effective_prefer_max,
        )
        print(f"[DEBUG] {ev_id}({sensor}): after debounce={len(cands)} "
              f"(gap={debounce_s}s, prefer_key={effective_prefer_key}, "
              f"prefer_abs={effective_prefer_abs})")
        
        # ---- Window / conditions / metrics ----
        window = ev.get("window", {}) or {}
        pre_s  = window.get("pre_s",  def_pre)
        post_s = window.get("post_s", def_post)
        align  = window.get("align",  def_align)

        max_nan_fraction = (ev.get("quality", {}) or {}).get("max_nan_fraction", None)
        skip_if_clipped  = (ev.get("quality", {}) or {}).get("skip_if_clipped", False)

        pre_n  = _sec_to_samples_opt(pre_s, dt)  or 0
        post_n = _sec_to_samples_opt(post_s, dt) or 0

        kept = 0
        for c in cands:
            t0_idx = c["t0_index"]
            start_idx = t0_idx - pre_n
            end_idx   = t0_idx + post_n + 1
            start_idx, end_idx = _clip_bounds(len(df), start_idx, end_idx)
            edge_clip = (start_idx == 0 or end_idx == len(df))

            # ---- CONDITIONS ----
            if not _apply_conditions(df, dt, ev_resolved, t0_idx, inputs_map):
                continue
            kept += 1

            seg = df.iloc[start_idx:end_idx]
            nan_frac = float(seg.isna().any(axis=1).mean())
            if (max_nan_fraction is not None) and (nan_frac > max_nan_fraction):
                continue

            if skip_if_clipped:
                clipped = False
                for key, colname in inputs_map.items():
                    if colname not in df.columns:
                        continue
                    arr = df[colname].to_numpy()
                    seg_arr = arr[start_idx:end_idx]
                    if np.any(seg_arr == np.nanmin(arr)) or np.any(seg_arr == np.nanmax(arr)):
                        clipped = True; break
                if clipped:
                    continue

            # ---- PRIMARY trigger result for this candidate ----
            trig_results = {}
            trig_results[primary_id] = dict(c)  # copy so we can add to it later if needed

            # ---- SECONDARY triggers (per primary candidate) ----
            sec_outputs: dict[str, dict] = {}
            for st in sec_trigs:
                if not isinstance(st, dict):
                    continue
                st_id   = st.get("id")
                st_type = st.get("type")
                if not st_id or not st_type:
                    continue

                base_name = st.get("base_trigger", primary_id)
                base_c = trig_results.get(base_name)
                if not base_c:
                    # no base trigger for this candidate → skip this secondary
                    continue

                base_t0_sec = float(base_c.get("t0_time", np.nan))
                if not np.isfinite(base_t0_sec):
                    continue

                # Build a resolved event dict for the secondary trigger
                st_ev = dict(ev_resolved)
                st_ev["trigger"] = st

                # Run the appropriate trigger type (SECONDARIES: all windowed via base_t0_sec)
                if st_type == "local_extrema":
                    st_cands = _trigger_local_extrema(df, dt, st_ev, base_t0_sec=base_t0_sec)
                elif st_type in ("simple_threshold_crossing", "threshold_crossing"):
                    st_cands = _trigger_threshold_crossing(df, dt, st_ev, base_t0_sec=base_t0_sec)
                elif st_type == "zero_crossing":
                    st_cands = _trigger_zero_crossing(df, dt, st_ev, base_t0_sec=base_t0_sec)
                elif st_type == "phased_threshold_crossing":
                    st_cands = _trigger_phased_threshold_crossing(df, dt, st_ev, base_t0_sec=base_t0_sec)
                else:
                    print(f"[WARN] Secondary trigger type '{st_type}' not implemented for '{ev_id}'.")
                    st_cands = []

                if not st_cands:
                    continue

                # ---- Secondary-specific debounce ----
                st_deb = (st.get("debounce") or {})
                st_gap_s    = st_deb.get("gap_s", primary_gap_s)
                st_pref_key = st_deb.get("prefer_key", effective_prefer_key)
                st_pref_abs = st_deb.get("prefer_abs", effective_prefer_abs)
                st_pref_max = st_deb.get("prefer_max", effective_prefer_max)

                if st_gap_s and st_gap_s > 0:
                    st_cands = _debounce_and_select(
                        st_cands,
                        dt,
                        st_gap_s,
                        prefer_key=st_pref_key,
                        prefer_abs=bool(st_pref_abs),
                        prefer_max=bool(st_pref_max),
                    )

                if not st_cands:
                    continue

                # --- New: use search.{min_delay_s,max_delay_s,direction} relative to base_t0_sec ---
                search_cfg = st.get("search", {}) or {}
                chosen = _pick_secondary_candidate(st_cands, base_t0_sec, search_cfg)
                if chosen is None:
                    continue

                trig_results[st_id] = chosen
                sec_outputs[st_id] = chosen
                

            # ---- Persist trigger timings into row columns (Option A) ----
            trigger_cols: dict[str, Any] = {}

            def _put_trigger(tid: str, c: dict) -> None:
                # Candidate dict contract: contains t0_time (sec) and t0_index (int)
                t = c.get("t0_time", np.nan)
                i = c.get("t0_index", -1)
                trigger_cols[f"{tid}_time_s"] = float(t) if np.isfinite(t) else np.nan
                trigger_cols[f"{tid}_idx"]    = int(i) if i is not None else -1

            # Primary trigger (write under schema trigger id)
            primary_c = trig_results.get(primary_id)
            if primary_c:
                _put_trigger(primary_id, primary_c)

            # Secondaries
            for tid, c in sec_outputs.items():
                _put_trigger(tid, c)

            # ---- METRICS ----
            m = _compute_metrics(
                df,
                dt,
                ev_resolved,
                t0_idx,
                start_idx,
                end_idx,
                trig_results=trig_results,
                primary_trigger_id=primary_id,
            )

            # ---- Contract mapping ----
            schema_id = ev_id                      # schema event definition id
            schema_version = schema.get("version") or schema.get("schema_version") or ""
            event_name = ev.get("label") or schema_id
            signal = (trig.get("signal") or "")    # schema terminology
            signal_col = inputs_map.get(signal) if signal else None
            signal_col = str(signal_col) if (signal_col is not None) else None
            signals = list((ev_resolved.get("inputs") or {}).keys())

            # Convert your internal [start_idx:end_idx) slicing to inclusive end_idx for contract
            end_idx_incl = int(max(start_idx, end_idx - 1))

            # event_id: unique per detected instance (Option B): "{schema_id}:{sensor}:{occurrence_index}"
            key = (schema_id, str(sensor))
            occ = occurrence_ctr.get(key, 0)
            occurrence_ctr[key] = occ + 1
            event_instance_id = f"{schema_id}:{sensor}:{occ}"

            # QC / optional fields
            qc_flags = []
            if edge_clip:
                qc_flags.append("edge_clipped")

            trigger_time_s = float(tvec[int(t0_idx)])
            row = {
                # ---- Row Identity (required) ----
                "event_id": event_instance_id,
                "schema_id": schema_id,
                "schema_version": str(schema_version),
                "event_name": str(event_name),

                # ---- Signal Context (required) ----
                "signal": str(signal),
                "signal_col": signal_col,
                "signals": signals or None,


                # ---- Time & Index Anchoring (required) ----
                "start_idx": int(start_idx),
                "end_idx": int(end_idx_incl),
                "start_time_s": float(tvec[int(start_idx)]),
                "end_time_s": float(tvec[int(end_idx_incl)]),
                "trigger_idx": int(t0_idx),
                "trigger_time_s": float(trigger_time_s),
                "trigger_datetime": (_t0_ts + pd.to_timedelta(trigger_time_s, unit="s")) if _t0_ts is not None else None,

                # ---- Provenance & QC (required) ----
                "detector_version": "schema/v0",
                "params_hash": _hash_event_params(ev_resolved, schema_version=schema_version),

                # ---- Optional / future-proof ----
                "qc_flags": qc_flags or None,
                "score": c.get("trigger_strength", None),
                "meta": {
                    "sensor": sensor,
                    "trigger_type": ttype,
                    "window": {"pre_s": float(pre_s), "post_s": float(post_s), "align": str(align)},
                    "edge_clip": bool(edge_clip),
                    "trigger_strength": c.get("trigger_strength"),
                    "trigger_value": c.get("trigger_value"),
                },
                
                # ---- NEW: Trigger-id columns (primary + secondaries) ----
                **trigger_cols,
            }

            # Optional: include segmentation if present
            if "segment_id" in df.columns:
                row["segment_id"] = df.iloc[int(t0_idx)]["segment_id"]

            # Optional: tags from schema (if you support them)
            if "tags" in ev and ev.get("tags") is not None:
                row["tags"] = ev.get("tags")

            # Optional: units (if you have a mapping; placeholder hook)
            # row["units"] = ...

            # Snapshot a few values at t0 using resolved inputs
            for k in ("disp","vel","acc","disp_norm"):
                colk = inputs_map.get(k)
                if colk in df.columns:
                    row[f"{k}_at_trigger"] = float(df.iloc[t0_idx][colk])

            # Save secondary trigger times (if any)
            if sec_outputs:
                row["meta"]["secondary_triggers"] = {
                    st_id: {"trigger_idx": int(sc["t0_index"]), "trigger_time_s": float(sc["t0_time"])}
                    for st_id, sc in sec_outputs.items()
                }

            row.update(m)
            rows.append(row)
            


    EVENTS_DF = pd.DataFrame(rows)

    if not EVENTS_DF.empty:
        EVENTS_DF = EVENTS_DF.sort_values(["schema_id","trigger_idx"]).reset_index(drop=True)


    globals()["EVENTS_DF"] = EVENTS_DF
    print(f"[Detect] Built EVENTS_DF with {len(EVENTS_DF)} rows "
          f"from {len(raw_events)} schema event(s) "
          f"→ {len(events)} sensor-expanded event(s).")
    if not EVENTS_DF.empty:
        print(EVENTS_DF[["event_id","schema_id","trigger_time_s","start_idx","end_idx"]].head(50).to_string(index=False))
    validate_events_df(EVENTS_DF, df=df)
    return EVENTS_DF

