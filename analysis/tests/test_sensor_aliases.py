from __future__ import annotations

from bodaqs_analysis.sensor_aliases import (
    canonical_end,
    canonical_sensor_from_text,
    canonical_sensor_id,
    canonicalize_signal_base,
    end_from_sensor,
    ends_match,
    sensor_matches_side,
    sensors_match,
)


def test_sensor_helpers_do_not_apply_legacy_semantic_aliases() -> None:
    assert canonical_sensor_id("fork") == "fork"
    assert canonical_sensor_id("front fork") == "front_fork"
    assert canonical_sensor_id("shock") == "shock"
    assert canonical_sensor_id("rear shock") == "rear_shock"

    assert not sensors_match("fork", "front_shock")
    assert not sensors_match("shock", "rear_shock")
    assert canonical_sensor_from_text("fork_vel_dom_suspension [mm/s]") == ""
    assert canonicalize_signal_base("shock_acc") == "shock_acc"


def test_end_helpers_require_explicit_front_or_rear_tokens() -> None:
    assert canonical_end("front") == "front"
    assert canonical_end("rear") == "rear"
    assert canonical_end("back") == ""
    assert end_from_sensor("rear_wheel_dom_wheel [mm]") == "rear"
    assert ends_match("rear_wheel", "rear")
    assert not ends_match("rear_wheel", "back")
    assert sensor_matches_side("front_wheel_dom_wheel [mm]", "front")
    assert not sensor_matches_side("fork_dom_suspension [mm]", "front")
