# signalname.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, List

from signalspec import (
    DEFAULT_SPEC,
    SignalSpec,
    KIND_SUFFIX_RAW,
    KIND_SUFFIX_QC,
    DOMAIN_PREFIX,
    OP_PREFIX,
)

class SignalNameError(ValueError):
    pass


@dataclass(frozen=True)
class SignalNameParts:
    base: str                      # snake_case base name, required
    kind: str = ""                 # "", "raw", "qc"
    domain: Optional[str] = None   # e.g. "suspension", "wheel", "bike", "world"
    unit: Optional[str] = None     # e.g. "mm", "mm/s", "V"
    ops: tuple[str, ...] = ()      # e.g. ("zeroed", "norm")

    @property
    def is_engineered_default(self) -> bool:
        return self.kind == ""

    @property
    def is_raw(self) -> bool:
        return self.kind == "raw"

    @property
    def is_qc(self) -> bool:
        return self.kind == "qc"


def parse_signal_name(name: str, spec: SignalSpec = DEFAULT_SPEC) -> SignalNameParts:
    """
    Parse a canonical signal column name into parts.

    Supports:
      <base><kind><domain> [unit]_op_<t1>_<t2>...
    Where:
      kind: "" | _raw | _qc
      domain: optional _dom_<domain>
      unit: ' [unit]' (space then bracketed unit)
      ops: optional '_op_' prefix + '_' joined tokens (single prefix only)
    """
    if not isinstance(name, str) or not name.strip():
        raise SignalNameError("name must be a non-empty string")

    s = name.strip()

    # 1) Extract unit + tail (ops) if present.
    # Unit format is exactly: " [<unit>]" and occurs before any ops.
    unit = None
    head = s
    tail = ""

    unit_start = s.find(" [")
    if unit_start != -1:
        unit_end = s.find("]", unit_start)
        if unit_end == -1:
            raise SignalNameError(f"missing closing ']' in unit: {name!r}")

        unit = s[unit_start + 2 : unit_end].strip()
        if not unit:
            raise SignalNameError(f"empty unit in: {name!r}")

        head = s[:unit_start]  # everything before " ["
        tail = s[unit_end + 1 :]  # everything after "]" (may be ops, may be empty)

    # 2) Parse ops from tail
    ops: List[str] = []
    if tail:
        if not tail.startswith(OP_PREFIX):
            raise SignalNameError(
                f"unexpected suffix after unit (expected '{OP_PREFIX}...'): {name!r}"
            )
        op_payload = tail[len(OP_PREFIX):]
        if not op_payload:
            raise SignalNameError(f"'{OP_PREFIX}' present but no op tokens: {name!r}")
        if OP_PREFIX in op_payload:
            raise SignalNameError(f"repeated '{OP_PREFIX}' is not allowed: {name!r}")

        ops = [t for t in op_payload.split("_") if t]
        if not ops:
            raise SignalNameError(f"no op tokens parsed from: {name!r}")

        if spec.strict_ops:
            unknown = [t for t in ops if t not in spec.allowed_ops]
            if unknown:
                raise SignalNameError(f"unknown op token(s) {unknown} in: {name!r}")

    # 3) Parse domain from head (optional, last _dom_ wins)
    domain = None
    base_and_kind = head

    dom_idx = head.rfind(DOMAIN_PREFIX)
    if dom_idx != -1:
        domain = head[dom_idx + len(DOMAIN_PREFIX):].strip()
        if not domain:
            raise SignalNameError(f"domain suffix present but empty: {name!r}")
        base_and_kind = head[:dom_idx]

        if spec.strict_domains and domain not in spec.allowed_domains:
            raise SignalNameError(f"unknown domain {domain!r} in: {name!r}")

    # 4) Parse kind from base_and_kind (optional)
    kind = ""
    base = base_and_kind

    if base_and_kind.endswith(KIND_SUFFIX_RAW):
        kind = "raw"
        base = base_and_kind[: -len(KIND_SUFFIX_RAW)]
    elif base_and_kind.endswith(KIND_SUFFIX_QC):
        kind = "qc"
        base = base_and_kind[: -len(KIND_SUFFIX_QC)]

    base = base.strip()
    if not base:
        raise SignalNameError(f"missing base name in: {name!r}")

    # Note: we don't enforce snake_case here; validator can do that.
    return SignalNameParts(
        base=base,
        kind=kind,
        domain=domain,
        unit=unit,
        ops=tuple(ops),
    )


def format_signal_name(parts: SignalNameParts, spec: SignalSpec = DEFAULT_SPEC) -> str:
    """
    Format SignalNameParts back into a canonical column name.

    Does not enforce higher-level rules (e.g., engineered must have unit) — that is done
    in validate_signals().
    """
    if not parts.base or not isinstance(parts.base, str):
        raise SignalNameError("parts.base must be a non-empty string")

    # kind suffix
    kind_suffix = ""
    if parts.kind == "":
        kind_suffix = ""
    elif parts.kind == "raw":
        kind_suffix = KIND_SUFFIX_RAW
    elif parts.kind == "qc":
        kind_suffix = KIND_SUFFIX_QC
    else:
        raise SignalNameError(f"unknown kind: {parts.kind!r}")

    # domain suffix
    dom_suffix = ""
    if parts.domain is not None:
        if not isinstance(parts.domain, str) or not parts.domain:
            raise SignalNameError("domain must be a non-empty string or None")
        if spec.strict_domains and parts.domain not in spec.allowed_domains:
            raise SignalNameError(f"unknown domain: {parts.domain!r}")
        dom_suffix = f"{DOMAIN_PREFIX}{parts.domain}"

    # unit
    unit_str = ""
    if parts.unit is not None:
        if not isinstance(parts.unit, str) or not parts.unit.strip():
            raise SignalNameError("unit must be a non-empty string or None")
        unit_str = f" [{parts.unit.strip()}]"

    # ops
    ops_str = ""
    if parts.ops:
        if OP_PREFIX in "_".join(parts.ops):
            # paranoia guard: ops tokens should never contain the prefix
            raise SignalNameError("ops tokens must not contain OP_PREFIX")
        if spec.strict_ops:
            unknown = [t for t in parts.ops if t not in spec.allowed_ops]
            if unknown:
                raise SignalNameError(f"unknown op token(s): {unknown}")
        ops_str = OP_PREFIX + "_".join(parts.ops)

    return f"{parts.base}{kind_suffix}{dom_suffix}{unit_str}{ops_str}"
