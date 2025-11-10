# functions/geoportal/v4/geojson_loader.py
from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache
from typing import Iterable, Dict, Any, Tuple, Optional, List

import ipyleaflet

from functions.geoportal.v4.utils import padded_bounds
from functions.geoportal.v4.config import CFG
from functions.geoportal.v4.popups import show_popup, popup_html_for_polygon


# =====================================================================
# POINT MARKERS (existing)
# =====================================================================
def load_icon_group_from_geojson(
    path: Path,
    m: ipyleaflet.Map,
    active_marker_ref,
    on_show_timeseries=None,      # optional
):
    if not path or not path.exists():
        raise FileNotFoundError(f"GeoJSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    coords_latlon: List[Tuple[float, float]] = []
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
                show_popup(m, lat, lon, props, mk, active_marker_ref, on_show_timeseries)
        )
        group.add_layer(marker)

    bounds = padded_bounds(coords_latlon) if coords_latlon else None
    return group, bounds


# =====================================================================
# CENTER-PIVOT (CPF) YEARLY POLYGONS
# =====================================================================

def _cpf_candidate_names(year: int) -> List[str]:
    """Filename candidates, prefer simplified; use config templates if present."""
    templates = getattr(CFG, "cpf_filename_templates", None)
    if templates:
        return [tpl.format(year=year) for tpl in templates]
    # fallback hard-coded order
    return [
        f"CPF_fields_{year}_simpl.geojson",
        f"CPF_fileds_{year}_simpl.geojson",
        f"CPF_fields_{year}.geojson",
        f"CPF_fileds_{year}.geojson",
    ]


def _cpf_candidate_paths(year: int) -> Iterable[Path]:
    base = Path(CFG.cpf_geojson_dir)
    for name in _cpf_candidate_names(year):
        yield base / name


def _cpf_resolve_path(year: int) -> Path:
    for p in _cpf_candidate_paths(year):
        if p.exists():
            return p
    tried = ", ".join(str(p) for p in _cpf_candidate_paths(year))
    raise FileNotFoundError(f"No CPF GeoJSON for year={year}. Tried: {tried}")


# Fast JSON loader with caching (each file parsed once per process)
@lru_cache(maxsize=64)
def _load_fc_cached(path_str: str) -> Dict[str, Any]:
    path = Path(path_str)
    try:
        import ujson as _json  # faster if available
    except Exception:
        import json as _json
    with path.open("r", encoding="utf-8") as f:
        return _json.load(f)


def _safe_bbox(fc: Dict[str, Any]) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """Use GeoJSON-level bbox if present: [minx, miny, maxx, maxy]."""
    bb = fc.get("bbox")
    if isinstance(bb, (list, tuple)) and len(bb) == 4:
        west, south, east, north = map(float, bb)
        return (south, west), (north, east)
    return None


# Sample every N vertices for a quick bounds approximation
_SAMPLE_STEP = 8

def _featurecollection_bounds_fast(fc: Dict[str, Any]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    # 1) O(1) fast path via bbox
    bb = _safe_bbox(fc)
    if bb:
        return bb

    # 2) approximate by sampling
    mins = [180.0, 90.0]
    maxs = [-180.0, -90.0]

    def sample_coords(geom: Dict[str, Any]):
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])
        if gtype == "Polygon":
            for ring in coords:
                for i in range(0, len(ring), _SAMPLE_STEP):
                    x, y = ring[i]
                    yield x, y
        elif gtype == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    for i in range(0, len(ring), _SAMPLE_STEP):
                        x, y = ring[i]
                        yield x, y

    for ft in fc.get("features", []):
        geom = ft.get("geometry") or {}
        for x, y in sample_coords(geom):
            if x < mins[0]: mins[0] = x
            if y < mins[1]: mins[1] = y
            if x > maxs[0]: maxs[0] = x
            if y > maxs[1]: maxs[1] = y

    if mins[0] == 180.0:  # empty fallback
        return (0.0, 0.0), (0.0, 0.0)
    return (mins[1], mins[0]), (maxs[1], maxs[0])  # (south, west), (north, east)


def _on_each_feature_attach_popup(feature: Dict[str, Any], layer: ipyleaflet.GeoJSON, **kwargs):
    props = feature.get("properties", {}) or {}
    layer.popup = popup_html_for_polygon(props)


def load_cpf_layer_for_year(
    year: int,
    name: Optional[str] = None,
) -> Tuple[ipyleaflet.GeoJSON, Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    Python-side load (data=...) with cached JSON and fast bounds.
    """
    path = _cpf_resolve_path(year)
    fc = _load_fc_cached(str(path))

    layer = ipyleaflet.GeoJSON(
        data=fc,
        name=name or f"{CFG.cpf_layer_name} {year}",
        style=CFG.cpf_style,
        hover_style=CFG.cpf_hover_style,
        on_each_feature=_on_each_feature_attach_popup,
    )
    bounds = _featurecollection_bounds_fast(fc)
    return layer, bounds


def available_cpf_years() -> list[int]:
    years = getattr(CFG, "cpf_years", [])
    return sorted(list(years))


def load_cpf_layer_for_year_url(
    year: int,
    name: Optional[str] = None,
) -> Tuple[ipyleaflet.GeoJSON, None]:
    """
    Fast path: let the browser fetch the GeoJSON by URL (no Python-side JSON payload).
    Uses CFG.cpf_http_base (same server as your XYZ tiles) and prefers simplified files.
    """
    # find a filename that actually exists on disk
    path = _cpf_resolve_path(year)
    fname = path.name

    base = str(getattr(CFG, "cpf_http_base", "")).rstrip("/")
    if not base:
        raise RuntimeError(
            "CFG.cpf_http_base is empty; set it to e.g. 'http://127.0.0.1:8766/center_pivot'"
        )
    url = f"{base}/{fname}"

    layer = ipyleaflet.GeoJSON(
        url=url,
        name=name or f"{getattr(CFG, 'cpf_layer_name', 'Center-Pivot Fields')} {year}",
        style=getattr(CFG, "cpf_style", {"color": "#6BBF59", "weight": 1, "opacity": 0.8,
                                          "fillColor": "#90EE90", "fillOpacity": 0.35}),
        hover_style=getattr(CFG, "cpf_hover_style", {"weight": 2, "opacity": 1.0, "fillOpacity": 0.5}),
    )
    return layer, None
# functions/geoportal/v4/geojson_loader.py
def _drop_unsupported_geoms(fc: Dict[str, Any]) -> Dict[str, Any]:
    feats = []
    for ft in fc.get("features", []):
        g = ft.get("geometry") or {}
        if g.get("type") in ("Polygon", "MultiPolygon"):
            feats.append(ft)
    out = dict(fc)
    out["features"] = feats
    return out

def load_cpf_layer_for_year(year: int, name: Optional[str] = None):
    path = _cpf_resolve_path(year)
    fc = _load_fc_cached(str(path))
    fc = _drop_unsupported_geoms(fc)   # <-- filter here
    layer = ipyleaflet.GeoJSON(
        data=fc,
        name=name or f"{CFG.cpf_layer_name} {year}",
        style=CFG.cpf_style,
        hover_style=CFG.cpf_hover_style,
        on_each_feature=_on_each_feature_attach_popup,
    )
    bounds = _featurecollection_bounds_fast(fc)
    return layer, bounds
