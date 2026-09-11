from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis.library_api.activity_index import build_activity_index_from_frame
from bodaqs_analysis.spatial_context_corpus import load_corpus_case, load_corpus_manifest


CORPUS_ROOT = Path(__file__).parent / "data" / "spatial_context"


def test_activity_index_preserves_source_runs_and_conservative_time_cells() -> None:
    frame = pd.DataFrame(
        {
            "time_s": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
            "active_mask_qc": [1, 1, 1, 0, 1, 1],
        }
    )

    index = build_activity_index_from_frame(
        frame,
        time_column="time_s",
        activity_column="active_mask_qc",
    )

    assert index["status"] == "succeeded"
    assert index["sample_count"] == 6
    assert index["active_sample_count"] == 5
    assert index["inactive_sample_count"] == 1
    assert [(run["start_index"], run["end_index"]) for run in index["active_runs"]] == [(0, 3), (4, 6)]
    assert [(run["start_index"], run["end_index"]) for run in index["inactive_runs"]] == [(3, 4)]
    assert index["active_intervals_s"] == [[0.0, 2.5], [3.5, 5.5]]
    assert index["known_intervals_s"] == [[0.0, 5.5]]


def test_vectorized_sample_cells_match_the_reference_intervalisation() -> None:
    from bodaqs_analysis.library_api.activity_index import sample_cell_intervals

    times = np.array([3.0, 0.0, 1.0, 2.0, 10.0, np.nan, 10.0, 12.5])
    selections = [
        np.array([True, True, True, True, True, False, True, False]),
        np.array([False, True, False, True, False, True, False, True]),
        np.zeros(len(times), dtype=bool),
    ]
    for selected in selections:
        assert sample_cell_intervals(times, selected) == _reference_sample_cells(times, selected)


@pytest.mark.parametrize("case_id", ["pipenhot_full", "sendit2_full", "rapid_activity_boundaries"])
def test_activity_index_is_compact_for_real_regression_sessions(case_id: str) -> None:
    manifest = load_corpus_manifest(CORPUS_ROOT)
    session = load_corpus_case(CORPUS_ROOT, case_id, manifest=manifest)
    frame = session["df"]
    index = build_activity_index_from_frame(
        frame,
        time_column="time_s",
        activity_column="active_mask_qc",
    )

    assert index["sample_count"] >= 26_000
    assert index["summary"]["encoded_run_count"] <= 10
    assert index["summary"]["runs_per_sample"] < 0.001


def _reference_sample_cells(times: np.ndarray, selected: np.ndarray) -> list[tuple[float, float]]:
    valid_times = np.sort(np.unique(times[np.isfinite(times)]))
    positive = np.diff(valid_times)
    positive = positive[positive > 1e-9]
    nominal = (
        float(np.median(positive))
        if positive.size >= 2
        else (min(float(positive[0]), 0.1) if positive.size else 0.001)
    )
    half = nominal / 2.0
    cells = sorted(
        (max(0.0, float(time) - half), float(time) + half)
        for time in times[selected]
        if np.isfinite(time)
    )
    intervals: list[tuple[float, float]] = []
    for start, end in cells:
        if intervals and start <= intervals[-1][1] + 1e-9:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    return intervals
