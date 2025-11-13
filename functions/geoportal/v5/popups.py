# functions/geoportal/v5/popups.py
from __future__ import annotations
from typing import Any, Callable, Optional

import ipyleaflet
import ipywidgets as W

from functions.geoportal.v5.utils import html_table_popup
from functions.geoportal.v5.config import CFG


def show_popup(
    m: ipyleaflet.Map,
    lat: float,
    lon: float,
    props: Optional[dict[str, Any]],
    marker: Optional[ipyleaflet.Marker],
    active_marker_ref,
    # Optional callback: given feature props, returns an ipywidget to render (or None).
    # Used by sensors to inline-plot a time series; polygons can pass None to disable.
    on_show_timeseries: Optional[Callable[[dict], W.Widget | None]] = None,
) -> None:
    """
    Open a Leaflet popup at (lat, lon) showing a key/value table from `props`.
    - If `marker` is provided, temporarily highlight it and de-highlight the previous one.
    - If `on_show_timeseries` is provided, render a button that, when clicked,
      calls the callback and embeds the returned widget in the popup.

    Parameters
    ----------
    m : ipyleaflet.Map
        Target map.
    lat, lon : float
        Location to place the popup.
    props : dict | None
        Feature properties to display in a small table.
    marker : ipyleaflet.Marker | None
        The marker that was clicked (if any). For polygon clicks pass None.
    active_marker_ref : SimpleNamespace-like with `.current`
        Used to remember and reset the previously active marker icon.
    on_show_timeseries : Callable[[dict], ipywidgets.Widget | None] | None
        Optional callback to build an inline widget (e.g., a Plotly chart).
    """
    # Preserve current view so opening the popup doesn't jump the map
    prev_center, prev_zoom = tuple(m.center), m.zoom

    # -------------------------
    # Marker icon highlight (only if a Marker was passed)
    # -------------------------
    if marker is not None:
        try:
            # reset previously active marker (if different)
            if active_marker_ref.current and active_marker_ref.current is not marker:
                active_marker_ref.current.icon = ipyleaflet.AwesomeIcon(
                    name=CFG.icon_name,
                    marker_color=CFG.icon_color_default,
                    icon_color=CFG.icon_icon_color,
                )

            # set the newly clicked one as active
            marker.icon = ipyleaflet.AwesomeIcon(
                name=CFG.icon_name,
                marker_color=CFG.icon_color_active,
                icon_color=CFG.icon_icon_color,
            )
            active_marker_ref.current = marker
        except Exception:
            # icon change is non-critical — ignore any failures
            pass

    # -------------------------
    # Build popup content
    # -------------------------
    table = html_table_popup(props or {})
    child: W.Widget = table  # default content is the attribute table

    if on_show_timeseries is not None:
        # Optional inline plot control
        btn = W.Button(
            description="Show Soil Moisture Sensor Reads",
            button_style="primary",
            layout=W.Layout(margin="6px 0 0 0"),
            tooltip="Load and display the related time series below",
        )
        out = W.Output(layout=W.Layout(display="block"))

        def _on_click(_):
            out.clear_output(wait=True)
            try:
                widget = on_show_timeseries(props or {})
                if widget is not None:
                    out.children = [widget]
                else:
                    out.children = [W.HTML("<i>No figure to show.</i>")]
            except Exception as e:
                # Surface the error to the user inside the popup (no traceback)
                out.children = [W.HTML(f"<pre>Failed to load time series: {e}</pre>")]

        btn.on_click(_on_click)
        child = W.VBox([table, btn, out])

    # -------------------------
    # Replace any existing popups, then add the new one
    # -------------------------
    try:
        for layer in list(m.layers):
            if isinstance(layer, ipyleaflet.Popup):
                m.remove_layer(layer)
    except Exception:
        # Removing old popups is best-effort
        pass

    popup = ipyleaflet.Popup(
        location=(float(lat), float(lon)),
        child=child,
        close_button=True,
        auto_close=True,
        close_on_escape_key=True,
        auto_pan=True,
        min_width=420,   # wider so tables/plots fit comfortably
        max_width=820,
    )

    m.add_layer(popup)

    # Restore previous view (avoid zoom/center jumps some backends may trigger)
    try:
        m.center, m.zoom = prev_center, prev_zoom
    except Exception:
        pass
