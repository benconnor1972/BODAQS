# BODAQS — Minimum Signal Registry Semantics (v0.1)

This document defines the **minimum required semantics** for `session["meta"]["signals"]` so that downstream code (event detection, segment extraction, metrics, and visualization) can resolve schema “signals/roles” (e.g. `disp`, `vel`, `acc`) to concrete dataframe columns **without relying on column-name string hacks**.

It is intentionally **minimal**: it does not require full provenance graphs or transform metadata, but it *does* require enough structure to make resolution deterministic and contract-valid.

---

## 1) Scope

Applies to any analysis `Session` object that carries a `pandas.DataFrame` in `session["df"]`.

Downstream components that assume this registry:

- `detect_events_from_schema(..., meta=session["meta"])`
- `extract_segments(..., meta=session["meta"])`
- metrics and viz tooling that use SegmentBundle outputs

---

## 2) Registry shape

`session["meta"]["signals"]` MUST be a mapping:

```text
{ <df_column_name: str> : <SignalInfo: dict> }
```

Where `<df_column_name>` **must be exactly the column name** present in `session["df"].columns`.

---

## 3) Required coverage

### 3.1 One entry per numeric column

For every **numeric** column in `session["df"]` (excluding timebase columns like `time_s` and other explicitly non-signal fields), there MUST be a corresponding entry in `session["meta"]["signals"]`.

### 3.2 No extraneous entries (recommended)

It is strongly recommended that the registry does not include keys that are not present in `session["df"].columns`.

---

## 4) SignalInfo minimum fields

Each `SignalInfo` MUST contain the following keys:

- `kind`: `"" | "raw" | "qc"`
  - `""` means engineered/derived default signals.
  - `"raw"` means raw sensor/ADC domain.
  - `"qc"` means quality-control / flags.

- `unit`: `str | None`
  - For `kind == ""`, **unit MUST be non-empty** (e.g. `"mm"`, `"mm/s"`, `"V"`).
  - For `kind == "raw"`, unit SHOULD be `"counts"` (or another documented raw unit).
  - For `kind == "qc"`, unit SHOULD be `None`.
  - Dimensionless derived signals (e.g. normalised displacement) MUST use unit `"1"`.


- `domain`: `str | None`
  - Optional, but **highly recommended** when the same physical quantity can exist in multiple frames/domains.
  - Examples: `"sensor"`, `"wheel"`, `"bike"`, `"world"`.

- `op_chain`: `list[str]`
  - List of analysis-side operation tokens applied to produce this column (possibly empty).
  - Examples: `["zeroed"]`, `["zeroed", "norm"]`.

### Optional but recommended keys

- `source`: `list[str]`
  - Parent column name(s) this column derives from (especially for `_op_*` or derived velocity/acceleration channels).

- `notes`: `str`
  - Free text diagnostics or hints.

---

## 5) Compatibility with naming spec (v0.2)

This minimum registry is compatible with the column grammar in **Signal naming & units spec (v0.2)**:

- `kind`, `domain`, `unit`, and `op_chain` should be directly parseable from the column name when the name is canonical.
- The registry is still required even if names are canonical, because the registry is the **API surface** used by resolution logic.

---

## 6) Resolution expectations (for Option 1)

When resolving schema roles (e.g. `disp`, `vel`, `acc`) to columns, downstream code SHOULD use the registry to:

1. Filter candidates by `kind` (usually engineered `""`),
2. Filter by `unit` and `domain` as required by the schema,
3. Prefer “cleaner” stages using `op_chain` (policy-defined ranking),
4. Fall back deterministically and emit actionable diagnostics if no match exists.

This document does **not** define the ranking policy; it defines the minimum metadata required for any reasonable policy to operate.

---

## 7) Validation checklist

A session is compliant with this minimum registry if:

- `session["meta"]["signals"]` exists and is a dict
- Every numeric df column has a registry entry keyed by the exact column name
- Every entry has keys: `kind`, `unit`, `domain`, `op_chain`
- `kind == ""` entries have a non-empty `unit`
- `op_chain` is a list (possibly empty)

---

## 8) Implementation notes

- If you have both (a) a canonical naming parser and (b) legacy “best effort” heuristics, you may build the registry in **permissive mode** early, then run a later **standardization** pass that renames legacy columns and rebuilds/validates the registry in strict mode.
- Avoid overwriting a high-fidelity registry with a “minimal” one late in the pipeline; that can silently discard semantics needed by event/segment resolution.
