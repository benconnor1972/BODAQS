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

Use the CSS custom properties rather than one-off values.

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

Use `--weight-semibold` for headings and important labels. Avoid heavy/bold
text in metadata boxes unless it is a true status or action.

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
the relevant title or control.

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
