# functions/geoportal/v6/datepalm_loader.py
from __future__ import annotations

import json
from urllib.request import urlopen
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from pathlib import Path

import ipyleaflet
import ipywidgets as W
import pandas as pd
import plotly.graph_objects as go

from functions.geoportal.v6.config import CFG
from functions.geoportal.v6.popups import show_popup
from functions.geoportal.v6.timeseries import _to_time_strings  # 👈 NEW


# Optional reprojection (if pyproj is available)
try:
    from pyproj import CRS, Transformer
except Exception:
    CRS = None
    Transformer = None


def _read_geojson_from_url(url: str) -> Dict[str, Any]:
    with urlopen(url) as r:
        data = r.read()
    return json.loads(data.decode("utf-8"))


def _parse_epsg_from_crs(crs_obj: Dict[str, Any] | None) -> str | None:
    if not crs_obj:
        return None
    props = (crs_obj or {}).get("properties") or {}
    name = props.get("name") or props.get("code") or ""
    name = str(name).replace("::", ":")
    if name.startswith("EPSG:"):
        return name
    for token in name.split(":"):
        if token.isdigit() and len(token) in (4, 5):
            return f"EPSG:{token}"
    return None


def _sample_pairs(coords_any: Any, max_pairs: int = 8) -> List[Tuple[float, float]]:
    pairs: List[Tuple[float, float]] = []

    def add_pairs(seq):
        for ring in seq:
            for pt in ring[:4]:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    pairs.append((float(pt[0]), float(pt[1])))
                    if len(pairs) >= max_pairs:
                        return True
        return False

    try:
        if isinstance(coords_any, list) and coords_any:
            # Polygon: [[ [x,y], ... ], ... ]
            if isinstance(coords_any[0][0][0], (int, float)):  # type: ignore[index]
                add_pairs(coords_any)
            else:
                # MultiPolygon: [ [ [ [x,y], ... ] ], ... ]
                for poly in coords_any:
                    if add_pairs(poly):
                        break
    except Exception:
        pass
    return pairs


