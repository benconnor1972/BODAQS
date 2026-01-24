# signalspec.py
from __future__ import annotations
from dataclasses import dataclass
from typing import FrozenSet

KIND_SUFFIX_RAW = "_raw"
KIND_SUFFIX_QC  = "_qc"

DOMAIN_PREFIX = "_dom_"
OP_PREFIX     = "_op_"

RAW_UNIT_DEFAULT = "counts"

@dataclass(frozen=True)
class SignalSpec:
    allowed_domains: FrozenSet[str]
    allowed_ops: FrozenSet[str]
    raw_unit_default: str = RAW_UNIT_DEFAULT
    strict_ops: bool = True
    strict_domains: bool = True

DEFAULT_SPEC = SignalSpec(
    allowed_domains=frozenset({"suspension", "wheel", "bike", "world"}),
    allowed_ops=frozenset({
        "zeroed", "norm", "clip", "filt", "fill", "smooth", "detrend", "cal", "resamp",
    }),
)
