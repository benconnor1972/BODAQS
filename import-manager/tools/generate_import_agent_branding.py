from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from PIL import Image


DEFAULT_SVG_PATH = Path(__file__).resolve().parents[2] / "bodocs" / "public" / "favicon.svg"
DEFAULT_TRAY_PNG_PATH = (
    Path(__file__).resolve().parents[1] / "bodaqs_import_manager" / "import_agent_assets" / "tray_icon.png"
)
DEFAULT_APP_PNG_PATH = (
    Path(__file__).resolve().parents[1] / "bodaqs_import_manager" / "import_agent_assets" / "app_icon.png"
)
DEFAULT_ASSET_ICO_PATH = (
    Path(__file__).resolve().parents[1] / "bodaqs_import_manager" / "import_agent_assets" / "app_icon.ico"
)
DEFAULT_APP_ICO_PATH = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "bodaqs_import_agent.ico"


def _default_browser_candidates() -> list[Path]:
    import os

    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    return [path for path in candidates if str(path).strip()]


def resolve_browser_executable(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Browser executable not found: {path}")
        return path

    for candidate in _default_browser_candidates():
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError("Could not find a Chromium-based browser executable for SVG rasterization")


def rasterize_svg_to_png(
    *,
    svg_path: Path,
    output_png_path: Path,
    browser_executable: Path,
    viewport_px: int = 320,
) -> Path:
    output_png_path.parent.mkdir(parents=True, exist_ok=True)
    file_url = svg_path.resolve().as_uri()
    command = [
        str(browser_executable),
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=1000",
        "--default-background-color=00000000",
        f"--window-size={viewport_px},{viewport_px}",
        f"--screenshot={output_png_path}",
        file_url,
    ]
    subprocess.run(command, check=True)
    return output_png_path


def _write_variant_svg(*, source_svg_path: Path, output_svg_path: Path, stroke_hex: str) -> Path:
    svg_text = source_svg_path.read_text(encoding="utf-8")
    svg_text = svg_text.replace("stroke:#000", f"stroke:{stroke_hex}")
    output_svg_path.write_text(svg_text, encoding="utf-8")
    return output_svg_path


def normalize_tray_png(*, png_path: Path, output_size_px: int = 256) -> Path:
    with Image.open(png_path) as image:
        rgba = image.convert("RGBA")
        bbox = rgba.getbbox()
        trimmed = rgba.crop(bbox) if bbox is not None else rgba

        canvas = Image.new("RGBA", (output_size_px, output_size_px), (0, 0, 0, 0))
        inset = max(8, output_size_px // 16)
        usable_size = output_size_px - (2 * inset)
        trimmed.thumbnail((usable_size, usable_size), Image.Resampling.LANCZOS)

        offset_x = (output_size_px - trimmed.width) // 2
        offset_y = (output_size_px - trimmed.height) // 2
        canvas.alpha_composite(trimmed, (offset_x, offset_y))
        canvas.save(png_path, format="PNG")
    return png_path


def build_ico_from_png(*, png_path: Path, ico_path: Path) -> Path:
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    with Image.open(png_path) as image:
        rgba = image.convert("RGBA")
        rgba.save(ico_path, format="ICO", sizes=sizes)
    return ico_path


def generate_branding_assets(
    *,
    svg_path: Path,
    tray_png_path: Path,
    app_png_path: Path,
    asset_ico_path: Path,
    app_ico_path: Path,
    browser_executable: Path,
) -> tuple[Path, Path, Path, Path]:
    with tempfile.TemporaryDirectory(prefix="bodaqs-branding-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        tray_svg_path = _write_variant_svg(
            source_svg_path=svg_path,
            output_svg_path=temp_dir / "tray_icon.svg",
            stroke_hex="#0f172a",
        )
        app_svg_path = _write_variant_svg(
            source_svg_path=svg_path,
            output_svg_path=temp_dir / "app_icon.svg",
            stroke_hex="#0f172a",
        )

        rasterize_svg_to_png(
            svg_path=tray_svg_path,
            output_png_path=tray_png_path,
            browser_executable=browser_executable,
        )
        rasterize_svg_to_png(
            svg_path=app_svg_path,
            output_png_path=app_png_path,
            browser_executable=browser_executable,
        )
        normalize_tray_png(png_path=app_png_path)
        build_ico_from_png(png_path=app_png_path, ico_path=asset_ico_path)
        app_ico_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(asset_ico_path, app_ico_path)

    normalize_tray_png(png_path=tray_png_path)
    return tray_png_path, app_png_path, asset_ico_path, app_ico_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate branded BODAQS tray/app icon assets from favicon.svg.")
    parser.add_argument("--svg", default=str(DEFAULT_SVG_PATH))
    parser.add_argument("--tray-png", default=str(DEFAULT_TRAY_PNG_PATH))
    parser.add_argument("--app-png", default=str(DEFAULT_APP_PNG_PATH))
    parser.add_argument("--asset-ico", default=str(DEFAULT_ASSET_ICO_PATH))
    parser.add_argument("--app-ico", default=str(DEFAULT_APP_ICO_PATH))
    parser.add_argument("--browser", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    svg_path = Path(args.svg).expanduser().resolve()
    tray_png_path = Path(args.tray_png).expanduser().resolve()
    app_png_path = Path(args.app_png).expanduser().resolve()
    asset_ico_path = Path(args.asset_ico).expanduser().resolve()
    app_ico_path = Path(args.app_ico).expanduser().resolve()
    browser_executable = resolve_browser_executable(args.browser or None)

    generate_branding_assets(
        svg_path=svg_path,
        tray_png_path=tray_png_path,
        app_png_path=app_png_path,
        asset_ico_path=asset_ico_path,
        app_ico_path=app_ico_path,
        browser_executable=browser_executable,
    )
    print(f"Generated tray PNG: {tray_png_path}")
    print(f"Generated app PNG: {app_png_path}")
    print(f"Generated asset ICO: {asset_ico_path}")
    print(f"Generated app ICO: {app_ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
