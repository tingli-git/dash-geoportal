# functions/geoportal/v6/app.py
# source .venv/bin/activate
# cd /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server
# python -m http.server 8766 
from __future__ import annotations
import math
from pathlib import Path
from typing import Optional, Tuple, List

import solara
import ipyleaflet
import ipywidgets as W

from starlette.responses import PlainTextResponse
from solara.server.fastapi import app as solara_app

from functions.geoportal.v6.config import CFG
from functions.geoportal.v6.state import ReactiveRefs
from functions.geoportal.v6.basemap import (
    create_base_map, osm_layer, esri_world_imagery_layer,
    ensure_controls, ensure_base_layers,
)
from functions.geoportal.v6.layers import (
    remove_prior_groups, add_group_and_fit,
    upsert_overlay_by_name, set_layer_visibility, set_layer_opacity,
)
from functions.geoportal.v6.widgets import use_debounce, GeoJSONDrop
from functions.geoportal.v6.errors import Toast, use_toast
from functions.geoportal.v6.geojson_loader import load_icon_group_from_geojson
from functions.geoportal.v6.timeseries import resolve_csv_path, read_timeseries, build_plotly_widget, TimeSeriesFigure
from functions.geoportal.v6.center_pivot_loader import build_center_pivot_layer
from functions.geoportal.v6.datepalm_loader import build_datepalms_layer  # NEW


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

    raster_visible, set_raster_visible = solara.use_state(True)
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
    cp_visible, set_cp_visible = solara.use_state(False)
    cp_opacity, set_cp_opacity = solara.use_state(0.6)

    cp_use_http, set_cp_use_http = solara.use_state(True)
    cp_clip_roi_enabled, set_cp_clip_roi_enabled = solara.use_state(True)

    cp_layer, set_cp_layer = solara.use_state(None)

    # --- Date Palms (Qassim) state ---
    dp_visible, set_dp_visible = solara.use_state(True)
    dp_opacity, set_dp_opacity = solara.use_state(0.55)  # slightly higher default
    dp_layer, set_dp_layer = solara.use_state(None)

    # Map & base layers
    m = solara.use_memo(lambda: create_base_map(CFG.map_center, CFG.map_zoom, CFG.map_width, CFG.map_height), [])
    osm = solara.use_memo(osm_layer, [])
    esri = solara.use_memo(esri_world_imagery_layer, [])

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

        if bounds:
            try:
                m.fit_bounds(bounds, max_zoom=_zmax or getattr(CFG, "fit_bounds_max_zoom", 14))
            except TypeError:
                m.fit_bounds(bounds)
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

    def _attach_raster():
        if raster_layer is None:
            return
        upsert_overlay_by_name(m, raster_layer, below_markers=True)  # inserts above base tiles
    solara.use_effect(_attach_raster, [m, raster_layer])

    # Visibility & opacity for raster
    def _raster_visibility_effect():
        if raster_layer:
            set_layer_visibility(m, raster_layer, raster_visible)
    solara.use_effect(_raster_visibility_effect, [m, raster_layer, raster_visible])
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
        remove_prior_groups(m, keep=icon_group, names_to_prune={CFG.layer_group_name, "Sensor markers", ""})
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
            # add on top (last)
            m.add_layer(icon_group)
    solara.use_effect(_sync_markers, [icon_group, bounds])

    # -------------------------
    # Center-Pivot build/attach helpers
    # -------------------------
    def _ensure_cp_layer():
        nonlocal cp_layer
        if not cp_visible:
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

    solara.use_effect(_ensure_cp_layer, [cp_visible, cp_year_index, cp_opacity, cp_use_http, cp_clip_roi_enabled, raster_layer])

    def _apply_cp_visibility():
        if cp_layer is None:
            return
        if (not cp_visible) and (cp_layer in m.layers):
            try:
                m.remove_layer(cp_layer)
            except Exception:
                pass
    solara.use_effect(_apply_cp_visibility, [cp_visible, cp_layer])

    # -------------------------
    # Date Palms (Qassim) build/attach helpers
    # -------------------------
    def _ensure_dp_layer():
        nonlocal dp_layer
        if not dp_visible:
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
        try:
            dp_bounds = getattr(layer, "_bounds", None)
            if dp_bounds:
                m.fit_bounds(dp_bounds, max_zoom=getattr(CFG, "fit_bounds_max_zoom", 14))
        except Exception:
            pass
        set_dp_layer(layer)
        # Date Palms goes after CPF (and before sensors)
        _insert_after(layer, cp_layer if cp_layer in m.layers else raster_layer)

    solara.use_effect(_ensure_dp_layer, [dp_visible, dp_opacity, cp_layer])

    def _apply_dp_visibility():
        if dp_layer is None:
            return
        if (not dp_visible) and (dp_layer in m.layers):
            try:
                m.remove_layer(dp_layer)
            except Exception:
                pass
    solara.use_effect(_apply_dp_visibility, [dp_visible, dp_layer])

    # -------------------------
    # Keep sensors on top whenever either overlay (CPF/DP) changes
    # -------------------------
    def _float_sensors_top():
        if icon_group and (icon_group in m.layers):
            # remove & re-add to top
            try:
                m.remove_layer(icon_group)
            except Exception:
                pass
            m.add_layer(icon_group)
    solara.use_effect(_float_sensors_top, [icon_group, cp_layer, dp_layer])

    # -------------------------
    # UI
    # -------------------------
    with solara.Column(gap="0.75rem"):
        solara.Markdown("### 🌴 Geoportal for Date Palm Field Informatics")

        with solara.Card("", style={"padding": "12px"}):
            with solara.Row(
                gap="1rem",
                style={
                    "alignItems": "flex-end",
                    "flexWrap": "nowrap",
                    "overflowX": "auto",
                    "whiteSpace": "nowrap",
                },
            ):
                with solara.Column(style={"flex": "1 1 0", "minWidth": "380px"}):
                    solara.Markdown("**Tree–Vege–Bare Classification**")
                    with solara.Row(gap="0.75rem", style={"alignItems": "center", "flexWrap": "nowrap"}):
                        solara.Switch(label="Visible", value=raster_visible, on_value=set_raster_visible)
                        with solara.Div(style={"width": "220px"}):
                            solara.SliderFloat(
                                label="Opacity",
                                value=raster_opacity, min=0.0, max=1.0, step=0.01,
                                on_value=set_raster_opacity,
                            )
                    _legend_inline_row()

                solara.Div(style={"width": "1px", "height": "48px", "background": "#e0e0e0", "margin": "0 6px"})

                with solara.Column(style={"flex": "0 0 auto", "width": "360px"}):
                    solara.Markdown("**Date Palm Fields (Qassim)**")
                    with solara.Row(gap="0.75rem", style={"alignItems": "center", "flexWrap": "nowrap"}):
                        solara.Switch(label="Visible", value=dp_visible, on_value=set_dp_visible)
                        with solara.Div(style={"width": "220px"}):
                            solara.SliderFloat(
                                label="Opacity",
                                value=dp_opacity, min=0.1, max=1.0, step=0.05,
                                on_value=set_dp_opacity,
                            )

                solara.Div(style={"width": "1px", "height": "48px", "background": "#e0e0e0", "margin": "0 6px"})

                with solara.Column(style={"flex": "0 0 auto", "width": "560px"}):
                    solara.Markdown("**Center-Pivot Fields (CPF)**")
                    with solara.Row(gap="0.75rem", style={"alignItems": "center", "flexWrap": "nowrap"}):
                        solara.Switch(label="Visible", value=cp_visible, on_value=set_cp_visible)
                        with solara.Div(style={"width": "360px"}):
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
