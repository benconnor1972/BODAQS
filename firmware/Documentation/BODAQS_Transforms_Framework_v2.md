# BODAQS Transform Framework

This document describes the **transform framework** used in the BODAQS firmware.
It covers how transforms are defined, loaded, selected, and applied at runtime.

SD card hardware, filesystems, and backend selection are documented separately in
`SD_Card_Architecture.md`. This document assumes SD access is already available.

---

## 1. Purpose and design goals

The transform framework exists to:

- Convert **real‑world sensor values** into alternative representations
- Allow sensor-specific calibration and shaping without firmware recompilation
- Keep runtime logic simple and predictable
- Enforce **firm, explicit contracts** between configuration, files, and code

Key design principles:

- Transform identity is explicit and stable
- Filenames are *not* part of the runtime contract
- Failure modes are safe and visible
- No automatic “guessing” or canonicalisation at runtime

---

## 2. Transform types

BODAQS currently supports two transform types:

### 2.1 LUT (Lookup Table)

- File format: `.lut.csv`
- Piecewise-linear mapping
- Optional clamping or extrapolation
- Human-readable and easy to tune

### 2.2 Polynomial

- File formats:
  - `.poly.json`
  - `.poly.cfg`
- Arbitrary-order polynomial mapping
- Suitable for smooth, analytic curves

Each transform defines its own metadata and mapping parameters.

---

## 3. On-disk layout

Transforms are stored per sensor:

```
/cal/<sensor_name>/
```

Example:
```
/cal/rear_shock/wheel_mm.lut.csv
/cal/front_shock/travel.poly.json
```

The directory name **must exactly match the sensor name** as defined in configuration.

---

## 4. Transform identity (critical contract)

### 4.1 Source of identity

Each transform has a **logical identity**:

- Preferably defined explicitly via `meta.id` in the file header
- Otherwise derived from the filename as a fallback

This identity is stored as:

```
transform.meta.id
```

### 4.2 Configuration contract

Sensor configuration selects a transform via:

```ini
sensorX.output_id=<transform_id>
```

**Important:**

> Transform filenames are *not* identifiers.  
> Only `transform.meta.id` is used for selection.

Example:

```
Filename:   lut_wheel_mm.lut.csv
meta.id:    wheel_mm

output_id=wheel_mm        ✅ correct
output_id=lut_wheel_mm    ❌ incorrect
```

No canonicalisation, prefix stripping, or filename matching is performed at runtime.
If `output_id` does not exactly match a loaded `meta.id`, the transform will not be found.

This is a deliberate design choice.

---

## 5. Transform loading

### 5.1 Load timing

Transforms are loaded:

- During sensor construction
- Before transform selection and attachment
- Once per boot (not dynamically reloaded)

### 5.2 Loading process

For each sensor:

1. The directory `/cal/<sensor_name>/` is scanned
2. Supported transform files are parsed
3. Metadata and mapping data are loaded
4. Transforms are stored internally, keyed by `meta.id`

If the directory does not exist, loading is skipped without error.

---

## 6. Transform application point

Transforms are applied **after conversion to real-world units**.

The sensor pipeline is:

1. ADC read (raw counts)
2. Optional smoothing (EMA, deadband)
3. Zero offset and polarity handling
4. Conversion to real-world units (e.g. mm)
5. **Transform application**
6. Final value logged

### Output modes

- `RAW`
  - Bypasses transforms entirely
  - Logs raw (smoothed) ADC counts
- `LINEAR`
  - Logs real-world units without transform
- `POLY` / `LUT`
  - Applies the selected transform to real-world units

Polarity inversion is applied *before* transform evaluation.

---

## 7. Transform selection and attachment

After loading:

1. The sensor’s `output_id` is read from configuration
2. The registry is queried using `<sensor_name, output_id>`
3. If found, the transform is attached to the sensor
4. If not found, the identity transform is used

---

## 8. Failure behaviour and fallbacks

Failure is handled safely and explicitly.

### 8.1 Identity fallback

If any of the following occur:

- Transform directory is missing
- Transform file fails to parse
- `output_id` does not match any loaded transform

Then:

> The sensor falls back to the **identity transform**, and logging continues.

This behaviour is intentional and prevents logging failures from blocking operation.

### 8.2 ID collisions

If multiple transform files resolve to the same `meta.id`:

- The **last-loaded transform overwrites earlier ones**
- No warning is currently issued

This is acceptable but should be avoided in practice.

---

## 9. Web UI responsibilities

The web UI may present filenames or labels to the user, but:

> When persisting configuration, the UI **must write `transform.meta.id`** to `output_id`.

Writing filenames or derived names is invalid and will result in identity fallback at runtime.

---

## 10. Transform lifecycle summary

1. Sensor defined in configuration
2. Sensor instance created
3. TransformRegistry scans `/cal/<sensor>/`
4. Transform files parsed and indexed by `meta.id`
5. `output_id` matched against loaded transforms
6. Selected transform attached to sensor
7. Transform applied during each sample

---

## 11. Design decisions (summary)

- Transform identity is explicit and stable
- Filenames are not part of the runtime contract
- No canonicalisation or heuristic matching
- Identity fallback is safe and intentional
- Transform logic is independent of SD hardware details

This approach prioritises correctness, debuggability, and long-term maintainability.

---

_End of document._
