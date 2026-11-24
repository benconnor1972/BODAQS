from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml
from pathlib import Path

from bodaqs_analysis.detect import (
    _expand_event_instances,
    _resolve_inputs_for_event,
    detect_events_from_schema,
)
from bodaqs_analysis.schema import parse_event_schema


def _df() -> pd.DataFrame:
    time_s = np.arange(8, dtype=float)
    return pd.DataFrame(
        {
            "time_s": time_s,
            "rear_wheel_dom_wheel [mm]": np.linspace(0.0, 70.0, len(time_s)),
            "rear_wheel_dom_wheel [1]_op_Butterworth_10Hz_2Order_norm": np.linspace(0.0, 0.5, len(time_s)),
            "rear_wheel_vel_dom_wheel [mm/s]": np.array([4.0, 3.0, 2.0, 1.0, -1.0, -2.0, -3.0, -4.0]),
            "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order": np.array(
                [4.0, 3.0, 2.0, 1.0, -1.0, -2.0, -3.0, -4.0]
            ),
        }
    )


def _meta() -> dict:
    return {
        "session_id": "semantic_event_test",
        "signals": {
            "rear_wheel_dom_wheel [mm]": {
                "sensor": "rear_wheel",
                "end": "rear",
                "domain": "wheel",
                "quantity": "disp",
                "kind": "",
                "unit": "mm",
                "op_chain": [],
            },
            "rear_wheel_dom_wheel [1]_op_Butterworth_10Hz_2Order_norm": {
                "sensor": "rear_wheel",
                "end": "rear",
                "domain": "wheel",
                "quantity": "disp_norm",
                "kind": "",
                "unit": "1",
                "op_chain": ["Butterworth_10Hz_2Order", "norm"],
                "processing_role": "primary_analysis",
            },
            "rear_wheel_vel_dom_wheel [mm/s]": {
                "sensor": "rear_wheel",
                "end": "rear",
                "domain": "wheel",
                "quantity": "vel",
                "kind": "",
                "unit": "mm/s",
                "op_chain": [],
            },
            "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order": {
                "sensor": "rear_wheel",
                "end": "rear",
                "domain": "wheel",
                "quantity": "vel",
                "kind": "",
                "unit": "mm/s",
                "op_chain": ["Butterworth_10Hz_2Order", "Savgol20ms3Poly", "Butterworth_8Hz_2Order"],
                "processing_role": "primary_analysis",
            },
        },
    }


def test_semantic_event_inputs_bind_primary_analysis_columns_without_sensors() -> None:
    schema = {
        "version": "semantic-input-test",
        "events": [
            {
                "id": "semantic_rebound",
                "label": "semantic rebound",
                "inputs": {
                    "disp": {"end": "rear", "domain": "wheel", "quantity": "disp", "unit": "mm"},
                    "vel": {
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "vel",
                        "unit": "mm/s",
                        "processing_role": "primary_analysis",
                    },
                    "disp_norm": {
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp_norm",
                        "unit": "1",
                        "processing_role": "primary_analysis",
                    },
                },
                "trigger": {
                    "id": "rebound_start",
                    "type": "simple_threshold_crossing",
                    "signal": "vel",
                    "value": 0.0,
                    "dir": "falling",
                    "edge_ignore_s": 0.0,
                },
                "window": {"pre_s": 0.0, "post_s": 0.0, "align": "trigger"},
            }
        ],
    }

    events = detect_events_from_schema(_df(), schema=schema, meta=_meta())

    assert len(events) == 1
    assert events.loc[0, "schema_id"] == "semantic_rebound"
    assert events.loc[0, "signal"] == "vel"
    assert (
        events.loc[0, "signal_col"]
        == "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order"
    )
    assert events.loc[0, "event_id"] == "semantic_rebound:semantic:0"
    assert events.loc[0, "meta"]["event_context"] == "semantic"


def test_semantic_event_input_selector_is_ambiguous_without_processing_role() -> None:
    event = {
        "id": "ambiguous_event",
        "inputs": {
            "vel": {
                "end": "rear",
                "domain": "wheel",
                "quantity": "vel",
                "unit": "mm/s",
            }
        },
    }

    with pytest.raises(ValueError, match="matched multiple signals"):
        _resolve_inputs_for_event(event, {}, meta=_meta())


