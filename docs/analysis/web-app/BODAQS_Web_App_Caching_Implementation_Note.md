# BODAQS Web App Caching Implementation Note

Status: draft  
Date: 2026-07-01  
Audience: library API / web app / analysis-view implementation

This note records the caching work added during the web application prototype
performance pass, and the likely next enhancements. The current goal is to make
common analysis workflows feel snappy without changing the persisted library
contract or requiring users to manage cache state manually.

## Current Cache Layers

### Browser-Side Analysis Data Cache

The simple suspension analysis view keeps reusable analysis data in the browser
while the application is open. This reduces repeated fetch and recomputation
when a user:

- changes time windows within the same study set
- toggles sessions, ends, sectors, or inactive-period exclusion
- closes and reopens the same analysis view during the same browser session
- opens overlapping analysis views that need the same session-level inputs

This cache is best at avoiding repeated client-side transformation work and
duplicate network calls inside one active browser session. It does not survive a
full browser restart unless data is also available from server-side caches.

### Server-Side Analysis Adequacy Cache

The library API caches analysis-view adequacy evaluations. These evaluations are
keyed from the analysis view, adequacy policy version, scope, study-set revision,
session references, and relevant catalog-level session dependencies.

Adequacy entries are stored in:

- an in-memory LRU cache for fast repeat checks
- a persisted JSON cache under `.bodaqs_library_api_cache` for reopen/restart
  performance

Study-set create/update warms adequacy for known analysis views. Library refresh
and relevant library mutations invalidate cached adequacy entries.

This is useful because adequacy is a good candidate for reuse: if the analysis
view definition, study set, and underlying session metadata have not changed,
the answer should not change.

### Server-Side Analysis Input Cache

The library API now also has an in-memory `analysis_input` cache for repeated
raw analysis-input queries:

- signal queries
- event queries
- metric queries

Entries are cached per library, per session, per query kind, and per request
shape. Cache keys include fingerprints for the artifact files read by the query,
including size and modification time, so rewritten parquet or metadata artifacts
naturally produce a new key and avoid stale results.

This is intentionally in-memory only for now. It improves repeated access during
one running library-service process, especially when multiple tabs or analysis
views ask for overlapping session data. It does not yet accelerate service
restart or cold reopen of heavy signal/event/metric payloads.

## Invalidation Behaviour

The current approach combines two protections:

- Dependency-aware keys include artifact fingerprints, so changed files miss old
  cache entries.
- Explicit invalidation clears relevant namespaces on broad mutations such as
  library refresh and session delete.

This means stale data risk is low for normal prototype workflows. The approach
does not attempt fine-grained removal of only the affected cached query entries;
it favours simple, safe invalidation while the API surface is still evolving.

## What Is Not Cached Yet

The following are deliberately not persisted or only partially cached:

- Heavy signal/event/metric query payloads across service restarts.
- Timeseries-window responses used by the signal inspector.
- GPS point payloads and map-ready geometry.
- Fully composed analysis-view render datasets.
- Cross-tab shared browser cache via IndexedDB or a service worker.

These are all possible future layers, but each carries more storage, invalidation,
or complexity cost than the current adequacy and in-memory query caches.

## Likely Future Enhancements

### 1. Persisted Analysis Input Cache

Persist selected signal/event/metric query results to disk, probably as compact
JSON or parquet-backed cache records under `.bodaqs_library_api_cache`.

Expected benefit:

- Faster reopen/restart performance for repeated study-set analysis.
- Better support for users who close and reopen analysis tabs frequently.

Risks/tradeoffs:

- Cache files may become large for dense signal payloads.
- Cache pruning policy becomes important.
- Cache key and artifact dependency rules need continued discipline.

Recommended approach:

- Start with persisted event/metric query payloads, which are smaller and more
  structured.
- Add signal payload persistence only after measuring real payload sizes and
  load-time impact.

### 2. Timeseries Window Cache

Cache server responses for signal-inspector time windows, keyed by session,
selected signals/events, requested window, sampling/downsampling policy, and
artifact fingerprints.

Expected benefit:

- Faster repeated inspection of the same session and window.
- Better feel when navigating back to recently viewed bookmarks or ranges.

Risks/tradeoffs:

- Many small near-duplicate windows could create cache churn.
- Cache keys need quantisation or exact-window policy to avoid low hit rates.

### 3. GPS And Map Geometry Cache

Cache simplified GPS paths and map-ready overlays for sessions, study sets, and
tracks.

Expected benefit:

- Faster session-browser map updates.
- Less repeated geometry simplification in common map previews.

Risks/tradeoffs:

- Needs careful source selection when sessions contain multiple GPS sources.
- Track/study-set edits should invalidate relevant geometry.

### 4. Cross-Tab Browser Cache

Move more browser-side analysis data into a shared cache layer such as IndexedDB,
so multiple analysis tabs can reuse the same fetched session payloads.

Expected benefit:

- Stronger performance for the likely workflow of opening multiple analysis tabs
  against the same study set.

Risks/tradeoffs:

- More complicated cache lifecycle and storage limits.
- Need a clear invalidation handshake with library service cache keys or library
  revision metadata.

### 5. Cache Diagnostics And Developer Tooling

Extend diagnostics to expose per-namespace hit rates, approximate payload sizes,
oldest/newest entries, and invalidation counts.

Expected benefit:

- Easier confidence-building before persisting larger payloads.
- Easier performance regression investigation.

Risks/tradeoffs:

- Low product value for users unless kept behind a developer-oriented surface.

## Recommended Next Step

Leave the current cache stack in place while gathering real usage feedback. The
next high-value technical step is measurement rather than another cache layer:

- record timings for library-service query handlers
- record payload sizes for signal/event/metric responses
- compare cold, warm in-memory, and warm persisted adequacy paths
- identify whether signal payload size, parquet read time, JSON serialization, or
  client-side transformation dominates the remaining delay

If repeated reopen/startup remains painful after measurement, the best next cache
candidate is persisted event/metric query payloads, followed by selective
persisted signal payloads if the measurements justify the storage cost.
