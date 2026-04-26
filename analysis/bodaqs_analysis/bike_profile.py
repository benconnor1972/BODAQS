from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .sensor_aliases import canonical_sensor_id, normalize_sensor_token, sensors_match
from .signal_registry import build_signals_registry
from .signalname import SignalNameParts, format_signal_name


logger = logging.getLogger(__name__)

BIKE_PROFILE_SCHEMA = "bodaqs.bike_profile"
BIKE_PROFILE_VERSION = 1


def load_bike_profile(path: str | Path) -> Dict[str, Any]:
    """Load and minimally validate a BODAQS bike profile JSON document."""
    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Bike profile not found: {profile_path}")

    with profile_path.open("r", encoding="utf-8") as f:
        profile = json.load(f)

    validate_bike_profile(profile, path=profile_path)
    return profile


def validate_bike_profile(profile: Mapping[str, Any], *, path: Optional[str | Path] = None) -> None:
    """Validate the bike-profile fields required by the runtime resolver."""
    label = f" ({path})" if path is not None else ""
    if not isinstance(profile, Mapping):
        raise ValueError(f"Bike profile must be a JSON object{label}")
    if profile.get("schema") != BIKE_PROFILE_SCHEMA:
        raise ValueError(
            f"Unexpected bike profile schema{label}: {profile.get('schema')!r} "
            f"(expected {BIKE_PROFILE_SCHEMA!r})"
        )
    if int(profile.get("version", -1)) != BIKE_PROFILE_VERSION:
        raise ValueError(
            f"Unexpected bike profile version{label}: {profile.get('version')!r} "
            f"(expected {BIKE_PROFILE_VERSION})"
        )
    if not _nonempty_str(profile.get("bike_profile_id")):
        raise ValueError(f"Bike profile missing non-empty 'bike_profile_id'{label}")
    if not _nonempty_str(profile.get("display_name")):
        raise ValueError(f"Bike profile missing non-empty 'display_name'{label}")

    ranges = profile.get("normalization_ranges", [])
    if ranges is not None:
        if not isinstance(ranges, Sequence) or isinstance(ranges, (str, bytes, bytearray)):
            raise ValueError(f"Bike profile 'normalization_ranges' must be an array{label}")
        _validate_normalization_ranges(ranges, label=label)

    _validate_signal_transforms(profile.get("signal_transforms", []), label=label)


