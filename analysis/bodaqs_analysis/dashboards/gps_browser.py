from __future__ import annotations

from typing import Any, Mapping

import ipywidgets as W
from IPython.display import display

from bodaqs_analysis.widgets.gps_browser_widget import make_gps_browser_rebuilder
from bodaqs_analysis.widgets.session_selector import attach_refresh
from bodaqs_analysis.widgets.session_window_browser_widget import make_session_window_browser_rebuilder
from bodaqs_analysis.widgets.time_selection import SessionTimeSelection, make_session_time_selection


class DashboardHandle(dict[str, Any]):
    """Notebook-friendly dashboard handle that displays its UI when shown."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._skip_next_ipython_display = False

    def mark_displayed(self) -> None:
        self._skip_next_ipython_display = True

    def _ipython_display_(self) -> None:
        if self._skip_next_ipython_display:
            self._skip_next_ipython_display = False
            return
        ui = self.get("ui")
        if ui is not None:
            display(ui)
            return
        display(repr(self))

    def _repr_mimebundle_(
        self,
        include: Any = None,
        exclude: Any = None,
    ) -> Any:
        if self._skip_next_ipython_display:
            self._skip_next_ipython_display = False
            return {"text/plain": ""}, {}

        ui = self.get("ui")
        if ui is not None and hasattr(ui, "_repr_mimebundle_"):
            bundle = ui._repr_mimebundle_(include=include, exclude=exclude)
            if isinstance(bundle, tuple) and len(bundle) == 2:
                return bundle
            return bundle, {}

        return {"text/plain": repr(self)}, {}

    def __repr__(self) -> str:
        ui = self.get("ui")
        widgets = self.get("widgets")
        parts = [f"ui={type(ui).__name__}" if ui is not None else "ui=None"]
        if isinstance(widgets, Mapping):
            parts.append(f"widgets={list(widgets.keys())}")
        return f"DashboardHandle({', '.join(parts)})"

    def _repr_pretty_(self, p: Any, cycle: bool) -> None:
        if cycle:
            p.text("DashboardHandle(...)")
            return
        p.text(repr(self))


def make_session_gps_dashboard(
    sel: Mapping[str, Any],
    *,
    selection_model: SessionTimeSelection | None = None,
    session_browser_kwargs: Mapping[str, Any] | None = None,
    gps_browser_kwargs: Mapping[str, Any] | None = None,
    auto_display: bool = False,
) -> DashboardHandle:
    """
    Compose the session window browser with the linked GPS map/altitude browser.

    Both sub-widgets share a single SessionTimeSelection so session changes,
    visible windows, and pinned points stay synchronized in one notebook cell.
    """
    shared_selection = selection_model or make_session_time_selection()
    session_browser_kwargs = dict(session_browser_kwargs or {})
    gps_browser_kwargs = dict(gps_browser_kwargs or {})

    session_out = W.Output()
    gps_out = W.Output()

    session_browser = make_session_window_browser_rebuilder(
        sel=sel,
        out=session_out,
        selection_model=shared_selection,
        **session_browser_kwargs,
    )
    gps_browser = make_gps_browser_rebuilder(
        sel=sel,
        out=gps_out,
        selection_model=shared_selection,
        **gps_browser_kwargs,
    )

    root = W.VBox(
        [
            W.HTML("<h3 style='margin:0;'>Session Browser</h3>"),
            session_out,
            W.HTML("<h3 style='margin:0;'>GPS Browser</h3>"),
            gps_out,
        ],
        layout=W.Layout(width="100%"),
    )

    def refresh() -> None:
        session_browser["rebuild"]()
        gps_browser["rebuild"]()

    refresh_handle = attach_refresh(sel, rebuild_fns=[refresh])

    def detach() -> None:
        try:
            refresh_handle["detach"]()
        except Exception:
            pass

    handle = DashboardHandle(
        {
        "ui": root,
        "widgets": {
            "session_browser": session_browser,
            "gps_browser": gps_browser,
        },
        "selection_model": shared_selection,
        "refresh": refresh,
        "detach": detach,
        }
    )

    if auto_display:
        display(root)
        handle.mark_displayed()
    return handle
