# BODAQS Workbench Typography Audit

Review date: 14 October 2026.

Implementation update: 14 October 2026. All four suggested passes have now
been applied with the explicit status/time-window exceptions below. The finding tables retain the original audit observations
so the before/after decisions remain reviewable.

| Findings | Current status |
| --- | --- |
| T01–T07 | Shared UI-font reset and explicit 12px regular entered/selected values; 10px semibold field labels; 12px regular checkbox/radio options; UI-font tag textarea; compact annotation-filter actions. Advanced JSON remains monospace. |
| T08 | Ordinary metadata labels are 10px semibold and values 11px regular. Modal helper text is 11px regular; warning/status body text is 12px regular. |
| T09 | Ordinary scope-summary values are 11px regular. Analysis category/requirement headings now use sentence case and semibold. Nested status badges retain emphasis. |
| T10–T11 | Video-info management uses the shared secondary action; both session and bookmark context-menu commands use 11px semibold. |
| T12 | Track/filter/scenario list names now use 12px semibold. Track Manager headings also use semibold. |
| T13–T15 | Authored section/modal/drawer headings use sentence case. GPS/QA modal titles use display labels rather than raw `gps`/`qc` identifiers. Built-in analysis headings are normalized without changing arbitrary record names. |
| T16 | Section headings use sentence case/semibold. Heavy status weights and uppercase status styling are deliberately retained. |
| T17 | Analysis hero titles use the guide's 17px analysis-title token. |
| T18 | Cumulative tooltip titles/values now use 9px text, with more room in the tooltip. Time-window overview text remains unchanged as requested. |
| T19 | Raster canvas axes now use the UI font stack and axis-size tokens, shared with uPlot. |
| T20 | Chart-axis ticks/titles use 11px across the audited SVG/canvas/uPlot paths, including altitude, spatial histograms, contours and signal preview/Inspector. |

Browser computed-style checks confirm that representative text inputs, selects
and ordinary textareas use the UI font at 12px/400 without capitalization
transforms. Checkbox/radio labels and the JSON exception were also checked.
Browser checks for passes 3/4 additionally verify 11px axis text, 9px cumulative
tooltip text, unchanged 6px time-window ticks, 17px analysis titles, and preserved
800/900 status weights. The complete frontend suite (45 tests) and production
build passed. Heading, chart and field typography rules are now documented in
the design guide.

The largest inconsistencies are in form controls: some use browser-default
fonts, while others inherit small, semibold label typography. Secondary issues
include oversized metadata, heavy metadata weights, inconsistent heading case,
and very small chart annotations. These were the findings at the initial audit;
the implementation status above identifies the subsequent changes.

The requested tag outline change is complete. Tags retain the grouping tile
layout and now use the first grouping palette color, `#2f7d6d`, for their
outlines in both the editor and session table. Other grouping colors continue
to represent individual groupings; tags do not acquire an arbitrary color cycle.

## Guide and review scope

The existing guide is [BODAQS Web App Design Language](BODAQS_Web_App_Design_Language.md).
Its typography section specifies the UI font stack, body/control text at 12 px,
dense table text at 11.5 px, captions at 11 px, uppercase labels/table headers at
10 px, and micro labels at 9 px. It calls for semibold headings/important labels
and discourages heavy metadata unless it represents a true status or action.
It also requires tokens instead of one-off values and recommends moving helper
text behind info markers.

This is a complete source and stylesheet pass over the currently implemented
Workbench screens, modals and shared controls. Chromium computed-style checks
covered 83 representative text/control elements using the same markup contexts
and current CSS, including the `.app-shell` overrides. Those checks establish
font family, size, weight and transformation; they are not a screenshot walk
through every live recording, map, chart combination or error state. Responsive
rules were included in the stylesheet review. Third-party map rendering and
canvas export fonts are identified separately below.

Classification:

- **Guide deviation:** a concrete mismatch with the documented typography or
  intended use.
- **Peer inconsistency:** comparable controls differ, but the guide does not
  specify enough to call one version wrong.
