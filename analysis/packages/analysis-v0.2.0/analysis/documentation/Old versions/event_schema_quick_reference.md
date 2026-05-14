
# Event Schema Quick Reference

## Blocks

- `events[]`
- `trigger`
- `secondary_triggers[]`
- `preconditions` / `postconditions`
- `debounce`
- `window`
- `metrics[]`

## Trigger types

| Type | Purpose |
|------|---------|
| simple_threshold_crossing | Crossing detection |
| phased_threshold_crossing | Pattern: NEG→ZERO→POS |
| local_extrema | Min/max with prominence |
| zero_crossing | Special threshold crossing |

## Debounce

```yaml
debounce:
  gap_s: float
  prefer_key: "trigger_strength" | ...
  prefer_abs: bool
  prefer_max: bool
```

## Metric ops

- mean
- max
- min
- peak
- delta
- integral
- time_above

---

# End of Document
