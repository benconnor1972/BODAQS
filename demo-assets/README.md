# BODAQS Demo Assets

This directory is staged into the BODAQS Desktop installer when present. A
curated demo library should be generated here before release builds.

Expected runtime package shape:

```text
demo-assets/
  demo_manifest.json
  libraries/
    bodaqs-demo/
      library_definition.json
      runs/
      ...
  study_sets/
  tracks/
  bookmarks/
  session_filters/
```

Use `tools/build_demo_library.py` with a recipe from `demo-assets/recipes/` to
build or refresh the curated payload. The installer and Import Manager will only
offer demo-library installation when this directory contains at least one
library under `libraries/*/library_definition.json`.