def test_semantic_event_expansion_injects_context_into_input_selectors() -> None:
    event = {
        "id": "expanded_event",
        "expand": {"end": ["rear", "front"]},
        "inputs": {
            "vel": {
                "domain": "wheel",
                "quantity": "vel",
                "unit": "mm/s",
                "processing_role": "primary_analysis",
            },
            "raw_front": {
                "end": "front",
                "domain": "wheel",
                "quantity": "raw",
                "unit": "counts",
            },
        },
    }

    expanded = _expand_event_instances(event, {})

    assert [ev["_expansion"] for ev in expanded] == [{"end": "rear"}, {"end": "front"}]
    assert [ev["inputs"]["vel"]["end"] for ev in expanded] == ["rear", "front"]
    assert [ev["inputs"]["raw_front"]["end"] for ev in expanded] == ["front", "front"]


def test_semantic_expanded_event_detects_one_instance_per_resolved_end() -> None:
    df = _df().copy()
    df["front_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order"] = [
        2.0,
        1.0,
        -1.0,
        -2.0,
        -3.0,
        -4.0,
        -5.0,
        -6.0,
    ]
    meta = _meta()
    meta["signals"][
        "front_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order"
    ] = {
        "sensor": "front_wheel",
        "end": "front",
        "domain": "wheel",
        "quantity": "vel",
        "kind": "",
        "unit": "mm/s",
        "op_chain": ["Butterworth_10Hz_2Order", "Savgol20ms3Poly", "Butterworth_8Hz_2Order"],
        "processing_role": "primary_analysis",
    }
    schema = {
        "version": "semantic-expand-test",
        "events": [
            {
                "id": "expanded_rebound",
                "expand": {"end": ["rear", "front"]},
                "inputs": {
                    "vel": {
                        "domain": "wheel",
                        "quantity": "vel",
                        "unit": "mm/s",
                        "processing_role": "primary_analysis",
                    }
                },
                "trigger": {
                    "id": "rebound_start",
                    "type": "simple_threshold_crossing",
                    "signal": "vel",
                    "value": 0.0,
                    "dir": "falling",
                    "edge_ignore_s": 0.0,
                },
                "window": {"pre_s": 0.0, "post_s": 0.0, "align": "trigger"},
            }
        ],
    }

    events = detect_events_from_schema(df, schema=schema, meta=meta)

    assert sorted(events["event_id"].tolist()) == [
        "expanded_rebound:front:0",
        "expanded_rebound:rear:0",
    ]
    assert sorted(row["input_expansion"]["end"] for row in events["meta"]) == ["front", "rear"]


def test_basic_schema_has_migrated_to_semantic_event_inputs() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "event schema" / "event_schema - Basic.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))

    assert schema["specification"] == "0.1.2"
    assert schema["version"] == "7"

    events = schema.get("events") or []
    assert len(events) == 4
    assert all("inputs" in ev for ev in events)
    assert all("expand" in ev for ev in events)
    assert all("sensors" not in ev for ev in events)

    for ev in events:
        assert ev["expand"] == {"end": ["rear", "front"]}
        inputs = ev["inputs"]
        assert set(inputs) == {"disp", "vel", "acc", "disp_norm"}
        for role, selector in inputs.items():
            assert selector["processing_role"] == "primary_analysis"
            assert selector["domain"] == "wheel"
            assert "end" not in selector
            if role == "disp_norm":
                assert selector["quantity"] == "disp_norm"
                assert selector["unit"] == "1"
            elif role == "vel":
                assert selector["quantity"] == "vel"
                assert selector["unit"] == "mm/s"
            elif role == "acc":
                assert selector["quantity"] == "acc"
                assert selector["unit"] == "mm/s^2"
            else:
                assert selector["quantity"] == "disp"
                assert selector["unit"] == "mm"


def test_parse_event_schema_accepts_mapping_text_and_bytes() -> None:
    schema_obj = {"events": [{"id": "test_event"}], "version": "1"}
    schema_text = "events:\n  - id: test_event\nversion: '1'\n"

    parsed_from_mapping = parse_event_schema(schema_obj)
    parsed_from_text, meta_from_text = parse_event_schema(schema_text, return_meta=True)
    parsed_from_bytes = parse_event_schema(schema_text.encode("utf-8"))

    assert parsed_from_mapping == schema_obj
    assert parsed_from_text["events"][0]["id"] == "test_event"
    assert parsed_from_bytes["version"] == "1"
    assert meta_from_text["source_path"] is None
    assert isinstance(meta_from_text["sha256"], str) and meta_from_text["sha256"]
