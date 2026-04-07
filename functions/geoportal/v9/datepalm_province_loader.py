from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import ipyleaflet
import pyogrio

from functions.geoportal.v9.config import CFG


ProvinceMap = Dict[str, Path]


@lru_cache(maxsize=32)
def _province_geojson_data(
    path_str: str,
    simplify_tolerance: float | None,
    bbox: Tuple[float, float, float, float] | None = None,
) -> Tuple[Dict[str, Any], Optional[List[List[float]]]]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Province source missing: {path}")

    layer_name = _preferred_province_layer(path)
    gdf = gpd.read_file(path, layer=layer_name, bbox=bbox)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        try:
            gdf = gdf.to_crs(4326)
        except Exception:
            pass

    if simplify_tolerance is not None and simplify_tolerance > 0:
        simplified = gdf.copy()
        simplified["geometry"] = simplified.geometry.simplify(simplify_tolerance, preserve_topology=True)
        simplified = simplified[~(simplified.geometry.is_empty | simplified.geometry.isna())]
        if not simplified.empty:
            gdf = simplified

    if gdf.empty:
        raise ValueError(f"Province data at {path} contains no geometry.")

    data = json.loads(gdf.to_json())
    bounds = _bounds_from_gdf(gdf)
    return data, bounds


def _bounds_from_features(features: List[Dict[str, Any]]) -> Optional[List[List[float]]]:
    if not features:
        return None
    try:
        gdf = gpd.GeoDataFrame.from_features(features)
    except Exception:
        return None
    if gdf.empty:
        return None
    return _bounds_from_gdf(gdf)


def _simple_geojson_path(province: str) -> Path | None:
    directory = Path(getattr(CFG, "datepalms_province_simple_dir", ""))
    if not directory:
        return None
    path = directory / f"{province}.geojson"
    return path if path.exists() else None


@lru_cache(maxsize=32)
def _prebuilt_simple_geojson(path_str: str) -> Tuple[Dict[str, Any], Optional[List[List[float]]]]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Prebuilt geojson missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    bounds = _bounds_from_features(data.get("features", []))
    return data, bounds


def _province_paths() -> ProvinceMap:
    dir_path = Path(getattr(CFG, "datepalms_province_dir", ""))
    if not dir_path.is_dir():
        return {}
    provinces: ProvinceMap = {}
    for path in sorted(dir_path.glob("*.gpkg")):
        provinces[path.stem] = path
    return provinces

def _preferred_province_layer(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        layers = pyogrio.list_layers(str(path))
    except Exception:
        return None
    for name in layers:
        if name and not name.lower().startswith("layer_styles"):
            return name
    return layers[0] if layers else None


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
    bbox: Tuple[float, float, float, float] | None = None,
    simplify_tolerance: float | None = None,
    use_prebuilt_simple: bool = False,
    fill_color: str | None = None,
    edge_color: str | None = None,
    edge_weight: float | None = None,
    fill_opacity: float | None = None,
    hover_weight: float | None = None,
    name_suffix: str | None = None,
) -> Tuple[ipyleaflet.GeoJSON | None, str | None]:
    paths = _province_paths()
    path = paths.get(province)
    if path is None:
        return None, f"Province '{province}' has no configured GeoPackage in {CFG.datepalms_province_dir}."

    data: Dict[str, Any] | None = None
    bounds: Optional[List[List[float]]] = None

    if use_prebuilt_simple:
        simple_path = _simple_geojson_path(province)
        if simple_path:
            try:
                data, bounds = _prebuilt_simple_geojson(str(simple_path.resolve()))
            except Exception as exc:
                return None, f"Failed to load province '{province}' simple view: {exc}"
        else:
            use_prebuilt_simple = False

    if data is None:
        try:
            data, bounds = _province_geojson_data(
                str(path.resolve()),
                simplify_tolerance,
                bbox=bbox,
            )
        except Exception as exc:
            return None, f"Failed to load province '{province}': {exc}"

    default_fill = getattr(CFG, "datepalms_province_fill_color", "#84ff11")
    default_edge = getattr(CFG, "datepalms_province_edge_color", "#5ea700")
    default_weight = float(getattr(CFG, "datepalms_province_edge_weight", 2.0))
    default_opacity = float(getattr(CFG, "datepalms_province_fill_opacity", 0.4))

    fill_color = fill_color or default_fill
    edge_color = edge_color or default_edge
    edge_weight_value = float(edge_weight) if edge_weight is not None else default_weight
    fill_opacity_value = float(fill_opacity) if fill_opacity is not None else default_opacity
    hover_weight_value = float(hover_weight) if hover_weight is not None else edge_weight_value + 0.75

    layer_name = f"Date Palm Fields {province}"
    if name_suffix:
        layer_name = f"{layer_name}{name_suffix}"

    layer = ipyleaflet.GeoJSON(
        data=data,
        name=layer_name,
        style={
            "fillColor": fill_color,
            "fillOpacity": fill_opacity_value,
            "color": edge_color,
            "weight": edge_weight_value,
        },
        hover_style={"weight": hover_weight_value},
    )

    if bounds:
        setattr(layer, "_bounds", bounds)
    return layer, None