def apply_signal_transforms(
    session: Dict[str, Any],
    bike_profile: Mapping[str, Any],
    *,
    bike_profile_path: Optional[str | Path] = None,
    output_conflict_policy: str = "skip",
) -> Dict[str, Any]:
    """
    Apply enabled bike-profile signal transforms to ``session['df']``.

    The default conflict policy is conservative: if the target output column
    already exists, the transform is skipped and the existing column is kept.
    """
    if output_conflict_policy != "skip":
        raise ValueError("Only output_conflict_policy='skip' is currently supported")

    validate_bike_profile(bike_profile, path=bike_profile_path)
    _ensure_signal_registry(session)

    transforms = bike_profile.get("signal_transforms") or []
    if not transforms:
        _record_transform_application(
            session,
            bike_profile=bike_profile,
            bike_profile_path=bike_profile_path,
            generated=[],
            skipped=[],
            warnings=[],
        )
        return session

    df = session.get("df")
    if not isinstance(df, pd.DataFrame):
        raise ValueError("session['df'] must be a pandas DataFrame")

    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []

    for transform in transforms:
        if not isinstance(transform, Mapping):
            continue

        transform_id = str(transform.get("id"))
        if transform.get("enabled") is False:
            skipped.append({"transform_id": transform_id, "reason": "disabled"})
            continue

        input_selector = transform.get("input")
        output_semantics = transform.get("output")
        if not isinstance(input_selector, Mapping) or not isinstance(output_semantics, Mapping):
            continue

        signals = ((session.get("meta") or {}).get("signals") or {})
        matches = [
            str(col)
            for col, info in signals.items()
            if isinstance(info, Mapping) and _matches_selector(info, input_selector)
        ]

        if not matches:
            warning = f"bike_profile_signal_transform_input_unmatched:{transform_id}"
            warnings.append(warning)
            skipped.append(
                {
                    "transform_id": transform_id,
                    "reason": "input_unmatched",
                    "selector": dict(input_selector),
                }
            )
            logger.info(
                "Bike profile signal transform did not match an input signal: "
                "bike_profile_id=%s transform_id=%s selector=%s",
                bike_profile.get("bike_profile_id"),
                transform_id,
                dict(input_selector),
            )
            continue

        if len(matches) > 1:
            raise ValueError(
                "Bike profile signal transform matched multiple input signals: "
                f"transform_id={transform_id!r} matches={matches}"
            )

        input_col = matches[0]
        output_col = _output_column_name(output_semantics, fallback=transform_id)
        if output_col in df.columns:
            warning = f"bike_profile_signal_transform_output_exists:{transform_id}:{output_col}"
            warnings.append(warning)
            skipped.append(
                {
                    "transform_id": transform_id,
                    "reason": "output_exists",
                    "input_column": input_col,
                    "output_column": output_col,
                }
            )
            logger.info(
                "Bike profile signal transform skipped because output already exists: "
                "bike_profile_id=%s transform_id=%s output_column=%s",
                bike_profile.get("bike_profile_id"),
                transform_id,
                output_col,
            )
            continue

        values = pd.to_numeric(df[input_col], errors="coerce").to_numpy(dtype=float)
        df.loc[:, output_col] = _evaluate_transform(values, transform)
        _merge_channel_info(
            session,
            output_col,
            _channel_info_for_output(
                output_semantics,
                input_col=input_col,
                transform_id=transform_id,
            ),
        )
        generated.append(
            {
                "transform_id": transform_id,
                "input_column": input_col,
                "output_column": output_col,
                "method": str(transform.get("method")),
            }
        )
        logger.info(
            "Bike profile signal transform applied: bike_profile_id=%s transform_id=%s input_column=%s output_column=%s",
            bike_profile.get("bike_profile_id"),
            transform_id,
            input_col,
            output_col,
        )

        # Later transforms can consume signals generated by earlier transforms.
        build_signals_registry(session, strict=False)

    _record_transform_application(
        session,
        bike_profile=bike_profile,
        bike_profile_path=bike_profile_path,
        generated=generated,
        skipped=skipped,
        warnings=warnings,
    )
    return session


def _validate_normalization_ranges(ranges: Sequence[Any], *, label: str) -> None:
    seen_ids: set[str] = set()
    for i, item in enumerate(ranges):
        if not isinstance(item, Mapping):
            raise ValueError(f"Bike profile normalization_ranges[{i}] must be an object{label}")
        range_id = item.get("id")
        if not _nonempty_str(range_id):
            raise ValueError(f"Bike profile normalization_ranges[{i}] missing non-empty 'id'{label}")
        range_id = str(range_id)
        if range_id in seen_ids:
            raise ValueError(f"Bike profile duplicate normalization range id {range_id!r}{label}")
        seen_ids.add(range_id)

        signal = item.get("signal")
        if not isinstance(signal, Mapping) or not signal:
            raise ValueError(f"Bike profile normalization range {range_id!r} missing non-empty 'signal'{label}")

        try:
            full_range = float(item.get("full_range"))
        except (TypeError, ValueError):
            raise ValueError(f"Bike profile normalization range {range_id!r} has invalid 'full_range'{label}") from None
        if not math.isfinite(full_range) or full_range <= 0:
            raise ValueError(f"Bike profile normalization range {range_id!r} full_range must be > 0{label}")


