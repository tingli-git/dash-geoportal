from __future__ import annotations
import json
from pathlib import Path
import ipyleaflet
from functions.geoportal.v5.utils import padded_bounds
from functions.geoportal.v5.config import CFG
from functions.geoportal.v5.popups import show_popup

def load_icon_group_from_geojson(
    path: Path,
    m: ipyleaflet.Map,
    active_marker_ref,
    on_show_timeseries=None,      # <-- NEW (optional)
):
    if not path or not path.exists():
        raise FileNotFoundError(f"GeoJSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    coords_latlon = []
    group = ipyleaflet.LayerGroup(name=CFG.layer_group_name)
    base_icon = ipyleaflet.AwesomeIcon(
        name=CFG.icon_name, marker_color=CFG.icon_color_default, icon_color=CFG.icon_icon_color
    )

    for feat in data.get("features", []):
        geom = (feat or {}).get("geometry", {}) or {}
        props = (feat or {}).get("properties", {}) or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = (geom.get("coordinates") or [None, None])[:2]
        if lat is None or lon is None:
            continue

        coords_latlon.append((lat, lon))
        marker = ipyleaflet.Marker(location=(lat, lon), icon=base_icon)

        # capture defaults to avoid late-binding
        marker.on_click(
            lambda props=props, lat=lat, lon=lon, mk=marker, **_:
                show_popup(m, lat, lon, props, mk, active_marker_ref, on_show_timeseries)  # passes callback
        )
        group.add_layer(marker)

    bounds = padded_bounds(coords_latlon) if coords_latlon else None
    return group, bounds
