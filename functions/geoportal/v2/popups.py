from __future__ import annotations
from typing import Any, Callable
import ipyleaflet
import ipywidgets as W
from functions.geoportal.v2.utils import html_table_popup
from functions.geoportal.v2.config import CFG

def show_popup(
    m: ipyleaflet.Map,
    lat: float,
    lon: float,
    props: dict[str, Any] | None,
    marker: ipyleaflet.Marker,
    active_marker_ref,
    # callback returns an ipywidget to render inside the popup (or None)
    on_show_timeseries: Callable[[dict], W.Widget | None] | None = None,
):
    prev_center, prev_zoom = tuple(m.center), m.zoom

    # icon behavior unchanged
    if active_marker_ref.current and active_marker_ref.current is not marker:
        active_marker_ref.current.icon = ipyleaflet.AwesomeIcon(
            name=CFG.icon_name, marker_color=CFG.icon_color_default, icon_color=CFG.icon_icon_color
        )
    marker.icon = ipyleaflet.AwesomeIcon(
        name=CFG.icon_name, marker_color=CFG.icon_color_active, icon_color=CFG.icon_icon_color
    )
    active_marker_ref.current = marker

    # table
    html = html_table_popup(props or {})
    child: W.Widget = html  # default content

    # optional inline plot
    if on_show_timeseries is not None:
        btn = W.Button(description="Show time series", button_style="primary",
                       layout=W.Layout(margin="6px 0 0 0"))
        out = W.Output(layout=W.Layout(display="block"))
        def _click(_):
            out.clear_output(wait=True)
            try:
                w = on_show_timeseries(props or {})  # may return a widget
                if w is not None:
                    out.children = [w]  # <-- render widget directly
                else:
                    out.children = [W.HTML("<i>No figure to show.</i>")]
            except Exception as e:
                out.children = [W.HTML(f"<pre>Failed to load time series: {e}</pre>")]
        
        btn.on_click(_click)
        child = W.VBox([html, btn, out])

    # remove old popups
    for layer in list(m.layers):
        if isinstance(layer, ipyleaflet.Popup):
            m.remove_layer(layer)

    # widen popup here
    popup = ipyleaflet.Popup(
        location=(lat, lon),
        child=child,
        close_button=True,
        auto_close=True,
        close_on_escape_key=True,
        auto_pan=True,
        min_width=420,      # <-- wider
        max_width=820,      # <-- much wider
    )
    m.add_layer(popup)
    m.center, m.zoom = prev_center, prev_zoom