def _validate_signal_transforms(transforms: Any, *, label: str) -> None:
    if transforms is None:
        return
    if not isinstance(transforms, Sequence) or isinstance(transforms, (str, bytes, bytearray)):
        raise ValueError(f"Bike profile 'signal_transforms' must be an array{label}")

    seen_ids: set[str] = set()
    for i, item in enumerate(transforms):
        if not isinstance(item, Mapping):
            raise ValueError(f"Bike profile signal_transforms[{i}] must be an object{label}")
        transform_id = item.get("id")
        if not _nonempty_str(transform_id):
            raise ValueError(f"Bike profile signal_transforms[{i}] missing non-empty 'id'{label}")
        transform_id = str(transform_id)
        if transform_id in seen_ids:
            raise ValueError(f"Bike profile duplicate signal transform id {transform_id!r}{label}")
        seen_ids.add(transform_id)

        if not isinstance(item.get("input"), Mapping) or not item.get("input"):
            raise ValueError(f"Bike profile signal transform {transform_id!r} missing non-empty 'input'{label}")
        if not isinstance(item.get("output"), Mapping) or not item.get("output"):
            raise ValueError(f"Bike profile signal transform {transform_id!r} missing non-empty 'output'{label}")

        method = item.get("method")
        if method not in {"lut", "polynomial"}:
            raise ValueError(f"Bike profile signal transform {transform_id!r} method must be 'lut' or 'polynomial'{label}")
        if method == "lut":
            _validate_lut_transform(item, transform_id=transform_id, label=label)
        else:
            _validate_polynomial_transform(item, transform_id=transform_id, label=label)


def _validate_lut_transform(transform: Mapping[str, Any], *, transform_id: str, label: str) -> None:
    points = transform.get("lut")
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes, bytearray)) or len(points) < 2:
        raise ValueError(f"Bike profile LUT transform {transform_id!r} requires at least two LUT points{label}")

    xs: list[float] = []
    for i, point in enumerate(points):
        if not isinstance(point, Mapping):
            raise ValueError(f"Bike profile LUT transform {transform_id!r} point {i} must be an object{label}")
        try:
            x = float(point.get("input"))
            y = float(point.get("output"))
        except (TypeError, ValueError):
            raise ValueError(f"Bike profile LUT transform {transform_id!r} point {i} has non-numeric input/output{label}") from None
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"Bike profile LUT transform {transform_id!r} point {i} has non-finite input/output{label}")
        xs.append(x)

    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError(f"Bike profile LUT transform {transform_id!r} inputs must be strictly increasing{label}")

    interpolation = transform.get("interpolation", "linear")
    if interpolation not in {"linear", "nearest"}:
        raise ValueError(f"Bike profile LUT transform {transform_id!r} interpolation must be 'linear' or 'nearest'{label}")
    extrapolation = transform.get("extrapolation", "clamp")
    if extrapolation not in {"clamp", "linear", "error"}:
        raise ValueError(f"Bike profile LUT transform {transform_id!r} extrapolation must be 'clamp', 'linear', or 'error'{label}")


def _validate_polynomial_transform(transform: Mapping[str, Any], *, transform_id: str, label: str) -> None:
    polynomial = transform.get("polynomial")
    if not isinstance(polynomial, Mapping):
        raise ValueError(f"Bike profile polynomial transform {transform_id!r} missing 'polynomial' object{label}")

    coeffs = polynomial.get("coefficients")
    if not isinstance(coeffs, Sequence) or isinstance(coeffs, (str, bytes, bytearray)) or not coeffs:
        raise ValueError(f"Bike profile polynomial transform {transform_id!r} requires coefficients{label}")
    try:
        parsed = [float(x) for x in coeffs]
    except (TypeError, ValueError):
        raise ValueError(f"Bike profile polynomial transform {transform_id!r} coefficients must be numeric{label}") from None
    if not all(math.isfinite(x) for x in parsed):
        raise ValueError(f"Bike profile polynomial transform {transform_id!r} coefficients must be finite{label}")

    order = polynomial.get("coefficient_order", "ascending")
    if order not in {"ascending", "descending"}:
        raise ValueError(
            f"Bike profile polynomial transform {transform_id!r} coefficient_order must be 'ascending' or 'descending'{label}"
        )