- **Review exception:** a deliberate density/technical choice may justify the
  difference; it should not be changed automatically.

## Findings

### Form fonts and entered values

| ID | Priority | Location and evidence | Inconsistency | Guide comparison |
| --- | --- | --- | --- | --- |
| T01 | High | Tags and user issues selector controls; Event Browser range fields and selectors; shared analysis selector controls. [AnnotationFilters.tsx](../../../application/cohort-workbench-prototype/src/components/AnnotationFilters.tsx), [EventBrowser.tsx](../../../application/cohort-workbench-prototype/src/components/EventBrowser.tsx), [AnalysisControls.tsx](../../../application/cohort-workbench-prototype/src/components/AnalysisControls.tsx). | These controls lack a UI font reset. Representative selects/number inputs compute to **Arial, 13.33 px, 400**, while adjoining labels/headings use the Aptos/Plex/Segoe UI stack. Other controls use the UI font at 12 px or inherit 10 px labels. | Guide deviation: general UI font stack and 12 px controls. This is a font-family mismatch, not just a slightly different size. |
| T02 | High | Signal Inspector video-path/name/offset fields, bookmark-name fields and signal search. `App.css`: `.signal-inspector-video-form input`, `.signal-inspector-save-row input`, `.signal-inspector-primary-signals-filter input`. | Video/bookmark input samples compute to **Arial, 12 px, 400**; signal search computes to **Arial, 13.33 px, 400**. Some nearby selects explicitly inherit the UI font. Setting size alone does not reset the browser's input font family. | Guide deviation: UI font stack. Peer inconsistency between fields in the same inspector. |
| T03 | High | Edit note and Flag and tag. `App.css`: `.note-editor-form label` and `.note-editor-form input, select, textarea`. | Entered text, including explanations, computes to **10 px, 650**, because `font: inherit` copies the label styling. The labels correctly have label typography, but their values copy it. Signal Inspector video values instead use 12 px regular text. | Guide deviation: labels are 10 px, but ordinary controls/body text are 12 px. Peer inconsistency. The recently restyled flag/tag editor inherits this existing note-editor issue. |
| T04 | High | Filter Manager and Scenario Editor. `App.css`: `.filter-manager-row`, `.condition-main-grid`, `.scenario-condition-grid`, and their input/select rules. | Name fields compute to **11 px, 650**; numeric/text predicate controls and custom-column/meaning picker inputs to **10 px, 650**. This repeats the inherited-label problem, with different sizes even within the same editing workflow. | Guide deviation for entered values. The broad `.app-shell` label rule overrides several declared 900 weights: the visible label weight in these samples is 650, not 900. |
| T05 | High | Filter Manager's Tags condition. [FilterManagerModal.tsx](../../../application/cohort-workbench-prototype/src/components/FilterManagerModal.tsx): `Tag names (one per line)` textarea. | The ordinary tag-entry textarea has no shared control class/font rule and computes to **monospace, 13.33 px, 400**. Adjacent visual-builder inputs are UI-font, 10 px semibold. | Guide deviation: this is user tag text, not code. The intentionally monospaced advanced JSON editor is a separate, reasonable exception. |
| T06 | Medium | Library root control, Study Set name, grouping name, GPS source picker and Track Manager creation/trackpoint forms. `App.css`: `.library-root-control`, `.study-name-row`, `.grouping-editor`, `.gps-source-select`, `.track-create-form`, `.trackpoint-form`. | Label sizes alternate between **10 and 11 px**. Their values commonly inherit that size and semibold weight, rather than using regular control text. | Guide deviation for ordinary controls; smaller peer inconsistency in labels. These older forms share the same root cause as T03/T04. |
| T07 | Medium | Tags and user issues temporary-filter panel. `App.css`: `.session-annotation-filter-controls`; [AnnotationFilters.tsx](../../../application/cohort-workbench-prototype/src/components/AnnotationFilters.tsx). | Labels remain **14 px semibold, sentence case**, and plain action buttons inherit **14 px regular**. Nearby filter controls use compact 10 px uppercase labels and 11/12 px semibold actions. Its native-font selects are covered by T01. | Guide deviation in label/control sizing; peer inconsistency with the adjoining selector/filter controls. |

