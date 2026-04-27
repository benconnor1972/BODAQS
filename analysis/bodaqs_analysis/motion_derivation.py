from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .preprocess_filters import build_butterworth_op_tag
from .signal_selectors import resolve_signal_selector
from .signalname import SignalNameParts, format_signal_name, parse_signal_name
from .signalspec import DEFAULT_SPEC, SignalSpec
from .va import _effective_savgol_params, _savgol_numpy


@dataclass(frozen=True)
class MaterializedSavgolWindow:
    requested_window_ms: float
    requested_samples: int
    window_points: int
    poly_order: int
    adjusted: bool
    warnings: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "requested_window_ms": float(self.requested_window_ms),
            "requested_samples": int(self.requested_samples),
            "window_points": int(self.window_points),
            "poly_order": int(self.poly_order),
            "adjusted": bool(self.adjusted),
            "warnings": list(self.warnings),
        }


def build_savgol_op_tag(window_ms: float, poly_order: int) -> str:
    """Return a parser-safe op token for Savitzky-Golay derivative provenance."""
    return f"Savgol{_format_decimal_token(window_ms)}ms{int(poly_order)}Poly"


def sg_window_samples(
    window_ms: float,
    fs_hz: float,
    poly_order: int,
    *,
    signal_length: Optional[int] = None,
    strict: bool = True,
) -> MaterializedSavgolWindow:
    """Materialize a user-facing S-G window duration into valid sample counts."""
    window_ms = _positive_float(window_ms, "window_ms")
    fs_hz = _positive_float(fs_hz, "fs_hz")
    poly_order = _positive_int(poly_order, "poly_order")

    requested = int(round(window_ms * 1e-3 * fs_hz))
    window = max(1, requested)
    warnings: List[str] = []

    if window % 2 == 0:
        window += 1
        warnings.append("rounded window adjusted to odd sample count")

    min_window = poly_order + 2
    if min_window % 2 == 0:
        min_window += 1
    if window < min_window:
        window = min_window
        warnings.append("window increased to exceed polynomial order")

    if signal_length is not None:
        signal_length = _positive_int(signal_length, "signal_length")
        if window > signal_length:
            candidate = signal_length if signal_length % 2 == 1 else signal_length - 1
            if candidate < 3:
                if strict:
                    raise ValueError(
                        "Signal is too short for Savitzky-Golay derivation: "
                        f"signal_length={signal_length}"
                    )
                candidate = max(1, candidate)
            if candidate <= poly_order:
                if strict:
                    raise ValueError(
                        "Signal is too short for requested Savitzky-Golay polynomial: "
                        f"signal_length={signal_length}, poly_order={poly_order}"
                    )
                poly_order = max(1, candidate - 1)
                warnings.append("polynomial order reduced for short signal")
            window = candidate
            warnings.append("window reduced for available signal length")

    adjusted = window != requested or bool(warnings)
    return MaterializedSavgolWindow(
        requested_window_ms=float(window_ms),
        requested_samples=int(requested),
        window_points=int(window),
        poly_order=int(poly_order),
        adjusted=bool(adjusted),
        warnings=tuple(warnings),
    )


