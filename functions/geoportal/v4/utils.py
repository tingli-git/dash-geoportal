from __future__ import annotations
from typing import Iterable, Sequence
from ipywidgets import HTML

def padded_bounds(coords: Sequence[tuple[float, float]], min_span=0.05, pad=0.25):
    if not coords:
        return None
    lats = [lat for lat, lon in coords]
    lons = [lon for lat, lon in coords]
    south, west = min(lats), min(lons)
    north, east = max(lats), max(lons)
    lat_span = max(north - south, min_span)
    lon_span = max(east - west, min_span)
    south -= lat_span * pad
    north += lat_span * pad
    west  -= lon_span * pad
    east  += lon_span * pad
    return [[south, west], [north, east]]

def html_table_popup(props: dict | None) -> HTML:
    def render_cell(v):
        if isinstance(v, str) and v.startswith("http"):
            return f"<a href='{v}' target='_blank' rel='noopener'>{v}</a>"
        return str(v)

    rows = ""
    if props:
        for k, v in props.items():
            rows += (
                f"<tr><th style='text-align:left;padding:4px 8px'>{k}</th>"
                f"<td style='padding:4px 0'>{render_cell(v)}</td></tr>"
            )
    else:
        rows = "<tr><td><i>No properties</i></td></tr>"

    return HTML(
        f"""
        <style>
        .leaflet-popup-content-wrapper {{ background: transparent !important; box-shadow: none !important; }}
        .leaflet-popup-tip {{ background: transparent !important; }}
        </style>
        <div style="
                    max-height:400px;
                    overflow:auto;
                    background-color: rgba(255, 255, 255, 0.75);
                    border-radius: 8px;
                    padding: 8px;
                    box-shadow: 0 1px 4px rgba(0,0,0,0.3);
                    min-width: 380px;            /* add this */
        ">
        <table style="border-collapse:collapse;font-size:13px;width:100%">{rows}</table>
        </div>
        """
    )
