# functions/geoportal/v10/app.py
# cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/
# source .venv/bin/activate
# # check required pkgs use $ python -m pip list
# cd /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server
# python -m http.server 8766 
#-----------------------------------
# in another terminal:
# cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/
# source .venv/bin/activate
# python -m pip install -e .
# solara run --production /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/functions/geoportal/v10/app.py 
## if solara not founded, run $ hash -r 
# solara application will be running at localhost:8765
# ------------------------------------
# in the third terminal 
# cloudflared tunnel --url http://localhost:8765
# copy the url that can be shared to others
from __future__ import annotations
import json
import math
import sqlite3
from pathlib import Path
from typing import Optional, Tuple, List

import solara
import ipyleaflet
import ipywidgets as W

from starlette.responses import PlainTextResponse
from solara.server.fastapi import app as solara_app

from functions.geoportal.v10.config import CFG
from functions.geoportal.v10.state import ReactiveRefs
from functions.geoportal.v10.basemap import (
    create_base_map, osm_layer, esri_world_imagery_layer,
    ensure_controls, ensure_base_layers,
)
from functions.geoportal.v10.layers import (
    upsert_overlay_by_name, set_layer_opacity,
)
from functions.geoportal.v10.widgets import use_debounce
from functions.geoportal.v10.errors import Toast, use_toast
from functions.geoportal.v10.geojson_loader import load_icon_group_from_geojson
from functions.geoportal.v10.timeseries import resolve_csv_path, read_timeseries, build_plotly_widget, TimeSeriesFigure
from functions.geoportal.v10.center_pivot_loader import build_center_pivot_layer
from functions.geoportal.v10.datepalm_loader import build_datepalms_layer  # NEW
from functions.geoportal.v10.ksa_bounds_loader import build_ksa_bounds_layer
from functions.geoportal.v10.tree_health_loader import build_tree_health_layer, clear_tree_health_highlight
from functions.geoportal.v10.datepalm_province_loader import list_date_palm_provinces


# -------------------------
# small API (health check)
# -------------------------
API_PREFIX = "/api"

@solara_app.get(f"{API_PREFIX}/ping")
def ping():
    return PlainTextResponse("pong")



# -------------------------
# External tiles server base (manual)
# -------------------------
TILES_HTTP_BASE: str = getattr(CFG, "tiles_http_base", "http://127.0.0.1:8766")

PRODUCT_TREE_VEGE = "tree_vege"
PRODUCT_DATEPALM = "datepalm"
PRODUCT_DATEPALM_FIELDS = "datepalm_fields"
PRODUCT_TREE_HEALTH = "tree_health"
PRODUCT_SENSORS = "sensors"
PRODUCT_CENTER_PIVOT = "cpf"

PRODUCT_ORDER = [
    PRODUCT_TREE_HEALTH,
    PRODUCT_SENSORS,
    PRODUCT_CENTER_PIVOT,
    PRODUCT_DATEPALM_FIELDS,
    PRODUCT_DATEPALM,
    PRODUCT_TREE_VEGE,
]

PRODUCT_LABELS = {
    PRODUCT_TREE_VEGE: "Tree–Vege–NonVege Classification",
    PRODUCT_DATEPALM: "Date Palm Fields Qassim Manual",
    PRODUCT_DATEPALM_FIELDS: "Date Palm Fields",
    PRODUCT_TREE_HEALTH: "Tree Health",
    PRODUCT_SENSORS: "Sensors in AlDka",
    PRODUCT_CENTER_PIVOT: "Center-Pivot Fields",
}

PROVINCE_NATIONAL = "__national__"
PROVINCE_LABELS = {
    PROVINCE_NATIONAL: "NATIONAL",
}

PRODUCT_DEFAULT_ZOOM = {
    PRODUCT_TREE_HEALTH: 16,
    PRODUCT_SENSORS: 16,
    PRODUCT_DATEPALM_FIELDS: 6,
}


# -------------------------
# filesystem tile introspection (for UI & fitBounds)
# -------------------------
def _detect_zoom_range(tiles_folder: Path) -> Tuple[Optional[int], Optional[int]]:
    try:
        z_levels = sorted(int(p.name) for p in tiles_folder.iterdir() if p.is_dir() and p.name.isdigit())
    except FileNotFoundError:
        return None, None
    return (z_levels[0], z_levels[-1]) if z_levels else (None, None)

def _detect_extension(tiles_folder: Path) -> Optional[str]:
    for zdir in sorted((p for p in tiles_folder.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name)):
        for xdir in sorted((p for p in zdir.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name)):
            if list(xdir.glob("*.png")) or list(xdir.glob("*.PNG")):
                return "png"
            if list(xdir.glob("*.jpg")) or list(xdir.glob("*.JPG")) or list(xdir.glob("*.jpeg")) or list(xdir.glob("*.JPEG")):
                return "jpg"
    return None

