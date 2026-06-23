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
| Session Selector heading | Browse sessions from the selected libraries. Use filters from the filter panel or filter directly in the table to narrow the list. | Distinguishes browsing/filtering from Study Set membership. |
| Session selector table selection controls | Click a row to select it. Ctrl/Cmd-click toggles rows; Shift-click selects a range. | Explains table multi-select and primary-session behavior. |
| GPS Location heading | Preview the selected session GPS path and any selected or attached tracks. | Explains the GPS preview panel. |
| Filters heading | Create and apply reusable filters on the sessions displayed. Filters stack and combine with table filtering. | Explains saved filters versus ad hoc column filters. |
| Saved filter row description | Dynamic: the saved filter's description field. | Provides per-filter context without adding a second visible row. |
| Filter manager field selector | Dynamic: field-specific help text from the filter field definition. | Explains the selected condition field. |
| Current Study Set heading | The working Study Set comprising sessions and optional groupings and tracks. | Explains the Study Set object. |
| Study Set sessions subsection | List of the sessions in this study set. Removing a session removes it from the Study Set, but not from the library. | Explains session membership and safe removal. |
| Study Set session table selection controls | Click rows to choose sessions for grouping. Ctrl/Cmd-click toggles rows; Shift-click selects a range. | Explains grouping selection behavior. |
| Study Set tracks subsection | Tracks are GPS paths with defined points that can be used for geospatial filtering and sector-based analysis. | Explains attached tracks. |
| Saved Study Sets heading | Saved Study Sets can be loaded into the editor above, inspected, or opened directly in the analysis view. | Explains saved Study Set actions. |

## Geospatial Workbench

| UI location | Helper text | Used for |
| --- | --- | --- |
| Geospatial Workbench heading | Create and manage re-usable tracks and trackpoints and attach them to the current Study Set. | Explains the whole panel. |
| Primary GPS card | Shows GPS source and coverage for the selected session. | Explains primary GPS summary. |
| Study Set GPS card | Summarizes GPS quality for Study Set sessions. | Explains aggregate GPS adequacy. |
| Track Manager card | Tracks are GPS paths with defined points that can be used for geospatial filtering and sector-based analysis. | Explains track ownership and cutline policy. |
| Run trackpoint query action | Trackpoint query prototype: runs all trackpoints on the active track against the selected libraries with a 5 m tolerance. | Explains the prototype query behavior. |
| Match Preview card | Match preview shows current session/track coverage using available track-match summaries. | Explains match preview source and purpose. |

## Simple Suspension Metrics View

| UI location | Helper text | Used for |
| --- | --- | --- |
| Visualization hero heading | Simple Suspension Metrics for one or more Study Set sessions or groups. Groups combine their member sessions. | Explains the quick-view model. |
| Select and Filter heading | Choose which sessions, groups, ends, sectors, scope, layout, and time windows are shown in this analysis view. Study Set membership is not changed. | Explains the consolidated visualization controls and separates view state from canonical Study Set membership. |
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