### Metadata and action text

| ID | Priority | Location and evidence | Inconsistency | Guide comparison |
| --- | --- | --- | --- | --- |
| T08 | Medium | Session metadata, GPS/video information and Track/Study Set detail modals. `App.css`: `.detail-list dt`, `.detail-list dd`, `.modal-note`, `.alert-list`. | Detail labels are **11 px/800/uppercase**, while ordinary values and several explanatory/warning paragraphs inherit **14 px/400**. Note-editor metadata is **11 px/400**; Signal Inspector GPS metadata is also 11 px. | Guide deviation: heavy ordinary metadata and body values above the 12 px body token. Peer inconsistency among information panels. |
| T09 | Medium | Analysis Launcher scope summary and ordinary identifiers/counts in analysis metadata. `App.css`: `.analysis-scope-summary dt/dd`; `.analysis-view-category`, `.analysis-requirement-tier`. | Generic summary values compute to **14 px/800**, whereas the note/flag summary explicitly resets values to **11 px/400**. Category labels use bold 800; most neighboring panel titles use semibold 650. | Guide deviation for non-status metadata. A genuine status/count emphasis may be intentional; review the actual field before removing emphasis. |
| T10 | Medium | Video information modal's `Manage video in Signal Inspector` action. [SessionVideoInfo.tsx](../../../application/cohort-workbench-prototype/src/components/SessionVideoInfo.tsx). | The button uses `secondary` rather than the shared `secondary-action` class and computes to **14 px/400**. Standard modal actions are **12 px/650**. | Guide deviation and clear peer inconsistency. Similar plain buttons elsewhere should be reviewed in their own parent context, since some inherit a compact button rule. |
| T11 | Low | Session row menu versus Signal Inspector bookmark menu. `App.css`: `.session-row-context-menu button`, `.signal-inspector-bookmark-context-menu button`. | Session actions are **11 px/650**; bookmark actions are **12 px/650**. Both are small context-menu commands. | Peer inconsistency only: either density can be reasonable. The guide allows compact buttons but does not mandate one context-menu size. |
| T12 | Low | Track Manager list versus saved filter/scenario list. `App.css`: `.track-manager-list-item`, `.filter-manager-list-item strong`. | Representative track names inherit **14 px/700**; filter names use **12 px/700**. Track Manager side headings inherit browser heading weight 700 while common modal section headings explicitly use 650. | Peer inconsistency and heading-weight deviation. The guide does not establish a single list-title size, so review density before standardizing it. |

### Headings and capitalization

