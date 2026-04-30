"""Service layer wrapping bodaqs_analysis.preprocess_session.

Responsibilities:
- Accept raw file bytes from the route layer
- Write temporary files (CSV, sidecar, schema) that preprocess_session requires as paths
- Load the preprocess profile from bytes or fall back to the bundled default
- Encode processed signal columns as base64 float32
- Collect all pipeline warnings into a flat list
- Return a PreprocessResponse; never raise HTTPException (that is the route's job)

Temp files are cleaned up after every call regardless of success or failure.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bodaqs_analysis import preprocess_session
from bodaqs_analysis.preprocess_profile import preprocess_config_from_profile, validate_preprocess_profile

from ..schemas.preprocess import PreprocessResponse, SignalsPayload

# ---------------------------------------------------------------------------
# Default preprocess profile
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE_PATH = Path(__file__).parent.parent / "default_preprocess_profile.json"

# Loaded once at import time; re-read from disk if the file is edited and
# the process is restarted (no hot-reload needed — this is a server startup).
def _load_default_profile() -> dict[str, Any]:
    return json.loads(_DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Column encoding
# ---------------------------------------------------------------------------

# Columns that are infrastructure / QC and should not be sent to the frontend.
_EXCLUDE_COLUMNS = frozenset({
    "time_s",
    "sample_id",
    "active_mask_qc",
})


def _encode_column(series: pd.Series) -> str:
    """Encode a pandas Series as a base64 little-endian float32 byte string."""
    arr = pd.to_numeric(series, errors="coerce").to_numpy(dtype=np.float32)
    return base64.b64encode(arr.tobytes()).decode("ascii")


def _build_signals_payload(df: pd.DataFrame) -> SignalsPayload:
    """Extract numeric signal columns from the processed DataFrame and encode them."""
    column_names = [
        col for col in df.columns
        if col not in _EXCLUDE_COLUMNS and pd.api.types.is_numeric_dtype(df[col])
    ]
    return SignalsPayload(
        column_names=column_names,
        n_rows=len(df),
        columns={col: _encode_column(df[col]) for col in column_names},
    )


# ---------------------------------------------------------------------------
# DataFrame → JSON records (NaN → null)
# ---------------------------------------------------------------------------

def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON records with NaN serialised as null."""
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records"))


# ---------------------------------------------------------------------------
# Warning collection
# ---------------------------------------------------------------------------

def _collect_warnings(result: dict[str, Any]) -> list[str]:
    """Collect all pipeline warnings from the result dict into a flat list."""
    warnings: list[str] = []

    session = result.get("session") or {}
    qc = session.get("qc") or {}

    # Top-level QC warnings
    for w in qc.get("warnings") or []:
        if isinstance(w, str) and w not in warnings:
            warnings.append(w)

    # Bike profile warnings
    bp_warnings = ((qc.get("bike_profile") or {}).get("warnings")) or []
    for w in bp_warnings:
        if isinstance(w, str) and w not in warnings:
            warnings.append(w)

    return warnings


# ---------------------------------------------------------------------------
# Profile sanitisation
# ---------------------------------------------------------------------------

def _disable_fit_import(profile: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the profile with fit_import.enabled forced to False.

    The web API has no access to a FIT file directory, so FIT import must
    always be disabled regardless of what a user-supplied profile requests.
    A warning is NOT added here — the pipeline simply skips FIT enrichment
    when enabled=False, which is the correct silent behaviour.
    """
    import copy
    profile = copy.deepcopy(profile)
    fit_import = profile.get("config", {}).get("fit_import")
    if isinstance(fit_import, dict) and fit_import.get("enabled"):
        profile["config"]["fit_import"]["enabled"] = False
    return profile


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_preprocess(
    *,
    csv_bytes: bytes,
    csv_filename: str,
    sidecar_bytes: bytes,
    bike_profile_bytes: bytes,
    event_schema_bytes: bytes,
    preprocess_profile_bytes: bytes | None,
) -> PreprocessResponse:
    """Run the full preprocessing pipeline for one logger CSV.

    Args:
        csv_bytes: Raw bytes of the uploaded logger CSV.
        csv_filename: Original filename (used to derive session_id stem).
        sidecar_bytes: Raw bytes of the sidecar JSON.
        bike_profile_bytes: Raw bytes of the bike profile JSON.
        event_schema_bytes: Raw bytes of the event schema YAML.
        preprocess_profile_bytes: Raw bytes of the preprocess profile JSON,
            or None to use the bundled default.

    Returns:
        PreprocessResponse ready for JSON serialisation.

    Raises:
        ValueError: If any input file fails validation before the pipeline runs.
        Exception: Any exception raised by the pipeline propagates up;
            the route layer is responsible for converting to HTTP errors.
    """
    source_sha256 = hashlib.sha256(csv_bytes).hexdigest()

    # Load and validate profile objects from bytes before touching temp files.
    bike_profile: dict[str, Any] = json.loads(bike_profile_bytes)
    preprocess_profile: dict[str, Any] = (
        json.loads(preprocess_profile_bytes)
        if preprocess_profile_bytes is not None
        else _load_default_profile()
    )
    preprocess_profile = _disable_fit_import(preprocess_profile)
    validate_preprocess_profile(preprocess_profile)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        csv_path = tmp / csv_filename
        csv_path.write_bytes(csv_bytes)

        sidecar_path = tmp / "sidecar.json"
        sidecar_path.write_bytes(sidecar_bytes)

        schema_path = tmp / "event_schema.yaml"
        schema_path.write_bytes(event_schema_bytes)

        result = preprocess_session(
            str(csv_path),
            str(schema_path),
            preprocess_profile=preprocess_profile,
            sidecar_path=str(sidecar_path),
            bike_profile=bike_profile,
            strict=False,
        )

    session = result["session"]
    df: pd.DataFrame = session["df"]

    return PreprocessResponse(
        session_id=session["session_id"],
        meta=session.get("meta") or {},
        source_sha256=source_sha256,
        signals=_build_signals_payload(df),
        events=_df_to_records(result["events"]),
        metrics=_df_to_records(result["metrics"]),
        warnings=_collect_warnings(result),
    )
