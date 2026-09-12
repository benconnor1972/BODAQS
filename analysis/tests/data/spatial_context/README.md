# Spatial-context real-data regression corpus

This compact corpus is derived from the private `Sunday Collie intel gathering`
run. It retains the native-rate front and rear wheel-displacement evidence needed
by suspension activity, plus the GPS observations and activity mask needed by the
other spatial metrics.

Coordinates are relocated to a neutral origin, timestamps and altitude are
rebased, and unrelated channels are omitted. Route shape and suspension values
are retained because they are the evidence under test.

`manifest.json` records provenance, deterministic fault variants, canonical
configuration overrides, and tolerant output summaries. Rebuild it from a local
copy of the source library with:

```powershell
$env:PYTHONPATH = (Resolve-Path analysis).Path
.\.venv\Scripts\python.exe -m bodaqs_analysis.spatial_context_corpus `
  --source-library-root "$HOME\OneDrive\BODAQS-data\libraries\default-library" `
  --output-root "analysis\tests\data\spatial_context"
```

Review changes to the manifest when intentionally changing an algorithm or a
canonical parameter. Do not regenerate expectations merely to silence a failed
regression test.