| ID | Priority | Location and evidence | Inconsistency | Guide comparison |
| --- | --- | --- | --- | --- |
| T13 | Medium | Track Analysis Find sessions, Find tracks and Add to view cards versus Track Manager and general information modals. `App.css`: `.track-analysis-add-card h3`, `.track-manager-side h3`, `.modal-section h3`. | Query/result section headings are **13 px/800/uppercase**; Track Manager headings are **13 px/700/mixed case**; general modal sections are **13 px/650/mixed case**. These are peers within related track workflows. | Guide deviation in heading weight. Capitalization is a peer inconsistency; the guide does not require all section headings to use sentence case. |
| T14 | Medium | Session GPS and QA modal titles. [Modal.tsx](../../../application/cohort-workbench-prototype/src/components/Modal.tsx): `modalTitle`. | Titles interpolate internal tab identifiers, producing `session: gps` and `session: qc`, while the glyphs/menu use **GPS** and **QA**. `metadata` and `video` similarly remain raw lowercase identifiers. | Peer inconsistency and user-facing terminology mismatch. The guide does not explicitly prescribe modal-title case. |
| T15 | Low | Shared analysis drawer and modal headings. [AnalysisControls.tsx](../../../application/cohort-workbench-prototype/src/components/AnalysisControls.tsx), [ScenarioEditorModal.tsx](../../../application/cohort-workbench-prototype/src/components/ScenarioEditorModal.tsx), [GeospatialWorkbench.tsx](../../../application/cohort-workbench-prototype/src/components/GeospatialWorkbench.tsx). | The same drawer reads `Select and Filter` expanded and `Select and filter` collapsed. Modal titles mix `Filter Manager`, `New Track`, `Create or edit Scenario`, `View/edit note` and `Flag and tag`. | Peer inconsistency. Keep proper nouns/acronyms such as GPS, QA and Study Set; the guide itself uses mixed title/sentence case and does not settle a universal rule. |
| T16 | Low | GPS status, analysis readiness, Event Browser chart captions and Inspector versus analysis side-section titles. `App.css`: `.gps-route-status strong`, `.analysis-status-badge`, `.event-browser-chart figcaption`, `.viz-filter-group > strong`, `.signal-inspector-card h3`. | Status/section typography ranges from **11 px/900/uppercase** GPS status and **11 px/800/uppercase** analysis labels to **13 px/650/mixed case** Inspector card titles. | Peer inconsistency. Heavy true statuses are permitted by the guide, so uppercase/bold alone is not proof of a violation. Ordinary section labels deserve a separate review from warning/readiness badges. |
| T17 | Low | Simple Suspension and Phase Diagram hero titles versus Analysis Launcher titles. `App.css`: `.suspension-viz-hero h3`, `.analysis-launcher-title-row h3`. | Both identify an analysis scope, but the analysis screens use the **18 px modal-title token**, while the launcher uses the **17 px analysis-title token**. | Small guide/token-role deviation. A deliberately larger hero title could be documented as an exception. |

### Chart text

| ID | Priority | Location and evidence | Inconsistency | Guide comparison |
| --- | --- | --- | --- | --- |
| T18 | Medium | Suspension/Phase time-window ticks and cumulative-chart tooltip text. `App.css`: `.viz-time-window-overview .viz-time-window-tick-label`, `.viz-cumulative-tooltip text/title`. | These declare **6 px** ticks and **7 px** tooltip text, below the **9 px** micro-label token. Other chart labels are typically 10–12 px. | Guide deviation and review exception. SVG viewBox scaling affects apparent size, so judge them at their actual display/export dimensions before changing them. |
| T19 | Medium | Rasterized phase heatmap axes. [SuspensionVisualization.tsx](../../../application/cohort-workbench-prototype/src/components/SuspensionVisualization.tsx): `context.font = '12px system-ui, sans-serif'`. | The canvas path selects a different font stack from the surrounding SVG/UI and Signal Preview/Inspector uPlot axes. | Guide deviation in font family. A fallback or export path can expose the mismatch even when the standard SVG view looks consistent. |
| T20 | Low | Library altitude, Inspector altitude, spatial charts and signal previews. `App.css`: `.library-altitude-chart text`, `.signal-inspector-altitude-chart text`, `.track-analysis-spatial-chart-wrap text`, `.track-analysis-spatial-histogram text`; uPlot axis options. | Similar axis labels use **12, 11 and 10 px**, with 9 px boundary labels. | Review exception/peer inconsistency. Dense mini-plots may warrant smaller text; there is no explicit chart-axis-size rule in the guide. The uPlot font stack currently matches the guide, although its literal copy will not follow future token changes automatically. |

## Screen and modal coverage

The finding IDs above group shared causes rather than treating each affected
field as a separate defect.

