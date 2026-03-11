# signalspec.py
from __future__ import annotations
from dataclasses import dataclass
from typing import FrozenSet, Pattern, Tuple
import re

KIND_SUFFIX_RAW = "_raw"
KIND_SUFFIX_QC  = "_qc"

DOMAIN_PREFIX = "_dom_"
OP_PREFIX     = "_op_"

RAW_UNIT_DEFAULT = "counts"

@dataclass(frozen=True)
class SignalSpec:
    allowed_domains: FrozenSet[str]
    allowed_ops: FrozenSet[str]
    allowed_op_patterns: Tuple[Pattern[str], ...] = ()
    raw_unit_default: str = RAW_UNIT_DEFAULT
    strict_ops: bool = True
    strict_domains: bool = True

DEFAULT_SPEC = SignalSpec(
    allowed_domains=frozenset({"suspension", "wheel", "bike", "world"}),
    allowed_ops=frozenset({
        "zeroed", "norm", "clip", "filt", "fill", "smooth", "detrend", "cal", "resamp", "diff",
    }),
    allowed_op_patterns=(
        re.compile(r"^Butterworth_[0-9]+(?:p[0-9]+)?Hz_[1-9][0-9]*Order$"),
    ),
)


def is_allowed_op_token(token: str, spec: SignalSpec = DEFAULT_SPEC) -> bool:
    if token in spec.allowed_ops:
        return True
    for pat in spec.allowed_op_patterns:
        if pat.fullmatch(token):
            return True
    return False
