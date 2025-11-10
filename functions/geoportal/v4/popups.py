# functions/geoportal/v4/popups.py
from __future__ import annotations
from typing import Any, Callable
import html

import ipyleaflet
import ipywidgets as W

from functions.geoportal.v4.utils import html_table_popup
from functions.geoportal.v4.config import CFG


# -----------------------------------------------------------------------------
# Marker (sensor) popup with optional time-series button (unchanged behavior)
# -----------------------------------------------------------------------------
def show_popup(
    m: ipyleaflet.Map,
    lat: float,
    lon: float,
    props: dict[str, Any] | None,
    marker: ipyleaflet.Marker,
    active_marker_ref,
    on_show_timeseries: Callable[[dict], W.Widget | None] | None = None,
):
    prev_center, prev_zoom = tuple(m.center), m.zoom

    # icon state
    if active_marker_ref.current and active_marker_ref.current is not marker:
        active_marker_ref.current.icon = ipyleaflet.AwesomeIcon(
            name=CFG.icon_name, marker_color=CFG.icon_color_default, icon_color=CFG.icon_icon_color
        )
    marker.icon = ipyleaflet.AwesomeIcon(
        name=CFG.icon_name, marker_color=CFG.icon_color_active, icon_color=CFG.icon_icon_color
    )
    active_marker_ref.current = marker

    # attributes table
    html_widget = html_table_popup(props or {})
    child: W.Widget = html_widget

    # optional inline plot
    if on_show_timeseries is not None:
        btn = W.Button(
            description="Show time series",
            button_style="primary",
            layout=W.Layout(margin="6px 0 0 0"),
        )
        out = W.Output(layout=W.Layout(display="block"))

        def _click(_):
            out.clear_output(wait=True)
            try:
                w = on_show_timeseries(props or {})
                out.children = [w] if w is not None else [W.HTML("<i>No figure to show.</i>")]
            except Exception as e:
                out.children = [W.HTML(f"<pre>Failed to load time series: {e}</pre>")]

        btn.on_click(_click)
        child = W.VBox([html_widget, btn, out])

    # remove old popups
    for layer in list(m.layers):
        if isinstance(layer, ipyleaflet.Popup):
            m.remove_layer(layer)

    # show popup
    popup = ipyleaflet.Popup(
        location=(lat, lon),
        child=child,
        close_button=True,
        auto_close=True,
        close_on_escape_key=True,
        auto_pan=True,
        min_width=420,
        max_width=820,
    )
    m.add_layer(popup)
    m.center, m.zoom = prev_center, prev_zoom


# -----------------------------------------------------------------------------
# Center-pivot polygon popups
# -----------------------------------------------------------------------------
# Fields to display (key, label); supports fallbacks and light formatting
# Replace your POLY_FIELDS with aliases so both old/new names work:
POLY_FIELDS = [
    ("fd_id", "ID"),
    ("Field_type", "Type"),
    # accept both "Acreage_ha" and "Field_Acreage_ha"
    (("Acreage_ha", "Field_Acreage_ha"), "Area (ha)"),
    ("Year", "Year"),
    ("Region", "Region"),
]

def _fmt_value(key: str, val: Any, props: dict[str, Any]) -> str:
    """
    Format values for display:
      - Round hectares to 2 decimals
      - If Field_Acreage_ha missing but Field_Acreage_m2 exists, compute
      - Escape HTML in strings
    """
    # fill ha from m² if needed
    if key == "Field_Acreage_ha":
        if val is None:
            m2 = props.get("Field_Acreage_m2")
            if isinstance(m2, (int, float)):
                val = float(m2) / 10_000.0
        if isinstance(val, (int, float)):
            return f"{float(val):.2f}"
        # try parseable numeric string
        try:
            return f"{float(str(val)):.2f}"
        except Exception:
            return html.escape(str(val)) if val is not None else ""
    # general: number vs string
    if isinstance(val, (int, float)):
        # lean display; don’t over-format general numbers
        return str(val)
    return html.escape(str(val)) if val is not None else ""

def popup_html_for_polygon(props: dict[str, Any] | None) -> str:
    props = props or {}
    def _get(p, key_or_keys):
        if isinstance(key_or_keys, tuple):
            for k in key_or_keys:
                if k in p and p[k] is not None:
                    return p[k]
            return None
        return p.get(key_or_keys)

    rows = []
    for key, label in POLY_FIELDS:
        val = _get(props, key)
        if val is not None:
            rows.append(
                f"<tr><th style='text-align:left;padding-right:8px'>{label}</th><td>{val}</td></tr>"
            )
    if not rows:
        return "<div style='font-size:12px'>No attributes</div>"
    return "<table style='font-size:12px'>" + "".join(rows) + "</table>"
