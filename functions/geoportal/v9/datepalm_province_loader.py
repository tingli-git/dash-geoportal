from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import ipyleaflet

from functions.geoportal.v9.config import CFG


ProvinceMap = Dict[str, Path]


def _province_paths() -> ProvinceMap:
    dir_path = Path(getattr(CFG, "datepalms_province_dir", ""))
    if not dir_path.is_dir():
        return {}
    provinces: ProvinceMap = {}
    for path in sorted(dir_path.glob("*.gpkg")):
        provinces[path.stem] = path
    return provinces


def list_date_palm_provinces() -> List[str]:
    return list(sorted(_province_paths().keys()))


def _bounds_from_gdf(gdf: gpd.GeoDataFrame) -> Optional[List[List[float]]]:
    if gdf.empty:
        return None
    minx, miny, maxx, maxy = gdf.total_bounds
    return [[float(miny), float(minx)], [float(maxy), float(maxx)]]


def build_date_palm_province_layer(
    province: str,
    *,
    m: ipyleaflet.Map | None = None,
) -> Tuple[ipyleaflet.GeoJSON | None, str | None]:
    paths = _province_paths()
    path = paths.get(province)
    if path is None:
        return None, f"Province '{province}' has no configured GeoPackage in {CFG.datepalms_province_dir}."

    try:
        gdf = gpd.read_file(path)
    except Exception as exc:
        return None, f"Failed to read province '{province}': {exc}"

    if gdf.crs and gdf.crs.to_epsg() != 4326:
        try:
            gdf = gdf.to_crs(4326)
        except Exception:
            pass

    if gdf.empty:
        return None, f"Province '{province}' layer contains no geometry."

    try:
        data = json.loads(gdf.to_json())
    except Exception as exc:
        return None, f"Failed to serialize province '{province}' data to GeoJSON: {exc}"

    fill_color = getattr(CFG, "datepalms_province_fill_color", "#84ff11")
    edge_color = getattr(CFG, "datepalms_province_edge_color", "#5ea700")
    edge_weight = float(getattr(CFG, "datepalms_province_edge_weight", 2.0))
    fill_opacity = float(getattr(CFG, "datepalms_province_fill_opacity", 0.4))
    hover_weight = float(getattr(CFG, "datepalms_province_hover_weight", edge_weight + 0.75))

    layer = ipyleaflet.GeoJSON(
        data=data,
        name=f"Date Palm Fields {province}",
        style={
            "fillColor": fill_color,
            "fillOpacity": fill_opacity,
            "color": edge_color,
            "weight": edge_weight,
        },
        hover_style={"weight": hover_weight},
    )

    bounds = _bounds_from_gdf(gdf) or []
    if bounds:
        setattr(layer, "_bounds", bounds)
    return layer, None
