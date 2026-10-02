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


def test_sample_cells_are_stable_for_unsorted_duplicates_and_gaps() -> None:
    from bodaqs_analysis.library_api.activity_index import sample_cell_intervals

    times = np.array([3.0, 0.0, 1.0, 2.0, 10.0, np.nan, 10.0, 12.5])
    assert sample_cell_intervals(
        times,
        np.array([True, True, True, True, True, False, True, False]),
    ) == [(0.0, 3.5), (9.5, 11.25)]
    assert sample_cell_intervals(
        times,
        np.array([False, True, False, True, False, True, False, True]),
    ) == [(0.0, 0.5), (1.5, 2.5), (11.25, 13.0)]
    assert sample_cell_intervals(times, np.zeros(len(times), dtype=bool)) == []


def test_sample_cells_tolerate_high_rate_timestamp_jitter_without_fragmenting() -> None:
    from bodaqs_analysis.library_api.activity_index import sample_cell_intervals

    deltas = np.resize(np.array([0.00175, 0.00225, 0.0019, 0.0021]), 20_000)
    times = np.concatenate(([0.0], np.cumsum(deltas)))

    intervals = sample_cell_intervals(times, np.ones(len(times), dtype=bool))

    assert len(intervals) == 1
    assert intervals[0][0] == 0.0
    assert intervals[0][1] > times[-1]


def test_sample_cells_leave_real_dropouts_unknown() -> None:
    from bodaqs_analysis.library_api.activity_index import sample_cell_intervals

    times = np.array([0.0, 0.002, 0.004, 0.020, 0.022])

    assert sample_cell_intervals(times, np.ones(len(times), dtype=bool)) == [
        (0.0, pytest.approx(0.005)),
        (pytest.approx(0.019), pytest.approx(0.023)),
    ]


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
