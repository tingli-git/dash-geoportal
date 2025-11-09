# functions/geoportal/v3/app.py
from __future__ import annotations
import math
from pathlib import Path
from typing import Optional, Tuple, List

import solara
import ipyleaflet
import ipywidgets as W

from starlette.responses import PlainTextResponse
from solara.server.fastapi import app as solara_app

from functions.geoportal.v3.config import CFG
from functions.geoportal.v3.state import ReactiveRefs
from functions.geoportal.v3.basemap import (
    create_base_map, osm_layer, esri_world_imagery_layer,
    ensure_controls, ensure_base_layers,
)
from functions.geoportal.v3.layers import (
    remove_prior_groups, add_group_and_fit,
    upsert_overlay_by_name, set_layer_visibility, set_layer_opacity,
)
from functions.geoportal.v3.widgets import use_debounce, GeoJSONDrop
from functions.geoportal.v3.errors import Toast, use_toast
from functions.geoportal.v3.geojson_loader import load_icon_group_from_geojson
from functions.geoportal.v3.timeseries import resolve_csv_path, read_timeseries, build_plotly_widget, TimeSeriesFigure


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
# Set CFG.tiles_http_base in your config.py, e.g. "http://127.0.0.1:8766"
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

    # title (small inline)
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
        label = solara.Markdown(
            f"{it['name']}",
            style={"marginRight": "12px", "whiteSpace": "nowrap"}
        )
        row_children.extend([color_box, label])

    return solara.Row(
        children=row_children,
        gap="4px",
        style={"alignItems": "center"}
    )



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

    ts_title, set_ts_title = solara.use_state("")
    ts_df, set_ts_df = solara.use_state(None)

    default_tiles_dir = str(getattr(
        CFG, "default_tiles_dir",
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/tile_rasters/38RLQ_2024"
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

    # Map & base layers
    m = solara.use_memo(lambda: create_base_map(CFG.map_center, CFG.map_zoom, CFG.map_width, CFG.map_height), [])
    osm = solara.use_memo(osm_layer, [])
    esri = solara.use_memo(esri_world_imagery_layer, [])
    solara.use_effect(lambda: (ensure_base_layers(m, osm, esri), ensure_controls(m)), [])

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
            tms=False,  # TMS (flip Y) removed; using XYZ only
            attribution="© local tiles",
        )
        try:
            layer.z_index = 400
        except Exception:
            pass
        return layer

    raster_layer = solara.use_memo(
        _build_raster_layer,
        [debounced_raster_dir, tile_ext, raster_opacity, zmin, zmax]
    )

    def _attach_layer():
        if raster_layer is None:
            return
        upsert_overlay_by_name(m, raster_layer, below_markers=True)
        m.layers = list(m.layers)

    solara.use_effect(_attach_layer, [m, raster_layer])

    # Visibility & opacity
    solara.use_effect(lambda: (raster_layer and set_layer_visibility(m, raster_layer, raster_visible)),
                      [m, raster_layer, raster_visible])
    solara.use_effect(lambda: (raster_layer and set_layer_opacity(raster_layer, raster_opacity)),
                      [raster_layer, raster_opacity])

    # Markers / popups
    def on_show_timeseries(props: dict):
        try:
            csv_path = resolve_csv_path(props)
            df = read_timeseries(csv_path)
            title = f"Sensor time series — {props.get('name') or props.get('sensor_id') or props.get('id') or csv_path.stem}"
            set_ts_df(df); set_ts_title(title)
            show_toast(f"Loaded {csv_path}", "success")
            return build_plotly_widget(df, title)
        except Exception as e:
            set_ts_df(None); set_ts_title("")
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
        # keep sensors on top
        try:
            if hasattr(icon_group, "z_index"):
                icon_group.z_index = 10_000
        except Exception:
            pass
        layers = [ly for ly in m.layers if ly is not icon_group]
        layers.append(icon_group)
        m.layers = layers

    # keep sensors on top after any raster change
    solara.use_effect(_sync_markers, [icon_group, bounds, raster_layer, raster_visible, raster_opacity])

    # -------------------------
    # UI
    # -------------------------
    with solara.Column(gap="0.75rem"):
        solara.Markdown("### 🌴 Geoportal for Date Palm Field Informatics")

        # GeoJSON controls
        with solara.Row(gap="0.75rem", style={"align-items": "flex-end"}):
            solara.InputText(label="GeoJSON path:", value=geojson_path, on_value=set_geojson_path, continuous_update=True)
        GeoJSONDrop(on_saved_path=set_geojson_path, label="...or drag & drop a .geojson to use it")

        # Raster overlay controls + Legend (outside the map)
        with solara.Card("Tree-Vege-Bare Classification", style={"padding": "10px"}):
            with solara.Row(gap="0.75rem", style={"alignItems": "center", "flexWrap": "wrap"}):
                #solara.InputText(
                #    label="Tiles folder (…/z/x/y.{png|jpg})",
                #    value=raster_dir, on_value=set_raster_dir, continuous_update=True,
                #    style={"minWidth": "520px"}
                #)
                solara.Switch(label="Visible", value=raster_visible, on_value=set_raster_visible)
                with solara.Div(style={"width": "220px"}):
                    solara.SliderFloat(
                        label="Opacity",
                        value=raster_opacity,
                        min=0.0, max=1.0, step=0.01,
                        on_value=set_raster_opacity,
                    )

                # 👉 INLINE LEGEND
                _legend_inline_row()

        # Map
        solara.display(m)

        # Optional timeseries panel
        if ts_df is not None:
            with solara.Column(style={"width": "100%"}):
                solara.Markdown(f"**{ts_title}**")
                TimeSeriesFigure(ts_df, title=ts_title)

        Toast(message=toast_state["message"], kind=toast_state["kind"], visible=toast_state["visible"], on_close=hide_toast)

    return