def resolve_normalization_ranges(
    session: Dict[str, Any],
    bike_profile: Mapping[str, Any],
    *,
    bike_profile_path: Optional[str | Path] = None,
    require_at_least_one: bool = True,
) -> Dict[str, float]:
    """
    Resolve semantic bike-profile normalization ranges to the legacy column map.

    Returns the dict currently consumed by ``normalize_and_scale``:
    ``{canonical_dataframe_column: full_range}``.
    """
    validate_bike_profile(bike_profile, path=bike_profile_path)
    _ensure_signal_registry(session)

    signals = ((session.get("meta") or {}).get("signals") or {})
    if not isinstance(signals, Mapping):
        signals = {}

    ranges = bike_profile.get("normalization_ranges") or []
    resolved: Dict[str, float] = {}
    resolved_records: list[dict[str, Any]] = []
    warnings: list[str] = []

    for range_item in ranges:
        if not isinstance(range_item, Mapping):
            continue

        range_id = str(range_item.get("id"))
        selector = range_item.get("signal")
        if not isinstance(selector, Mapping):
            continue

        matches = [
            str(col)
            for col, info in signals.items()
            if isinstance(info, Mapping) and _matches_selector(info, selector)
        ]

        if not matches:
            warning = f"bike_profile_normalization_range_unmatched:{range_id}"
            warnings.append(warning)
            logger.info(
                "Bike profile normalization range did not match a session signal: "
                "bike_profile_id=%s range_id=%s selector=%s",
                bike_profile.get("bike_profile_id"),
                range_id,
                dict(selector),
            )
            continue

        if len(matches) > 1:
            raise ValueError(
                "Bike profile normalization range matched multiple session signals: "
                f"range_id={range_id!r} matches={matches}"
            )

        column = matches[0]
        full_range = float(range_item.get("full_range"))
        if column in resolved and resolved[column] != full_range:
            raise ValueError(
                "Bike profile normalization ranges contain conflicting values for "
                f"signal {column!r}: {resolved[column]!r} vs {full_range!r}"
            )

        resolved[column] = full_range
        resolved_records.append(
            {
                "range_id": range_id,
                "column": column,
                "full_range": full_range,
                "selector": dict(selector),
            }
        )
        logger.info(
            "Bike profile normalization range matched: bike_profile_id=%s range_id=%s column=%s full_range=%s",
            bike_profile.get("bike_profile_id"),
            range_id,
            column,
            full_range,
        )

    if require_at_least_one and not resolved:
        raise ValueError(
            "Bike profile did not resolve any normalization ranges for this session: "
            f"bike_profile_id={bike_profile.get('bike_profile_id')!r}"
        )

    _record_resolution(
        session,
        bike_profile=bike_profile,
        bike_profile_path=bike_profile_path,
        resolved_records=resolved_records,
        warnings=warnings,
    )
    return resolved


def _evaluate_transform(values: np.ndarray, transform: Mapping[str, Any]) -> np.ndarray:
    method = transform.get("method")
    if method == "lut":
        return _evaluate_lut(values, transform)
    if method == "polynomial":
        return _evaluate_polynomial(values, transform)
    raise ValueError(f"Unsupported bike-profile transform method: {method!r}")


def _evaluate_lut(values: np.ndarray, transform: Mapping[str, Any]) -> np.ndarray:
    points = transform.get("lut")
    if not isinstance(points, Sequence):
        raise ValueError(f"LUT transform {transform.get('id')!r} missing LUT points")

    x = np.asarray([float(p["input"]) for p in points if isinstance(p, Mapping)], dtype=float)
    y = np.asarray([float(p["output"]) for p in points if isinstance(p, Mapping)], dtype=float)
    interpolation = str(transform.get("interpolation", "linear"))
    extrapolation = str(transform.get("extrapolation", "clamp"))

    out = np.full(values.shape, np.nan, dtype=float)
    finite = np.isfinite(values)
    if not finite.any():
        return out

    v = values[finite]
    if extrapolation == "error" and ((v < x[0]).any() or (v > x[-1]).any()):
        raise ValueError(f"LUT transform {transform.get('id')!r} input value outside LUT range")

    if interpolation == "nearest":
        idx = np.searchsorted(x, v, side="left")
        idx = np.clip(idx, 0, len(x) - 1)
        left_idx = np.clip(idx - 1, 0, len(x) - 1)
        choose_left = np.abs(v - x[left_idx]) <= np.abs(v - x[idx])
        chosen = np.where(choose_left, left_idx, idx)
        result = y[chosen]
    else:
        result = np.interp(v, x, y)

    below = v < x[0]
    above = v > x[-1]
    if extrapolation == "linear":
        first_slope = (y[1] - y[0]) / (x[1] - x[0])
        last_slope = (y[-1] - y[-2]) / (x[-1] - x[-2])
        result = np.asarray(result, dtype=float)
        result[below] = y[0] + first_slope * (v[below] - x[0])
        result[above] = y[-1] + last_slope * (v[above] - x[-1])
    elif extrapolation == "clamp":
        result = np.asarray(result, dtype=float)
        result[below] = y[0]
        result[above] = y[-1]

    out[finite] = result
    return out


