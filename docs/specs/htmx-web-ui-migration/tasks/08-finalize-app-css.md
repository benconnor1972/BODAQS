STEP 08: Finalize app.css with full design language
===================================================

STATUS
------

Status: COMPLETE
Completed: 2025-07-16
Verified by: implement (independent re-run)

Notes
-----
- The `app.css` created in T04 already contained the complete design language
  from the design doc — all 9 categories (CSS custom properties, typography,
  page shell, fieldsets/form rows, buttons, alerts, tables, htmx indicator,
  mobile responsive) were present and matched the design doc exactly.
- Updated the file header comment from "T08 will finalize" to reflect the
  finalized status.
- The CSS also retains carryover rules from the original inline CSS that the
  existing pages depend on: `h2` heading styling, `.row input[type='checkbox']`
  margin, and `small` margin-left. These do not conflict with the design
  language and are needed for existing page rendering.
- Design artifact HTML files were not modified (the task marks this as optional;
  the artifacts use inline CSS for standalone viewing which is the preferred
  approach per the task file).

DEPENDS ON: step 07

SPEC
----

Finalize `app.css` with the complete design language from the design doc. The initial `app.css` created in T04 was a basic copy of the old inline CSS. This task replaces it with the full design language implementation.

### app.css contents

The CSS must implement the Design Language section from `docs/design/htmx-web-ui-migration.md`:

**CSS custom properties (`:root`):**
```css
:root {
  --shadow-grey:  #212227;
  --dim-grey:     #637074;
  --lavender-grey: #8693ab;
  --powder-blue:  #aab9cf;
  --pale-sky:     #bdd4e7;
  --status-success-bg: #e7f5e7;
  --status-success-fg: #2d6a2d;
  --status-success-bd: #8bc34a;
  --status-error-bg:   #ffe7e7;
  --status-error-fg:   #8b2020;
  --status-error-bd:   #e57373;
  --status-warn-bg:    #fff3cd;
  --status-warn-fg:    #665500;
  --status-warn-bd:    #ffe08a;
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 24px;
}
```

**Typography:**
- `body`: system-ui font stack, 14px, line-height 1.5, color `--shadow-grey`

**Page shell:**
- `.titlebar`: 1.5em, bold, `--shadow-grey`
- `.netbar`: 0.9em, `--dim-grey`
- `.topnav`: `--shadow-grey` background, 8px radius, `--pale-sky` links, white on hover

**Fieldsets and form rows:**
- `fieldset`: `--pale-sky` background, `--dim-grey` border, 8px radius
- `legend`: bold, `--lavender-grey`
- `.row`: flex, align center, wrap, gap `--space-sm`
- `label`: min-width 160px, bold
- `input`, `select`: `--dim-grey` border, 4px radius, `--powder-blue` focus border with box-shadow glow
- `input:disabled`: opacity 0.5, `--dim-grey` background
- `small`: `--dim-grey`, 0.85em

**Buttons:**
- `button`: `--lavender-grey` background, white text, 6px radius
- `button:hover`: `--powder-blue` background, `--shadow-grey` text
- `button:disabled`: `--dim-grey` background, opacity 0.6

**Alerts:**
- `.alert-ok`: success bg/bd/fg
- `.alert-err`: error bg/bd/fg
- `.alert-warn`: warn bg/bd/fg

**Tables:**
- `th`: `--shadow-grey` background, `--pale-sky` text, uppercase, letter-spacing
- `td`: `--dim-grey` bottom border
- `tbody tr:nth-child(even)`: `--pale-sky` at 30% opacity
- `tbody tr:hover`: `--pale-sky`

**htmx indicator:**
- `.htmx-indicator`: `display: none`
- `.htmx-request .htmx-indicator`: `display: inline-block`, `--dim-grey`

**Mobile responsive (`@media (max-width: 480px)`):**
- `body`: margin `--space-sm`, 15px font
- `.row`: flex-direction column, align flex-start
- `label`: min-width 0
- `.topnav`: flex, wrap, gap `--space-sm`
- `fieldset`: padding `--space-sm`
- `th`, `td`: padding `--space-xs`, 0.85em

### Design artifact update

Update the design artifact HTML files in `docs/design/artifacts/htmx-web-ui-migration/` to use the final `app.css` (they currently have inline CSS). This is optional but helps verify the CSS renders correctly.

FILES TO CREATE
---------------

None.

FILES TO MODIFY
---------------

- `firmware/www/app.css`: Replace initial CSS with full design language implementation
- `docs/design/artifacts/htmx-web-ui-migration/01-design-language-showcase.html`: Optionally update to link to the final app.css (or keep inline for standalone viewing)

TEST CASES
----------

T1: app.css contains brand palette
    File contains `--shadow-grey: #212227` and `--lavender-grey: #8693ab`

T2: app.css contains semantic status colors
    File contains `--status-success-bg`, `--status-error-bg`, `--status-warn-bg`

T3: app.css contains spacing scale
    File contains `--space-xs` through `--space-xl`

T4: app.css contains mobile breakpoint
    File contains `@media (max-width: 480px)`

T5: app.css contains htmx indicator
    File contains `.htmx-indicator` and `.htmx-request .htmx-indicator`

T6: app.css contains nav bar styles
    File contains `.topnav` with `--shadow-grey` background

T7: app.css contains alert classes
    File contains `.alert-ok`, `.alert-err`, `.alert-warn`

VERIFICATION
------------

  cd firmware && make -C test test && pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f

Expected output:
  All tests passed.
  [PlatformIO build succeeds]

Exit code: 0

DONE WHEN
---------

- All previous tests still pass (30 total)
- PlatformIO build succeeds
- `firmware.bin` total size delta across all phases < 20 KB
- `app.css` contains all brand palette colors, semantic status colors, spacing scale
- `app.css` contains `@media (max-width: 480px)` mobile responsive breakpoint
- `app.css` contains `.htmx-indicator` and `.htmx-request .htmx-indicator` rules
- `app.css` contains `.alert-ok`, `.alert-err`, `.alert-warn` classes
- Open `/config` in browser DevTools at 375px width — no horizontal scroll, all fields tappable
