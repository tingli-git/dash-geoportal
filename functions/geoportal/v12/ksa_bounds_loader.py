# Updated ksa_bounds_loader.py with:
# - caching (fast)
# - separate name + area layers
# - Tabuk-specific vertical offset

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import ipyleaflet

from functions.geoportal.v12.config import CFG


def _normalize_name(name: str) -> str:
    return "" if not name else name.replace(" ", "_").replace("-", "_").strip().lower()


# -------- offsets (custom tweaks) --------
OFFSET_OVERRIDES = {
    "tabuk": -30,  # move 30px north
}


@lru_cache(maxsize=1)
def _province_area_lookup() -> dict[str, dict[str, float]]:
    lookup_path = getattr(CFG, "datepalms_province_lookup_json", None)
    if not lookup_path:
        return {}
    path = Path(lookup_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    result: dict[str, dict[str, float]] = {}
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        key = _normalize_name(str(name))
        try:
            area = float(entry.get("area_ha") or entry.get("area_m2") or 0)
        except Exception:
            continue
        result[key] = {"area_ha": area}
    return result


def _format_area_label(name: str | None) -> str | None:
    if not name:
        return None
    entry = _province_area_lookup().get(_normalize_name(name))
    if not entry:
        return None
    hectares = entry.get("area_ha")
    if hectares is None or not math.isfinite(hectares):
        return None
    return f"{int(round(hectares)):,} ha"


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


@lru_cache(maxsize=1)
def _load_gdf_cached() -> gpd.GeoDataFrame:
    return _load_gdf()


@lru_cache(maxsize=1)
def _load_gdf_wgs84() -> gpd.GeoDataFrame:
    gdf = _load_gdf_cached()
    try:
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
    except Exception:
        pass
    return gdf


def _build_geojson(gdf: gpd.GeoDataFrame) -> dict:
    try:
        geom_col = gdf.geometry.name
        geo_only = gdf[[geom_col]].copy()
        return json.loads(geo_only.to_json())
    except Exception as exc:
        raise RuntimeError(f"Failed to serialize KSA bounds: {exc}")


@lru_cache(maxsize=1)
def _build_geojson_cached() -> dict:
    return _build_geojson(_load_gdf_wgs84())


# -------- label layers --------

def _build_name_label_group(gdf: gpd.GeoDataFrame) -> ipyleaflet.LayerGroup:
    label_field = getattr(CFG, "ksa_bounds_label_field", "ADM1_EN")
    font_size = getattr(CFG, "ksa_bounds_label_font_size", "16px")
    font_color = getattr(CFG, "ksa_bounds_label_color", "#1f273b")
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

        name_norm = _normalize_name(name)
        offset = OFFSET_OVERRIDES.get(name_norm, 0)

        html = (
            f"<div style="
            f"'font-size:{font_size};color:{font_color};font-weight:600;opacity:0.8;"
            "text-shadow:0 0 4px rgba(255,255,255,0.85);white-space:nowrap;"
            f"transform:translate(-50%,-50%) translateY({offset}px);'"
            f"><span>{name}</span></div>"
        )

        icon = ipyleaflet.DivIcon(html=html, icon_size=(0, 0))
        markers.append(ipyleaflet.Marker(location=(centroid.y, centroid.x), icon=icon))

    return ipyleaflet.LayerGroup(layers=markers, name="KSA province names")


def _build_area_label_group(gdf: gpd.GeoDataFrame) -> ipyleaflet.LayerGroup:
    label_field = getattr(CFG, "ksa_bounds_label_field", "ADM1_EN")
    font_size = getattr(CFG, "ksa_bounds_label_font_size", "16px")
    font_color = getattr(CFG, "ksa_bounds_label_color", "#1f273b")
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

        area_label = _format_area_label(name)
        if not area_label:
            continue

        name_norm = _normalize_name(name)
        base_offset = 20
        extra_offset = OFFSET_OVERRIDES.get(name_norm, 0)
        total_offset = base_offset + extra_offset

        html = (
            f"<div style="
            f"'font-size:{font_size};color:{font_color};font-weight:800;opacity:0.8;"
            "text-shadow:0 0 4px rgba(255,255,255,0.85);white-space:nowrap;"
            f"transform:translate(-50%,-50%) translateY({total_offset}px);'"
            f"><span style='display:block;font-size:0.8rem;'>{area_label}</span></div>"
        )

        icon = ipyleaflet.DivIcon(html=html, icon_size=(0, 0))
        markers.append(ipyleaflet.Marker(location=(centroid.y, centroid.x), icon=icon))

    return ipyleaflet.LayerGroup(layers=markers, name="KSA field acreage")


# -------- main builder --------

def build_ksa_bounds_layer(
    *,
    m: ipyleaflet.Map | None = None,
    show_area: bool = False,
) -> tuple[ipyleaflet.LayerGroup | None, str | None]:
    try:
        gdf = _load_gdf_wgs84()
    except Exception as exc:
        return None, str(exc)

    try:
        data = _build_geojson_cached()
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

    layers = [boundary, _build_name_label_group(gdf)]

    if show_area:
        layers.append(_build_area_label_group(gdf))

    group = ipyleaflet.LayerGroup(
        layers=layers,
        name=getattr(CFG, "ksa_bounds_layer_name", "KSA bounds"),
    )

    return group, None