def _evaluate_polynomial(values: np.ndarray, transform: Mapping[str, Any]) -> np.ndarray:
    polynomial = transform.get("polynomial")
    if not isinstance(polynomial, Mapping):
        raise ValueError(f"Polynomial transform {transform.get('id')!r} missing polynomial object")

    coeffs = np.asarray([float(x) for x in polynomial.get("coefficients", [])], dtype=float)
    if str(polynomial.get("coefficient_order", "ascending")) == "ascending":
        coeffs_for_polyval = coeffs[::-1]
    else:
        coeffs_for_polyval = coeffs

    input_offset = float(polynomial.get("input_offset", 0.0) or 0.0)
    input_scale = float(polynomial.get("input_scale", 1.0) or 1.0)
    output_offset = float(polynomial.get("output_offset", 0.0) or 0.0)

    out = np.full(values.shape, np.nan, dtype=float)
    finite = np.isfinite(values)
    if finite.any():
        x_eval = (values[finite] - input_offset) * input_scale
        out[finite] = np.polyval(coeffs_for_polyval, x_eval) + output_offset
    return out


def _output_column_name(output_semantics: Mapping[str, Any], *, fallback: str) -> str:
    sensor = output_semantics.get("sensor")
    sensor_token = normalize_sensor_token(canonical_sensor_id(sensor)) or normalize_sensor_token(fallback) or "signal"

    quantity = output_semantics.get("quantity")
    quantity_token = normalize_sensor_token(quantity)
    if quantity_token in {"", "disp", "raw"}:
        base = sensor_token
    else:
        base = f"{sensor_token}_{quantity_token}"

    kind = "raw" if quantity_token == "raw" else ""
    domain = output_semantics.get("domain") if _nonempty_str(output_semantics.get("domain")) else None
    unit = _clean_unit(output_semantics.get("unit")) or None
    return format_signal_name(
        SignalNameParts(
            base=base,
            kind=kind,
            domain=domain,
            unit=unit,
            ops=(),
        )
    )


def _channel_info_for_output(
    output_semantics: Mapping[str, Any],
    *,
    input_col: str,
    transform_id: str,
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "source_columns": [input_col],
        "transform_chain": [transform_id],
    }
    for key in ("sensor", "quantity", "domain", "unit"):
        value = output_semantics.get(key)
        if isinstance(value, str) and value.strip():
            info[key] = canonical_sensor_id(value) if key == "sensor" else value.strip()
    if "quantity" in info:
        info["role"] = info["quantity"]
    return info


def _merge_channel_info(session: Dict[str, Any], column: str, info: Mapping[str, Any]) -> None:
    meta = session.setdefault("meta", {})
    channel_info = meta.setdefault("channel_info", {})
    if not isinstance(channel_info, dict):
        channel_info = {}
        meta["channel_info"] = channel_info

    existing = channel_info.get(column)
    merged = dict(existing) if isinstance(existing, Mapping) else {}
    merged.update(dict(info))
    channel_info[column] = merged


def _ensure_signal_registry(session: Dict[str, Any]) -> None:
    meta = session.setdefault("meta", {})
    signals = meta.get("signals") if isinstance(meta, dict) else None
    if isinstance(signals, Mapping) and signals:
        return
    build_signals_registry(session, strict=False)


