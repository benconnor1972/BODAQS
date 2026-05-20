# Data Syn Bike Export Implementation Plan

## Goal

Optionally emit data.syn.bike-compatible outputs for new import-agent sessions
when the target BODAQS library opts in. The canonical BODAQS artifact contract
remains unchanged.

## Decisions

- The setting is per-library, stored in `library_definition.json`.
- Existing imported sessions are not backfilled by v1.
- Outputs live under `<library>/syn/`.
- Each session gets its own helper text file with manual data.syn.bike settings.
- Raw export values may be calibrated synthetic ADC counts scaled to the target
  ADC bit count, because data.syn.bike assumes rail-to-rail raw input.

## Implementation Touch Points

- Extend `bodaqs_analysis.exporters.data_syn_bike` with calibrated full-scale
  raw scaling and helper-settings rendering.
- Extend import-agent library provisioning to write an export settings block.
- Extend the manager UI to show and toggle the per-library export setting.
- During import, after canonical artifacts are written, generate optional
  `syn/` outputs if the target library enables them.
- Record a library-level syn export manifest for audit/debugging.

## Non-Goals

- No automatic backfill for old sessions.
- No change to logger firmware output format.
- No change to canonical session/event/metric artifacts.
