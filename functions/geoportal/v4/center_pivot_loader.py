# functions/geoportal/v4/center_pivot_loader.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from types import SimpleNamespace

import ipyleaflet

from functions.geoportal.v4.config import CFG
from functions.geoportal.v4.popups import show_popup

BBox = Tuple[float, float, float, float]  # (south, west, north, east)


def _year_to_filename(year: int) -> str:
    return f"CPF_fields_{year}_simpl.geojson"


def _feature_bbox_intersects(feature: Dict[str, Any], bbox: BBox) -> bool:
    """Fast bbox filter for Polygon/MultiPolygon."""
    s, w, n, e = bbox
    geom = (feature or {}).get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return False

    def _bbox_of_poly(coordlist):
        # coordlist: [ [ [lon,lat], ... ] , ... rings ]
        lon_min, lat_min, lon_max, lat_max = 10**9, 10**9, -10**9, -10**9
        for ring in coordlist:
            for lon, lat in ring:
                lon_min = min(lon_min, lon)
                lat_min = min(lat_min, lat)
                lon_max = max(lon_max, lon)
                lat_max = max(lat_max, lat)
        # return as (south, west, north, east)
        return (lat_min, lon_min, lat_max, lon_max)

    if gtype == "Polygon":
        fs, fw, fn, fe = _bbox_of_poly(coords)
    elif gtype == "MultiPolygon":
        lat_min, lon_min, lat_max, lon_max = 10**9, 10**9, -10**9, -10**9
        for poly in coords:
            s2, w2, n2, e2 = _bbox_of_poly(poly)
            lat_min = min(lat_min, s2)
            lon_min = min(lon_min, w2)
            lat_max = max(lat_max, n2)
            lon_max = max(lon_max, e2)
        fs, fw, fn, fe = lat_min, lon_min, lat_max, lon_max
    else:
        return False

    # disjoint?
    return not (fn < s or fs > n or fe < w or fw > e)


def build_center_pivot_layer(
    year: int,
    *,
    visible: bool,
    use_http_url: bool = True,
    clip_to_bbox: Optional[BBox] = None,
    m: Optional[ipyleaflet.Map] = None,
    active_marker_ref: Optional[SimpleNamespace] = None,
):
    """
    Returns (layer, error_message). `layer` is the *base* CPF layer (light green).
    A separate pink highlight layer is managed on click for responsiveness.

    Notes:
    - If use_http_url=True and clip_to_bbox is not None, clipping cannot be applied
      by a static HTTP server. In that case, the full file is fetched by the browser.
      To actually clip, set use_http_url=False.
    """
    if year not in getattr(CFG, "center_pivot_years", ()):
        return None, f"Year {year} not in allowed set: {getattr(CFG, 'center_pivot_years', ())}"

    name = getattr(CFG, "center_pivot_layer_name", "Center-Pivot Fields")

    # Prepare a place on the map to hold the "current highlight" single-feature layer
    if m is not None and not hasattr(m, "_cpf_highlight_layer"):
        m._cpf_highlight_layer = None  # ipyleaflet.GeoJSON holding 1 selected feature

    # Base style: fast static (no dynamic restyling)
    base_style = {
        "color": "#56B4E9",   # light blue color blind
        "weight": 1,
        "fillOpacity": 0.35,
    }
    base_hover = {"weight": 2}

    # ---- build the base layer (URL or clipped local) ----
    if use_http_url and clip_to_bbox is None:
        # Fast path: browser fetches the full file
        url = f"{CFG.center_pivot_http_base}/{_year_to_filename(year)}"
        layer = ipyleaflet.GeoJSON(
            url=url,
            name=name,
            style=base_style,
            hover_style=base_hover,
        )
    else:
        # Local read (+ optional clip)
        fp = Path(CFG.center_pivot_dir) / _year_to_filename(year)
        if not fp.exists():
            return None, f"CPF file not found: {fp}"
        with fp.open("r", encoding="utf-8") as f:
            gj = json.load(f)

        feats = gj.get("features", [])
        if clip_to_bbox is not None:
            feats = [ft for ft in feats if _feature_bbox_intersects(ft, clip_to_bbox)]
        data = {"type": "FeatureCollection", "features": feats}

        layer = ipyleaflet.GeoJSON(
            data=data,
            name=name,
            style=base_style,
            hover_style=base_hover,
        )

    # ---- click handler: create/update a thin pink highlight layer with only the clicked feature ----
    def _on_click(event, feature, **kwargs):
        if not m:
            return

        # Clean properties for popup
        props = dict((feature or {}).get("properties") or {})
        # remove style-ish keys from popup
        props.pop("style", None)
        props.pop("_style", None)
        props.pop("visual_style", None)

        # Build a single-feature GeoJSON for highlight
        single = {"type": "FeatureCollection", "features": [feature]}

        # Remove previous highlight layer if any
        try:
            if m._cpf_highlight_layer and (m._cpf_highlight_layer in m.layers):
                m.remove_layer(m._cpf_highlight_layer)
        except Exception:
            pass

        # Create a new highlight layer (pink) just for the selected feature
        highlight_style = {
            "color": "#CC79A7",   # pink outline - colorblind friendly
            "weight": 3,
            "fillOpacity": 0.45,
        }
        try:
            hl = ipyleaflet.GeoJSON(
                data=single,
                name="CPF Selected",
                style=highlight_style,
            )
        except Exception:  # fallback if feature is not serializable as-is
            try:
                fcopy = json.loads(json.dumps(feature))
                hl = ipyleaflet.GeoJSON(
                    data={"type": "FeatureCollection", "features": [fcopy]},
                    name="CPF Selected",
                    style=highlight_style,
                )
            except Exception:
                hl = None

        m._cpf_highlight_layer = hl
        if hl is not None:
            # Insert above the base layer and below sensor markers (app ensures sensors float to top)
            try:
                # Prefer to put it right after the base layer
                if layer in m.layers:
                    idx = list(m.layers).index(layer)
                    m.layers = tuple(list(m.layers[:idx + 1]) + [hl] + list(m.layers[idx + 1:]))
                else:
                    m.add_layer(hl)
            except Exception:
                m.add_layer(hl)

        # Popup position — Leaflet passes click [lat, lon]
        latlon = kwargs.get("coordinates")
        if isinstance(latlon, (list, tuple)) and len(latlon) == 2:
            lat, lon = float(latlon[0]), float(latlon[1])
        else:
            lat, lon = float(m.center[0]), float(m.center[1])

        ref = active_marker_ref or SimpleNamespace(current=None)
        show_popup(m, lat, lon, props, None, active_marker_ref=ref)

    layer.on_click(_on_click)

    # visibility hint
    try:
        layer.visible = bool(visible)
    except Exception:
        pass

    return layer, None