def _looks_lonlat(pairs: List[Tuple[float, float]]) -> bool:
    ok = 0
    for x, y in pairs:
        if -180.5 <= x <= 180.5 and -90.5 <= y <= 90.5:
            ok += 1
    return ok >= max(1, len(pairs) // 2)


def _looks_latlon(pairs: List[Tuple[float, float]]) -> bool:
    ok = 0
    for x, y in pairs:
        if -90.5 <= x <= 90.5 and -180.5 <= y <= 180.5:
            ok += 1
    return ok >= max(1, len(pairs) // 2)


def _swap_feature_coords(feature: Dict[str, Any]) -> Dict[str, Any]:
    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "Polygon" and isinstance(coords, list):
        geom["coordinates"] = [[[float(y), float(x)] for x, y in ring] for ring in coords]
    elif gtype == "MultiPolygon" and isinstance(coords, list):
        geom["coordinates"] = [[[[float(y), float(x)] for x, y in ring] for ring in poly] for poly in coords]
    feature["geometry"] = geom
    return feature


def _reproject_feature_geometry(feature: Dict[str, Any], transformer) -> Dict[str, Any]:
    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")

    def proj_pt(x, y):
        lon, lat = transformer.transform(x, y)
        return [float(lon), float(lat)]

    if gtype == "Polygon" and isinstance(coords, list):
        geom["coordinates"] = [[proj_pt(x, y) for x, y in ring] for ring in coords]
    elif gtype == "MultiPolygon" and isinstance(coords, list):
        geom["coordinates"] = [[[proj_pt(x, y) for x, y in ring] for ring in poly] for poly in coords]
    feature["geometry"] = geom
    return feature


def _bounds_of_feature(feature: Dict[str, Any]) -> Tuple[float, float, float, float] | None:
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates")
    if not coords:
        return None
    xmin, ymin, xmax, ymax = 1e30, 1e30, -1e30, -1e30

    def update(pt):
        nonlocal xmin, ymin, xmax, ymax
        x, y = pt
        xmin = min(xmin, x)
        ymin = min(ymin, y)
        xmax = max(xmax, x)
        ymax = max(ymax, y)

    try:
        if geom.get("type") == "Polygon":
            for ring in coords:
                for x, y in ring:
                    update((float(x), float(y)))
        elif geom.get("type") == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    for x, y in ring:
                        update((float(x), float(y)))
        else:
            return None
    except Exception:
        return None
    return xmin, ymin, xmax, ymax


def _maybe_fix_coords_and_reproject(gj: Dict[str, Any]) -> Dict[str, Any]:
    feats = list(gj.get("features", []))
    if not feats:
        return gj

    # Sample coordinate sanity
    first = (feats[0] or {}).get("geometry") or {}
    pairs = _sample_pairs(first.get("coordinates"))

    # A) Attempt EPSG reprojection if coords not degrees
    degrees_like = _looks_lonlat(pairs) or _looks_latlon(pairs)
    if not degrees_like and Transformer and CRS:
        src_epsg = _parse_epsg_from_crs(gj.get("crs")) or getattr(CFG, "datepalms_crs_fallback", None)
        if src_epsg:
            try:
                transformer = Transformer.from_crs(
                    CRS.from_user_input(src_epsg),
                    CRS.from_epsg(4326),
                    always_xy=True,
                )
                feats = [_reproject_feature_geometry(dict(ft), transformer) for ft in feats]
                return {"type": "FeatureCollection", "features": feats}
            except Exception:
                # fall through to heuristic swapping if needed
                pass

    # B) If looks lat/lon, swap to lon/lat
    if _looks_latlon(pairs) and not _looks_lonlat(pairs):
        feats = [_swap_feature_coords(dict(ft)) for ft in feats]
        return {"type": "FeatureCollection", "features": feats}

    # else: assume already lon/lat degrees
    return gj


def _bounds_of_collection(gj: Dict[str, Any]) -> List[List[float]] | None:
    xmin, ymin, xmax, ymax = 1e30, 1e30, -1e30, -1e30
    any_feat = False
    for ft in gj.get("features", []):
        b = _bounds_of_feature(ft)
        if not b:
            continue
        any_feat = True
        x0, y0, x1, y1 = b
        xmin = min(xmin, x0)
        ymin = min(ymin, y0)
        xmax = max(xmax, x1)
        ymax = max(ymax, y1)
    if not any_feat:
        return None
    # Leaflet bounds [[south, west],[north, east]] == [[ymin, xmin],[ymax, xmax]]
    return [[ymin, xmin], [ymax, xmax]]


# -----------------------------
# NDVI time-series helper (ONLY for datepalm polygons)
# -----------------------------
def _build_ndvi_widget(props: Dict[str, Any]) -> W.Widget:
    """
    Build a Plotly widget for NDVI time series of a given date-palm field.
    CSV is expected to be named <Field_id>.csv with two columns:
    [date, ndvi_median].
    """
    try:
        # Support different casing of the property name
        field_id = (
            props.get("Field_id")
            or props.get("field_id")
            or props.get("FIELD_ID")
        )
        if not field_id:
            return W.HTML("<pre>No 'Field_id' property on this polygon; cannot load NDVI.</pre>")

        # 1) Try local filesystem path
        csv_dir = getattr(CFG, "ndvi_csv_dir", None)
        df = None
        src_str = ""
        if csv_dir is not None:
            csv_path = Path(csv_dir) / f"{field_id}.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                src_str = f"Local file: {csv_path}"

        # 2) Fallback to HTTP if local missing
        if df is None:
            base = getattr(CFG, "ndvi_http_base", "").rstrip("/")
            if base:
                url = f"{base}/{field_id}.csv"
                df = pd.read_csv(url)
                src_str = f"HTTP URL: {url}"

        if df is None:
            return W.HTML(f"<pre>No NDVI CSV found for Field_id={field_id!r}</pre>")

        if df.empty:
            return W.HTML(
                f"<pre>NDVI CSV for Field_id={field_id!r} is empty.\nSource: {src_str}</pre>"
            )

        # Expect two columns: date and ndvi_median
        if df.shape[1] < 2:
            return W.HTML(
                f"<pre>NDVI CSV for Field_id={field_id!r} must have at least 2 columns.\n"
                f"Got columns: {list(df.columns)}</pre>"
            )

        # Be lenient about column names, use first 2 columns
        date_col = df.columns[0]
        ndvi_col = df.columns[1]

        # Parse datetime, then convert to nice strings for Plotly (avoids 1e18 ticks)
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col]).sort_values(date_col)

        if df.empty:
            return W.HTML(
                f"<pre>NDVI CSV for Field_id={field_id!r} has no valid dates after parsing.\n"
                f"Source: {src_str}</pre>"
            )

        x_dt = df[date_col]
        # Use same helper as sensor timeseries: nice "YYYY-MM-DD" strings
        x_str = _to_time_strings(x_dt, fmt="%Y-%m-%d")
        y = pd.to_numeric(df[ndvi_col], errors="coerce")

        if y.dropna().empty:
            return W.HTML(
                f"<pre>NDVI CSV for Field_id={field_id!r} has no numeric NDVI values "
                f"in column '{ndvi_col}'.\nSource: {src_str}</pre>"
            )

        # Make the figure wider so the time series is more readable
        manual_width = 1800  # wider than popup; Box will scroll horizontally

        fig = go.FigureWidget()
        fig.add_scatter(
            x=x_str,
            y=y,
            mode="lines+markers",
            name="NDVI median",
            hovertemplate="Date: %{x}<br>NDVI: %{y:.3f}<extra></extra>",
        )
        fig.update_layout(
            title=f"NDVI time series — Field {field_id}",
            xaxis_title="Date",
            yaxis_title="NDVI (median)",
            margin=dict(l=60, r=20, t=60, b=50),
            width=manual_width,
            height=340,
        )

        fig.update_xaxes(
            tickangle=-45,
        )

        # Wrap in a Box so it scrolls horizontally if width > popup
        return W.Box(
            [fig],
            layout=W.Layout(width="100%", overflow_x="auto")
        )
    except Exception as e:
        # Surface full error text in popup so it's visible
        return W.HTML(f"<pre>Failed to load NDVI time series:\n{e}</pre>")


