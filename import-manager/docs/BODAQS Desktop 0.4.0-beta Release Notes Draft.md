# BODAQS Desktop 0.4.0-beta Release Notes Draft

Status: draft for beta testing  
Build date: 14 October 2026  
Release date: TBD

BODAQS Desktop `0.4.0-beta` expands the Workbench with an Event Browser,
reusable Scenarios, spatial-context analysis, session annotations and more
consistent presentation. It also adds background cache warming and improves
BDQ v2 and multi-IMU import support. These notes cover changes since Desktop
`0.3.0-beta` and the macOS-only `0.3.1-beta` maintenance release.

## Component versions

| Component | Version |
| --- | --- |
| BODAQS Desktop bundle | `0.4.0-beta` |
| BODAQS Import Manager | `0.1.11-beta` |
| BODAQS Library Service | `0.3.0-beta` |
| BODAQS Workbench | `0.3.0-beta` |

Import Manager advances from `0.1.10-beta` because its bundled import engine
and packaged validation have changed. The installer records all four versions
in `component_versions.json`, also used by Help → About BODAQS Desktop.

## Highlights

- Added **Event browser (beta)** to inspect detected events with schema-defined
  signal windows, trigger markers, metrics, tags and aligned comparisons.
- Added saved Scenarios and a visual predicate builder, including custom-column
  selection, secondary streams and **Choose by meaning** semantic selection.
- Added **Find matching sessions** for one selected Scenario, with a minimum
  total-duration threshold, progress, cancellation and paginated results.
- Added spatial-context views and filtering based on gradient, twistiness and
  suspension activity where the processed session contains those products.
- Added session tags and user-reported GPS/QA flags, kept separate from
  automatically calculated GPS and QA results.
- Added idle warming of reusable activity indexes, Scenario evaluations and
  standard signal previews, with foreground priority and a Pause/Enable control.
- Improved video attachment from the library and standardized Workbench
  typography, chart labels, helper markers and metadata presentation.

## Workbench

### Scenarios and session search

The library Scenarios box lists saved definitions. Select one row without
checkboxes, set **Minimum total duration (s)** and run **Find matching sessions**.
Search uses the selected libraries and current table/search filters. A match
requires at least one qualifying episode and the requested total duration.
The saved Scenario's episode duration, eligibility and gap-bridging policies
still apply. Incomplete and unavailable evaluations are counted separately.

Results show matching duration and can add individual sessions to the Study Set.
**Apply scenario filter** and **Clear scenario filter** share one toggle above
the scrolling result list. The filter is temporary. Searches support up to
10,000 candidate references, with the existing per-session episode limit.

The visual builder offers column suggestions grouped by stream and semantic
selection through **Choose by meaning**. Library signal catalogs report the
fraction of sessions containing each signal. Suggestions help author reusable
definitions; they do not attach a Scenario to the suggestion library.

### Session annotations and video

The session context menu provides **Flag and tag…** and **Edit note**. Tags use
compact tiles, have an optional session-selector column, and support temporary
and saved filtering. User GPS and general QA issue flags can carry an
explanation without changing automatic GPS/QA assessments.

The video glyph and context menu show attached-video information. For sessions
without an attachment, Add video opens the Signal Inspector and invokes its
video-path browser. Video availability in the library Inspector context has
been corrected.

### Presentation

- Tightened the library Filters list spacing.
- Standardized labels separately from entered values, with sentence-case
  section/modal/analysis headings and preserved proper nouns and user names.
- Standardized chart axes at 11 px and cumulative-chart tooltips at a minimum
  of 9 px; retained the approved compact time-window text and heavy statuses.
- Replaced matching literal typography values with shared tokens and used the
  UI font stack for raster chart axes.
- Moved general explanations behind focusable info markers while retaining
  actionable warnings, errors and live counts.
- Listed metadata signals individually and grouped them by stream.

## Library Service and caching

Per-session Scenario evaluations are reusable across library searches and
analysis. Criterion diagnostics are a presentation choice, so requests that
omit them can reuse the same underlying evaluation. Cache dependency tracking
includes secondary-stream registration metadata and spatial distance data.
Standard preview keys ignore display-only session labels and redundant IDs.

