---
name: oled-mockup
description: >
  Converts photos or screenshots of dark OLED / embedded-display UIs into clean,
  high-resolution PNG mockups with a black background and pale blue pixel-font text.
  Use this skill whenever the user shares an image of a small LCD/OLED screen and
  wants a clean vector-style or documentation-quality version of it — even if they
  just say "clean this up", "make this look nicer", "recreate this UI", or "I want
  a clean version of my device screen". Works on single images or batches.
---

# OLED Mockup Skill

## What this skill does

Takes one or more photos/screenshots of embedded-device OLED/LCD displays and
produces clean PNG mockups: black background, pale blue (`#B3CFEF`) Adafruit
GFX pixel font, 800 × 400 px (preserving the 2:1 OLED aspect ratio).

## Assets bundled with this skill

| File | Purpose |
|------|---------|
| `scripts/render_oled.py` | PIL-based renderer — always call this, never hand-roll PIL code |
| `assets/adafruits-gfx-library-default-font.ttf` | Adafruit GFX 5×7 pixel font (scaled to 800 px output) |

The renderer accepts a JSON config on **stdin** or as a **file path argument**.
See the top of `render_oled.py` for the full config schema.

---

## Step-by-step workflow

### 1 · Read the skill assets path

The skill lives at a path discoverable via your environment. Resolve it once:

```python
import os
SKILL_DIR  = os.path.dirname(os.path.abspath("<this SKILL.md>"))
SCRIPT     = os.path.join(SKILL_DIR, "scripts/render_oled.py")
FONT       = os.path.join(SKILL_DIR, "assets/adafruits-gfx-library-default-font.ttf")
```

### 2 · Analyse each image carefully

Look at the image and extract:

**Text content** — read every character exactly as shown, including:
- Leading spaces and cursor markers (`>`, `  `)
- Checkbox markers: `[ ]` (empty), `[*]` (selected)
- Muted/zeroed markers: `[M]`, `[Z|R]` etc.
- Right-aligned elements (`^`, battery %, IP addresses)
- All punctuation, underscores, colons, slashes

**Layout type** — pick the closest match:

| Type | Signature |
|------|-----------|
| `menu` | Title on row 0, list items below, possibly a right-aligned glyph on row 0 |
| `info` | Small header line → large (2×) centre text (1–2 lines) → small pinned footer |
| `custom` | Anything else: sparse items at non-consecutive rows, mixed large/small on same screen |

**Font sizes** — on a 128×64 OLED, "large" text is exactly 2× taller than "small".
If the tallest characters are roughly the same height as all others, everything is `sm`.
Only use `"size": "lg"` when the text is visibly twice the height of the surrounding text.

**Footer structure** — many screens show `Time  HH MM SS` left-aligned with a battery
percentage (`81%`) right-aligned on the same bottom row. Render these as two separate
elements (`footer_left` / `footer_right`) so nothing gets clipped.

### 3 · Build the JSON config

Use the simplest type that accurately describes the screen.

**Menu example:**
```json
{
  "type": "menu",
  "lines": [
    "Calibration",
    "> front_shock [Z|R]",
    "  Stringpot [Z|R]",
    "  spare1 [Z|R]",
    "  spare2 [Z|R]"
  ],
  "output": "/path/to/output.png",
  "font_path": "/path/to/font.ttf"
}
```

**Info example:**
```json
{
  "type": "info",
  "header":      "WiFi  off",
  "big_lines":   ["500 Hz", "1 Channel"],
  "footer_left": "Time  13 26 09",
  "footer_right":"81%",
  "output": "/path/to/output.png",
  "font_path": "/path/to/font.ttf"
}
```

**Custom example** (sparse rows, mixed sizes, right-aligned):
```json
{
  "type": "custom",
  "elements": [
    {"text": "IP  192.168.1.132", "row": 0},
    {"text": "Range start",       "row": 2},
    {"text": "Count  1942",       "row": 3},
    {"text": "Time  13 29 22",    "row": "footer_left"},
    {"text": "81%",               "row": "footer_right"}
  ],
  "output": "/path/to/output.png",
  "font_path": "/path/to/font.ttf"
}
```

**Menu with right-aligned annotation** (e.g. Sample Rate screen):
```json
{
  "type": "menu",
  "lines": ["Sample Rate", "  [ ] 50 Hz", "  [ ] 100 Hz", "> [*] 500 Hz"],
  "right_annotations": {"0": "^"},
  "output": "/path/to/output.png",
  "font_path": "/path/to/font.ttf"
}
```

### 4 · Render

Write the config to a temp JSON file and call the renderer:

```bash
python3 /path/to/scripts/render_oled.py /tmp/oled_config.json
```

Or pipe via stdin:

```bash
echo '<json>' | python3 /path/to/scripts/render_oled.py
```

Save outputs to the user's workspace folder so they can open them directly.

### 5 · For batches

Process images one at a time (analyse → render → next). Name outputs after the
original file, e.g. `mainmenu.png` → `mainmenu_clean.png` (or replace in-place if
the user asks). When all are done, present the full list of output file links.

---

## Common pitfalls

- **Don't guess text** — if a character is ambiguous in the photo (glare, angle),
  note it with `?` rather than inventing content.
- **Preserve spacing** — the gap between words like `WiFi  off` (two spaces) is
  deliberate; it's how the Adafruit library aligns columns.
- **Footer clipping** — never concatenate the time and battery % into a single
  string; always split into `footer_left` / `footer_right`.
- **Large vs small** — err on the side of `sm` unless the text is unambiguously 2×
  taller; most OLED menu screens use only `sm`.
- **Row 0 is the title** — menus conventionally have an unindented title on row 0
  and indented items (with or without `>` cursor) on rows 1+.
