# functions/geoportal/v7/popups.py
from __future__ import annotations
from typing import Any, Callable, Optional

import ipyleaflet
import ipywidgets as W
from IPython.display import display

from functions.geoportal.v8.utils import html_table_popup
from functions.geoportal.v8.config import CFG


def show_popup(
    m: ipyleaflet.Map,
    lat: float,
    lon: float,
    props: Optional[dict[str, Any]],
    marker: Optional[ipyleaflet.Marker],
    active_marker_ref,
    # Optional callback: given feature props, returns an ipywidget to render (or None).
    on_show_timeseries: Optional[Callable[[dict], W.Widget | None]] = None,
    # Optional label so sensors + NDVI can use different button text
    timeseries_button_label: Optional[str] = None,
    min_width: int | None = None,
    max_width: int | None = None,
) -> None:
    """
    Open a Leaflet popup at (lat, lon) showing a key/value table from `props`,
    and optionally a time-series widget (sensor or NDVI) under a button.
    """
    try:
        prev_center = tuple(m.center) if m.center is not None else None
    except Exception:
        prev_center = None
    try:
        prev_zoom = m.zoom
    except Exception:
        prev_zoom = None

    # -------------------------
    # Marker icon highlight (for sensors only)
    # -------------------------
    if marker is not None:
        try:
            if active_marker_ref.current and active_marker_ref.current is not marker:
                active_marker_ref.current.icon = ipyleaflet.AwesomeIcon(
                    name=CFG.icon_name,
                    marker_color=CFG.icon_color_default,
                    icon_color=CFG.icon_icon_color,
                )

            marker.icon = ipyleaflet.AwesomeIcon(
                name=CFG.icon_name,
                marker_color=CFG.icon_color_active,
                icon_color=CFG.icon_icon_color,
            )
            active_marker_ref.current = marker
        except Exception:
            pass

    # -------------------------
    # Build popup content
    # -------------------------
    table = html_table_popup(props or {})
    child: W.Widget = table

    if on_show_timeseries is not None:
        btn = W.Button(
            description=timeseries_button_label or "Show Soil Moisture Sensor Reads",
            button_style="primary",
            layout=W.Layout(margin="6px 0 0 0"),
            tooltip="Load and display the related time series below",
        )
        out = W.Output(layout=W.Layout(display="block"))

        def _on_click(_):
            out.clear_output(wait=True)
            try:
                widget = on_show_timeseries(props or {})
                with out:
                    if widget is not None:
                        display(widget)
                    else:
                        display(W.HTML("<i>No figure to show.</i>"))
            except Exception as e:
                with out:
                    display(W.HTML(f"<pre>Failed to load time series: {e}</pre>"))

        btn.on_click(_on_click)
        child = W.VBox([table, btn, out])

    # -------------------------
    # Replace any existing popups, then add new one
    # -------------------------
    try:
        for layer in list(m.layers):
            if isinstance(layer, ipyleaflet.Popup):
                m.remove_layer(layer)
    except Exception:
        pass

    popup = ipyleaflet.Popup(
        location=(float(lat), float(lon)),
        child=child,
        close_button=True,
        auto_close=True,
        close_on_escape_key=True,
        auto_pan=False,
        keep_in_view=False,
        min_width=min_width or 1800,
        max_width=max_width or 3000,
    )

    m.add_layer(popup)

    print(f"[POPUP] showing {props.get('sensor_id') or props.get('name') or 'sensor'}")
    try:
        if prev_center is not None and tuple(m.center) != tuple(prev_center):
            m.center = prev_center
        if prev_zoom is not None and m.zoom != prev_zoom:
            m.zoom = prev_zoom
    except Exception:
        pass
    if prev_center is not None:
        setattr(m, "_pending_center_restore", prev_center)
    if prev_zoom is not None:
        setattr(m, "_pending_zoom_restore", prev_zoom)
