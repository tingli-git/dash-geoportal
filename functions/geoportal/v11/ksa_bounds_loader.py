from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import ipyleaflet

from functions.geoportal.v11.config import CFG


def _load_gdf() -> gpd.GeoDataFrame:
    gpkg_path = getattr(CFG, "ksa_bounds_gpkg", None)
    http_url = getattr(CFG, "ksa_bounds_http_url", None)
    if gpkg_path:
        path = Path(gpkg_path)
        if path.exists():
            layer_name = getattr(CFG, "ksa_bounds_layer_source", None)
            kwargs = {}
            if layer_name:
                kwargs["layer"] = layer_name
            return gpd.read_file(path, **kwargs)
    if http_url:
        return gpd.read_file(http_url)
    raise FileNotFoundError("No valid KSA bounds source configured.")


def _build_geojson(gdf: gpd.GeoDataFrame) -> dict:
    try:
        geom_col = gdf.geometry.name
        geo_only = gdf[[geom_col]].copy()
        return json.loads(geo_only.to_json())
    except Exception as exc:
        raise RuntimeError(f"Failed to serialize KSA bounds: {exc}")


def _build_label_group(gdf: gpd.GeoDataFrame) -> ipyleaflet.LayerGroup:
    label_field = getattr(CFG, "ksa_bounds_label_field", "ADM1_EN")
    font_size = getattr(CFG, "ksa_bounds_label_font_size", "12px")
    font_color = getattr(CFG, "ksa_bounds_label_color", "#0f172a")
    markers = []
    for _, row in gdf.iterrows():
        geom = row.get("geometry")
        if geom is None or geom.is_empty:
            continue
        centroid = geom.centroid
        if centroid.is_empty:
            continue
        name = row.get(label_field)
        if not name:
            continue
        html = (
            f"<div style="
            f"'font-size:{font_size};color:{font_color};font-weight:600;opacity:0.8;"
            "text-shadow:0 0 4px rgba(255,255,255,0.85);white-space:nowrap;transform:translate(-50%,-50%);'"
            f">{name}</div>"
        )
        icon = ipyleaflet.DivIcon(html=html, icon_size=(0, 0))
        markers.append(ipyleaflet.Marker(location=(centroid.y, centroid.x), icon=icon))
    return ipyleaflet.LayerGroup(layers=markers, name=getattr(CFG, "ksa_bounds_label_layer_name", "KSA labels"))


def build_ksa_bounds_layer(
    *,
    m: ipyleaflet.Map | None = None,
) -> tuple[ipyleaflet.LayerGroup | None, str | None]:
    try:
        gdf = _load_gdf()
    except Exception as exc:
        return None, str(exc)

    try:
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
    except Exception:
        pass

    try:
        data = _build_geojson(gdf)
    except Exception as exc:
        return None, str(exc)
    boundary = ipyleaflet.GeoJSON(
        data=data,
        style={
            "color": getattr(CFG, "ksa_bounds_edge_color", "#cbd5f5"),
            "weight": float(getattr(CFG, "ksa_bounds_edge_weight", 1.5)),
            "fillOpacity": 0.0,
        },
        hover_style={
            "weight": float(getattr(CFG, "ksa_bounds_hover_weight", 2.0)),
        },
    )
    labels = _build_label_group(gdf)
    group = ipyleaflet.LayerGroup(
        layers=[boundary, labels],
        name=getattr(CFG, "ksa_bounds_layer_name", "KSA bounds"),
    )
    return group, None
