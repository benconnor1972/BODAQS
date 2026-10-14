# BODAQS Web App Design Language

Status: draft  
Audience: web app implementation / UI review / future feature design

This document describes the emerging visual and interaction language of the
BODAQS web app. It is intended to keep future UI work consistent without turning
the prototype into a heavy design-system exercise.

The app should feel precise, technical, compact, and calm. It is an engineering
tool first, but it should avoid looking like a raw admin console. The general
direction is compact corporate/technical UI with BODAQS teal, black, white, and
quiet neutral surfaces.

## Source Of Truth

Current implementation tokens live in:

```text
application/cohort-workbench-prototype/src/index.css
application/cohort-workbench-prototype/src/App.css
```

This document describes intended usage. If the code and this document diverge,
either update the code or update this document as part of the same change.

## Visual Principles

- Use compact density by default. The app is used for data browsing and
  inspection, so vertical padding should be purposeful rather than generous.
- Prefer quiet surfaces and crisp borders over heavy shadows or large blocks of
  color.
- Use BODAQS teal for active affordances, selected state, map/track highlights,
  and primary action emphasis.
- Use black/dark neutral for primary content and rear-series visualization.
- Keep rounded corners tight: just enough to take the sharpness off.
- Keep helper text out of the primary layout. Use info icons and maintain the
  helper text inventory.
- Prefer explicit state labels and counts in panel title bars rather than
  separate summary tiles where space is tight.

## Core Tokens

Use the CSS custom properties rather than one-off values. Replace literal
font sizes and weights with an applicable role token when the values match.
Do not round a deliberate value to the nearest token; values without a matching
token retain their existing appearance until separately reviewed.

### Colors

| Token | Value | Swatch | Usage |
| --- | --- | --- | --- |
| `--ink` | `#101820` | <span style="display:inline-block;width:48px;height:14px;background:#101820;border:1px solid #d7dfdd"></span> | Main text, dark series, strong chart marks. |
| `--muted` | `#5b6670` | <span style="display:inline-block;width:48px;height:14px;background:#5b6670;border:1px solid #d7dfdd"></span> | Secondary text, metadata, low-emphasis labels. |
| `--surface-ground` | `#eef2f1` | <span style="display:inline-block;width:48px;height:14px;background:#eef2f1;border:1px solid #d7dfdd"></span> | Page background. |
| `--surface` | `#ffffff` | <span style="display:inline-block;width:48px;height:14px;background:#ffffff;border:1px solid #d7dfdd"></span> | Panels, cards, inputs. |
| `--surface-subtle` | `#fbfcfc` | <span style="display:inline-block;width:48px;height:14px;background:#fbfcfc;border:1px solid #d7dfdd"></span> | Light internal blocks. |
| `--surface-warm` | `#f4f7f6` | <span style="display:inline-block;width:48px;height:14px;background:#f4f7f6;border:1px solid #d7dfdd"></span> | Table headers, muted card sections. |
| `--line` | `#d7dfdd` | <span style="display:inline-block;width:48px;height:14px;background:#d7dfdd;border:1px solid #d7dfdd"></span> | Default borders and table separators. |
| `--line-strong` | `#9fb0ad` | <span style="display:inline-block;width:48px;height:14px;background:#9fb0ad;border:1px solid #d7dfdd"></span> | Stronger separators and axes. |
| `--teal` / `--green` | `#008c95` | <span style="display:inline-block;width:48px;height:14px;background:#008c95;border:1px solid #d7dfdd"></span> | Primary accent, front-series color, active controls. |
| `--teal-soft` | `#e3f2f2` | <span style="display:inline-block;width:48px;height:14px;background:#e3f2f2;border:1px solid #d7dfdd"></span> | Selected rows, soft active backgrounds. |
| `--teal-quiet` | `#cfe6e5` | <span style="display:inline-block;width:48px;height:14px;background:#cfe6e5;border:1px solid #d7dfdd"></span> | Quiet accent borders and fills. |
| `--teal-strong` | `#00666d` | <span style="display:inline-block;width:48px;height:14px;background:#00666d;border:1px solid #d7dfdd"></span> | Accent text and icon emphasis. |
| `--amber` | `#b66a2c` | <span style="display:inline-block;width:48px;height:14px;background:#b66a2c;border:1px solid #d7dfdd"></span> | Draft/unsaved/caution state. |
| `--red` | `#983d3d` | <span style="display:inline-block;width:48px;height:14px;background:#983d3d;border:1px solid #d7dfdd"></span> | Delete/destructive/error state. |
| `--blue` | `#28668a` | <span style="display:inline-block;width:48px;height:14px;background:#28668a;border:1px solid #d7dfdd"></span> | Secondary analytical accent when teal/black are occupied. |

### Typography

