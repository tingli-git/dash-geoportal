from __future__ import annotations
import ipyleaflet
from typing import Any
from functions.geoportal.v1.utils import html_table_popup
from functions.geoportal.v1.config import CFG

def show_popup(m: ipyleaflet.Map, lat: float, lon: float, props: dict[str, Any] | None,
               marker: ipyleaflet.Marker, active_marker_ref):
    """Render a styled popup at (lat, lon) and highlight the clicked marker."""
    prev_center, prev_zoom = tuple(m.center), m.zoom

    if active_marker_ref.current and active_marker_ref.current is not marker:
        active_marker_ref.current.icon = ipyleaflet.AwesomeIcon(
            name=CFG.icon_name, marker_color=CFG.icon_color_default, icon_color=CFG.icon_icon_color
        )

    marker.icon = ipyleaflet.AwesomeIcon(
        name=CFG.icon_name, marker_color=CFG.icon_color_active, icon_color=CFG.icon_icon_color
    )
    active_marker_ref.current = marker

    html = html_table_popup(props or {})
    popup = ipyleaflet.Popup(
        location=(lat, lon),
        child=html,
        close_button=True,
        auto_close=True,
        close_on_escape_key=True,
        auto_pan=False,
    )
    # remove existing popups
    for layer in list(m.layers):
        if isinstance(layer, ipyleaflet.Popup):
            m.remove_layer(layer)

    m.add_layer(popup)
    m.center, m.zoom = prev_center, prev_zoom
