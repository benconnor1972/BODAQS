"""Normal BDQ import preserves the local BMI270 production evidence."""
import json
import struct
from pathlib import Path

import pytest

from bodaqs_analysis.pipeline import load_bdq_session
from test_io_bdq_v2 import (
    CHUNK_HEADER, FILE_HEADER, _chunk,
    _bdq_v2_bytes, _catalog, _imu_record, _metadata, _observation, _primary_record,
)
from test_io_bdq_storage_types import _phase6_imu_session


def test_local_bmi270_normal_import_keeps_native_counts_configuration_and_fifo_gap(tmp_path: Path):
    metadata = _metadata()
    config = _phase6_imu_session()['meta']['imu_configs']['frame_imu']
    metadata['imu_configs'] = {'imu_1': config}
    path = tmp_path / 'local-bmi270.bdq'
    catalog = _catalog()
    catalog['streams'][1]['acquisition'] = {
        'effective_accel_rate_hz': 200, 'effective_gyro_rate_hz': 200,
        'requested_profile': 'orientation_200',
    }
    path.write_bytes(_bdq_v2_bytes(
        metadata=metadata, catalog=catalog,
        primary_records=[_primary_record(0,100000,0), _primary_record(1,120000,0)],
        imu_1_records=[_imu_record(0,0,-2048), _imu_record(2,256,-1024,1)],
        imu_1_observations=[_observation(0,0,100000,100000), _observation(256,2,110000,110000)],
    ))
    session = load_bdq_session(path)
    raw = session['stream_dfs']['imu_1']
    assert raw['accel_x_raw'].tolist() == [-2048,-1024]
    assert raw['temperature_raw'].tolist() == [512,512]
    assert session['meta']['imu_configs']['imu_1'] == config
    derived = session['stream_dfs']['imu_imu_1']
    assert derived['accel_x_m_s2'].iloc[0] == pytest.approx(-9.80665)
    assert derived['body_accel_y_m_s2'].iloc[0] == pytest.approx(9.80665)
    assert derived['gyro_x_rad_s'].iloc[0] == pytest.approx(2.181661564992912)
    assert session['qc']['imu']['imu_1']['sequence']['missing_samples'] == 1
    assert session['meta']['secondary_streams']['imu_1']['clock_id'] == 'bmi270:imu_1'


def test_local_bmi270_absent_source_retains_identity_and_zero_records(tmp_path: Path):
    path = tmp_path / "absent.bdq"
    # An absent sensor remains declared but writes no stream-data chunks.
    original = _bdq_v2_bytes()
    parts = [original[:FILE_HEADER.size]]
    offset, sequence = FILE_HEADER.size, 0
    while offset < len(original):
        _, _, kind, _, length, _ = CHUNK_HEADER.unpack_from(original, offset)
        payload = original[offset + CHUNK_HEADER.size:offset + CHUNK_HEADER.size + length]
        offset += CHUNK_HEADER.size + length
        if kind == 3 and struct.unpack_from("<H", payload)[0] == 2:
            continue
        if kind == 5:
            summary = json.loads(payload)
            summary["streams"][1]["records_written"] = 0
            payload = json.dumps(summary).encode()
        parts.append(_chunk(kind, sequence, payload))
        sequence += 1
    path.write_bytes(b"".join(parts))
    session = load_bdq_session(path)
    assert session["stream_dfs"]["imu_1"].empty
    source = session["meta"]["secondary_streams"]["imu_1"]
    assert source["sensor"] == "imu_1"
    assert source["clock_id"] == "bmi270:imu_1"
    assert "imu_imu_1" not in session["stream_dfs"]
    assert session["qc"]["imu"]["imu_1"]["status"] == "failed"


def test_local_bmi270_missing_clock_relation_preserves_raw_without_engineering_alignment(tmp_path: Path):
    path = tmp_path / 'unrelated.bdq'
    path.write_bytes(_bdq_v2_bytes(imu_1_observations=[]))
    session = load_bdq_session(path)
    raw = session['stream_dfs']['imu_1']
    assert raw['accel_x_raw'].tolist() == [100,110]
    assert 'time_s' not in raw.columns
    assert 'imu_imu_1' not in session['stream_dfs']
