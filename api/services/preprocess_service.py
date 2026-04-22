from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Dict

import numpy as np

from bodaqs_analysis.pipeline import run_macro
from api.schemas.preprocess import PreprocessConfig

_EXCLUDE_COLS = {"active_mask_qc"}

# Column dtypes that can be represented as float32 signals
_NUMERIC_KINDS = frozenset("biufc")  # bool, int, uint, float, complex


def _is_numeric_col(series) -> bool:
    """Return True if the column can be safely cast to float32."""
    return series.dtype.kind in _NUMERIC_KINDS


def _cols_to_base64_float32(df, cols: list[str]) -> dict[str, str]:
    result = {}
    for col in cols:
        arr = df[col].to_numpy(dtype=np.float32, na_value=np.nan)
        result[col] = base64.b64encode(arr.tobytes()).decode("ascii")
    return result


def run_preprocess(csv_bytes: bytes, config: PreprocessConfig, filename: str = "input.csv") -> Dict[str, Any]:
    source_sha256 = hashlib.sha256(csv_bytes).hexdigest()

    # Strip .gz suffix so the CSV is written with its original name
    orig_name = filename.removesuffix(".gz") if filename.endswith(".gz") else filename

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / orig_name  # session_id = stem of this path
        schema_path = Path(tmpdir) / "schema.yaml"
        csv_path.write_bytes(csv_bytes)
        schema_path.write_text(config.schema_yaml, encoding="utf-8")

        result = run_macro(
            str(csv_path),
            str(schema_path),
            zeroing_enabled=config.zeroing_enabled,
            zero_window_s=config.zero_window_s,
            zero_min_samples=config.zero_min_samples,
            clip_0_1=config.clip_0_1,
            active_signal_disp_col=config.active_signal_disp_col,
            active_signal_vel_col=config.active_signal_vel_col,
            active_disp_thresh=config.active_disp_thresh,
            active_vel_thresh=config.active_vel_thresh,
            active_window=config.active_window,
            active_padding=config.active_padding,
            active_min_seg=config.active_min_seg,
            normalize_ranges=config.normalize_ranges,
            sample_rate_hz=config.sample_rate_hz,
            butterworth_smoothing=[b.model_dump() for b in config.butterworth_smoothing] or None,
            butterworth_generate_residuals=config.butterworth_generate_residuals,
            strict=config.strict,
        )

    session = result["session"]
    df = session["df"]
    meta_clean = json.loads(json.dumps(session["meta"], default=str))
    signal_cols = [c for c in df.columns if c not in _EXCLUDE_COLS and _is_numeric_col(df[c])]

    events_df = result.get("events")
    metrics_df = result.get("metrics")

    events = events_df.to_dict("records") if events_df is not None and not events_df.empty else []
    metrics = metrics_df.to_dict("records") if metrics_df is not None and not metrics_df.empty else []

    # Ensure all event/metric values are JSON-serializable (numpy scalars → Python native)
    events = json.loads(json.dumps(events, default=str))
    metrics = json.loads(json.dumps(metrics, default=str))

    return {
        "session_id": str(session["session_id"]),
        "meta": meta_clean,
        "signals": {
            "column_names": signal_cols,
            "n_rows": len(df),
            "columns": _cols_to_base64_float32(df, signal_cols),
        },
        "events": events,
        "metrics": metrics,
        "source_sha256": source_sha256,
    }
