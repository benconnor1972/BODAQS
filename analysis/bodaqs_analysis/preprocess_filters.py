from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .signalname import SignalNameParts, format_signal_name, parse_signal_name
from .signalspec import DEFAULT_SPEC, SignalSpec


@dataclass(frozen=True)
class ButterworthSmoothingConfig:
    cutoff_hz: float
    order: int
    op_tag: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cutoff_hz": float(self.cutoff_hz),
            "order": int(self.order),
            "op_tag": str(self.op_tag),
        }


def _is_int_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, np.integer)):
        return True
    if isinstance(value, (float, np.floating)):
        return bool(np.isfinite(value) and float(value).is_integer())
    return False


def _format_cutoff_token(cutoff_hz: float) -> str:
    # Use 12 significant digits to avoid noisy float tails while preserving intent.
    as_decimal = Decimal(f"{float(cutoff_hz):.12g}")
    text = format(as_decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not text:
        text = "0"
    return text.replace(".", "p")


def build_butterworth_op_tag(cutoff_hz: float, order: int) -> str:
    return f"Butterworth_{_format_cutoff_token(cutoff_hz)}Hz_{int(order)}Order"


def normalize_butterworth_smoothing_configs(
    configs: Optional[Sequence[Mapping[str, Any]]],
) -> List[ButterworthSmoothingConfig]:
    if configs is None:
        return []
    if isinstance(configs, (str, bytes)):
        raise ValueError("butterworth_smoothing must be a sequence of dicts, not a string")

    normalized: List[ButterworthSmoothingConfig] = []
    seen_tags: set[str] = set()

    for idx, raw in enumerate(configs):
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"butterworth_smoothing[{idx}] must be a dict with cutoff_hz/order keys"
            )

        cutoff_raw = raw.get("cutoff_hz", None)
        order_raw = raw.get("order", None)

        try:
            cutoff_hz = float(cutoff_raw)
        except (TypeError, ValueError):
            raise ValueError(f"butterworth_smoothing[{idx}].cutoff_hz must be numeric") from None
        if not np.isfinite(cutoff_hz) or cutoff_hz <= 0:
            raise ValueError(f"butterworth_smoothing[{idx}].cutoff_hz must be > 0")

        if not _is_int_like(order_raw):
            raise ValueError(f"butterworth_smoothing[{idx}].order must be a positive integer")
        order = int(order_raw)
        if order <= 0:
            raise ValueError(f"butterworth_smoothing[{idx}].order must be a positive integer")

        op_tag = build_butterworth_op_tag(cutoff_hz=cutoff_hz, order=order)
        if op_tag in seen_tags:
            raise ValueError(
                f"Duplicate Butterworth smoothing config after canonicalization: {op_tag}"
            )
        seen_tags.add(op_tag)

        normalized.append(
            ButterworthSmoothingConfig(cutoff_hz=float(cutoff_hz), order=int(order), op_tag=op_tag)
        )
    return normalized


def _is_displacement_signal(col: str, *, spec: SignalSpec) -> bool:
    try:
        parts = parse_signal_name(col, spec=spec)
    except Exception:
        return False
    return parts.kind == "" and parts.unit == "mm"


def _filter_single_series_safely(
    y: pd.Series,
    *,
    sos: np.ndarray,
) -> Tuple[Optional[np.ndarray], Optional[str]]:
    y_num = pd.to_numeric(y, errors="coerce")
    if y_num.notna().sum() < 3:
        return None, "too_few_valid_samples"

    y_filled = y_num.interpolate(limit_direction="both")
    if y_filled.isna().any():
        return None, "cannot_interpolate_nans"

    arr = y_filled.to_numpy(dtype=float)
    try:
        from scipy.signal import sosfiltfilt  # type: ignore
    except Exception as exc:
        return None, f"scipy_unavailable:{exc}"

    try:
        filt = sosfiltfilt(sos, arr)
    except ValueError as exc:
        return None, f"short_or_invalid_for_sosfiltfilt:{exc}"

    filt = np.asarray(filt, dtype=float)
    nan_mask = y_num.isna().to_numpy(dtype=bool)
    if nan_mask.any():
        filt[nan_mask] = np.nan
    return filt, None