| Surface reviewed | Findings or outcome |
| --- | --- |
| Library header, root/library picker and collapsed root rows | T06; app/page title tokens otherwise consistent. |
| Session Selector, search, column chooser, table headers and row menu | T07/T11; table headers follow the uppercase label token. Tags column uses the requested grouping-style tiles. |
| Filters list and temporary annotation filters | T07; broad label override prevents declared 900 legend weights from actually appearing as 900. |
| Selected session GPS, map controls and altitude preview | T06/T16/T20. |
| Signal Preview | T20; uPlot axis font stack matches the UI guide. |
| Tracks list, trackpoint editor and GPS match summaries | T06/T12/T16. |
| Study Set builder, groupings, selected/saved-session tables and saved Study Sets | T06/T09. Grouping and tag outlines now match the default grouping palette. |
| Edit note | T03; header/summary structure follows shared modal styling. |
| Flag and tag | T03 inherited from Edit note; no flag state changes on opening. |
| Session QA, GPS, metadata and video-info modals | T08/T10/T14/T16. |
| Track details and saved Study Set details | T08; common modal section headings otherwise use the shared 13 px semibold rule. |
| Track Manager/New Track | T06/T12/T13/T15. |
| Filter Manager, visual conditions, trackpoint conditions and advanced JSON | T04/T05; JSON monospace is intentional. |
| Scenario Editor, numeric builder, custom column, semantic picker and advanced JSON | T04/T15; meaning details summary also inherits plain 14 px text beside 10 px labels. JSON monospace is intentional. |
| Analysis Launcher, readiness cards, requirements and scope summary | T09/T16/T17. |
| Signal Inspector charts, mode/signal/event controls, bookmarks, GPS/altitude/video panels and context menu | T02/T11/T16/T20. |
| Simple Suspension Analysis, its select/filter drawer and comparison charts | T01/T15/T16/T17/T18/T20. |
| Phase Diagram, contour/conditional controls, legends and raster fallback | T01/T15/T16/T17/T18/T19/T20. |
| Track Analysis and Lap Timing, spatial metrics, track/session lists, altitude and video | T01/T06/T16/T20; associated find/add modals covered by T13. |
| Event Browser, populations/scenarios, time/metric filters, pinned events, schema tags and aligned charts | T01/T16/T20. |
| Find sessions, Find tracks and Add to view modals | T06/T13. |
| Unsaved Study Set dialog and demo welcome dialog | Shared modal-title/action patterns are consistent; no additional distinctive typography finding. Promotional kicker and link emphasis are reasonable exceptions. |
| Shared badges, info tooltips, map/route wrappers and loading/error/empty states | T08/T16. Monospace JSON, acronym capitalization and map attribution density should not be treated as generic defects. Third-party map internals were not restyled. |

## Additional guide differences

The token cleanup replaced 72 literal font sizes and 22 literal weights in
`App.css` with applicable existing tokens, and the JSON editor uses the shared
code font stack. No matching literal sizes/weights remain in that stylesheet.
The approved 6px time-window text and unmatched 600/700 weights retain their
existing appearance. Runtime chart font fallbacks remain necessary when CSS
is unavailable.

General explanations in annotations, note fields, scenario controls and track
analysis now use info markers. Shared analysis-card hints also use markers.
Actionable reference/catalog warnings, errors, empty states and live counts
remain visible. Markers support keyboard focus and do not toggle an enclosing
control when clicked. The helper-text inventory records these locations.

Validation: all 47 frontend tests passed, including keyboard-description and
checkbox-isolation checks for info markers. The production build passed.

## Suggested order for a later styling pass

1. Establish a shared font reset for native controls, then distinguish label
   typography from entered-value typography (T01–T07).
2. Normalize ordinary metadata and modal actions (T08–T12).
3. Agree on section/modal/drawer capitalization and heading weights, preserving
   proper nouns and meaningful status emphasis (T13–T17).
4. Inspect chart text at actual on-screen/export sizes before deciding which
   density exceptions to retain (T18–T20).

All four passes are implemented as described above. The guide records the
agreed field/metadata rules, sentence-case headings, 17px analysis titles,
11px chart axes and 9px cumulative tooltips. Heavy statuses and the compact
time-window overview retain their explicitly approved exceptions. The
helper-text inventory now includes the subsequent info-marker cleanup.
