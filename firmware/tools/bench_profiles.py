"""Small, explicit candidate recipes shared by plans and evidence contracts."""
PROFILES = {
    "production": {"logger_env": "bodaqs_s3_mini_n4r2", "measurement": {"version": 1},
                   "master_flags": ["SPI_MEASUREMENT_PROFILE=legacy"]},
    "first-recording": {"logger_env": "bodaqs_s3_mini_n4r2_imu_smoke",
        "measurement": {"version": 2, "physical_bytes": 256, "requested_hz": 16000000, "guard_us": 25},
        "master_flags": ["SPI_MEASUREMENT_PROFILE=first-recording"]},
    "mixed-diagnostic": {"logger_env": "bodaqs_s3_mini_n4r2_imu_adc_smoke",
        "measurement": {"version": 2, "physical_bytes": 256, "requested_hz": 16000000,
            "guard_us": 25, "minimum_start_spacing_us": 500, "cs_setup_us": 5,
            "spi_rx_capacity": 2, "phase_timing": True, "queue_timing": True,
            "reply_capture_capacity": 4, "flow_diagnostics": True},
        "master_flags": ["SPI_MEASUREMENT_PROFILE=first-recording", "SPI_RX_CAPACITY=2",
                         "SPI_PHASE_TIMING=1", "SPI_QUEUE_TIMING=1"]},
}


def review_result(value: dict, base: str, head: str) -> dict:
    """Typed source binding, independent of human prose/capitalisation."""
    import re
    if not isinstance(base,str) or not re.fullmatch("[0-9a-f]{40}",base) or not re.fullmatch("[0-9a-f]{40}",head):
        raise ValueError("Exact reviewed base/head commits required")
    if value.get("schema") != "bodaqs.review.v1" or value.get("base") != base or value.get("head") != head:
        raise ValueError("Review schema/base/head mismatch")
    if value.get("outcome") != "passed" or not isinstance(value.get("findings"), list):
        raise ValueError("Review has no passing typed outcome")
    if any(f.get("resolution") not in ("resolved", "accepted") for f in value["findings"]):
        raise ValueError("Unresolved review findings")
    evidence = value.get("evidence", [])
    if not evidence or any(not isinstance(e, dict) or not e.get("path") or
                           not re.fullmatch("[0-9a-f]{64}", e.get("sha256", "")) for e in evidence):
        raise ValueError("Review evidence hashes missing")
    return value
