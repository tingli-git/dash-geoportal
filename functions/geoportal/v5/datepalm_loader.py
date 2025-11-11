# functions/geoportal/v5/datepalm_loader.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Dict, Any
from types import SimpleNamespace

import ipyleaflet

from functions.geoportal.v5.config import CFG
from functions.geoportal.v5.popups import show_popup


def build_datepalm_layer(
    *,
    visible: bool,
    use_http_url: bool = True,
    m: Optional[ipyleaflet.Map] = None,
    active_marker_ref: Optional[SimpleNamespace] = None,
):
    """
    Load the single Date Palm fields GeoJSON as a simple overlay.
    - URL mode (default): served by your local HTTP server (fast).
    - Local mode: read the file from disk and push the data (useful if you need pre-processing).
    - Clicking a polygon shows an attribute popup.
    """
    name = getattr(CFG, "datepalm_layer_name", "Date Palm Fields")
    filename = getattr(CFG, "datepalm_filename", "Qassim_datepalm_fields_polygons.geojson")

    base_style = {
        "color": "#F9A825",     # golden outline
        "weight": 1.5,
        "fillOpacity": 0.30,
    }
    hover_style = {"weight": 2.5}

    if use_http_url:
        url = f"{CFG.datepalm_http_base}/{filename}"
        layer = ipyleaflet.GeoJSON(
            url=url,
            name=name,
            style=base_style,
            hover_style=hover_style,
        )
    else:
        fp = Path(CFG.datepalm_dir) / filename
        if not fp.exists():
            return None, f"Date palm GeoJSON not found: {fp}"
        with fp.open("r", encoding="utf-8") as f:
            gj = json.load(f)
        layer = ipyleaflet.GeoJSON(
            data=gj,
            name=name,
            style=base_style,
            hover_style=hover_style,
        )

    # Popup on click (attribute table)
    def _on_click(event, feature, **kwargs):
        if not m:
            return
        props = dict((feature or {}).get("properties") or {})
        # strip style-ish keys if present
        props.pop("style", None)
        props.pop("_style", None)
        props.pop("visual_style", None)

        latlon = kwargs.get("coordinates")
        if isinstance(latlon, (list, tuple)) and len(latlon) == 2:
            lat, lon = float(latlon[0]), float(latlon[1])
        else:
            lat, lon = float(m.center[0]), float(m.center[1])

        ref = active_marker_ref or SimpleNamespace(current=None)
        show_popup(m, lat, lon, props, None, active_marker_ref=ref)

    layer.on_click(_on_click)

    try:
        layer.visible = bool(visible)
    except Exception:
        pass

    return layer, None
