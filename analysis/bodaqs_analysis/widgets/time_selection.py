from __future__ import annotations

from typing import Any, Optional

from traitlets import Any as TraitAny
from traitlets import HasTraits, Unicode


class SessionTimeSelection(HasTraits):
    """
    Small shared state object for cross-widget session/window/point linking.

    Widgets publish and observe these traits to stay synchronized without
    depending on each other's internal control structure.
    """

    session_key = Unicode(default_value=None, allow_none=True)
    window_t0_s = TraitAny(default_value=None, allow_none=True)
    window_t1_s = TraitAny(default_value=None, allow_none=True)
    selected_time_s = TraitAny(default_value=None, allow_none=True)
    source = Unicode(default_value="", allow_none=True)

    def update_state(
        self,
        *,
        session_key: Optional[str] = None,
        window_t0_s: Optional[float] = None,
        window_t1_s: Optional[float] = None,
        selected_time_s: Any = None,
        set_selected_time: bool = False,
        source: Optional[str] = None,
    ) -> None:
        with self.hold_trait_notifications():
            if source is not None:
                self.source = str(source)
            if session_key is not None:
                self.session_key = str(session_key)
            if window_t0_s is not None or window_t1_s is not None:
                if window_t0_s is None or window_t1_s is None:
                    self.window_t0_s = None
                    self.window_t1_s = None
                else:
                    a = float(window_t0_s)
                    b = float(window_t1_s)
                    self.window_t0_s = min(a, b)
                    self.window_t1_s = max(a, b)
            if set_selected_time:
                self.selected_time_s = None if selected_time_s is None else float(selected_time_s)

    def set_session(self, session_key: str, *, source: Optional[str] = None) -> None:
        self.update_state(session_key=session_key, source=source)

    def set_window(self, t0_s: float, t1_s: float, *, source: Optional[str] = None) -> None:
        self.update_state(window_t0_s=t0_s, window_t1_s=t1_s, source=source)

    def set_selected_time(self, time_s: Optional[float], *, source: Optional[str] = None) -> None:
        self.update_state(selected_time_s=time_s, set_selected_time=True, source=source)

    def clear_selected_time(self, *, source: Optional[str] = None) -> None:
        self.update_state(selected_time_s=None, set_selected_time=True, source=source)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_key": self.session_key,
            "window_t0_s": self.window_t0_s,
            "window_t1_s": self.window_t1_s,
            "selected_time_s": self.selected_time_s,
            "source": self.source,
        }


def make_session_time_selection() -> SessionTimeSelection:
    return SessionTimeSelection()