def _leaflet_bounds_from_xyz(tiles_folder: Path, z: int) -> Optional[List[List[float]]]:
    zdir = tiles_folder / str(z)
    if not zdir.exists():
        return None
    xs = sorted(int(p.name) for p in zdir.iterdir() if p.is_dir() and p.name.isdigit())
    if not xs:
        return None
    x_min, x_max = xs[0], xs[-1]
    ys: List[int] = []
    for x in (x_min, x_max):
        xdir = zdir / str(x)
        for pat in ("*.png", "*.PNG", "*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
            ys += [int(p.stem) for p in xdir.glob(pat)]
    if not ys:
        return None
    y_min, y_max = min(ys), max(ys)

    def num2lat(y: int, z: int) -> float:
        n = math.pi - 2.0 * math.pi * y / (2 ** z)
        return math.degrees(math.atan(math.sinh(n)))

    def num2lon(x: int, z: int) -> float:
        return x / (2 ** z) * 360.0 - 180.0

    west  = num2lon(x_min, z)
    east  = num2lon(x_max + 1, z)
    north = num2lat(y_min, z)
    south = num2lat(y_max + 1, z)
    return [[south, west], [north, east]]


def _roi_to_bounds(roi: tuple[float, float, float, float] | None) -> Optional[List[List[float]]]:
    if not roi:
        return None
    south, west, north, east = roi
    return [[south, west], [north, east]]


def _bounds_to_bbox(bounds: List[List[float]] | None) -> Tuple[float, float, float, float] | None:
    if not bounds or len(bounds) != 2:
        return None
    south, west = bounds[0]
    north, east = bounds[1]
    try:
        return float(west), float(south), float(east), float(north)
    except Exception:
        return None


def _vector_layer_id_from_mbtiles(province: str) -> Optional[str]:
    cache_dir = Path(getattr(CFG, "datepalms_tile_cache_dir", ""))
    if not cache_dir or not cache_dir.is_dir():
        return None
    mbtiles = cache_dir / f"{province}.mbtiles"
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


# -------------------------
# Legend: small renderer for the card (outside the map)
# -------------------------
def _legend_inline_row():
    enabled = getattr(CFG, "raster_legend_enabled", True)
    if not enabled:
        return solara.Div()

    items = getattr(CFG, "raster_legend", [])
    title = getattr(CFG, "raster_legend_title", "")

    row_children = []
    if title:
        row_children.append(
            solara.Markdown(
                f"**{title}:**",
                style={"marginRight": "8px", "whiteSpace": "nowrap", "fontSize": "0.95rem"},
            )
        )

    for it in items:
        color_box = solara.Div(
            style={
                "width": "14px",
                "height": "14px",
                "background": it["color"],
                "border": "1px solid #666",
                "borderRadius": "3px",
                "marginRight": "4px",
            }
        )
        label = solara.Markdown(
            f"{it['name']}",
            style={"margin": "0", "fontSize": "0.9rem", "whiteSpace": "nowrap", "marginRight": "10px"},
        )
        row_children.extend([color_box, label])

    return solara.Row(
        children=row_children,
        gap="6px",
        style={"alignItems": "center", "flexWrap": "nowrap"},
    )


def _tree_health_badges():
    healthy_color = getattr(CFG, "tree_health_color_healthy", "#66C2A5")
    infested_color = getattr(CFG, "tree_health_color_infested", "#D1495B")
    healthy_count = getattr(CFG, "tree_health_healthy_count", None)
    infested_count = getattr(CFG, "tree_health_infested_count", None)

    def badge(color: str):
        return solara.Div(
            style={
                "width": "16px",
                "height": "16px",
                "borderRadius": "50%",
                "background": color,
                "border": "1px solid rgba(0,0,0,0.25)",
            }
        )

    return solara.Row(
        children=[
            badge(healthy_color),
            solara.Markdown(
                f"Healthy{f' ({healthy_count})' if healthy_count is not None else ''}",
                style={"margin": "0", "fontSize": "0.9rem"},
            ),
            badge(infested_color),
            solara.Markdown(
                f"Infested{f' ({infested_count})' if infested_count is not None else ''}",
                style={"margin": "0", "fontSize": "0.9rem"},
            ),
        ],
        gap="0.35rem",
        style={"alignItems": "center", "marginTop": "0.6rem"},
    )


def _product_legend(product: str):
    if product == PRODUCT_TREE_VEGE:
        return _legend_inline_row()
    if product == PRODUCT_TREE_HEALTH:
        return _tree_health_badges()
    if product == PRODUCT_DATEPALM_FIELDS:
        return solara.Div()
    if product == PRODUCT_DATEPALM:
        return solara.Markdown(
            "Date Palm Fields Qassim Manual — filled polygons representing Qassim farms, clipped to the current ROI.",
            style={"fontSize": "0.9rem", "color": "#444", "marginTop": "0.5rem"},
        )
    if product == PRODUCT_CENTER_PIVOT:
        return solara.Markdown(
            "Center-Pivot Fields — yearly polygons rendered from the CPF archive.",
            style={"fontSize": "0.9rem", "color": "#444", "marginTop": "0.5rem"},
        )
    if product == PRODUCT_SENSORS:
        icon_color = getattr(CFG, "icon_color_default", "blue")
        return solara.Row(
            children=[
                solara.Div(
                    style={
                        "width": "14px",
                        "height": "14px",
                        "borderRadius": "50%",
                        "background": icon_color,
                        "border": "1px solid rgba(0,0,0,0.25)",
                    }
                ),
                solara.Markdown(
                    "Sensors in AlDka — sensor icon colors follow the configured mapping.",
                    style={"margin": "0", "fontSize": "0.9rem"},
                ),
            ],
            gap="0.35rem",
            style={"alignItems": "center", "marginTop": "0.5rem"},
        )
    return solara.Div()


def _product_summary(product: str):
    if product == PRODUCT_TREE_HEALTH:
        total = getattr(CFG, "tree_health_total_count", None)
        if total is not None:
            return solara.Markdown(
                f"Total number of trees: {total}",
                style={"marginTop": "0.5rem", "fontSize": "0.95rem", "color": "#222"},
            )
    return solara.Div()


# -------------------------
# Main Solara page
# -------------------------
@solara.component
def Page():
    show_toast, hide_toast, toast_state = use_toast()

    # UI state
    geojson_path, set_geojson_path = solara.use_state(str(CFG.default_geojson))
    debounced_geojson = use_debounce(geojson_path, delay_ms=500)
    refs = ReactiveRefs()
    ## turn off the below two line if not showing as page at the bottom of the map window
    #ts_title, set_ts_title = solara.use_state("")
    #ts_df, set_ts_df = solara.use_state(None)

    default_tiles_dir = str(getattr(
        CFG, "default_tiles_dir",
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/38RLQ_2024"
    ))
    raster_dir, set_raster_dir = solara.use_state(default_tiles_dir)
    debounced_raster_dir = use_debounce(raster_dir, delay_ms=350)
    raster_opacity, set_raster_opacity = solara.use_state(float(getattr(CFG, "raster_opacity_default", 0.75)))
    sensor_opacity, set_sensor_opacity = solara.use_state(float(getattr(CFG, "sensor_opacity_default", 1.0)))

    active_product, set_active_product = solara.use_state(None)
    pending_fit_product = solara.use_ref(None)

    # Derived
    tile_ext, set_tile_ext = solara.use_state("png")
    zmin, set_zmin = solara.use_state(None)
    zmax, set_zmax = solara.use_state(None)
    tile_bounds, set_tile_bounds = solara.use_state(None)

    # --- Center-Pivot state ---
    years = list(getattr(CFG, "center_pivot_years", (2021,)))
    year_index_map = {i: y for i, y in enumerate(years)}
    index_by_year = {y: i for i, y in enumerate(years)}

    cp_year_index, set_cp_year_index = solara.use_state(
        index_by_year.get(int(getattr(CFG, "center_pivot_default_year", years[-1])), 0)
    )
    cp_opacity, set_cp_opacity = solara.use_state(0.6)
    cp_use_http, set_cp_use_http = solara.use_state(True)
    cp_clip_roi_enabled, set_cp_clip_roi_enabled = solara.use_state(True)

    cp_layer, set_cp_layer = solara.use_state(None)
    ksa_layer = None
    province_names = solara.use_memo(list_date_palm_provinces, [])
    selected_date_palm_province, set_selected_date_palm_province = solara.use_state(None)
    date_palm_tile_layers, set_date_palm_tile_layers = solara.use_state({})
    # --- Date Palms (Qassim) state ---
    dp_opacity, set_dp_opacity = solara.use_state(float(getattr(CFG, "datepalms_default_opacity", 0.55)))
    dp_layer_full, set_dp_layer_full = solara.use_state(None)
    dp_layer_simple, set_dp_layer_simple = solara.use_state(None)
    dp_active_layer_ref = solara.use_ref(None)

    # --- Tree Health state ---
    th_opacity, set_th_opacity = solara.use_state(float(getattr(CFG, "tree_health_fill_opacity", 0.75)))
    th_layer, set_th_layer = solara.use_state(None)

    # Map & base layers
    m = solara.use_memo(lambda: create_base_map(CFG.map_center, CFG.map_zoom, CFG.map_width, CFG.map_height), [])
    osm = solara.use_memo(osm_layer, [])
    esri = solara.use_memo(esri_world_imagery_layer, [])

    map_debug_attached = solara.use_ref(False)
    current_zoom, set_current_zoom = solara.use_state(getattr(CFG, "map_zoom", 6))

    def _attach_map_debug():
        if map_debug_attached.current:
            return

        def _on_center(change):
            print(f"[MAP center] {change.old} -> {change.new}")

        def _on_zoom(change):
            print(f"[MAP zoom] {change.old} -> {change.new}")

        try:
            m.observe(_on_center, names="center")
            m.observe(_on_zoom, names="zoom")
            map_debug_attached.current = True
        except Exception:
            pass

    solara.use_effect(_attach_map_debug, [])

    def _attach_zoom_listener():
        def _on_zoom(change):
            if change.new is None:
                return
            set_current_zoom(float(change.new))

        try:
            m.observe(_on_zoom, names="zoom")
        except Exception:
            pass

    solara.use_effect(_attach_zoom_listener, [])

    def _tile_url_for_province(province: str) -> str:
        return (
            CFG.datepalms_tile_url_template
            .replace("{base}", CFG.datepalms_tile_base_url)
            .replace("{province}", province)
        )

    def _remove_layer(layer: ipyleaflet.Layer):
        if layer and (layer in m.layers):
            try:
                m.remove_layer(layer)
            except Exception:
                pass

    def _cleanup_date_palm_tile_layers():
        for layer in list(date_palm_tile_layers.values()):
            _remove_layer(layer)
        set_date_palm_tile_layers({})

    def _build_tile_layer(province: str, style_config: dict[str, str]) -> ipyleaflet.VectorTileLayer:
        url = _tile_url_for_province(province)
        print(
            "[DATE PALM TILE] building",
            dict(
                province=province,
                url=url,
            ),
        )
        style_key = _vector_layer_id_from_mbtiles(province) or "*"
        layer = ipyleaflet.VectorTileLayer(
            url=url,
            name=f"{CFG.datepalms_tile_layer_name} ({province})",
            min_zoom=0,
            max_zoom=int(getattr(CFG, "datepalms_tiles_max_zoom", 14)),
            attribution="© local tiles",
            renderer="svg",
            vector_tile_layer_styles={style_key: style_config},
        )
        setattr(layer, "_province", province)
        try:
            layer.style = style_config
        except Exception:
            pass
        return layer

    def _ensure_date_palm_tile_layer():
        should_show = (
            active_product == PRODUCT_DATEPALM_FIELDS
            and selected_date_palm_province
        )
        if not should_show:
            _cleanup_date_palm_tile_layers()
            return

        provinces = (
            list(province_names)
            if selected_date_palm_province == PROVINCE_NATIONAL
            else [selected_date_palm_province]
        )
        if not provinces:
            _cleanup_date_palm_tile_layers()
            return

        anchor: ipyleaflet.Layer | None = cp_layer if (cp_layer and cp_layer in m.layers) else raster_layer
        active_set = {selected_date_palm_province} if selected_date_palm_province != PROVINCE_NATIONAL else set(province_names)

        for province in list(date_palm_tile_layers.keys()):
            if province not in active_set:
                _remove_layer(date_palm_tile_layers.pop(province))

        style_config = {
            "fillColor": getattr(CFG, "datepalms_province_fill_color", "#64ff11"),
            "color": getattr(CFG, "datepalms_province_edge_color", "#5ea700"),
            "weight": float(getattr(CFG, "datepalms_province_edge_weight", 2.0)),
            "fillOpacity": float(getattr(CFG, "datepalms_province_fill_opacity", 0.4)),
        }

        provinces_to_render = province_names if selected_date_palm_province == PROVINCE_NATIONAL else [selected_date_palm_province]
        for province in provinces_to_render:
            layer = date_palm_tile_layers.get(province)
            if layer is None:
                layer = _build_tile_layer(province, style_config)
                date_palm_tile_layers[province] = layer
            if layer not in m.layers:
                _insert_after(layer, anchor)
    solara.use_effect(
        _ensure_date_palm_tile_layer,
        [selected_date_palm_province, active_product],
    )

    def _apply_product_zoom(product: str):
        target = PRODUCT_DEFAULT_ZOOM.get(product)
        if target is None:
            return
        try:
            if getattr(m, "zoom", None) is not None and m.zoom != target:
                m.zoom = target
        except Exception:
            pass

    solara.use_effect(lambda: _apply_product_zoom(active_product), [active_product])

    # ensure controls WITHOUT returning a tuple (keeps LayersControl alive)
    def _init_controls_effect():
        ensure_base_layers(m, osm, esri)
        ensure_controls(m)  # adds LayersControl if missing
    solara.use_effect(_init_controls_effect, [])

    def _ensure_ksa_layer():
        nonlocal ksa_layer
        if ksa_layer and (ksa_layer in m.layers):
            return
        layer, err = build_ksa_bounds_layer(m=m)
        if err:
            show_toast(err, "error")
            return
        ksa_layer = layer
        _insert_after(layer, esri)

    solara.use_effect(_ensure_ksa_layer, [m, esri])

    def _attach_restore_view():
        if getattr(m, "_pending_restore_observer", False):
            return

        def _center_observer(change):
            pending = getattr(m, "_pending_center_restore", None)
            if not pending:
                return
            if change.new is None:
                return
            if tuple(change.new) != tuple(pending):
                setattr(m, "_pending_center_restore", None)
                try:
                    m.center = pending
                except Exception:
                    pass

        def _zoom_observer(change):
            pending_zoom = getattr(m, "_pending_zoom_restore", None)
            if pending_zoom is None:
                return
            if change.new is None:
                return
            if change.new != pending_zoom:
                setattr(m, "_pending_zoom_restore", None)
                try:
                    m.zoom = pending_zoom
                except Exception:
                    pass

        m.observe(_center_observer, names="center")
        m.observe(_zoom_observer, names="zoom")
        m._pending_restore_observer = True

    solara.use_effect(_attach_restore_view, [])

    # ---------- Helper: insert overlay after an anchor layer ----------
    def _insert_after(layer: ipyleaflet.Layer, anchor: ipyleaflet.Layer | None):
        if layer in m.layers:
            return
        if anchor and (anchor in m.layers):
            idx = list(m.layers).index(anchor)
            # add just after the anchor
            # remove+readd to preserve LayersControl registration
            m.add_layer(layer)
            # No tuple reassignments
        else:
            m.add_layer(layer)
    # -----------------------------------------------------------------

    def _fit_bounds(bounds: list | tuple | None):
        if not bounds:
            return
        padding = getattr(CFG, "fit_bounds_padding", (20, 20))
        max_zoom = getattr(CFG, "fit_bounds_max_zoom", 16)
        try:
            try:
                m.fit_bounds(bounds, padding=padding, max_zoom=max_zoom)
            except TypeError:
                m.fit_bounds(bounds)
            except Exception as exc:
                print(f"[DEBUG fit] failed to fit_bounds {bounds}: {exc}")
                return
            try:
                if getattr(m, "zoom", None) is not None and max_zoom is not None and m.zoom > max_zoom:
                    m.zoom = max_zoom
            except Exception:
                pass
        except Exception as exc:
            print(f"[DEBUG fit] failed to fit_bounds {bounds}: {exc}")
        finally:
            try:
                if getattr(m, "zoom", None) is not None and max_zoom is not None and m.zoom > max_zoom:
                    m.zoom = max_zoom
            except Exception:
                pass

    def _request_fit(product: str):
        pending_fit_product.current = product
        refs.did_fit_ref.current = False
        print(f"[DEBUG request_fit] product={product}")

    def _maybe_fit_product(product: str, bounds):
        print(f"[DEBUG fit request] pending={pending_fit_product.current} active={active_product} target={product} bounds_set={bounds is not None}")
        if pending_fit_product.current != product:
            return
        if not bounds:
            return
        _fit_bounds(bounds)
        pending_fit_product.current = None

    def _clear_popups():
        try:
            for layer in list(m.layers):
                if isinstance(layer, ipyleaflet.Popup):
                    m.remove_layer(layer)
        except Exception:
            pass
        for attr in ("_datepalms_highlight_layer", "_cpf_highlight_layer"):
            try:
                existing = getattr(m, attr, None)
                if existing and (existing in m.layers):
                    m.remove_layer(existing)
                setattr(m, attr, None)
            except Exception:
                pass
        refs.active_marker_ref.current = None
        try:
            clear_tree_health_highlight()
        except Exception:
            pass

    def _refresh_cp_layer():
        nonlocal cp_layer
        if cp_layer and (cp_layer in m.layers):
            try:
                m.remove_layer(cp_layer)
            except Exception:
                pass
        cp_layer = None
        set_cp_layer(None)

    def _slider_float(label, value, setter, min_val, max_val, step, width="240px"):
        return solara.Div(
            style={"width": width},
            children=[
                solara.SliderFloat(
                    label=label,
                    value=value,
                    min=min_val,
                    max=max_val,
                    step=step,
                    on_value=setter,
                )
            ]
        )

    def _on_cp_year_change(value):
        _refresh_cp_layer()
        set_cp_year_index(value)

    def _render_cp_year_buttons():
        buttons = []
        for year in years:
            is_active = year_index_map.get(cp_year_index) == year
            btn_style = {
                "minWidth": "62px",
                "padding": "0.35rem 0.65rem",
                "borderRadius": "6px",
                "border": "1px solid #cbd5f5",
                "background": "#0f766e" if is_active else "#f1f5f9",
                "color": "#fff" if is_active else "#0f172a",
                "fontWeight": "600" if is_active else "500",
            }
            buttons.append(
                solara.Button(
                    str(year),
                    text=True,
                    style=btn_style,
                    on_click=lambda _event=None, target=year: (_on_cp_year_change(index_by_year.get(target, 0))),
                )
            )
        return solara.Row(
            children=buttons,
            gap="0.35rem",
            style={
                "flexWrap": "nowrap",
                "alignItems": "center",
                "overflowX": "auto",
                "paddingBottom": "4px",
            },
        )

    def _render_date_palm_province_buttons():
        if not province_names:
            return solara.Markdown(
                "Province GeoPackages missing. Check the datasource directory.",
                style={"fontSize": "0.85rem", "color": "#888"},
            )

        buttons = []
        buttons = []
        all_provinces = list(province_names) + [PROVINCE_NATIONAL]
        for province in all_provinces:
            is_active = selected_date_palm_province == province
            style_button = {
                "minWidth": "190px",
                "padding": "0.45rem 0.85rem",
                "borderRadius": "999px",
                "border": "none",
                "background": "transparent",
                "color": "#0284c7" if is_active else "#0f172a",
                "fontWeight": "600" if is_active else "500",
                "fontSize": "0.9rem",
            }
            label = PROVINCE_LABELS.get(province, province)
            buttons.append(
                solara.Button(
                    label,
                    text=True,
                    style=style_button,
                    on_click=lambda event=None, target=province: _on_date_palm_fields_province_click(target),
                )
            )
        return solara.Div(
            children=buttons,
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(7, minmax(0, 1fr))",
                "gap": "0.7rem",
                "maxWidth": "920px",
            },
        )

    def _on_date_palm_fields_province_click(target: str):
        set_selected_date_palm_province(target)

    def _product_controls(product: str):
        base_style = {"alignItems": "center", "gap": "0.75rem", "flexWrap": "nowrap"}
        if product == PRODUCT_TREE_VEGE:
            return solara.Row(
                gap="0.5rem",
                style=base_style,
                children=[
                    solara.Div(
                        style={"width": "260px"},
                        children=[
                            _slider_float("Opacity", raster_opacity, set_raster_opacity, 0.0, 1.0, 0.01)
                        ],
                    )
                ],
            )
        if product == PRODUCT_DATEPALM_FIELDS:
            return solara.Row(
                gap="0.5rem",
                style={**base_style, "width": "100%"},
                children=[
                    solara.Div(
                        style={"flex": "0 0 70%", "maxWidth": "70%"},
                        children=[
                            solara.Markdown(
                                "Province – select a province to load the fields",
                                style={"marginBottom": "0.35rem", "fontSize": "0.95rem"},
                            ),
                            _render_date_palm_province_buttons(),
                        ],
                    ),
                ],
            )
        if product == PRODUCT_DATEPALM:
            return solara.Row(
                gap="0.5rem",
                style=base_style,
                children=[
                    solara.Div(
                        style={"width": "260px"},
                        children=[
                            _slider_float("Opacity", dp_opacity, set_dp_opacity, 0.1, 1.0, 0.05)
                        ],
                    )
                ],
            )
        if product == PRODUCT_TREE_HEALTH:
            return solara.Row(
                gap="0.5rem",
                style=base_style,
                children=[
                    solara.Div(
                        style={"width": "260px"},
                        children=[
                            _slider_float("Opacity", th_opacity, set_th_opacity, 0.1, 1.0, 0.05)
                        ],
                    )
                ],
            )
        if product == PRODUCT_SENSORS:
            return solara.Row(
                gap="0.5rem",
                style=base_style,
                children=[
                    solara.Div(
                        style={"width": "260px"},
                        children=[
                            _slider_float("Opacity", sensor_opacity, set_sensor_opacity, 0.1, 1.0, 0.05)
                        ],
                    )
                ],
            )
        if product == PRODUCT_CENTER_PIVOT:
            return solara.Row(
                gap="0.75rem",
                style=base_style,
                children=[
                    solara.Div(
                        style={"width": "220px"},
                        children=[
                            solara.Markdown("Year"),
                            _render_cp_year_buttons(),
                        ],
                    ),
                    solara.Div(
                        style={"width": "220px"},
                        children=[
                            _slider_float("Opacity", cp_opacity, set_cp_opacity, 0.1, 1.0, 0.05, width="220px"),
                        ],
                    ),
                ],
            )
        return solara.Div()

    # React to tiles folder changes (used for ext, bounds, fit)
    def _on_tiles_folder_change():
        folder = Path(debounced_raster_dir).resolve()
        if not folder.exists():
            show_toast(f"Tiles folder not found: {folder}", "warning")
            return

        ext = _detect_extension(folder) or "png"
        _zmin, _zmax = _detect_zoom_range(folder)
        bounds = _leaflet_bounds_from_xyz(folder, _zmax) if _zmax is not None else None

        set_tile_ext(ext)
        set_zmin(_zmin)
        set_zmax(_zmax)
        set_tile_bounds(bounds)

        _maybe_fit_product(PRODUCT_TREE_VEGE, bounds)
        if _zmin is not None and m.zoom < _zmin:
            m.zoom = _zmin

        show_toast(f"Tiles ready z∈[{_zmin},{_zmax}] • ext=.{ext}", "success")

    solara.use_effect(_on_tiles_folder_change, [debounced_raster_dir])

    # Raster overlay (single upsert)
    def _build_raster_layer():
        cache_buster = abs(hash(debounced_raster_dir)) % (10**8)
        layer = ipyleaflet.TileLayer(
            url=f"{TILES_HTTP_BASE}/{{z}}/{{x}}/{{y}}.{tile_ext}?v={cache_buster}",
            name=str(getattr(CFG, "raster_layer_name", "Raster")),
            opacity=float(raster_opacity),
            min_zoom=0 if zmin is None else min(0, zmin),
            max_zoom=22 if zmax is None else max(22, zmax),
            no_wrap=True,
            tile_size=256,
            tms=False,  # XYZ
            attribution="© local tiles by Ting Li",
        )
        try:
            layer.z_index = 400
        except Exception:
            pass
        return layer

    raster_layer = solara.use_memo(_build_raster_layer, [debounced_raster_dir, tile_ext, raster_opacity, zmin, zmax])

    def _render_raster_layer():
        if raster_layer is None:
            return
        if active_product == PRODUCT_TREE_VEGE:
            upsert_overlay_by_name(m, raster_layer, below_markers=True)
            _maybe_fit_product(PRODUCT_TREE_VEGE, tile_bounds)
        elif raster_layer in m.layers:
            try:
                m.remove_layer(raster_layer)
            except Exception:
                pass

    solara.use_effect(_render_raster_layer, [m, raster_layer, active_product, tile_bounds])
    solara.use_effect(lambda: (raster_layer and set_layer_opacity(raster_layer, raster_opacity)),
                      [raster_layer, raster_opacity])

    # Markers / popups
    def on_show_timeseries(props: dict):
        #try:
        #    csv_path = resolve_csv_path(props)
        #    df = read_timeseries(csv_path)
        #    title = f"Sensor time series — {props.get('name') or props.get('sensor_id') or props.get('id') or csv_path.stem}"
        #    set_ts_df(df); set_ts_title(title)
        #    show_toast(f"Loaded {csv_path}", "success")
        #    return build_plotly_widget(df, title)
        #except Exception as e:
        #    set_ts_df(None); set_ts_title("")
        #    show_toast(str(e), "error")
        #    return W.HTML(f"<pre>{e}</pre>")
        
        """
        Build a Plotly widget for the clicked sensor and show it ONLY in the popup.
        No more bottom-of-map time series panel.
        """
        try:
            csv_path = resolve_csv_path(props)
            df = read_timeseries(csv_path)
            title = (
                f"Sensor time series — "
                f"{props.get('name') or props.get('sensor_id') or props.get('id') or csv_path.stem}"
            )
            show_toast(f"Loaded {csv_path}", "success")
            # This widget is rendered inside the popup by show_popup()
            return build_plotly_widget(df, title)
        except Exception as e:
            show_toast(str(e), "error")
            return W.HTML(f"<pre>{e}</pre>")

    def _build_group():
        try:
            group, bounds = load_icon_group_from_geojson(Path(debounced_geojson), m, refs.active_marker_ref, on_show_timeseries)
            return group, bounds, None
        except Exception as e:
            return None, None, str(e)

    icon_group, bounds, load_err = solara.use_memo(_build_group, [debounced_geojson])
    solara.use_effect(lambda: show_toast(load_err, "error") if load_err else None, [load_err])

    def _sync_markers():
        if not icon_group:
            return
        print(f"[SYNC MARKERS] active={active_product}")
        if active_product != PRODUCT_SENSORS:
            if icon_group in m.layers:
                try:
                    m.remove_layer(icon_group)
                except Exception:
                    pass
            return

        if icon_group not in m.layers:
            m.add_layer(icon_group)
        _maybe_fit_product(PRODUCT_SENSORS, bounds)

        try:
            if hasattr(icon_group, "z_index"):
                icon_group.z_index = 10_000
        except Exception:
            pass

    solara.use_effect(_sync_markers, [icon_group, bounds, active_product])

    def _apply_sensor_opacity():
        if not icon_group:
            return
        for marker in getattr(icon_group, "layers", []):
            try:
                if sensor_opacity is not None:
                    marker.opacity = float(sensor_opacity)
            except Exception:
                pass

    solara.use_effect(_apply_sensor_opacity, [icon_group, sensor_opacity])

    # -------------------------
    # Center-Pivot build/attach helpers
    # -------------------------
    def _ensure_cp_layer():
        nonlocal cp_layer
        print(f"[CPF] active={active_product} cp_layer_set={cp_layer is not None}")
        target_year = year_index_map.get(cp_year_index)
        existing_year = getattr(cp_layer, "_year", None)
        if cp_layer is not None and existing_year != target_year:
            if cp_layer in m.layers:
                try:
                    m.remove_layer(cp_layer)
                except Exception:
                    pass
            cp_layer = None
            set_cp_layer(None)
        if cp_layer is None:
            clip_bbox = tuple(getattr(CFG, "center_pivot_default_roi", (24.0, 40.0, 28.0, 45.0))) if cp_clip_roi_enabled else None

            layer, err = build_center_pivot_layer(
                year_index_map.get(cp_year_index, years[-1]),
                visible=True,
                use_http_url=bool(cp_use_http and (clip_bbox is None)),
                clip_to_bbox=clip_bbox,
                m=m,
                active_marker_ref=refs.active_marker_ref,
            )
            if err:
                show_toast(err, "error")
                set_cp_layer(None)
                return

            try:
                layer.style = {**(layer.style or {}), "fillOpacity": float(cp_opacity)}
            except Exception:
                pass

            cp_layer = layer
            set_cp_layer(layer)
            setattr(layer, "_year", target_year)

        if cp_layer is None:
            return

        if active_product == PRODUCT_CENTER_PIVOT:
            if cp_layer not in m.layers:
                _insert_after(cp_layer, raster_layer)
            roi_bounds = _roi_to_bounds(getattr(CFG, "center_pivot_default_roi", None))
            _maybe_fit_product(PRODUCT_CENTER_PIVOT, roi_bounds)
        else:
            if cp_layer in m.layers:
                try:
                    m.remove_layer(cp_layer)
                except Exception:
                    pass

    solara.use_effect(
        _ensure_cp_layer,
        [active_product, cp_year_index, cp_opacity, cp_use_http, cp_clip_roi_enabled, raster_layer],
    )

    # -------------------------
    # Date Palm Fields (per province) build/attach helper
    # -------------------------

    def _sync_date_palm_fields_layers():
        def _remove(layer):
            if layer and (layer in m.layers):
                try:
                    m.remove_layer(layer)
                except Exception:
                    pass

        anchor: ipyleaflet.Layer | None = cp_layer if (cp_layer and cp_layer in m.layers) else raster_layer
        if active_product != PRODUCT_DATEPALM_FIELDS or not selected_date_palm_province:
            for layer in date_palm_tile_layers:
                _remove(layer)
            return

        print("[DEBUG date palm sync]", dict(
            active_product=active_product,
            selected_province=selected_date_palm_province,
            current_zoom=current_zoom,
            tile_layers=len(date_palm_tile_layers),
            layers=[type(layer).__name__ for layer in m.layers],
        ))

        for layer in date_palm_tile_layers:
            if layer and layer not in m.layers:
                print("[DEBUG add layer]", dict(
                    anchor_type=type(anchor).__name__ if anchor else None,
                    layers_before=[type(layer).__name__ for layer in m.layers],
                    province=getattr(layer, "_province", None),
                ))
                _insert_after(layer, anchor)
                print("[DEBUG layers after insert]", [type(layer).__name__ for layer in m.layers])

        # National view and per-province view share the same tile color, so no color change is needed.

    solara.use_effect(
        _sync_date_palm_fields_layers,
        [
            active_product,
            selected_date_palm_province,
            cp_layer,
            raster_layer,
            date_palm_tile_layers,
        ],
    )

    # -------------------------
    # Date Palms (Qassim) build/attach helpers
    # -------------------------
    def _ensure_dp_layer():
        nonlocal dp_layer_full, dp_layer_simple
        if not dp_layer_full:
            layer, err = build_datepalms_layer(
                visible=True,
                m=m,
                active_marker_ref=refs.active_marker_ref,
                simplify_tolerance=None,
            )
            if err:
                show_toast(err, "error")
            else:
                try:
                    style_now = dict(getattr(layer, "style", {}) or {})
                    style_now["fillOpacity"] = float(dp_opacity)
                    layer.style = style_now
                except Exception:
                    pass
                set_dp_layer_full(layer)

        if not dp_layer_simple:
            tolerance = getattr(CFG, "datepalms_simplify_tolerance", None)
            if tolerance is not None and tolerance > 0:
                layer, err = build_datepalms_layer(
                    visible=False,
                    m=m,
                    active_marker_ref=refs.active_marker_ref,
                    simplify_tolerance=tolerance,
                )
                if err:
                    show_toast(err, "error")
                else:
                    try:
                        layer.style = {**(getattr(layer, "style", {}) or {}), "opacity": 0.85}
                    except Exception:
                        pass
                    set_dp_layer_simple(layer)
        return

    solara.use_effect(_ensure_dp_layer, [active_product, dp_opacity, cp_layer, raster_layer])

    def _sync_datepalm_display():
        if active_product != PRODUCT_DATEPALM:
            for layer in (dp_layer_full, dp_layer_simple):
                if layer and (layer in m.layers):
                    try:
                        m.remove_layer(layer)
                    except Exception:
                        pass
            return

        anchor = cp_layer if (cp_layer and cp_layer in m.layers) else raster_layer
        desired = dp_layer_simple if (current_zoom <= 14 and dp_layer_simple) else dp_layer_full
        other = dp_layer_full if desired is dp_layer_simple else dp_layer_simple

        if other and (other in m.layers):
            try:
                m.remove_layer(other)
            except Exception:
                pass

        if desired and desired not in m.layers:
            _insert_after(desired, anchor)
        if desired:
            _maybe_fit_product(PRODUCT_DATEPALM, getattr(desired, "_bounds", None))

    solara.use_effect(_sync_datepalm_display, [
        active_product,
        current_zoom,
        dp_layer_full,
        dp_layer_simple,
        cp_layer,
        raster_layer,
    ])

    # -------------------------
    # Tree Health points layer
    # -------------------------
    def _ensure_th_layer():
        nonlocal th_layer
        print(f"[TREE HEALTH] active={active_product} th_layer_set={th_layer is not None}")
        if th_layer is None:
            layer, err = build_tree_health_layer(m=m, active_marker_ref=refs.active_marker_ref, fill_opacity=th_opacity)
            if err:
                show_toast(err, "error")
                set_th_layer(None)
                return
            set_th_layer(layer)

        if th_layer is None:
            return

        for marker in getattr(th_layer, "layers", []):
            try:
                marker.fill_opacity = float(th_opacity)
                marker.opacity = float(th_opacity)
            except Exception:
                pass

        if active_product == PRODUCT_TREE_HEALTH:
            anchor: ipyleaflet.Layer | None = cp_layer if (cp_layer and cp_layer in m.layers) else raster_layer
            for layer in (dp_layer_full, dp_layer_simple):
                if layer and (layer in m.layers):
                    anchor = layer
                    break
            if th_layer not in m.layers:
                _insert_after(th_layer, anchor)
            _maybe_fit_product(PRODUCT_TREE_HEALTH, getattr(th_layer, "_bounds", None))
        else:
            if th_layer in m.layers:
                try:
                    m.remove_layer(th_layer)
                except Exception:
                    pass
            clear_tree_health_highlight()

    solara.use_effect(_ensure_th_layer, [active_product, dp_layer_full, dp_layer_simple, cp_layer, raster_layer, th_opacity])

    # -------------------------
    # Keep sensors on top whenever either overlay (CPF/DP) changes
    # -------------------------
    def _float_sensors_top():
        if active_product != PRODUCT_SENSORS:
            return
        if icon_group and (icon_group in m.layers):
            try:
                m.remove_layer(icon_group)
            except Exception:
                pass
            m.add_layer(icon_group)

    solara.use_effect(_float_sensors_top, [icon_group, cp_layer, dp_layer_full, dp_layer_simple, th_layer, active_product])

    def _select_product(product: str):
        if product == active_product:
            return
        _clear_popups()
        if product != PRODUCT_DATEPALM_FIELDS:
            _request_fit(product)
        set_active_product(product)

    def _product_button_style(product: str):
        active = product == active_product
        base = {
            "borderRadius": "999px",
            "padding": "0.45rem 1.1rem",
            "minWidth": "180px",
            "fontWeight": "600",
            "fontSize": "0.95rem",
            "transition": "background 0.2s ease",
            "cursor": "pointer",
            "margin": "0",
        }
        if active:
            base.update({
                "background": "#0f766e",
                "color": "#f8fafc",
                "border": "1px solid #0f766e",
            })
        else:
            base.update({
                "background": "transparent",
                "color": "#0f172a",
                "border": "1px solid #cbd5f5",
            })
        return base

    with solara.Column(gap="0.75rem"):
        solara.Markdown("### 🌴 Geoportal for Date Palm Field Informatics")

        with solara.Card("", style={"padding": "16px"}):
            solara.Markdown("**Products**", style={"fontSize": "1.15rem"})
            with solara.Row(
                gap="0.5rem",
                style={
                    "flexWrap": "wrap",
                    "alignItems": "stretch",
                },
            ):
                for product in PRODUCT_ORDER:
                    solara.Button(
                        PRODUCT_LABELS.get(product, product),
                        text=True,
                        on_click=lambda event=None, product=product: _select_product(product),
                        style=_product_button_style(product),
                    )
            controls_widget = _product_controls(active_product) if active_product else None
            legend_items = []
            if active_product:
                legend_items.append(
                    solara.Markdown(
                        f"**Active product:** {PRODUCT_LABELS.get(active_product)}",
                        style={"margin": "0", "fontSize": "0.95rem"},
                    )
                )
                legend_extra = _product_legend(active_product)
                if legend_extra:
                    legend_items.append(legend_extra)
            legend_widget = solara.Column(children=legend_items) if legend_items else None
            if legend_widget or controls_widget:
                with solara.Row(
                    gap="1rem",
                    style={
                        "alignItems": "flex-start",
                        "flexWrap": "nowrap",
                        "marginTop": "0.75rem",
                    },
                ):
                    if controls_widget:
                        solara.Div(
                            style={"flex": "0 0 70%", "maxWidth": "70%"},
                            children=[controls_widget],
                        )
                    if legend_widget:
                        solara.Div(
                            style={"flex": "0 0 30%", "maxWidth": "30%"},
                            children=[legend_widget],
                        )
            summary_widget = _product_summary(active_product)
            if summary_widget:
                summary_widget

        solara.display(m)
        ## turn off if not showing the time sereis at the map window bottom
        #if ts_df is not None:
        #    with solara.Column(style={"width": "100%"}):
        #        solara.Markdown(f"**{ts_title}**")
        #        TimeSeriesFigure(ts_df, title=ts_title)
#
        #Toast(message=toast_state["message"], kind=toast_state["kind"], visible=toast_state["visible"], on_close=hide_toast)
        Toast(
            message=toast_state["message"],
            kind=toast_state["kind"],
            visible=toast_state["visible"],
            on_close=hide_toast,
        )

    return
