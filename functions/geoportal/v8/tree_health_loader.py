# functions/geoportal/v7/tree_health_loader.py
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

import ipyleaflet

from functions.geoportal.v8.config import CFG
from functions.geoportal.v8.popups import show_popup
from functions.geoportal.v8.utils import padded_bounds


def _read_geojson(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _point_latlon(feature: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates")
    if not coords:
        return None
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            lon = float(coords[0])
            lat = float(coords[1])
            return lat, lon
        except Exception:
            return None
    return None


def _status_from_props(props: Dict[str, Any]) -> str:
    candidates = (
        props.get("Infestation_Status"),
        props.get("infestation_status"),
        props.get("Infestation Status"),
        props.get("status"),
    )
    for val in candidates:
        if val is None:
            continue
        stripped = str(val).strip()
        if stripped:
            return stripped.lower()
    return ""


def _color_for_status(status: str) -> str:
    healthy = getattr(CFG, "tree_health_color_healthy", "#66C2A5")
    infested = getattr(CFG, "tree_health_color_infested", "#D1495B")
    fallback = getattr(CFG, "tree_health_color_default", "#8C8C8C")
    if not status:
        return fallback
    if "healthy" in status:
        return healthy
    if "infest" in status:
        return infested
    return fallback


def _collect_markers(
    features: Iterable[Dict[str, Any]],
    m: ipyleaflet.Map | None,
    active_marker_ref,
) -> Tuple[List[ipyleaflet.CircleMarker], List[Tuple[float, float]]]:
    layers: List[ipyleaflet.CircleMarker] = []
    locations: List[Tuple[float, float]] = []
    radius_val = getattr(CFG, "tree_health_point_radius", 6.0)
    try:
        radius = int(round(float(radius_val)))
    except Exception:
        radius = 6
    fill_opacity = float(getattr(CFG, "tree_health_fill_opacity", 0.75))
    weight_val = getattr(CFG, "tree_health_stroke_weight", 1.5)
    try:
        weight = int(round(float(weight_val)))
    except Exception:
        weight = 2

    for feature in features:
        point = _point_latlon(feature)
        if not point:
            continue
        props = dict((feature or {}).get("properties") or {})
        color = _color_for_status(_status_from_props(props))
        marker = ipyleaflet.CircleMarker(
            location=point,
            radius=radius,
            color=color,
            fill_color=color,
            weight=weight,
            fill_opacity=fill_opacity,
            opacity=0.95,
        )

        def _make_click_handler(lat_val, lon_val, props_snapshot, marker_ref):
            def _handler(**_):
                if m is None:
                    return
                show_popup(
                    m,
                    lat_val,
                    lon_val,
                    props_snapshot,
                    marker_ref,
                    active_marker_ref=active_marker_ref,
                )
            return _handler

        marker.on_click(_make_click_handler(point[0], point[1], props, marker))
        layers.append(marker)
        locations.append(point)

    return layers, locations


def build_tree_health_layer(
    *,
    m: ipyleaflet.Map | None = None,
    active_marker_ref=None,
) -> Tuple[ipyleaflet.LayerGroup | None, str | None]:
    name = getattr(CFG, "tree_health_layer_name", "Tree Health")
    geojson_path = Path(getattr(CFG, "tree_health_geojson_file", ""))
    if not geojson_path:
        return None, "CFG.tree_health_geojson_file is not configured."
    if not geojson_path.exists():
        return None, f"Tree Health GeoJSON not found: {geojson_path}"

    try:
        gj = _read_geojson(geojson_path)
    except Exception as exc:
        return None, f"Failed to read Tree Health GeoJSON: {exc}"

    features = list(gj.get("features", []) or [])
    layers, locations = _collect_markers(features, m, active_marker_ref)
    if not layers:
        return None, "Tree Health GeoJSON contains no valid point features."

    layer = ipyleaflet.LayerGroup(layers=layers, name=name)
    bounds = padded_bounds(locations)
    setattr(layer, "_bounds", bounds)
    return layer, None


_highlight_ref = SimpleNamespace(marker=None)


def _restore_marker(marker: ipyleaflet.CircleMarker):
    default = getattr(marker, "_tree_health_default_color", None)
    if default:
        marker.fill_color = default
        marker.color = default


def _highlight_marker(marker: ipyleaflet.CircleMarker):
    prev = getattr(_highlight_ref, "marker", None)
    if prev and prev is not marker:
        _restore_marker(prev)
    _highlight_ref.marker = marker
    highlight_color = getattr(CFG, "tree_health_active_color", "#FFD166")
    marker.fill_color = highlight_color
    marker.color = highlight_color


def clear_tree_health_highlight():
    prev = getattr(_highlight_ref, "marker", None)
    if prev:
        _restore_marker(prev)
        _highlight_ref.marker = None
