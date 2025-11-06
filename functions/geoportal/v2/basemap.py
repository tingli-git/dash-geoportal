from __future__ import annotations
import ipyleaflet
from ipywidgets import Layout

def create_base_map(center: tuple[float, float], zoom: int, width: str, height: str) -> ipyleaflet.Map:
    return ipyleaflet.Map(
        center=list(center), zoom=zoom, scroll_wheel_zoom=True, layout=Layout(height=height, width=width)
    )

def osm_layer() -> ipyleaflet.TileLayer:
    return ipyleaflet.TileLayer(
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attribution="© OpenStreetMap contributors",
        name="OpenStreetMap", base=True, max_zoom=19,
    )

def esri_world_imagery_layer() -> ipyleaflet.TileLayer:
    return ipyleaflet.TileLayer(
        url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attribution="© Esri, Maxar, Earthstar Geographics",
        name="ESRI World Imagery", max_zoom=19,
    )

def ensure_controls(m: ipyleaflet.Map):
    if not any(isinstance(c, ipyleaflet.LayersControl) for c in m.controls):
        m.add_control(ipyleaflet.LayersControl(position="topright"))
    if not any(isinstance(c, ipyleaflet.ScaleControl) for c in m.controls):
        m.add_control(ipyleaflet.ScaleControl(position="bottomleft"))

def ensure_base_layers(m: ipyleaflet.Map, *layers: ipyleaflet.TileLayer):
    for lyr in layers:
        if lyr not in m.layers:
            m.add_layer(lyr)