def derive_motion_channels(
    session: Mapping[str, Any],
    motion_derivation: Optional[Mapping[str, Any]],
    *,
    sample_rate_hz: float,
    strict: bool = True,
    spec: SignalSpec = DEFAULT_SPEC,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Generate filtered displacement, velocity, and acceleration analysis channels.

    This is intentionally a reusable stage helper. It does not mutate ``session``
    and does not rebuild the session signal registry; callers can merge the
    returned dataframe and metadata during pipeline integration.
    """
    df = session.get("df")
    if not isinstance(df, pd.DataFrame):
        raise ValueError("session['df'] must be a pandas DataFrame")

    sample_rate_hz = _positive_float(sample_rate_hz, "sample_rate_hz")
    config = dict(motion_derivation or {})
    if not bool(config.get("enabled", False)):
        return df.copy(), {
            "enabled": False,
            "generated": [],
            "skipped": [],
            "warnings": [],
            "sample_rate_hz": float(sample_rate_hz),
        }

    sources = config.get("sources") or []
    primary = config.get("primary")
    secondary = config.get("secondary") or []
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        raise ValueError("motion_derivation.sources must be a list")
    if not isinstance(primary, Mapping):
        raise ValueError("motion_derivation.primary must be an object when enabled")
    if not isinstance(secondary, Sequence) or isinstance(secondary, (str, bytes)):
        raise ValueError("motion_derivation.secondary must be a list")

    out = df.copy()
    generated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    warnings: List[str] = []
    generated_channel_info: Dict[str, Dict[str, Any]] = {}

    profiles: List[Tuple[str, Mapping[str, Any], str]] = [("primary", primary, "primary_analysis")]
    for raw_profile in secondary:
        if not isinstance(raw_profile, Mapping):
            raise ValueError("motion_derivation.secondary entries must be objects")
        profiles.append((str(raw_profile.get("id")), raw_profile, "secondary_analysis"))

    for source_idx, source in enumerate(sources):
        if not isinstance(source, Mapping):
            raise ValueError(f"motion_derivation.sources[{source_idx}] must be an object")
        source_id = str(source.get("id") or f"source_{source_idx}").strip()
        selector = source.get("selector")
        source_col = resolve_signal_selector(
            session,
            selector if isinstance(selector, Mapping) else None,
            purpose=f"motion_derivation source {source_id!r}",
            allow_missing=not strict,
        )
        if source_col is None:
            skipped.append({"source_id": source_id, "reason": "source_not_found", "selector": selector})
            continue
        if source_col not in out.columns:
            skipped.append({"source_id": source_id, "source_col": source_col, "reason": "source_column_missing"})
            continue

        for profile_id, profile, role in profiles:
            try:
                profile_result = _derive_profile_for_source(
                    out,
                    source_col=source_col,
                    source_id=source_id,
                    profile_id=profile_id,
                    role=role,
                    profile=profile,
                    sample_rate_hz=sample_rate_hz,
                    spec=spec,
                    strict=strict,
                )
            except Exception:
                if strict:
                    raise
                skipped.append(
                    {
                        "source_id": source_id,
                        "source_col": source_col,
                        "profile_id": profile_id,
                        "reason": "derivation_failed",
                    }
                )
                continue

            generated_by_col = {str(item.get("output_col")): item for item in profile_result["generated"]}
            for col, values in profile_result["series"].items():
                if col in out.columns:
                    skipped.append(
                        {
                            "source_id": source_id,
                            "source_col": source_col,
                            "profile_id": profile_id,
                            "output_col": col,
                            "reason": "output_column_already_exists",
                        }
                    )
                    continue
                out[col] = values
                generated_channel_info[col] = profile_result["channel_info"][col]
                generated_item = generated_by_col.get(str(col))
                if generated_item is not None:
                    generated.append(generated_item)

            warnings.extend(profile_result["warnings"])

    return out, {
        "enabled": True,
        "generated": generated,
        "skipped": skipped,
        "warnings": warnings,
        "sample_rate_hz": float(sample_rate_hz),
        "generated_channel_info": generated_channel_info,
    }


def _derive_profile_for_source(
    df: pd.DataFrame,
    *,
    source_col: str,
    source_id: str,
    profile_id: str,
    role: str,
    profile: Mapping[str, Any],
    sample_rate_hz: float,
    spec: SignalSpec,
    strict: bool,
) -> Dict[str, Any]:
    source_parts = parse_signal_name(source_col, spec=spec)
    if source_parts.kind != "" or source_parts.unit != "mm":
        raise ValueError(f"motion derivation source must be engineered displacement [mm], got {source_col!r}")

    disp_cutoff = _positive_float(profile.get("displacement_lowpass_hz"), "displacement_lowpass_hz")
    disp_order = _positive_int(profile.get("displacement_lowpass_order"), "displacement_lowpass_order")
    vel_cutoff = _positive_float(profile.get("velocity_lowpass_hz"), "velocity_lowpass_hz")
    vel_order = _positive_int(profile.get("velocity_lowpass_order"), "velocity_lowpass_order")
    acc_cutoff = _positive_float(profile.get("acceleration_lowpass_hz"), "acceleration_lowpass_hz")
    acc_order = _positive_int(profile.get("acceleration_lowpass_order"), "acceleration_lowpass_order")
    sg_poly = _positive_int(profile.get("sg_polyorder"), "sg_polyorder")

    for name, cutoff in (
        ("displacement_lowpass_hz", disp_cutoff),
        ("velocity_lowpass_hz", vel_cutoff),
        ("acceleration_lowpass_hz", acc_cutoff),
    ):
        _validate_cutoff(cutoff, sample_rate_hz=sample_rate_hz, name=name)

    disp_bw_tag = build_butterworth_op_tag(disp_cutoff, disp_order)
    vel_sg = sg_window_samples(
        _positive_float(profile.get("velocity_sg_window_ms"), "velocity_sg_window_ms"),
        sample_rate_hz,
        sg_poly,
        signal_length=len(df),
        strict=strict,
    )
    acc_sg = sg_window_samples(
        _positive_float(profile.get("acceleration_sg_window_ms"), "acceleration_sg_window_ms"),
        sample_rate_hz,
        sg_poly,
        signal_length=len(df),
        strict=strict,
    )
    vel_sg_tag = build_savgol_op_tag(vel_sg.requested_window_ms, vel_sg.poly_order)
    acc_sg_tag = build_savgol_op_tag(acc_sg.requested_window_ms, acc_sg.poly_order)
    vel_bw_tag = build_butterworth_op_tag(vel_cutoff, vel_order)
    acc_bw_tag = build_butterworth_op_tag(acc_cutoff, acc_order)

    source_series = _numeric_interpolated(df[source_col])
    disp_filtered = _butterworth_lowpass(
        source_series,
        sample_rate_hz=sample_rate_hz,
        cutoff_hz=disp_cutoff,
        order=disp_order,
    )

    vel = _savgol_derivative(
        disp_filtered,
        window_points=vel_sg.window_points,
        poly_order=vel_sg.poly_order,
        deriv=1,
        dt=1.0 / sample_rate_hz,
    )
    acc = _savgol_derivative(
        disp_filtered,
        window_points=acc_sg.window_points,
        poly_order=acc_sg.poly_order,
        deriv=2,
        dt=1.0 / sample_rate_hz,
    )
    vel_filtered = _butterworth_lowpass(
        pd.Series(vel, index=df.index),
        sample_rate_hz=sample_rate_hz,
        cutoff_hz=vel_cutoff,
        order=vel_order,
    )
    acc_filtered = _butterworth_lowpass(
        pd.Series(acc, index=df.index),
        sample_rate_hz=sample_rate_hz,
        cutoff_hz=acc_cutoff,
        order=acc_order,
    )

    nan_mask = pd.to_numeric(df[source_col], errors="coerce").isna().to_numpy(dtype=bool)
    for arr in (disp_filtered, vel_filtered, acc_filtered):
        arr[nan_mask] = np.nan

    source_ops = tuple(source_parts.ops)
    disp_col = _format_derived_col(
        source_parts,
        base=source_parts.base,
        unit="mm",
        ops=source_ops + (disp_bw_tag,),
        spec=spec,
    )
    vel_col = _format_derived_col(
        source_parts,
        base=f"{source_parts.base}_vel",
        unit="mm/s",
        ops=source_ops + (disp_bw_tag, vel_sg_tag, vel_bw_tag),
        spec=spec,
    )
    acc_col = _format_derived_col(
        source_parts,
        base=f"{source_parts.base}_acc",
        unit="mm/s^2",
        ops=source_ops + (disp_bw_tag, acc_sg_tag, acc_bw_tag),
        spec=spec,
    )

    generated: List[Dict[str, Any]] = []
    channel_info: Dict[str, Dict[str, Any]] = {}
    for output_col, quantity, unit, ops in (
        (disp_col, "disp", "mm", (disp_bw_tag,)),
        (vel_col, "vel", "mm/s", (disp_bw_tag, vel_sg_tag, vel_bw_tag)),
        (acc_col, "acc", "mm/s^2", (disp_bw_tag, acc_sg_tag, acc_bw_tag)),
    ):
        generated.append(
            {
                "source_id": source_id,
                "source_col": source_col,
                "profile_id": profile_id,
                "role": role,
                "output_col": output_col,
                "quantity": quantity,
                "unit": unit,
            }
        )
        channel_info[output_col] = {
            "unit": unit,
            "domain": source_parts.domain,
            "quantity": quantity,
            "source": [source_col],
            "source_columns": [source_col],
            "processing_role": role,
            "motion_source_id": source_id,
            "motion_profile_id": profile_id,
            "op_chain": list(source_ops + tuple(ops)),
            "derivation": {
                "method": "motion_derivation",
                "source_col": source_col,
                "displacement_lowpass_hz": float(disp_cutoff),
                "displacement_lowpass_order": int(disp_order),
                "velocity_sg_window": vel_sg.as_dict(),
                "velocity_lowpass_hz": float(vel_cutoff),
                "velocity_lowpass_order": int(vel_order),
                "acceleration_sg_window": acc_sg.as_dict(),
                "acceleration_lowpass_hz": float(acc_cutoff),
                "acceleration_lowpass_order": int(acc_order),
            },
        }

    return {
        "series": {
            disp_col: disp_filtered,
            vel_col: vel_filtered,
            acc_col: acc_filtered,
        },
        "generated": generated,
        "channel_info": channel_info,
        "warnings": list(vel_sg.warnings + acc_sg.warnings),
    }


def _format_derived_col(
    source_parts: SignalNameParts,
    *,
    base: str,
    unit: str,
    ops: Sequence[str],
    spec: SignalSpec,
) -> str:
    return format_signal_name(
        SignalNameParts(
            base=base,
            kind="",
            domain=source_parts.domain,
            unit=unit,
            ops=tuple(ops),
        ),
        spec=spec,
    )


def _savgol_derivative(
    y: np.ndarray,
    *,
    window_points: int,
    poly_order: int,
    deriv: int,
    dt: float,
) -> np.ndarray:
    eff = _effective_savgol_params(len(y), window_points, poly_order)
    if eff is None:
        if len(y) >= 2:
            if deriv == 1:
                return np.gradient(y, dt)
            return np.gradient(np.gradient(y, dt), dt)
        return np.full_like(y, np.nan, dtype=float)
    w_eff, p_eff = eff
    try:
        from scipy.signal import savgol_filter  # type: ignore

        return np.asarray(savgol_filter(y, w_eff, p_eff, deriv=deriv, delta=dt, mode="interp"), dtype=float)
    except Exception:
        return np.asarray(_savgol_numpy(y, w_eff, p_eff, deriv=deriv, dt=dt), dtype=float)


def _butterworth_lowpass(
    series: pd.Series,
    *,
    sample_rate_hz: float,
    cutoff_hz: float,
    order: int,
) -> np.ndarray:
    try:
        from scipy.signal import butter, sosfiltfilt  # type: ignore
    except Exception as exc:
        raise ImportError("Motion derivation requires scipy.signal for Butterworth filtering") from exc

    sos = butter(
        N=int(order),
        Wn=float(cutoff_hz),
        btype="lowpass",
        fs=float(sample_rate_hz),
        output="sos",
    )
    return np.asarray(sosfiltfilt(sos, _numeric_interpolated(series).to_numpy(dtype=float)), dtype=float)


def _numeric_interpolated(series: pd.Series) -> pd.Series:
    y = pd.to_numeric(series, errors="coerce")
    if y.notna().sum() < 3:
        raise ValueError("series has too few valid samples")
    y = y.interpolate(limit_direction="both")
    if y.isna().any():
        raise ValueError("series contains NaNs that could not be interpolated")
    return y


def _validate_cutoff(cutoff_hz: float, *, sample_rate_hz: float, name: str) -> None:
    nyquist_hz = 0.5 * float(sample_rate_hz)
    if cutoff_hz >= nyquist_hz:
        raise ValueError(f"{name} ({cutoff_hz}) must be below Nyquist ({nyquist_hz})")


def _positive_float(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric") from None
    if not np.isfinite(out) or out <= 0:
        raise ValueError(f"{name} must be > 0")
    return out


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    if isinstance(value, (int, np.integer)):
        out = int(value)
    elif isinstance(value, (float, np.floating)):
        if not np.isfinite(value) or not float(value).is_integer():
            raise ValueError(f"{name} must be a positive integer")
        out = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise ValueError(f"{name} must be a positive integer")
        out = int(text)
    else:
        raise ValueError(f"{name} must be a positive integer") from None
    if out <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return out


def _format_decimal_token(value: float) -> str:
    as_decimal = Decimal(f"{float(value):.12g}")
    text = format(as_decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not text:
        text = "0"
    return text.replace(".", "p")
