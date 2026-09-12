from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis.spatial_context import derive_spatial_context
from bodaqs_analysis.spatial_context_corpus import (
    CORPUS_SCHEMA,
    corpus_config,
    load_corpus_case,
    load_corpus_manifest,
)


CORPUS_ROOT = Path(__file__).parent / "data" / "spatial_context"


def _case_ids() -> list[str]:
    manifest = load_corpus_manifest(CORPUS_ROOT)
    return [str(case["case_id"]) for case in manifest["cases"]]


@pytest.mark.parametrize("case_id", _case_ids())
def test_spatial_context_real_data_regression_corpus(case_id: str) -> None:
    manifest = load_corpus_manifest(CORPUS_ROOT)
    case = next(case for case in manifest["cases"] if case["case_id"] == case_id)
    expected = case["expect"]
    tolerances = manifest["numeric_tolerances"]
    session = load_corpus_case(CORPUS_ROOT, case_id, manifest=manifest)

    result = derive_spatial_context(session, corpus_config())
    stream = result.stream_df
    selected = result.stream_meta.get("distance_source", {}).get("selected") or {}

    assert manifest["schema"] == CORPUS_SCHEMA
    assert result.stream_meta["status"] == expected["status"]
    assert selected.get("candidate_kind") == expected["distance_source"]
    assert sorted(result.stream_meta.get("warnings", [])) == expected["warnings"]
    assert len(stream) == expected["spatial_rows"]
    if expected["distance_m"] is not None:
        assert float(stream["distance_m"].max()) == pytest.approx(
            expected["distance_m"], abs=tolerances["distance_absolute_m"]
        )

    for column, metric_expected in expected["metrics"].items():
        values = pd.to_numeric(stream[column], errors="coerce").dropna()
        assert len(values) == metric_expected["valid_rows"]
        for summary_name, actual in (
            ("median", values.median()),
            ("p95", values.quantile(0.95)),
        ):
            wanted = metric_expected[summary_name]
            if wanted is None:
                assert np.isnan(actual)
            else:
                assert float(actual) == pytest.approx(
                    wanted,
                    rel=tolerances["metric_relative"],
                    abs=tolerances["metric_absolute"],
                )


@pytest.mark.parametrize(
    "case_id",
    ["pipenhot_full", "sendit2_full", "rapid_activity_boundaries"],
)
def test_real_cases_do_not_bridge_metrics_across_inactivity(case_id: str) -> None:
    session = load_corpus_case(CORPUS_ROOT, case_id)
    result = derive_spatial_context(session, corpus_config())
    stream = result.stream_df
    inactive = ~stream["active_mask_qc"].fillna(False).astype(bool)

    for column in (
        "gradient_fraction",
        "twistiness_rad_per_m",
        "front_suspension_activity",
        "rear_suspension_activity",
        "combined_suspension_activity",
    ):
        assert stream.loc[inactive, column].isna().all()


def test_real_case_variant_omits_rear_metrics_without_rear_wheel_evidence() -> None:
    session = load_corpus_case(CORPUS_ROOT, "rapid_activity_boundaries_no_rear_wheel")
    result = derive_spatial_context(session, corpus_config())

    assert "rear_suspension_activity" not in result.stream_df
    assert "combined_suspension_activity" not in result.stream_df
    assert "front_suspension_activity" in result.stream_df


def test_real_case_variant_requires_activity_mask_for_all_metrics() -> None:
    session = load_corpus_case(CORPUS_ROOT, "rapid_activity_boundaries_no_active_mask")
    result = derive_spatial_context(session, corpus_config())

    assert result.stream_meta["status"] == "unavailable"
    assert not result.stream_df["active_mask_qc"].any()
    assert result.stream_df["gradient_fraction"].isna().all()
    assert result.stream_df["twistiness_rad_per_m"].isna().all()
    assert "front_suspension_activity" not in result.stream_df
    assert "rear_suspension_activity" not in result.stream_df