def _record_resolution(
    session: Dict[str, Any],
    *,
    bike_profile: Mapping[str, Any],
    bike_profile_path: Optional[str | Path],
    resolved_records: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    source = session.setdefault("source", {})
    meta = session.setdefault("meta", {})
    qc = session.setdefault("qc", {})

    bike_profile_id = bike_profile.get("bike_profile_id")
    if isinstance(bike_profile_id, str) and bike_profile_id.strip():
        source["bike_profile_id"] = bike_profile_id
        meta["bike_profile_id"] = bike_profile_id
    if bike_profile_path is not None:
        source["bike_profile_path"] = str(bike_profile_path)

    bike_profile_qc = qc.setdefault("bike_profile", {})
    if not isinstance(bike_profile_qc, dict):
        bike_profile_qc = {}
        qc["bike_profile"] = bike_profile_qc
    bike_profile_qc.update(
        {
            "bike_profile_id": bike_profile_id,
            "bike_profile_path": str(bike_profile_path) if bike_profile_path is not None else None,
            "normalization_ranges": resolved_records,
        }
    )
    bike_profile_warnings = bike_profile_qc.setdefault("warnings", [])
    for warning in warnings:
        if warning not in bike_profile_warnings:
            bike_profile_warnings.append(warning)

    qc_warnings = qc.setdefault("warnings", [])
    for warning in warnings:
        if warning not in qc_warnings:
            qc_warnings.append(warning)


def _record_transform_application(
    session: Dict[str, Any],
    *,
    bike_profile: Mapping[str, Any],
    bike_profile_path: Optional[str | Path],
    generated: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    source = session.setdefault("source", {})
    meta = session.setdefault("meta", {})
    qc = session.setdefault("qc", {})
    qc_transforms = qc.setdefault("transforms", {})

    bike_profile_id = bike_profile.get("bike_profile_id")
    if isinstance(bike_profile_id, str) and bike_profile_id.strip():
        source["bike_profile_id"] = bike_profile_id
        meta["bike_profile_id"] = bike_profile_id
    if bike_profile_path is not None:
        source["bike_profile_path"] = str(bike_profile_path)

    transform_record = {
        "applied": bool(generated),
        "bike_profile_id": bike_profile_id,
        "bike_profile_path": str(bike_profile_path) if bike_profile_path is not None else None,
        "generated": generated,
        "skipped": skipped,
        "warnings": warnings,
    }
    qc_transforms["bike_profile_signal_transforms"] = transform_record

    bike_profile_qc = qc.setdefault("bike_profile", {})
    if not isinstance(bike_profile_qc, dict):
        bike_profile_qc = {}
        qc["bike_profile"] = bike_profile_qc
    bike_profile_qc.update(
        {
            "bike_profile_id": bike_profile_id,
            "bike_profile_path": str(bike_profile_path) if bike_profile_path is not None else None,
            "signal_transforms": transform_record,
        }
    )
    bike_profile_warnings = bike_profile_qc.setdefault("warnings", [])
    qc_warnings = qc.setdefault("warnings", [])
    for warning in warnings:
        if warning not in bike_profile_warnings:
            bike_profile_warnings.append(warning)
        if warning not in qc_warnings:
            qc_warnings.append(warning)


def _matches_selector(signal_info: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    for key in ("sensor", "quantity", "domain", "unit"):
        expected = selector.get(key)
        if expected is None or (isinstance(expected, str) and not expected.strip()):
            continue

        actual = signal_info.get(key)
        if key == "sensor":
            if not _sensor_matches(actual, expected):
                return False
        elif key == "unit":
            if _clean_unit(actual) != _clean_unit(expected):
                return False
        else:
            if normalize_sensor_token(actual) != normalize_sensor_token(expected):
                return False

    return True


def _sensor_matches(actual: Any, expected: Any) -> bool:
    actual_canonical = canonical_sensor_id(actual)
    expected_canonical = canonical_sensor_id(expected)
    if sensors_match(actual_canonical, expected_canonical):
        return True
    return normalize_sensor_token(actual_canonical) == normalize_sensor_token(expected_canonical)


def _clean_unit(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
