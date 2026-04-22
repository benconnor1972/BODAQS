import base64
import hashlib
import pytest
from api.schemas.preprocess import PreprocessConfig
from api.services.preprocess_service import run_preprocess


@pytest.fixture
def csv_bytes():
    from pathlib import Path
    return Path("analysis/logs_test/2026-02-20_13-08-45.CSV").read_bytes()


@pytest.fixture
def base_config_dict():
    from pathlib import Path
    return {
        "schema_yaml": Path("analysis/event schema/event_schema.yaml").read_text(encoding="utf-8"),
        "normalize_ranges": {
            "front_shock_dom_suspension [mm]": 170.0,
            "rear_shock_dom_suspension [mm]": 150.0,
        },
        "zeroing_enabled": False,
        "strict": False,
    }


def test_returns_correct_session_id(csv_bytes, base_config_dict):
    config = PreprocessConfig(**base_config_dict)
    result = run_preprocess(csv_bytes, config, filename="2026-02-20_13-08-45.CSV")
    assert result["session_id"] == "2026-02-20_13-08-45"


def test_returns_source_sha256(csv_bytes, base_config_dict):
    config = PreprocessConfig(**base_config_dict)
    result = run_preprocess(csv_bytes, config, filename="2026-02-20_13-08-45.CSV")
    expected = hashlib.sha256(csv_bytes).hexdigest()
    assert result["source_sha256"] == expected


def test_signals_has_time_column(csv_bytes, base_config_dict):
    config = PreprocessConfig(**base_config_dict)
    result = run_preprocess(csv_bytes, config, filename="2026-02-20_13-08-45.CSV")
    assert "time_s" in result["signals"]["column_names"]
    assert result["signals"]["n_rows"] > 0


def test_signal_columns_are_base64_float32(csv_bytes, base_config_dict):
    config = PreprocessConfig(**base_config_dict)
    result = run_preprocess(csv_bytes, config, filename="2026-02-20_13-08-45.CSV")
    n_rows = result["signals"]["n_rows"]
    col_b64 = result["signals"]["columns"]["time_s"]
    decoded = base64.b64decode(col_b64)
    assert len(decoded) == n_rows * 4  # float32 = 4 bytes per value


def test_active_mask_qc_excluded(csv_bytes, base_config_dict):
    config = PreprocessConfig(**base_config_dict)
    result = run_preprocess(csv_bytes, config, filename="2026-02-20_13-08-45.CSV")
    assert "active_mask_qc" not in result["signals"]["column_names"]


def test_meta_is_json_serializable(csv_bytes, base_config_dict):
    import json
    config = PreprocessConfig(**base_config_dict)
    result = run_preprocess(csv_bytes, config, filename="2026-02-20_13-08-45.CSV")
    json.dumps(result["meta"])  # must not raise


def test_events_have_required_keys(csv_bytes, base_config_dict):
    config = PreprocessConfig(**base_config_dict)
    result = run_preprocess(csv_bytes, config, filename="2026-02-20_13-08-45.CSV")
    assert len(result["events"]) > 0
    first = result["events"][0]
    for key in ("event_name", "schema_id", "start_time_s", "end_time_s"):
        assert key in first, f"Missing key: {key}"


def test_metrics_have_required_keys(csv_bytes, base_config_dict):
    config = PreprocessConfig(**base_config_dict)
    result = run_preprocess(csv_bytes, config, filename="2026-02-20_13-08-45.CSV")
    assert len(result["metrics"]) > 0
    first = result["metrics"][0]
    for key in ("event_id", "schema_id"):
        assert key in first, f"Missing key: {key}"