| Token | Value | Usage |
| --- | --- | --- |
| `--font-ui` | `Aptos, "IBM Plex Sans", "Segoe UI", sans-serif` | General UI font stack. |
| `--text-page-title` | `23px` | App/page title. |
| `--text-modal-title` | `18px` | Modal title. |
| `--text-panel-title` | `16px` | Major panel title. |
| `--text-analysis-title` | `17px` | Analysis panel/chart title. |
| `--text-section-title` | `13px` | Title-bar metadata and section labels. |
| `--text-body` | `12px` | Normal controls and body text. |
| `--text-table` | `11.5px` | Dense table content. |
| `--text-caption` | `11px` | Metadata, helper summaries, compact buttons. |
| `--text-label` | `10px` | Uppercase form labels and table headers. |
| `--text-micro` | `9px` | Very dense labels only. |
| `--text-chart-axis` | `11px` | Chart axis ticks and titles across SVG, canvas and uPlot. |

Use `--weight-semibold` for headings and important labels. Avoid heavy/bold
text in metadata boxes unless it is a true status or action.

### Headings and Section Labels

Use sentence case for authored section labels, modal titles, analysis drawer
headings and modal headings. Preserve proper nouns and acronyms, including
BODAQS Workbench, Study Set, GPS, QA, FIT, JSON and sensor model identifiers.
Preserve user-provided session, track, grouping and Study Set names exactly;
do not run arbitrary record names through a lowercase/titlecase transform.

Examples: `Library selector`, `Select and filter`, `Filter manager`, `New track`,
`GPS path`, `Simple suspension analysis`, and `Study Set builder`. Built-in
analysis view headings use sentence case even if older API metadata contains
the former title-case display name. Metadata and form labels/table headers keep
their separate uppercase label convention.

Headings/section labels use `--weight-semibold`; analysis scope/hero titles use
`--text-analysis-title` (17px), and modal titles use `--text-modal-title` (18px).
True statuses retain their existing heavy weights and uppercase styling for now;
the sentence-case heading rule does not apply to readiness/warning/status badges.

### Field Labels and Entered Values

Labels identify fields; entered values have their own typography. Controls must
set their font family, size and weight explicitly rather than copying the font
of an enclosing label.

| Role | Font | Size | Weight | Capitalization |
| --- | --- | --- | --- | --- |
| Field label | `--font-ui` | `--text-label` (10px) | `--weight-semibold` (650) | Uppercase. |
| Entered/selected value | `--font-ui` | `--text-body` (12px) | `--weight-regular` (400) | Preserve exactly; `text-transform: none`. |
| Checkbox/radio option text | `--font-ui` | `--text-body` (12px) | `--weight-regular` (400) | Sentence case for authored text; preserve user-provided names. |
| Helper text | `--font-ui` | `--text-caption` (11px) | `--weight-regular` (400) | Sentence case. |
| Ordinary metadata label | `--font-ui` | `--text-label` (10px) | `--weight-semibold` (650) | Existing uppercase metadata-label pattern. |
| Ordinary metadata value | `--font-ui` | `--text-caption` (11px) | `--weight-regular` (400) | Preserve the value. |

Placeholders use the entered-value typography with `--muted` color, rather
than bold or smaller text. Advanced JSON is the exception: it uses `--font-code`
(`ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace`) at
12px regular weight. Ordinary multiline notes, explanations and tag names use
the UI font.

Record names in selection lists may retain semibold emphasis; checkbox option
labels must not make their entire contents bold. Status badges keep their own
meaningful emphasis. Do not use ordinary metadata-value styling as a blanket
reset for nested badges or chart readouts.

Modal actions use the shared action classes at 12px semibold. Compact actions
and context-menu commands use 11px semibold. Saved filter/scenario and Track
Manager list names use 12px semibold.

The shared form/metadata rules at the end of `App.css` override older
feature-specific inherited fonts. New controls should follow these rules rather
than introduce another local typography override.

### Geometry And Spacing

| Token | Value | Usage |
| --- | --- | --- |
| `--radius-tight` | `4px` | Very small blocks. |
| `--radius-control` | `5px` | Inputs, buttons, most panels. |
| `--radius-soft` | `7px` | Larger soft cards. |
| `--radius-card` | `8px` | Larger cards where extra softness is intentional. |
| `--radius-pill` | `999px` | Pills, badges, chips. |
| `--space-1` | `3px` | Small internal offsets. |
| `--space-2` | `5px` | Tight gaps. |
| `--space-3` | `7px` | Default compact gaps. |
| `--space-4` | `10px` | Panel padding. |
| `--space-5` | `12px` | Larger local rhythm. |
| `--space-6` | `18px` | Page/header spacing. |

## Panels

Panels are bordered white surfaces on the quiet grid background. Most panels use
`--border-subtle`, `--surface`, and `--radius-control`.

Panel title bars should generally contain:

- a short title on the left;
- an optional info icon next to the title;
- status/count text on the right;
- one small control if the panel can collapse or pull out.

Avoid placing large explanatory text inside panel bodies. Put explanations
behind the info icon and maintain:

```text
docs/analysis/web-app/BODAQS_Web_App_Helper_Text_Inventory.md
```

## Pull-Out And Collapsible Panels

The app uses pull-out panels where a control group is useful but should not
permanently consume screen real estate.

### Core Pattern

