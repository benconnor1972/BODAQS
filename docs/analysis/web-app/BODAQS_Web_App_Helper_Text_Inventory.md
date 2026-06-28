# BODAQS Web App Helper Text Inventory

Status: draft  
Audience: session browser / study-set builder / simple suspension metrics UI

This document lists the helper text currently exposed through small info icons in
the web app prototype. The purpose is to keep explanatory copy out of the main
layout while making the wording easy to review and refine.

## Browser And Study Set Builder

| UI location | Helper text | Used for |
| --- | --- | --- |
| Library Selector heading | Choose which libraries from the configured library root are included in the session browser. | Explains library inclusion scope. |
| Session Selector heading | Browse sessions from the selected libraries. Use reusable filters from the filter panel or column filter icons in the table to narrow the list. | Distinguishes browsing/filtering from Study Set membership. |
| GPS Location heading | Preview the selected session GPS path and any selected or attached tracks. | Explains the GPS preview panel. |
| Filters heading | Create and apply reusable filters on the sessions displayed. Filters stack and combine with table filtering. | Explains reusable filters versus ad hoc column filters. |
| Filter row description | Dynamic: the filter's description field. | Provides per-filter context inline with the filter name. |
| Filter manager field selector | Dynamic: field-specific help text from the filter field definition. | Explains the selected condition field. |
| Current Study Set heading | The working Study Set comprising sessions and optional groupings and tracks. | Explains the Study Set object. |
| Study Set sessions subsection | List of the sessions in this study set. Removing a session removes it from the Study Set, but not from the library. | Explains session membership and safe removal. |
| Study Set groupings subsection | Named collections of Study Set sessions. Sessions can belong to more than one grouping. | Explains grouping membership within a Study Set. |
| Study Set tracks subsection | Tracks are GPS paths with defined points that can be used for geospatial filtering and sector-based analysis. | Explains attached tracks. |
| Study Set GPS Location heading | Preview the GPS paths for sessions in the current Study Set and any tracks attached to it. | Explains the Study Set scoped GPS map. |
| Saved Study Sets heading | Saved Study Sets can be loaded into the editor above, inspected, or opened directly in the analysis view. | Explains saved Study Set actions. |
| Analysis launcher intro | Choose an analysis view for the current scope. The adequacy check reports whether the selected sessions have the required and recommended data for that view. Opening a view creates a separate browser tab so the Library Browser remains available. | Explains the analysis-view selection, adequacy-check step, and separate-tab analysis behavior. |
| Analysis launcher route note | Dynamic: saved Study Sets open with reloadable analysis routes; unsaved scopes open with temporary browser-local routes. | Explains route durability for saved versus unsaved analysis scopes. |
| Analysis route header | Browser | Returns the current analysis tab to the Library Browser by clearing the analysis route hash. |

## Geospatial Controls

| UI location | Helper text | Used for |
| --- | --- | --- |
| Selected session GPS card | Shows GPS source and coverage for the selected session. | Explains selected-session GPS summary. |
| Study Set GPS card | Summarizes GPS quality for Study Set sessions. | Explains aggregate GPS adequacy. |
| Tracks card | Tracks are reusable GPS paths with defined points. Select a track to preview it, or add it to the current Study Set. | Explains reusable tracks and Study Set attachment. |
| Track Manager modal | Guided track creation placeholder: this first cut creates a track from the current primary session GPS. | Explains the first-cut modal creation workflow. |
| Run trackpoint query action | Trackpoint query prototype: runs all trackpoints on the active track against the selected libraries with a 5 m tolerance. | Explains the prototype query behavior. |
| Match Preview card | Match preview shows current session/track coverage using available track-match summaries. | Explains match preview source and purpose. |

## Simple Suspension Metrics View

