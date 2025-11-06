from __future__ import annotations
import json
from pathlib import Path
import ipyleaflet
from functions.geoportal.v1.utils import padded_bounds
from functions.geoportal.v1.config import CFG
from functions.geoportal.v1.popups import show_popup

def load_icon_group_from_geojson(path: Path, m: ipyleaflet.Map, active_marker_ref) -> tuple[ipyleaflet.LayerGroup | None, list[list[float]] | None]:
    """
    Build a LayerGroup of markers + compute padded bounds.
    Returns (layer_group, bounds) or (None, None) if file missing.
    """
    if not path or not path.exists():
        return None, None

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    coords_latlon: list[tuple[float, float]] = []
    group = ipyleaflet.LayerGroup(name=CFG.layer_group_name)

    base_icon = ipyleaflet.AwesomeIcon(
        name=CFG.icon_name, marker_color=CFG.icon_color_default, icon_color=CFG.icon_icon_color
    )

    for feat in data.get("features", []):
        geom = feat.get("geometry", {})
        props = feat.get("properties", {}) or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom.get("coordinates", [None, None])
        if lat is None or lon is None:
            continue

        coords_latlon.append((lat, lon))
        marker = ipyleaflet.Marker(location=(lat, lon), icon=base_icon)
        # capture variables in default-arg closure to avoid late-binding
        marker.on_click(lambda props=props, lat=lat, lon=lon, mk=marker, **_: show_popup(m, lat, lon, props, mk, active_marker_ref))
        group.add_layer(marker)

    bounds = padded_bounds(coords_latlon) if coords_latlon else None
    return group, bounds
