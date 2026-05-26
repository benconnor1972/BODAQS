from __future__ import annotations

import queue
import sys
from importlib.resources import files
from typing import Any, Callable, Optional

try:
    import pystray
except Exception:  # pragma: no cover - exercised by runtime availability
    pystray = None

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - exercised by runtime availability
    Image = None
    ImageDraw = None


_ASSET_PACKAGE = "bodaqs_import_manager.import_agent_assets"
_TRAY_ICON_FILENAME = "tray_icon.png"


def tray_supported(*, platform: Optional[str] = None) -> bool:
    resolved_platform = platform or sys.platform
    return resolved_platform.startswith("win") and pystray is not None and Image is not None and ImageDraw is not None


def build_import_agent_tray_image(*, size: int = 64) -> Any:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is required to build the import-agent tray icon image")

    image = Image.new("RGBA", (size, size), (18, 34, 58, 255))
    draw = ImageDraw.Draw(image)

    margin = max(4, size // 12)
    wheel_radius = max(7, size // 5)
    left_cx = size * 0.32
    right_cx = size * 0.72
    wheel_cy = size * 0.72
    frame_top_y = size * 0.30
    frame_mid_x = size * 0.50
    line_width = max(3, size // 11)

    # Wheels
    draw.ellipse(
        (
            left_cx - wheel_radius,
            wheel_cy - wheel_radius,
            left_cx + wheel_radius,
            wheel_cy + wheel_radius,
        ),
        outline=(255, 255, 255, 235),
        width=line_width,
    )
    draw.ellipse(
        (
            right_cx - wheel_radius,
            wheel_cy - wheel_radius,
            right_cx + wheel_radius,
            wheel_cy + wheel_radius,
        ),
        outline=(255, 255, 255, 235),
        width=line_width,
    )

    # Stylized frame
    draw.line(
        [(left_cx, wheel_cy), (frame_mid_x, frame_top_y), (right_cx, wheel_cy)],
        fill=(77, 184, 255, 255),
        width=line_width,
        joint="curve",
    )
    draw.line(
        [(left_cx + wheel_radius * 0.15, wheel_cy), (frame_mid_x, wheel_cy - wheel_radius * 0.35)],
        fill=(77, 184, 255, 255),
        width=line_width,
    )
    draw.line(
        [(frame_mid_x, wheel_cy - wheel_radius * 0.35), (right_cx - wheel_radius * 0.2, wheel_cy)],
        fill=(77, 184, 255, 255),
        width=line_width,
    )
    draw.line(
        [(frame_mid_x, frame_top_y), (frame_mid_x + wheel_radius * 0.55, frame_top_y - wheel_radius * 0.45)],
        fill=(255, 214, 102, 255),
        width=max(2, line_width - 1),
    )
    draw.line(
        [(frame_mid_x, frame_top_y), (frame_mid_x - wheel_radius * 0.5, frame_top_y - wheel_radius * 0.18)],
        fill=(255, 214, 102, 255),
        width=max(2, line_width - 1),
    )

    # Rounded outer border for definition at small sizes.
    draw.rounded_rectangle(
        (margin // 2, margin // 2, size - margin // 2 - 1, size - margin // 2 - 1),
        radius=max(6, size // 8),
        outline=(255, 255, 255, 72),
        width=max(1, size // 32),
    )

    return image


def load_import_agent_tray_image() -> Any:
    if Image is None:
        raise RuntimeError("Pillow is required to load the import-agent tray icon image")

    try:
        asset = files(_ASSET_PACKAGE).joinpath(_TRAY_ICON_FILENAME)
        with asset.open("rb") as handle:
            image = Image.open(handle)
            return image.convert("RGBA")
    except Exception:
        return build_import_agent_tray_image()


class ImportAgentTrayIcon:
    def __init__(
        self,
        *,
        event_queue: "queue.Queue[dict[str, Any]]",
        status_supplier: Callable[[], dict[str, Any]],
        title: str = "BODAQS Import Manager",
    ) -> None:
        self.event_queue = event_queue
        self.status_supplier = status_supplier
        self.title = title
        self._icon: Any = None
        self._started = False

    @property
    def started(self) -> bool:
        return self._started and self._icon is not None

    def start(self) -> bool:
        if self.started:
            return True
        if not tray_supported():
            return False

        self._icon = pystray.Icon(
            "bodaqs-import-agent",
            load_import_agent_tray_image(),
            self._build_title(),
            menu=self._build_menu(),
        )
        self._icon.run_detached()
        self._started = True
        self.refresh()
        return True

    def stop(self) -> None:
        if self._icon is None:
            self._started = False
            return
        try:
            self._icon.stop()
        finally:
            self._icon = None
            self._started = False

    def refresh(self) -> None:
        if self._icon is None:
            return
        self._icon.title = self._build_title()
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def _build_title(self) -> str:
        status = self.status_supplier()
        watch_state = "watching" if status.get("watch_running") else "idle"
        source_count = int(status.get("source_count", 0))
        return f"{self.title} ({watch_state}, sources={source_count})"

    def _post(self, kind: str) -> None:
        self.event_queue.put({"kind": kind})

    def _build_menu(self) -> Any:
        if pystray is None:
            return None
        return pystray.Menu(
            pystray.MenuItem(
                "Open Manager",
                lambda icon, item: self._post("tray_show_window"),
                default=True,
            ),
            pystray.MenuItem(
                "Hide Manager",
                lambda icon, item: self._post("tray_hide_window"),
                enabled=lambda item: bool(self.status_supplier().get("window_visible")),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start Watch",
                lambda icon, item: self._post("tray_start_watch"),
                enabled=lambda item: bool(self.status_supplier().get("can_start_watch")),
            ),
            pystray.MenuItem(
                "Stop Watch",
                lambda icon, item: self._post("tray_stop_watch"),
                enabled=lambda item: bool(self.status_supplier().get("can_stop_watch")),
            ),
            pystray.MenuItem(
                "Import Now",
                lambda icon, item: self._post("tray_import_now"),
                enabled=lambda item: bool(self.status_supplier().get("can_import_now")),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start At Login",
                lambda icon, item: self._post("tray_toggle_auto_start"),
                checked=lambda item: bool(self.status_supplier().get("auto_start")),
                enabled=lambda item: bool(self.status_supplier().get("has_config")),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self._post("tray_quit")),
        )
