import pandas as pd
from typing import Optional, Sequence


def extract_metrics_df(
    events_df: pd.DataFrame,
    *,
    id_cols: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Return a wide metrics dataframe from an events_df.

    - Metric columns are those prefixed with 'm_'.
    - By default, keeps the Metrics Contract identity bundle if present.
    - Contract-aligned: does NOT add or require start/end window columns.
    """
    if events_df is None or len(events_df) == 0:
        return pd.DataFrame()

    metric_cols = [c for c in events_df.columns if str(c).startswith("m_")]

    if id_cols is None:
        # Preferred (contract-friendly) identity bundle
        preferred = (
            "event_id",
            "schema_id",
            "schema_version",
            "event_name",
            "signal",
            "segment_id",
            "trigger_time_s",
            "tags",
        )

        # Legacy fallback
        legacy = (
            "event_id",
            "event_type",
            "sensor",
            "t0_time",
            "t0_index",
            "start_index",
            "end_index",
        )

        # Contract-ish if it has the identity bundle (no need for trigger_idx in metrics)
        looks_contract = all(c in events_df.columns for c in ("schema_id", "schema_version", "event_name", "signal", "trigger_time_s"))
        id_cols = preferred if looks_contract else legacy

    keep = [c for c in id_cols if c in events_df.columns]
    return events_df[keep + metric_cols].copy()