The writable service enables one idle warmer at startup. It waits five seconds
after foreground work completes and builds one unit at a time. Recently used
sessions/Scenarios and recent imports/edits receive priority within a bounded
batch. Warming uses spare persistent-cache capacity and avoids promoting
speculative results into the shared memory cache. Import-agent locks suppress
new warm builds for the affected library. The worker is disabled in read-only
mode. Pause/Enable applies to the current service session.

User requests take priority at build boundaries. A read or evaluation already
in progress finishes before yielding; warming does not promise immediate
preemption. Finer interruption, byte budgets, wider candidate coverage and
additional cache products are recorded in the
[cache warming roadmap](../../docs/analysis/web-app/BODAQS_Library_Cache_Warming_Roadmap.md).

Search jobs and result lists are held in service memory and are lost on restart.
Underlying evaluation caches persist under
`<libraries root>/.bodaqs_library_api_cache/` in writable mode. Old preview cache
keys may miss once and rebuild after this update.

## Import Manager and import engine

- Expanded BDQ v2 multi-stream validation and import handling, including native
  IMU streams and multi-IMU recordings.
- Recorded the actual BDQ source contract in import provenance instead of
  identifying every BDQ import as v1.
- Improved logger Wi-Fi download retry handling.
- Corrected Windows About-version loading for installer-generated UTF-8
  manifests containing a byte-order mark.
- Expanded packaged BDQ smoke checks to include BDQ v1, BDQ v2 with four IMUs,
  and the installed Workbench layout.

## Compatibility and beta acceptance

Install the Workbench and Library Service together: the new search, annotation,
catalog and warming controls depend on their corresponding API endpoints.
Existing session artifacts remain usable when they contain the signals and
metadata required by the selected view. Spatial-context views require the
corresponding processed products; installing this release does not automatically
reprocess older sessions. Semantic selection requires suitable metadata and a
unique matching signal in the session.

Event Browser remains a beta feature. Validate event inspection and comparison
on representative recordings. Also check video attachment, note/tag/flag edits,
saved filters, secondary-stream Scenarios, search cancellation, imports and
cache warming under normal desktop workloads. Large recordings and slower
storage can extend the wait behind an in-progress warm unit. The first warmer
batch covers up to 16 sessions and four Scenarios rather than exhaustive
library coverage.

## Build and validation

The local Windows build includes the reviewed working-tree changes, including
uncommitted source files. It does not create a Git tag or publish a release.

- Full Python suite: 557 passed, 1 skipped.
- Frontend suite: 56 passed.
- Production Workbench build: passed.
- Packaged Import Manager BDQ v1 and four-IMU BDQ v2 smoke checks: passed.
- Staged desktop Workbench-layout smoke check: passed.
- Packaged Library Service: verified version `0.3.0-beta`, Workbench serving,
  idle activity/Scenario warming, Pause, and Scenario search results.
- Installer component manifest: verified all four requested versions.

## Windows download

- [Windows x64 installer](../dist/installer/windows/bodaqs-desktop-setup-0.4.0-beta.exe)
- Size: 108,935,418 bytes (103.9 MiB)
- [SHA-256 checksum](../dist/installer/windows/bodaqs-desktop-setup-0.4.0-beta.exe.sha256)
- [Build manifest](../dist/installer/windows/bodaqs-desktop-setup-0.4.0-beta.build-manifest.json)

```text
3D0ECDB72728E4CA8DEF1A0A17731F664D08097CD91B642D7E9F570EF83BF0C3
```

The installer contains Import Manager, Library Service and the built Workbench.
This package does not embed the optional demo library. Existing library paths
and installed demo data can continue to be used.

Desktop CI component defaults have been updated to Import Manager `0.1.11-beta`,
Library Service `0.3.0-beta` and Workbench `0.3.0-beta`. A `Desktop-v0.4.0-beta`
tag selects the bundle version; an ordinary main-branch push uses a CI build
identifier. This local build has not created or pushed that tag.

This locally generated installer is unsigned. Signing and publishing remain separate release steps.
