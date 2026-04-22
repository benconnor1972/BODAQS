import gzip
import json
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from api.main import app

client = TestClient(app)

FIXTURE_CSV = Path("analysis/logs_test/2026-02-20_13-08-45.CSV")
FIXTURE_SCHEMA = Path("analysis/event schema/event_schema.yaml")


@pytest.fixture
def csv_bytes():
    return FIXTURE_CSV.read_bytes()


@pytest.fixture
def csv_gz(csv_bytes):
    return gzip.compress(csv_bytes)


@pytest.fixture
def base_config_dict():
    return {
        "schema_yaml": FIXTURE_SCHEMA.read_text(encoding="utf-8"),
        "normalize_ranges": {
            "front_shock_dom_suspension [mm]": 170.0,
            "rear_shock_dom_suspension [mm]": 150.0,
        },
        "zeroing_enabled": False,
        "strict": False,
    }


def test_preprocess_200(csv_gz, base_config_dict):
    resp = client.post(
        "/api/preprocess",
        files={"csv_file": ("2026-02-20_13-08-45.CSV.gz", csv_gz, "application/gzip")},
        data={"config_json": json.dumps(base_config_dict)},
    )
    assert resp.status_code == 200


def test_preprocess_returns_session_id(csv_gz, base_config_dict):
    resp = client.post(
        "/api/preprocess",
        files={"csv_file": ("2026-02-20_13-08-45.CSV.gz", csv_gz, "application/gzip")},
        data={"config_json": json.dumps(base_config_dict)},
    )
    assert resp.json()["session_id"] == "2026-02-20_13-08-45"


def test_preprocess_invalid_config_422(csv_gz):
    resp = client.post(
        "/api/preprocess",
        files={"csv_file": ("test.csv.gz", csv_gz, "application/gzip")},
        data={"config_json": "not-json"},
    )
    assert resp.status_code == 422


def test_preprocess_accepts_uncompressed_csv(csv_bytes, base_config_dict):
    resp = client.post(
        "/api/preprocess",
        files={"csv_file": ("2026-02-20_13-08-45.CSV", csv_bytes, "text/csv")},
        data={"config_json": json.dumps(base_config_dict)},
    )
    assert resp.status_code == 200
