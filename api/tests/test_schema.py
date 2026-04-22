import pytest
from pydantic import ValidationError
from api.schemas.preprocess import PreprocessConfig

def test_valid_config():
    cfg = PreprocessConfig(
        schema_yaml="events: []",
        normalize_ranges={"front_shock_dom_suspension [mm]": 170.0},
    )
    assert cfg.zeroing_enabled is True
    assert cfg.strict is False

def test_missing_normalize_ranges_raises():
    with pytest.raises(ValidationError):
        PreprocessConfig(schema_yaml="events: []")

def test_butterworth_defaults_to_empty():
    cfg = PreprocessConfig(
        schema_yaml="events: []",
        normalize_ranges={"front_shock_dom_suspension [mm]": 170.0},
    )
    assert cfg.butterworth_smoothing == []
