from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional, Tuple
from types import SimpleNamespace

import ipyleaflet

from functions.geoportal.v14.config import CFG
from functions.geoportal.v14.cloud_assets import force_gcs_enabled
from functions.geoportal.v14.popups import show_popup

BBox = Tuple[float, float, float, float]  # kept for API compatibility


def build_center_pivot_layer(
    year: int,
    *,
    visible: bool,
    use_http_url: bool = True,
    clip_to_bbox: Optional[BBox] = None,
    m: Optional[ipyleaflet.Map] = None,
    active_marker_ref: Optional[SimpleNamespace] = None,
):
    """Return the yearly CPF vector-tile layer for the selected year."""
    if year not in getattr(CFG, "center_pivot_years", ()):
        return None, f"Year {year} not in allowed set: {getattr(CFG, 'center_pivot_years', ())}"

    name = getattr(CFG, "center_pivot_layer_name", "Center-Pivot Fields")
    base_style = {
        "fillColor": "#56B4E9",
        "color": "#56B4E9",
        "weight": 1,
        "fillOpacity": 0.35,
    }

    base_url = getattr(
        CFG,
        "center_pivot_tile_public_base_url" if force_gcs_enabled() else "center_pivot_tile_base_url",
        "",
    ).rstrip("/")
    year_stem = f"CPF_fields_{year}_simpl"
    url_template = str(getattr(CFG, "center_pivot_tile_url_template", "{base}/{year}/{z}/{x}/{y}.pbf"))
    url = url_template.format(base=base_url, year=year_stem, z="{z}", x="{x}", y="{y}")

    style_key = _vector_layer_id_from_mbtiles(year_stem) or "*"
    layer = ipyleaflet.VectorTileLayer(
        url=url,
        name=name,
        min_zoom=5,
        max_zoom=17,
        attribution="© local tiles",
        renderer="svg",
        interactive=True,
        feature_id="id",
        vector_tile_layer_styles={style_key: base_style},
    )
    try:
        layer.style = base_style
    except Exception:
        pass

    def _on_click(event, feature, **kwargs):
        if not m:
            return
        props = dict((feature or {}).get("properties") or {})
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

    # visibility hint
    try:
        layer.visible = bool(visible)
    except Exception:
        pass

    return layer, None


def _vector_layer_id_from_mbtiles(year_stem: str) -> Optional[str]:
    cache_dir = Path(getattr(CFG, "center_pivot_tiles_dir", "")).parent / "cpf_mbfiles"
    if not cache_dir or not cache_dir.is_dir():
        return None
    mbtiles = cache_dir / f"{year_stem}.mbtiles"
    if not mbtiles.exists():
        return None
    try:
        conn = sqlite3.connect(mbtiles)
        cur = conn.execute("SELECT value FROM metadata WHERE name='json'")
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        payload = json.loads(row[0])
        vector_layers = payload.get("vector_layers", [])
        if not vector_layers:
            return None
        return vector_layers[0].get("id")
    except Exception:
        return None
