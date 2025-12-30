from __future__ import annotations
import io
from typing import Any, Dict, List, Tuple
import hashlib
import os
import yaml

def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()

def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def load_event_schema(path: str) -> Tuple[Dict[str, Any], str]:
    data_bytes = _read_file_bytes(path)
    h = _sha256(data_bytes)
    schema = yaml.safe_load(io.BytesIO(data_bytes))
    if not isinstance(schema, dict):
        raise ValueError("Top-level YAML must be a mapping (dict).")
    return schema, h

def _validate_debounce_block(prefix: str, deb: Any, issues: List[str]):
    """Validate a debounce mapping: {gap_s, prefer_key, prefer_abs, prefer_max}."""
    if deb is None:
        return
    if not isinstance(deb, dict):
        issues.append(f"{prefix}.debounce must be a mapping if present.")
        return
    gap = deb.get("gap_s", None)
    if gap is not None and not isinstance(gap, (int, float)):
        issues.append(f"{prefix}.debounce.gap_s must be a number (seconds) if present.")
    pref_key = deb.get("prefer_key", None)
    if pref_key is not None and not isinstance(pref_key, str):
        issues.append(f"{prefix}.debounce.prefer_key must be a string if present.")
    pref_abs = deb.get("prefer_abs", None)
    if pref_abs is not None and not isinstance(pref_abs, bool):
        issues.append(f"{prefix}.debounce.prefer_abs must be a boolean if present.")
    pref_max = deb.get("prefer_max", None)
    if pref_max is not None and not isinstance(pref_max, bool):
        issues.append(f"{prefix}.debounce.prefer_max must be a boolean if present.")

def basic_validate(schema: Dict[str, Any]) -> List[str]:
    """Lightweight sanity checks; returns a list of issues (empty if OK)."""
    issues: List[str] = []

    # ---- defaults & naming ----
    defaults = schema.get("defaults", {}) or {}
    if not isinstance(defaults, dict):
        issues.append("defaults must be a mapping if present.")

    # deprecated global debounce_s
    if "debounce_s" in defaults:
        issues.append("defaults.debounce_s is deprecated; use defaults.debounce.gap_s instead.")

    def_debounce = defaults.get("debounce", None)
    if def_debounce is not None and not isinstance(def_debounce, dict):
        issues.append("defaults.debounce must be a mapping if present.")
    else:
        _validate_debounce_block("defaults", def_debounce, issues)

    naming = schema.get("naming", {}) or {}
    if naming and not isinstance(naming, dict):
        issues.append("naming must be a mapping if present.")

    suffixes = (naming.get("suffixes") or {}) if isinstance(naming, dict) else {}
    if not isinstance(suffixes, dict):
        issues.append("naming.suffixes must be a mapping of kind→suffix.")
        suffixes = {}
    if not suffixes:
        issues.append("naming.suffixes is empty or missing (suffix-only schema expects at least disp/vel/acc).")
    else:
        for k in ("disp", "vel", "acc"):
            if k not in suffixes:
                issues.append(f"naming.suffixes missing expected key '{k}' (disp/vel/acc).")

    # ---- events list ----
    events = schema.get("events")
    if not isinstance(events, list) or not events:
        issues.append("Missing or empty 'events' list.")
        return issues

    allowed_trigger_types = {
        "local_extrema",
        "simple_threshold_crossing",
        "threshold_crossing",
        "zero_crossing",
        "phased_threshold_crossing",
        "custom",
    }
    allowed_dirs = {"rising", "falling", "either"}

    for i, ev in enumerate(events):
        prefix = f"events[{i}]"
        if not isinstance(ev, dict):
            issues.append(f"{prefix}: must be a mapping.")
            continue

        # ---- sensors (suffix-only design requires them) ----
        sensors = ev.get("sensors", None)
        if not (isinstance(sensors, list) and sensors and all(isinstance(s, str) and s for s in sensors)):
            issues.append(f"{prefix}.sensors must be a non-empty list of strings.")

        # deprecated event-level debounce
        if "debounce" in ev:
            issues.append(f"{prefix}.debounce is deprecated; move debounce under trigger/debounce for each trigger.")
        if "debounce_s" in ev:
            issues.append(f"{prefix}.debounce_s is deprecated; use trigger.debounce.gap_s instead.")

        # ---- primary trigger ----
        trig = ev.get("trigger", None)
        if trig is None:
            issues.append(f"{prefix}: missing required key 'trigger'.")
            continue
        if not isinstance(trig, dict):
            issues.append(f"{prefix}.trigger must be a mapping.")
            continue

        ttype = trig.get("type")
        tsig  = trig.get("signal")
        tdir  = trig.get("dir", None)

        if ttype not in allowed_trigger_types:
            issues.append(f"{prefix}.trigger.type '{ttype}' not in allowed set {sorted(allowed_trigger_types)}.")
        if ttype != "custom" and not isinstance(tsig, str):
            issues.append(f"{prefix}.trigger.signal must be a string for non-custom triggers.")

        if ttype in ("simple_threshold_crossing", "threshold_crossing", "zero_crossing", "phased_threshold_crossing"):
            if tdir is not None and tdir not in allowed_dirs:
                issues.append(f"{prefix}.trigger.dir '{tdir}' must be one of {sorted(allowed_dirs)}.")

        # per-trigger debounce
        _validate_debounce_block(f"{prefix}.trigger", trig.get("debounce", None), issues)

        # --- secondary_triggers (optional) ---
        sec_trigs = ev.get("secondary_triggers", None)
        if sec_trigs is not None:
            if not isinstance(sec_trigs, list):
                issues.append(f"{prefix}.secondary_triggers must be a list if present.")
            else:
                for j, st in enumerate(sec_trigs):
                    sprefix = f"{prefix}.secondary_triggers[{j}]"
                    if not isinstance(st, dict):
                        issues.append(f"{sprefix}: must be a mapping.")
                        continue

                    st_type = st.get("type")
                    if st_type not in ("simple_threshold_crossing",
                                       "threshold_crossing",       # legacy alias
                                       "phased_threshold_crossing",
                                       "local_extrema",
                                       "zero_crossing",
                                       "custom"):
                        issues.append(f"{sprefix}.type '{st_type}' not in allowed set.")

                    st_id = st.get("id")
                    if not st_id:
                        issues.append(f"{sprefix}.id is required for secondary triggers.")

                    # Optional debounce block (per-secondary)
                    deb2 = st.get("debounce", None)
                    if deb2 is not None and not isinstance(deb2, dict):
                        issues.append(f"{sprefix}.debounce must be a mapping if present.")

                    # Optional search block (for relative time windowing)
                    search = st.get("search", None)
                    if search is not None:
                        if not isinstance(search, dict):
                            issues.append(f"{sprefix}.search must be a mapping if present.")
                        else:
                            for key in ("min_delay_s", "max_delay_s"):
                                val = search.get(key, None)
                                if val is not None and not isinstance(val, (int, float)):
                                    issues.append(
                                        f"{sprefix}.search.{key} must be a number (seconds) if present."
                                    )
                            sdir = search.get("direction", None)
                            if sdir is not None and sdir not in ("forward", "backward", "auto"):
                                issues.append(
                                    f"{sprefix}.search.direction must be 'forward', 'backward', or 'auto' if present."
                                )


        # ---- window & debounce (event-level window still valid) ----
        win = ev.get("window", None)
        if win is not None and not isinstance(win, dict):
            issues.append(f"{prefix}.window must be a mapping if present.")

        # ---- basic metrics shape ----
        metrics = ev.get("metrics", None)
        if metrics is not None:
            if not isinstance(metrics, list):
                issues.append(f"{prefix}.metrics must be a list if present.")
            else:
                for j, m in enumerate(metrics):
                    mprefix = f"{prefix}.metrics[{j}]"
                    if not isinstance(m, dict):
                        issues.append(f"{mprefix}: must be a mapping.")
                        continue
                    mtype = m.get("type")
                    if not isinstance(mtype, str):
                        issues.append(f"{mprefix}.type must be a string.")
                    if mtype == "interval_stats":
                        # not strictly required, but helpful to flag obvious mistakes
                        if "end_trigger" not in m:
                            issues.append(f"{mprefix}: interval_stats should specify 'end_trigger'.")

    return issues

