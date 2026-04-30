"""Pydantic request/response models for the preprocess endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SignalsPayload(BaseModel):
    """Processed signal columns encoded as base64 float32 arrays."""

    column_names: list[str] = Field(description="Ordered list of signal column names.")
    n_rows: int = Field(description="Number of samples in each column.")
    columns: dict[str, str] = Field(
        description="Map of column name → base64-encoded little-endian float32 array."
    )


class PreprocessResponse(BaseModel):
    """Response returned by POST /api/preprocess."""

    session_id: str = Field(description="Session identifier derived from the CSV filename stem.")
    meta: dict[str, Any] = Field(description="Session metadata (session['meta'] serialised to JSON).")
    source_sha256: str = Field(description="SHA-256 hex digest of the raw uploaded CSV bytes.")
    signals: SignalsPayload
    events: list[dict[str, Any]] = Field(
        description="Event detection results as records. NaN values are serialised as null."
    )
    metrics: list[dict[str, Any]] = Field(
        description="Metrics results as records. NaN values are serialised as null."
    )
    warnings: list[str] = Field(
        description="Pipeline warnings accumulated during preprocessing. Never empty-suppressed."
    )