def build_datepalms_layer(
    *,
    visible: bool = True,
    m: ipyleaflet.Map | None = None,
    active_marker_ref: SimpleNamespace | None = None,
):
    """
    - Loads GeoJSON from CFG.datepalms_http_url
    - If needed, fixes lat/long swap and/or reprojects to EPSG:4326
    - Computes bounds and stores them on layer._bounds for optional fit
    - Adds click popup & a highlight overlay
    - NDVI time series is shown via a separate button in the popup.
    """
    name = getattr(CFG, "datepalms_layer_name", "Date Palm Fields (Qassim)")
    url = getattr(CFG, "datepalms_http_url", None)
    if not url:
        return None, "CFG.datepalms_http_url is not set."

    if m is not None and not hasattr(m, "_datepalms_highlight_layer"):
        m._datepalms_highlight_layer = None

    base_style = getattr(
        CFG,
        "datepalms_style",
        {"color": "#0B6E4F", "weight": 2, "fillColor": "#74C69D", "fillOpacity": 0.55},
    )
    base_hover = getattr(
        CFG,
        "datepalms_style_hover",
        {"weight": 3, "fillOpacity": 0.65},
    )

    try:
        gj = _read_geojson_from_url(url)
    except Exception as e:
        return None, f"Failed to fetch Date Palms GeoJSON: {e}"

    gj = _maybe_fix_coords_and_reproject(gj)
    bounds = _bounds_of_collection(gj)

    layer = ipyleaflet.GeoJSON(
        data=gj,
        name=name,
        style=base_style,
        hover_style=base_hover,
    )
    # stash bounds for app to optionally fit
    setattr(layer, "_bounds", bounds)

    def _on_click(event, feature, **kwargs):
        if not m:
            return

        props = dict((feature or {}).get("properties") or {})
        # remove style-ish keys from popup table
        props.pop("style", None)
        props.pop("_style", None)
        props.pop("visual_style", None)

        # Remove previous highlight
        try:
            if getattr(m, "_datepalms_highlight_layer", None) in m.layers:
                m.remove_layer(m._datepalms_highlight_layer)
        except Exception:
            pass

        highlight_style = {"color": "#CC79A7", "weight": 3, "fillOpacity": 0.45}
        single = {"type": "FeatureCollection", "features": [feature]}

        try:
            hl = ipyleaflet.GeoJSON(
                data=single,
                name="Date Palm Selected",
                style=highlight_style,
            )
        except Exception:
            fcopy = json.loads(json.dumps(feature))
            hl = ipyleaflet.GeoJSON(
                data={"type": "FeatureCollection", "features": [fcopy]},
                name="Date Palm Selected",
                style=highlight_style,
            )
        m._datepalms_highlight_layer = hl
        m.add_layer(hl)

        latlon = kwargs.get("coordinates")
        if isinstance(latlon, (list, tuple)) and len(latlon) == 2:
            lat, lon = float(latlon[0]), float(latlon[1])
        else:
            lat, lon = m.center

        ref = active_marker_ref or SimpleNamespace(current=None)

        # NDVI-only popup button; does not affect sensor (soil-moisture) logic
        show_popup(
            m,
            lat,
            lon,
            props,
            None,  # polygon, not a Marker
            active_marker_ref=ref,
            on_show_timeseries=_build_ndvi_widget,
            timeseries_button_label="Show NDVI Time Series",
        )

    layer.on_click(_on_click)
    # app controls visibility by add/remove
    return layer, None