def apply_butterworth_smoothing(
    df: pd.DataFrame,
    *,
    sample_rate_hz: float,
    configs: Sequence[ButterworthSmoothingConfig],
    generate_residuals: bool = False,
    spec: SignalSpec = DEFAULT_SPEC,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if not np.isfinite(sample_rate_hz) or float(sample_rate_hz) <= 0:
        raise ValueError("sample_rate_hz must be finite and > 0 for Butterworth smoothing")

    out = df.copy()
    warnings: List[str] = []
    skipped: List[Dict[str, Any]] = []
    generated: List[Dict[str, Any]] = []
    generated_residuals: List[Dict[str, Any]] = []

    eligible_cols = [
        str(c)
        for c in out.columns
        if pd.api.types.is_numeric_dtype(out[c]) and _is_displacement_signal(str(c), spec=spec)
    ]

    if not configs:
        return out, {
            "configs": [],
            "eligible_columns": eligible_cols,
            "generated": generated,
            "generated_residuals": generated_residuals,
            "skipped": skipped,
            "warnings": warnings,
            "sample_rate_hz": float(sample_rate_hz),
            "generate_residuals": bool(generate_residuals),
        }

    nyquist_hz = 0.5 * float(sample_rate_hz)
    if nyquist_hz <= 0:
        raise ValueError("Nyquist frequency is non-positive; check sample_rate_hz")

    for cfg in configs:
        if cfg.cutoff_hz >= nyquist_hz:
            raise ValueError(
                f"Invalid Butterworth config {cfg.op_tag}: cutoff_hz ({cfg.cutoff_hz}) "
                f"must be below Nyquist ({nyquist_hz})"
            )

    try:
        from scipy.signal import butter  # type: ignore
    except Exception as exc:
        raise ImportError(
            "Butterworth smoothing requested, but scipy.signal is unavailable"
        ) from exc

    for cfg in configs:
        sos = butter(
            N=int(cfg.order),
            Wn=float(cfg.cutoff_hz),
            btype="lowpass",
            fs=float(sample_rate_hz),
            output="sos",
        )

        for src_col in eligible_cols:
            parts = parse_signal_name(src_col, spec=spec)
            dst_col = format_signal_name(
                SignalNameParts(
                    base=parts.base,
                    kind=parts.kind,
                    domain=parts.domain,
                    unit=parts.unit,
                    ops=tuple(list(parts.ops) + [cfg.op_tag]),
                ),
                spec=spec,
            )

            if dst_col in out.columns:
                skipped.append(
                    {
                        "source_col": src_col,
                        "op_tag": cfg.op_tag,
                        "reason": "output_column_already_exists",
                    }
                )
                continue

            filt, err = _filter_single_series_safely(out[src_col], sos=sos)
            if err is not None or filt is None:
                msg = (
                    f"[Butterworth] Skipped {src_col} with {cfg.op_tag}: {err or 'unknown_error'}"
                )
                warnings.append(msg)
                skipped.append(
                    {
                        "source_col": src_col,
                        "op_tag": cfg.op_tag,
                        "reason": err or "unknown_error",
                    }
                )
                continue

            out[dst_col] = filt
            generated.append(
                {
                    "source_col": src_col,
                    "output_col": dst_col,
                    "op_tag": cfg.op_tag,
                    "cutoff_hz": float(cfg.cutoff_hz),
                    "order": int(cfg.order),
                }
            )

            if generate_residuals:
                resid_col = f"{dst_col}_resid"
                if resid_col in out.columns:
                    skipped.append(
                        {
                            "source_col": src_col,
                            "op_tag": "diff",
                            "reason": "residual_output_column_already_exists",
                            "output_col": resid_col,
                        }
                    )
                else:
                    src_arr = pd.to_numeric(out[src_col], errors="coerce").to_numpy(dtype=float)
                    resid = src_arr - filt
                    out[resid_col] = resid
                    generated_residuals.append(
                        {
                            "source_col": src_col,
                            "smoothed_col": dst_col,
                            "output_col": resid_col,
                            "op_tag": "diff",
                        }
                    )

    return out, {
        "configs": [cfg.as_dict() for cfg in configs],
        "eligible_columns": eligible_cols,
        "generated": generated,
        "generated_residuals": generated_residuals,
        "skipped": skipped,
        "warnings": warnings,
        "sample_rate_hz": float(sample_rate_hz),
        "generate_residuals": bool(generate_residuals),
    }