Collapsed pull-outs should be visible as a narrow rail, not disappear entirely.
The rail tells users that content exists off-screen and can be restored.

```text
┌────┬─────────────────────────────┐
│ >  │ Main content                │
│ S  │                             │
│ e  │                             │
│ l  │                             │
│ e  │                             │
│ c  │                             │
│ t  │                             │
└────┴─────────────────────────────┘
```

Expanded pull-outs should become a full panel adjacent to the main content, not
float over it, unless a deliberate modal/overlay interaction is required.

```text
┌───────────────┬──────────────────┐
│ Select/filter │ Main content     │
│ controls      │                  │
│               │                  │
└───────────────┴──────────────────┘
```

### Controls

- A collapsed rail uses a chevron pointing toward the direction it will open.
- An expanded panel uses a small chevron button in the relevant top corner to
  collapse it.
- The chevron should be icon-first and compact, matching existing panel controls.
- Do not add duplicate text buttons such as `Expand` or `Collapse` when the rail
  and chevron already communicate the action.

### Height

Rails should usually span the full height of the associated main panel region.
This keeps the affordance available even when the user has scrolled inside a
view.

### Existing Examples

- Library/study-set screen: study set builder appears as a right-side panel and
  can collapse to a rail.
- Simple Suspension Analysis: `Select and filter` is a left-side pull-out.
- Track Analysis and Lap Timing: `Select and filter` is a left-side pull-out;
  altitude can collapse into a narrow rail to the left of lap timing.

## Tables

Tables should be dense, readable, and action-oriented.

- Use compact row height.
- Use uppercase `--text-label` for headers.
- Prefer counts in title bars over separate summary tiles.
- Use column controls sparingly and keep action icons in one horizontal row.
- Use a single row-highlight convention where possible: selected row shading
  plus a straight teal brace/edge marker for the primary selection.
- Destructive controls should be red and generally rightmost.

## Maps And Geospatial Controls

Maps should be functional, not decorative.

- Session GPS paths use the session color cycle.
- Tracks and cutlines use BODAQS teal/amber depending on saved/dirty state.
- Trackpoint glyphs should match between map and sidebar where possible.
- Trackpoint lists should read as ordered geometry: point dots connected by
  segment line glyphs.
- Track names and point names are first-class; segment names are optional aliases.

## Charts

Charts should prioritize comparability and quick interpretation.

Axis tick labels and axis titles use `--text-chart-axis` (11px) and `--font-ui`
across altitude, spatial, distribution, phase and signal charts. Canvas and
uPlot read these CSS tokens as well; raster fallback must not select a separate
system font. There are no size exceptions among those chart axes.

Cumulative-chart tooltip titles and values use at least `--text-micro` (9px).
The compact time-window overview is a separate approved density exception:
its existing text, including 6px tick labels, is retained. Other chart-axis
labels follow the 11px rule.

- Front series use BODAQS teal.
- Rear series use black/dark neutral.
- Axes and gridlines should be quiet; data marks should carry the visual weight.
- Prefer consistent x-axis ranges for comparable distributions.
- For time-series inspection, keep synchronized cursors stable and avoid layout
  shifts on hover.
- In stacked/multi-chart views, preserve vertical real estate by putting legends
  inside the chart area where practical.

## Buttons And Actions

Primary actions use teal/green emphasis. Secondary actions are quiet white
controls with borders. Destructive actions use red.

Button labels should be direct and task-based:

- `Save`
- `Save Draft`
- `Analyze`
- `Open BODAQS Workbench`
- `Delete`
- `Remove`

Avoid labels that describe implementation details rather than user intent.

## Status And Feedback

Use compact status badges or title-bar metadata for normal state. Use stronger
color only when the state needs attention.

- `saved`, `ready`, `usable`: teal/green or quiet neutral.
- `draft`, `unsaved`, `warning`: amber.
- `offline`, `failed`, destructive confirmation: red.

For read-only hosted demo mode, disabled write controls should remain visible
only when they help explain the capability boundary.

## Helper Text

Helper text should not permanently occupy layout space. Use an info marker near
the relevant title or control. Markers must expose their explanation on hover
and keyboard focus, without triggering an enclosing control. Keep actionable
warnings, errors, empty states and live counts visible.

When helper text is added or changed, update:

```text
docs/analysis/web-app/BODAQS_Web_App_Helper_Text_Inventory.md
```

## Markdown As A Guide Format

Markdown is suitable for this guide because it is version-controlled, reviewable,
and close to the code. It can include:

- color swatches using inline HTML;
- simple wireframes using text diagrams;
- screenshots linked from committed image assets if we choose to add them later;
- token tables copied directly from CSS.

If we later need richer visual documentation, keep this Markdown document as the
canonical text guide and add a linked visual appendix or Storybook-style examples.

## Open Design Questions

- Whether to formalize chart color palettes beyond front/rear and session path
  colors.
- Whether to split the growing `App.css` into feature-level CSS modules or a
  token/base/component structure.
- Whether to create screenshot-based regression examples for key screens.
- Whether pull-out panel rails should use one exact width everywhere, or vary
  between dense analysis views and the library browser.