| UI location | Helper text | Used for |
| --- | --- | --- |
| Visualization hero heading | Simple Suspension Metrics for one or more Study Set sessions or groups. Groups combine their member sessions. | Explains the quick-view model. |
| Select and Filter heading | Choose which sessions, groups, ends, sectors, scope, layout, and time windows are shown in this analysis view. Study Set membership is not changed. | Explains the consolidated visualization controls and separates view state from canonical Study Set membership. |
| Exclude inactive periods control | Uses preprocessing activity masks when available. | Explains the inactive-period exclusion checkbox. |
| Sector filter group, sector mode | Selected sectors only are displayed and included in the overall view. | Explains sector filtering when sector mode is active. |
| Sector filter group, whole-session mode | Sector selections applied only in sector scope. | Explains why sector chips remain visible outside sector mode. |
| Wheel displacement distribution panel | Wheel displacement, % of maximum travel, frequency distribution. | Explains displacement chart domain. |
| Wheel velocity distribution panel | Maximum vertical stroke velocity at the wheel, compression above the axis, rebound below the axis, frequency distribution. | Explains wheel velocity metric histogram. |
| Wheel stroke length distribution panel | Vertical stroke length at the wheel, compression above the axis, rebound below the axis, frequency distribution. | Explains wheel stroke-length metric histogram. |
| Compression metrics panel | Compression stroke maximum displacement vs maximum velocity, at the wheel, front/rear on one chart. | Explains compression scatter inputs. |
| Rebound metrics panel | Compression stroke maximum displacement vs maximum (negative) velocity, at the wheel, front/rear on one chart. | Explains rebound scatter inputs. |
| Event counts panel | Counts of detected events by event type. | Explains event count output. |
| Selected-sector distribution note | Overall charts pool only the selected sectors, not the whole session. Sector matching uses the available track-match intervals for each active session or group. | Explains sector distribution pooling. |
| Selected-sector metric/event notes | Dynamic: "`Metric` rows are assigned to selected sectors by primary trigger time." or "`Event` rows are assigned to selected sectors by primary trigger time." | Explains sector row assignment. |

## Signal Inspector

| UI location | Helper text | Used for |
| --- | --- | --- |
| Bookmarks card | Save bookmarks to return to windows or exact points while inspecting this session. | Explains session-tied window and point bookmark creation. |
| GPS card | Shows the session GPS path and highlights the portion covered by the current signal window when time-aligned GPS points are available. | Explains the read-only GPS context panel and current-window overlay. |
| Signals card | Select which available time-series signals are displayed in the inspector. | Explains signal visibility controls. |
| Events card | Select event overlays to show. | Explains event overlay controls. |
| Logger marks row | Shows logger/sample marks from the processed session dataframe when available. | Explains mark overlay toggle. |
| Selected event detail | Click an event marker to inspect its timing. Dense event groups remain hidden until selected in the Events list. | Explains event selection details. |

## Filter Field Help Text

| Field | Helper text | Used for |
| --- | --- | --- |
| Rider | Matches the rider value from session notes/catalog metadata. | Filter condition builder field help. |
| Bike | Matches the bike/profile label carried in the catalog. | Filter condition builder field help. |
| Note status | Filters by session note state: draft, edited or missing. | Filter condition builder field help. |
| QC severity | Filters by overall QC severity. | Filter condition builder field help. |
| Has GPS | Filters sessions by whether any GPS source is present. | Filter condition builder field help. |
| GPS quality | Filters by GPS completeness/quality summary. | Filter condition builder field help. |
| GPS source | Filters by GPS source type or stream name. | Filter condition builder field help. |
| Signals | Matches available signal names. | Filter condition builder field help. |
| Event schema | Matches event schema IDs. | Filter condition builder field help. |
| Preprocess profile | Matches the preprocessing profile recorded in the catalog. | Filter condition builder field help. |
| Firmware version | Matches firmware version metadata. | Filter condition builder field help. |
| Source filename | Matches the original source/archive filename. | Filter condition builder field help. |
| Trackpoint crossing | Runs an async GPS/trackpoint match query against selected libraries. | Filter condition builder field help. |

## Notes For Review

- Empty states, warnings, and live status readouts remain visible rather than
  hidden behind info icons.
- Dynamic helper text is generated from data objects where noted above.
- The wording in this document is the source for review and should be kept in
  sync with the app when helper text changes.
