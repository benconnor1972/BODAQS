# test_signalname.py
import pytest

from bodaqs_analysis.signalname import parse_signal_name, format_signal_name, SignalNameError, SignalNameParts
from bodaqs_analysis.signalspec import DEFAULT_SPEC

def rt(s: str) -> str:
    parts = parse_signal_name(s, DEFAULT_SPEC)
    return format_signal_name(parts, DEFAULT_SPEC)

def test_roundtrip_engineered():
    assert rt("rear_shock [mm]") == "rear_shock [mm]"
    assert rt("rear_shock_dom_suspension [mm]") == "rear_shock_dom_suspension [mm]"

def test_roundtrip_ops():
    assert rt("rear_shock [mm]_op_zeroed_norm") == "rear_shock [mm]_op_zeroed_norm"

def test_roundtrip_raw():
    assert rt("rear_shock_raw [counts]") == "rear_shock_raw [counts]"

def test_roundtrip_qc():
    assert rt("rear_shock_qc") == "rear_shock_qc"
    assert rt("rear_shock_qc_dropouts") == "rear_shock_qc_dropouts"

def test_domain_unknown_rejected():
    with pytest.raises(SignalNameError):
        parse_signal_name("rear_shock_dom_sensor [mm]", DEFAULT_SPEC)

def test_op_unknown_rejected():
    with pytest.raises(SignalNameError):
        parse_signal_name("rear_shock [mm]_op_blah", DEFAULT_SPEC)

def test_repeated_op_prefix_rejected():
    with pytest.raises(SignalNameError):
        parse_signal_name("rear_shock [mm]_op_zeroed_op_norm", DEFAULT_SPEC)

def test_bad_unit_brackets_rejected():
    with pytest.raises(SignalNameError):
        parse_signal_name("rear_shock [mm_op_zeroed", DEFAULT_SPEC)

def test_suffix_after_unit_must_be_op():
    with pytest.raises(SignalNameError):
        parse_signal_name("rear_shock [mm]_zeroed", DEFAULT_SPEC)

def test_format_unknown_kind():
    with pytest.raises(SignalNameError):
        format_signal_name(SignalNameParts(base="x", kind="weird"), DEFAULT_SPEC)
