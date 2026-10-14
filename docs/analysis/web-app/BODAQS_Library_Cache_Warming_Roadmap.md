# BODAQS Library cache warming roadmap

Updated: 14 October 2026

Idle cache warming prepares reusable results before the user asks for them.
Foreground requests take priority, and speculative work must stay within spare
cache capacity. The first slice covers activity indexes, saved Scenario
evaluations and standard signal previews. Further expansion depends on measured
foreground latency, cache reuse and disk consumption.

Standard preview keys now ignore display-only session labels and redundant
reference identifiers, so browser requests reuse the same entries as background
builds. Older preview cache keys can miss once and be rebuilt; session data
requires no migration.

## Implemented scope

The writable Library API starts one warming worker. It waits five seconds after
foreground work finishes, builds one unit at a time, and checks for waiting user
requests before each new unit. Health, warming-status, catalog-revision and query
status polling do not prevent warming. Scenario searches and trackpoint query
workers remain foreground work after their initiating HTTP request returns.

The planner uses catalogs already loaded by user activity. Each batch covers up
to 16 sessions, prioritizing recent scenario/preview use and then import/start
timestamps, and up to four saved Scenarios, prioritizing recent use and edits.
Plans refresh after a completed batch and at least 60 seconds. Library-root
changes replace the plan. An obsolete Scenario revision is skipped. The import
agent's per-library lock prevents new builds for that library while present.

| Cache candidate | First-slice behavior |
| --- | --- |
| Activity indexes | Build the canonical activity index once per session. |
| Saved Scenario evaluations | Build complete per-session evaluations; both searches and analysis can reuse them, with criterion diagnostics omitted from the response when requested. |
| Standard signal previews | Build the existing full-session, 900-point front/rear normalized wheel-displacement preview when those signals exist. Arbitrary windows and multistream combinations are excluded. |

Background results populate the existing root-level disk cache without promoting
speculative entries into the shared memory cache. Warming stops filling a namespace
at half its existing entry limit: 512 activity indexes, 1,024 per-session Scenario
evaluations and 128 standard previews. These limits include foreground-created
entries; warming does not evict existing entries to make space. Existing source
fingerprints and algorithm identities determine whether an evaluation is reusable.

Cache lookup/build locks coordinate duplicate requests within an adapter.
Persistent writes use distinct temporary files and coordinate same-entry access
within the process. Different service processes can still compute the same miss.

The library panel shows warming status and a Pause/Enable control. The setting
lasts for the service session; writable restarts enable warming again. Read-only
services do not run the worker. Pause stops the next unit, allowing a build already
in progress to finish. Background failures are counted in the status API and do
not fail a foreground request.

## Foreground latency and resource limits

Foreground requests arriving during a build wait for that single unit to finish;
the event loop remains available for lightweight status and pause requests. A
Parquet read or a long session evaluation is not forcibly interrupted. Import
locks are checked between units, so an import beginning during a build has the
same boundary. Shutdown also waits for the current unit.

The worker uses a one-second interval between attempts. Large recordings can
still consume significant CPU, disk bandwidth and temporary memory. This first
slice is bounded opportunistic work, not an operating-system idle detector or
a guaranteed foreground response-time limit.

## Performance acceptance

Compare warming disabled and enabled on representative libraries. Include long
primary recordings, high-rate secondary streams, several active Scenarios and
slow or network-backed storage. Measure foreground median and tail latency,
maximum wait behind one warm unit, CPU/memory peaks, bytes written and subsequent
cache reuse. Exercise pause, root changes, imports and shutdown during a build.

A useful next target is a foreground latency budget. If a whole-session unit
exceeds it, finer interruption boundaries should precede broader warming.

## Scheduling and cache management roadmap

1. Add cooperative checkpoints or row-group processing for long evaluations.
   Preserve episode continuity, eligibility masks and gap-bridging semantics at
   chunk boundaries. Consider an isolated worker process if cancellation needs
   to interrupt native work; account for its memory and startup costs.
2. Add byte-based disk and memory budgets, speculative-entry attribution and
   eviction that protects user-requested results. Reclaim obsolete fingerprints
   without repeatedly cycling through every Scenario/session combination.
3. Expand bounded planning beyond the current 16-session/four-Scenario batch,
   using measured demand and import notifications. Persist usage history only
   if its benefit justifies the added state. Full-library coverage is not promised
   by the first slice.
4. Persist the enable preference, add workload/time or battery-sensitive limits,
   and expose skipped-unit reasons, hit rates, build durations and disk growth.
   Decide whether read-only hosted deployments should prebuild caches during
   deployment rather than warm them at runtime.
5. Coordinate equivalent requests across service processes where needed. Keep
   persistent cache data disposable and separate from canonical session artifacts.

## Additional cache candidates

| Candidate | Benefit and next decision |
| --- | --- |
| Session and library signal catalogs | Improve opening and pickers after imports. Reuse revision-driven rebuilding; avoid repeatedly refreshing unchanged libraries. |
| Standard GPS route previews | Improve maps. Choose a few standard resolutions and source selections; current GPS cache is memory-only. |
| Track matches | Improve track searches. Prioritize recently used tracks and new sessions; avoid evaluating every track against every session. |
| Analysis readiness | Already cached and comparatively inexpensive. Warm known saved Study Sets only if measured startup cost warrants it. |
| Event/metric query results | Potentially improve analysis opening, but scopes and options create many variants. Select commonly used request forms before introducing persistence. |
| Arbitrary Inspector windows and multistream displays | Keep on demand initially. Their request space is too large for exhaustive warming. |

No firmware or preprocessing-format migration is required. Broader caches should
reuse canonical artifacts rather than introduce unconditional preprocessing work
for data the user may never inspect.
