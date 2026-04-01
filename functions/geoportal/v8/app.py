# functions/geoportal/v8/app.py
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
# solara run --production /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/functions/geoportal/v8/app.py 
## if solara not founded, run $ hash -r 
# solara application will be running at localhost:8765
# ------------------------------------
# in the third terminal 
# cloudflared tunnel --url http://localhost:8765
# copy the url that can be shared to others
from __future__ import annotations
import math
from pathlib import Path
from typing import Optional, Tuple, List

import solara
import ipyleaflet
import ipywidgets as W

from starlette.responses import PlainTextResponse
from solara.server.fastapi import app as solara_app

from functions.geoportal.v8.config import CFG
from functions.geoportal.v8.state import ReactiveRefs
from functions.geoportal.v8.basemap import (
    create_base_map, osm_layer, esri_world_imagery_layer,
    ensure_controls, ensure_base_layers,
)
from functions.geoportal.v8.layers import (
    remove_prior_groups, add_group_and_fit,
    upsert_overlay_by_name, set_layer_visibility, set_layer_opacity,
)
from functions.geoportal.v8.widgets import use_debounce, GeoJSONDrop
from functions.geoportal.v8.errors import Toast, use_toast
from functions.geoportal.v8.geojson_loader import load_icon_group_from_geojson
from functions.geoportal.v8.timeseries import resolve_csv_path, read_timeseries, build_plotly_widget, TimeSeriesFigure
from functions.geoportal.v8.center_pivot_loader import build_center_pivot_layer
from functions.geoportal.v8.datepalm_loader import build_datepalms_layer  # NEW
from functions.geoportal.v8.tree_health_loader import build_tree_health_layer, clear_tree_health_highlight


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

PRODUCTS: Tuple[Tuple[str, str], ...] = (
    ("raster", "Tree–Vege–NonVege Classification"),
    ("datepalms", "Date Palm Fields (Qassim)"),
    ("tree_health", "Tree Health"),
    ("cpf", "Center-Pivot Fields (CPF)"),
    ("sensors", "Sensors in AlDka"),
)


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
            solara.Markdown(f"**{title}:**", style={"marginRight": "8px", "whiteSpace": "nowrap"})
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
        label = solara.Markdown(f"{it['name']}", style={"marginRight": "12px", "whiteSpace": "nowrap"})
        row_children.extend([color_box, label])

    return solara.Row(children=row_children, gap="4px", style={"alignItems": "center"})


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
    if product == "raster":
        return _legend_inline_row()
    if product == "tree_health":
        return _tree_health_badges()
    if product == "datepalms":
        return solara.Markdown(
            "Date Palm Fields (Qassim) — filled polygons representing Qassim farms.",
            style={"fontSize": "0.9rem", "color": "#444", "marginTop": "0.5rem"},
        )
    if product == "cpf":
        return solara.Markdown(
            "Center-Pivot Fields — polygons clipped via the dataset + optional ROI.",
            style={"fontSize": "0.9rem", "color": "#444", "marginTop": "0.5rem"},
        )
    if product == "sensors":
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
                    "Sensors in AlDka — marker color and icon defined in configuration.",
                    style={"margin": "0", "fontSize": "0.9rem"},
                ),
            ],
            gap="0.35rem",
            style={"alignItems": "center", "marginTop": "0.5rem"},
        )
    return solara.Div()