def summarize_events(schema: Dict[str, Any]) -> pd.DataFrame:
    """
    Create a concise per-event summary table, including:
      - primary trigger type/signal/dir/value
      - sensors
      - window (pre_s/post_s/align)
      - primary debounce gap_s
      - secondary trigger IDs
    """
    rows = []

    defaults = schema.get("defaults", {}) or {}
    def_window = defaults.get("window", {}) or {}
    def_pre   = def_window.get("pre_s", None)
    def_post  = def_window.get("post_s", None)
    def_align = def_window.get("align", None)

    def_debounce = (defaults.get("debounce") or {})
    def_gap_s    = def_debounce.get("gap_s", None)
    def_pref_key = def_debounce.get("prefer_key", None)
    def_pref_abs = def_debounce.get("prefer_abs", None)
    def_pref_max = def_debounce.get("prefer_max", None)

    for ev in schema.get("events", []) or []:
        trig = ev.get("trigger", {}) or {}
        ttype = trig.get("type")
        tsig  = trig.get("signal")
        tdir  = trig.get("dir") or trig.get("kind")  # kind for local_extrema
        tvalue = trig.get("value")

        # window (with defaults)
        window = ev.get("window", {}) or {}
        pre = window.get("pre_s",  def_pre)
        post = window.get("post_s", def_post)
        align = window.get("align", def_align)

        # debounce: per-trigger, falling back to defaults
        tdeb = trig.get("debounce", {}) or {}
        gap_s = tdeb.get("gap_s", def_gap_s)
        prefer_key = tdeb.get("prefer_key", def_pref_key)
        prefer_abs = tdeb.get("prefer_abs", def_pref_abs)
        prefer_max = tdeb.get("prefer_max", def_pref_max)

        metrics = ev.get("metrics", []) or []

        sensors = ev.get("sensors", [])
        sensors_str = ", ".join(sensors) if isinstance(sensors, list) else ""

        sec_trigs = ev.get("secondary_triggers", []) or []
        secondary_ids = ", ".join(
            str(st.get("id")) for st in sec_trigs
            if isinstance(st, dict) and st.get("id")
        )

        rows.append({
            "id": ev.get("id"),
            "label": ev.get("label"),
            "sensors": sensors_str,
            "trigger_type": ttype,
            "trigger_signal": tsig,
            "trigger_dir/kind": tdir,
            "trigger_value": tvalue,
            "pre_s": pre,
            "post_s": post,
            "align": align,
            "primary_gap_s": gap_s,
            "primary_prefer_key": prefer_key,
            "primary_prefer_abs": prefer_abs,
            "primary_prefer_max": prefer_max,
            "n_secondary_triggers": len(sec_trigs),
            "secondary_ids": secondary_ids,
            "n_metrics": len(metrics),
        })

    cols = [
        "id", "label", "sensors",
        "trigger_type", "trigger_signal", "trigger_dir/kind", "trigger_value",
        "pre_s", "post_s", "align",
        "primary_gap_s", "primary_prefer_key", "primary_prefer_abs", "primary_prefer_max",
        "n_secondary_triggers", "secondary_ids",
        "n_metrics",
    ]
    return pd.DataFrame(rows, columns=cols)
