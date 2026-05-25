#!/usr/bin/env python3
"""
OLED Mockup Renderer
====================
Reads a JSON config from a file path (first argument) or stdin,
renders a clean OLED-style PNG, and writes it to config["output"].

Config schema
-------------
{
  "output": "path/to/result.png",   // required

  // Optional overrides
  "width":  800,                    // default 800
  "fg":     [179, 207, 239],        // text colour  (#B3CFEF)
  "bg":     [0, 0, 0],              // background

  // --- Screen type (choose one) ---

  // MENU: simple scrollable list
  "type": "menu",
  "lines": ["Title", "> Item A", "  Item B"],
  "right_annotations": {"0": "^"},  // row → text, drawn right-aligned

  // INFO: header + large centre text + pinned footer
  "type": "info",
  "header":       "WiFi  off",
  "big_lines":    ["500 Hz", "1 Channel"],
  "footer_left":  "Time  13 26 09",
  "footer_right": "81%",
  "big_after":    1,               // small rows before large text starts

  // CUSTOM: explicit element list
  "type": "custom",
  "elements": [
    {"text": "IP  192.168.1.132", "row": 0},
    {"text": "Range start",       "row": 2},
    {"text": "Count  1942",       "row": 3},
    {"text": "Time  13 29 22",    "row": "footer_left"},
    {"text": "81%",               "row": "footer_right"},
    {"text": "Label",             "row": 5, "size": "lg"},  // optional large
    {"text": "^",                 "row": 0, "align": "right"}
  ]
}

Row numbers (integer) place text on the small-text grid: y = MY + row × LH.
"footer_left" / "footer_right" pin to the bottom margin.
"size": "lg" renders with the 2× large font (still positioned on the sm grid row).
"""
import json, sys, os
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FONT = os.path.join(SCRIPT_DIR, "../assets/adafruits-gfx-library-default-font.ttf")


def render(config: dict) -> str:
    font_path = config.get("font_path", DEFAULT_FONT)
    W = config.get("width", 800)
    H = config.get("height", round(W * 64 / 128))   # 2:1 OLED ratio

    BG = tuple(config.get("bg", [0, 0, 0]))
    FG = tuple(config.get("fg", [179, 207, 239]))    # #B3CFEF

    SCALE = W / 128
    LH  = round(8  * SCALE)   # small line height
    LH2 = round(16 * SCALE)   # large line height
    MX  = round(5  * SCALE)   # left / right margin
    MY  = round(4  * SCALE)   # top  / bottom margin

    def mk_font(sz):
        return ImageFont.truetype(font_path, sz)

    SM = mk_font(round(W * 46 / 800))
    LG = mk_font(round(W * 88 / 800))

    img = Image.new("RGB", (W, H), BG)
    d   = ImageDraw.Draw(img)

    # ── Primitives ──────────────────────────────────────────────────────────

    def put(text, x, y, f=None, color=FG):
        """Draw text with its *top* at y (corrects for truetype baseline offset)."""
        if f is None:
            f = SM
        bb = f.getbbox(text)
        d.text((x, y - bb[1]), text, font=f, fill=color)

    def put_right(text, y, f=None, ref_text=None, color=FG):
        """Draw text right-aligned to W−MX, baseline-matched to ref_text."""
        if f is None:
            f = SM
        bb = f.getbbox(text)
        x = W - MX - (bb[2] - bb[0])
        if ref_text:
            ref_bb = f.getbbox(ref_text)
            d.text((x, y - ref_bb[1]), text, font=f, fill=color)
        else:
            put(text, x, y, f=f, color=color)

    def sm_y(row):
        return MY + int(row) * LH

    def lg_y(sm_rows, i):
        return MY + sm_rows * LH + i * LH2

    FOOTER_Y = H - MY - LH

    # ── Screen types ─────────────────────────────────────────────────────────

    kind = config.get("type", "custom")

    if kind == "menu":
        lines = config.get("lines", [])
        for i, ln in enumerate(lines):
            put(ln, MX, sm_y(i))
        for row_str, ann_text in config.get("right_annotations", {}).items():
            row = int(row_str)
            ref = lines[row] if row < len(lines) else ann_text
            put_right(ann_text, sm_y(row), ref_text=ref)

    elif kind == "info":
        header    = config.get("header", "")
        big_lines = config.get("big_lines", [])
        fl        = config.get("footer_left",  "")
        fr        = config.get("footer_right", None)
        big_after = config.get("big_after", 1)

        put(header, MX, sm_y(0))
        for i, ln in enumerate(big_lines):
            put(ln, MX, lg_y(big_after, i), f=LG)
        put(fl, MX, FOOTER_Y)
        if fr:
            put_right(fr, FOOTER_Y)

    else:  # custom
        for el in config.get("elements", []):
            text  = el.get("text", "")
            size  = el.get("size", "sm")
            align = el.get("align", "left")
            f     = LG if size == "lg" else SM
            row   = el.get("row")

            if row == "footer_left":
                y = FOOTER_Y
                put(text, MX, y, f=f)
            elif row == "footer_right":
                y = FOOTER_Y
                put_right(text, y, f=f)
            elif row is not None:
                y = sm_y(row)
                if align == "right":
                    put_right(text, y, f=f)
                else:
                    put(text, MX, y, f=f)

    out = config.get("output", "oled_output.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as fh:
            cfg = json.load(fh)
    else:
        cfg = json.load(sys.stdin)

    result = render(cfg)
    print(f"Saved: {result}")