def _product_summary(product: str):
    if product == "tree_health":
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

    # --- Date Palms (Qassim) state ---
    dp_layer, set_dp_layer = solara.use_state(None)
    dp_opacity = float(getattr(CFG, "datepalms_default_opacity", 0.55))

    # --- Tree Health state ---
    th_layer, set_th_layer = solara.use_state(None)

    active_product, set_active_product = solara.use_state("tree_health")

    # Map & base layers
    m = solara.use_memo(lambda: create_base_map(CFG.map_center, CFG.map_zoom, CFG.map_width, CFG.map_height), [])
    osm = solara.use_memo(osm_layer, [])
    esri = solara.use_memo(esri_world_imagery_layer, [])

    map_debug_attached = solara.use_ref(False)

    def _attach_map_debug():
        if map_debug_attached.current:
            return

        def _on_center_change(_=None):
            try:
                print(f"[DEBUG map] center changed -> {m.center}")
            except Exception as e:
                print(f"[DEBUG map] center change log failed: {e}")

        def _on_zoom_change(_=None):
            try:
                print(f"[DEBUG map] zoom changed -> {m.zoom}")
            except Exception as e:
                print(f"[DEBUG map] zoom change log failed: {e}")

        try:
            m.observe(_on_center_change, names="center")
            m.observe(_on_zoom_change, names="zoom")
            map_debug_attached.current = True
            print("[DEBUG map] observers attached")
        except Exception as e:
            print(f"[DEBUG map] failed to attach observers: {e}")

    solara.use_effect(_attach_map_debug, [])

    # ensure controls WITHOUT returning a tuple (keeps LayersControl alive)
    def _init_controls_effect():
        ensure_base_layers(m, osm, esri)
        ensure_controls(m)  # adds LayersControl if missing
    solara.use_effect(_init_controls_effect, [])

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

    # React to tiles folder changes (used for ext, bounds, fit)
    tiles_fit_done = solara.use_ref(False)
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

        if bounds and not tiles_fit_done.current:
            try:
                print("_on_tiles_folder_change" + (f" bounds={bounds}" if bounds else ""))  # debug
                m.fit_bounds(bounds, max_zoom=_zmax or getattr(CFG, "fit_bounds_max_zoom", 14))
            except TypeError:
                m.fit_bounds(bounds)
            tiles_fit_done.current = True
        if _zmin is not None and m.zoom < _zmin:
            m.zoom = _zmin

        show_toast(f"Tiles ready z∈[{_zmin},{_zmax}] • ext=.{ext}", "success")

    solara.use_effect(_on_tiles_folder_change, [debounced_raster_dir])

    def _reset_active_marker_icon():
        current = refs.active_marker_ref.current
        if current:
            try:
                current.icon = ipyleaflet.AwesomeIcon(
                    name=CFG.icon_name,
                    marker_color=CFG.icon_color_default,
                    icon_color=CFG.icon_icon_color,
                )
            except Exception:
                pass
            refs.active_marker_ref.current = None

    def _remove_all_popups():
        try:
            for layer in list(m.layers):
                if isinstance(layer, ipyleaflet.Popup):
                    m.remove_layer(layer)
        except Exception:
            pass

    def _clear_selection():
        _reset_active_marker_icon()
        _remove_all_popups()
        clear_tree_health_highlight()

    def _select_product(target: str):
        _clear_selection()
        if target == "sensors":
            refs.did_fit_ref.current = False
        if target != active_product:
            set_active_product(target)
            try:
                print(f"[DEBUG select_product] fitting product={target}")
                _fit_product(target)
            except Exception as e:
                print(f"[DEBUG select_product] fit failed for product={target}: {e}")

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

    def _manage_raster_layer():
        if raster_layer is None:
            return
        set_layer_visibility(m, raster_layer, active_product == "raster")
    solara.use_effect(_manage_raster_layer, [m, raster_layer, active_product])
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
            group, bounds = load_icon_group_from_geojson(
                Path(debounced_geojson),
                m,
                refs.active_marker_ref,
                on_show_timeseries,
            )
            return group, bounds, None
        except Exception as e:
            return None, None, str(e)

    icon_group, bounds, load_err = solara.use_memo(_build_group, [debounced_geojson])
    solara.use_effect(lambda: show_toast(load_err, "error") if load_err else None, [load_err])

    def _sync_markers():
        if not icon_group:
            return
        sensors_visible = (active_product == "sensors")
        if sensors_visible:
            remove_prior_groups(m, keep=icon_group, names_to_prune={CFG.layer_group_name, "Sensor markers", ""})
            print(
                "[DEBUG _sync_markers]",
                "active_product=", active_product,
                "sensors_visible=", sensors_visible,
                "did_fit=", refs.did_fit_ref.current,
                "has_bounds=", bool(bounds),
            )
            add_group_and_fit(
                m, icon_group, bounds, refs.did_fit_ref,
                max_zoom=getattr(CFG, "fit_bounds_max_zoom", 14),
                padding=getattr(CFG, "fit_bounds_padding", (20, 20))
            )
            try:
                if hasattr(icon_group, "z_index"):
                    icon_group.z_index = 10_000
            except Exception:
                pass
            if icon_group not in m.layers:
                m.add_layer(icon_group)
        else:
            if icon_group in m.layers:
                try:
                    m.remove_layer(icon_group)
                except Exception:
                    pass
    solara.use_effect(_sync_markers, [icon_group, bounds, active_product])

    # -------------------------
    # Center-Pivot build/attach helpers
    # -------------------------
    def _ensure_cp_layer():
        nonlocal cp_layer
        if active_product != "cpf":
            return

        if cp_layer and (cp_layer in m.layers):
            try:
                m.remove_layer(cp_layer)
            except Exception:
                pass

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

        set_cp_layer(layer)
        # CPF goes after raster
        _insert_after(layer, raster_layer)

    solara.use_effect(_ensure_cp_layer, [active_product, cp_year_index, cp_opacity, cp_use_http, cp_clip_roi_enabled, raster_layer])

    def _apply_cp_visibility():
        if cp_layer is None:
            return
        if active_product != "cpf" and (cp_layer in m.layers):
            try:
                m.remove_layer(cp_layer)
            except Exception:
                pass
    solara.use_effect(_apply_cp_visibility, [active_product, cp_layer])

    # -------------------------
    # Date Palms (Qassim) build/attach helpers
    # -------------------------
    def _ensure_dp_layer():
        nonlocal dp_layer
        if active_product != "datepalms":
            return

        if dp_layer and (dp_layer in m.layers):
            try:
                m.remove_layer(dp_layer)
            except Exception:
                pass

        layer, err = build_datepalms_layer(visible=True, m=m, active_marker_ref=refs.active_marker_ref)
        if err:
            show_toast(err, "error")
            set_dp_layer(None)
            return

        # Increase fillOpacity a bit so it's clearly visible above imagery/rasters
        try:
            style_now = dict(getattr(layer, "style", {}) or {})
            style_now.setdefault("color", "#0B6E4F")
            style_now.setdefault("weight", 2)
            style_now.setdefault("fillColor", "#74C69D")
            style_now["fillOpacity"] = float(dp_opacity)
            layer.style = style_now
        except Exception:
            pass
        
        # Optionally fit to the Date-Palm extent the first time we add it
        set_dp_layer(layer)
        # Date Palms goes after CPF (and before sensors)
        _insert_after(layer, cp_layer if cp_layer in m.layers else raster_layer)

    solara.use_effect(_ensure_dp_layer, [active_product, cp_layer])

    def _apply_dp_visibility():
        if dp_layer is None:
            return
        if active_product != "datepalms" and (dp_layer in m.layers):
            try:
                m.remove_layer(dp_layer)
            except Exception:
                pass
    solara.use_effect(_apply_dp_visibility, [active_product, dp_layer])

    # -------------------------
    # Tree Health points layer
    # -------------------------
    def _ensure_th_layer():
        nonlocal th_layer
        if active_product != "tree_health":
            return

        if th_layer and (th_layer in m.layers):
            try:
                m.remove_layer(th_layer)
            except Exception:
                pass

        layer, err = build_tree_health_layer(
            m=m,
            active_marker_ref=refs.active_marker_ref,
        )
        if err:
            show_toast(err, "error")
            set_th_layer(None)
            return

        set_th_layer(layer)
        anchor = None
        if dp_layer and (dp_layer in m.layers):
            anchor = dp_layer
        elif cp_layer and (cp_layer in m.layers):
            anchor = cp_layer
        else:
            anchor = raster_layer
        _insert_after(layer, anchor)

    solara.use_effect(_ensure_th_layer, [active_product, dp_layer, cp_layer, raster_layer])

    def _apply_th_visibility():
        if th_layer is None:
            return
        if active_product != "tree_health" and (th_layer in m.layers):
            try:
                m.remove_layer(th_layer)
            except Exception:
                pass
    solara.use_effect(_apply_th_visibility, [active_product, th_layer])

    def _fit_product(target: str):
        bounds_to_fit = None
        if target == "raster":
            bounds_to_fit = tile_bounds
        elif target == "datepalms" and dp_layer:
            bounds_to_fit = getattr(dp_layer, "_bounds", None)
        elif target == "tree_health" and th_layer:
            bounds_to_fit = getattr(th_layer, "_bounds", None)
        elif target == "cpf" and cp_layer:
            bounds_to_fit = getattr(cp_layer, "_bounds", None)
        elif target == "sensors":
            bounds_to_fit = bounds

        if not bounds_to_fit:
            return
        target_zoom = getattr(CFG, "product_fit_max_zoom", getattr(CFG, "fit_bounds_max_zoom", 14))
        if target == "tree_health":
            target_zoom = getattr(CFG, "tree_health_fit_max_zoom", target_zoom)
        try:
            print("_fit_product:", target, "bounds?", bool(bounds_to_fit), "zoom", target_zoom)
            m.fit_bounds(bounds_to_fit, max_zoom=target_zoom)
        except TypeError:
            m.fit_bounds(bounds_to_fit)
    # -------------------------
    # Keep sensors on top whenever either overlay (CPF/DP) changes
    # -------------------------
    def _float_sensors_top():
        if active_product != "sensors":
            return
        if icon_group and (icon_group in m.layers):
            # remove & re-add to top
            try:
                m.remove_layer(icon_group)
            except Exception:
                pass
            m.add_layer(icon_group)
    solara.use_effect(_float_sensors_top, [icon_group, cp_layer, dp_layer, th_layer, active_product])

    # -------------------------
    # UI
    # -------------------------
    with solara.Column(gap="0.75rem"):
        solara.Markdown("### 🌴 Geoportal for Date Palm Field Informatics")

        with solara.Card("", style={"padding": "12px"}):
            solara.Markdown("**Products**", style={"fontSize": "1.2rem"})
            def _product_button_style(key: str):
                style = {"textAlign": "left", "fontWeight": "600"}
                if active_product == key:
                    style.update({
                        "background": "#0f766e",
                        "color": "#fff",
                        "border": "1px solid #0f766e",
                        "boxShadow": "0 3px 6px rgba(15,118,110,0.25)",
                    })
                return style
            with solara.Row(
                gap="0.5rem",
                style={
                    "flexWrap": "wrap",
                },
            ):
                for key, label in PRODUCTS:
                    solara.Button(
                        label,
                        button_style="primary" if active_product == key else "secondary",
                        layout=W.Layout(min_width="210px", flex="1 1 200px"),
                        style=_product_button_style(key),
                        on_click=lambda *_args, target=key: _select_product(target),
                    )
            solara.Markdown(
                f"Currently showing: **{dict(PRODUCTS).get(active_product)}**",
                style={"marginTop": "0.5rem", "fontSize": "0.95rem", "color": "#444"},
            )
            legend_widget = _product_legend(active_product)
            if legend_widget:
                legend_widget
            summary_widget = _product_summary(active_product)
            if summary_widget:
                summary_widget

        if active_product == "cpf":
            with solara.Card("", style={"padding": "12px"}):
                solara.Markdown("**Center-Pivot Fields (CPF)**", style={"margin": "0", "fontSize": "1rem"})
                with solara.Row(
                    gap="0.75rem",
                    style={
                        "alignItems": "center",
                        "flexWrap": "wrap",
                    },
                ):
                    with solara.Div(style={"width": "240px"}):
                        solara.SliderInt(
                            label=f"Year: {year_index_map.get(cp_year_index)}",
                            value=cp_year_index, min=0, max=len(years) - 1, step=1,
                            on_value=set_cp_year_index,
                        )
                    with solara.Div(style={"width": "220px"}):
                        solara.SliderFloat(
                            label="Opacity",
                            value=cp_opacity, min=0.1, max=1.0, step=0.05,
                            on_value=set_cp_opacity,
                        )

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
