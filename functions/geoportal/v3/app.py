# functions/geoportal/v3/app.py
from __future__ import annotations
import math
from pathlib import Path
import solara
import ipyleaflet

from functions.geoportal.v3.config import CFG
from functions.geoportal.v3.state import ReactiveRefs
from functions.geoportal.v3.basemap import (
    create_base_map, osm_layer, esri_world_imagery_layer, ensure_controls, ensure_base_layers
)
from functions.geoportal.v3.layers import (
    remove_prior_groups, add_group_and_fit,
    upsert_overlay_by_name, set_layer_visibility, set_layer_opacity
)
from functions.geoportal.v3.widgets import use_debounce, GeoJSONDrop
from functions.geoportal.v3.errors import Toast, use_toast
from functions.geoportal.v3.geojson_loader import load_icon_group_from_geojson
from functions.geoportal.v3.timeseries import resolve_csv_path, read_timeseries, build_plotly_widget, TimeSeriesFigure
import ipywidgets as W

from starlette.staticfiles import StaticFiles
from solara.server.app import app as starlette_app

# The actual pyramid folder (your XYZ root)
PYRAMID_DIR = Path(CFG.default_tiles_dir).resolve()
assert PYRAMID_DIR.exists(), f"Tiles dir not found: {PYRAMID_DIR}"

# Mount this exact folder as `/tiles`
MOUNT_POINT = "/tiles"
starlette_app.mount(MOUNT_POINT, StaticFiles(directory=str(PYRAMID_DIR), html=False), name="tiles")



# ---------- helpers to inspect a local XYZ tile pyramid ----------
def _detect_zoom_range(tiles_folder: Path):
    z_levels = sorted(int(p.name) for p in tiles_folder.iterdir() if p.is_dir() and p.name.isdigit())
    if not z_levels:
        return None, None
    return z_levels[0], z_levels[-1]

def _tiles_xyz_bounds(tiles_folder: Path, z: int):
    """Return Leaflet bounds [[south, west], [north, east]] by scanning x/y at zoom z."""
    zdir = tiles_folder / str(z)
    if not zdir.exists():
        return None
    xs = sorted(int(p.name) for p in zdir.iterdir() if p.is_dir() and p.name.isdigit())
    if not xs:
        return None
    x_min, x_max = xs[0], xs[-1]

    ys = []
    for x in (x_min, x_max):
        xdir = zdir / str(x)
        ys_x = [int(p.stem) for p in xdir.glob("*.png")]
        if ys_x:
            ys.extend(ys_x)
    if not ys:
        ys = [int(p.stem) for p in (zdir / str(x_min)).glob("*.png")]
        if not ys:
            return None
    y_min, y_max = min(ys), max(ys)

    def num2lat(y, z):
        n = math.pi - 2.0 * math.pi * y / (2 ** z)
        return math.degrees(math.atan(math.sinh(n)))
    def num2lon(x, z):
        return x / (2 ** z) * 360.0 - 180.0

    west  = num2lon(x_min, z)
    east  = num2lon(x_max + 1, z)
    north = num2lat(y_min, z)
    south = num2lat(y_max + 1, z)
    return [[south, west], [north, east]]

def _sample_tile_path(tiles_folder: Path):
    for zdir in sorted([p for p in tiles_folder.iterdir() if p.is_dir() and p.name.isdigit()]):
        xs = sorted([p for p in zdir.iterdir() if p.is_dir() and p.name.isdigit()])
        if not xs:
            continue
        for xdir in (xs[0], xs[-1]):
            ys = sorted(list(xdir.glob("*.png")))
            if ys:
                return ys[0]
    return None


@solara.component
def Page():
    show_toast, hide_toast, toast_state = use_toast()

    # ---------- UI STATE ----------
    geojson_path, set_geojson_path = solara.use_state(str(CFG.default_geojson))
    debounced_path = use_debounce(geojson_path, delay_ms=500)
    refs = ReactiveRefs()

    ts_title, set_ts_title = solara.use_state("")
    ts_df, set_ts_df = solara.use_state(None)

    # Tiles folder default (your real path as fallback if CFG doesn't define it)
    fallback_tiles = "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/tile_rasters/38RLQ_2024"
    default_tiles_dir = str(getattr(CFG, "default_tiles_dir", fallback_tiles))
    default_raster_name = str(getattr(CFG, "raster_layer_name", "Tree-Vege-Nonveg classification"))
    default_raster_opacity = float(getattr(CFG, "raster_opacity_default", 0.75))

    raster_dir, set_raster_dir = solara.use_state(default_tiles_dir)
    raster_visible, set_raster_visible = solara.use_state(True)
    raster_opacity, set_raster_opacity = solara.use_state(default_raster_opacity)
    raster_tms, set_raster_tms = solara.use_state(False)  # you used --xyz ⇒ keep False
    debounced_raster_dir = use_debounce(raster_dir, delay_ms=400)

    # ---------- MAP & BASE LAYERS ----------
    m = solara.use_memo(lambda: create_base_map(CFG.map_center, CFG.map_zoom, CFG.map_width, CFG.map_height), [])
    osm = solara.use_memo(osm_layer, [])
    esri = solara.use_memo(esri_world_imagery_layer, [])
    solara.use_effect(lambda: (ensure_base_layers(m, osm, esri), ensure_controls(m)), [])

    # ---------- RASTER OVERLAY ----------
    def _make_raster_layer():
        folder = Path(debounced_raster_dir)
        if not folder.exists():
            return None, None, None, None, f"Tiles folder not found: {folder}"

        zmin, zmax = _detect_zoom_range(folder)
        if zmin is None:
            return None, None, None, None, f"No zoom levels found in: {folder}"

        # compute bounds (Leaflet expects [ [south, west], [north, east] ])
        bounds_latlon = _tiles_xyz_bounds(folder, zmax)
        sample = _sample_tile_path(folder)
        if sample is None or not sample.exists():
            return None, zmin, zmax, bounds_latlon, f"No PNG tiles found under: {folder}"

        try:
            layer = ipyleaflet.TileLayer(
            url=f"{MOUNT_POINT}/{{z}}/{{x}}/{{y}}.png",
            name=default_raster_name,
            opacity=float(raster_opacity),
            min_zoom=zmin,
            max_zoom=zmax,
            no_wrap=True,
            tile_size=256,
            tms=bool(raster_tms),   # keep False for XYZ; True only if your Y is flipped (TMS)
            attribution="© your data",
            )
            try:
                layer.z_index = 400
            except Exception:
                pass

            show_toast(f"Tiles ready z∈[{zmin},{zmax}] • sample: {sample}", "success")
            return layer, zmin, zmax, bounds_latlon, None
        except Exception as e:
            return None, zmin, zmax, bounds_latlon, f"Failed to create raster layer: {e}"


    raster_layer, zmin, zmax, tile_bounds, raster_err = solara.use_memo(
        _make_raster_layer, [debounced_raster_dir, raster_tms]
    )

    # Attach/replace below markers
    solara.use_effect(lambda: (raster_layer and upsert_overlay_by_name(m, raster_layer, below_markers=True)),
                      [m, raster_layer])

    # Visibility & opacity reactive
    solara.use_effect(lambda: (raster_layer and set_layer_visibility(m, raster_layer, raster_visible)),
                      [m, raster_layer, raster_visible])
    solara.use_effect(lambda: (raster_layer and set_layer_opacity(raster_layer, raster_opacity)),
                      [raster_layer, raster_opacity])

    # Errors / warnings
    solara.use_effect(lambda: show_toast(raster_err, "warning") if raster_err else None, [raster_err])

    # Auto-fit to tile bounds once; warn if zoomed out below zmin
    def _fit_and_warn():
        if not raster_layer:
            return
        if tile_bounds:
            try:
                m.fit_bounds(tile_bounds, max_zoom=zmax or CFG.fit_bounds_max_zoom)
            except TypeError:
                m.fit_bounds(tile_bounds)
            if zmin is not None and m.zoom < zmin:
                m.zoom = zmin
        if zmin is not None and m.zoom < zmin:
            show_toast(f"Zoom in to at least z={zmin} to see tiles.", "info")
    solara.use_effect(_fit_and_warn, [raster_layer, tile_bounds, m.zoom, zmin, zmax])

    # ---------- MARKERS / POPUPS ----------
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
            group, bounds = load_icon_group_from_geojson(Path(debounced_path), m, refs.active_marker_ref, on_show_timeseries)
            return group, bounds, None
        except Exception as e:
            return None, None, str(e)

    icon_group, bounds, load_err = solara.use_memo(_build_group, [debounced_path])
    solara.use_effect(lambda: setattr(refs.did_fit_ref, "current", False), [debounced_path])
    solara.use_effect(lambda: show_toast(load_err, "error") if load_err else None, [load_err])

    def _sync_markers():
        if not icon_group:
            return
        remove_prior_groups(m, keep=icon_group, names_to_prune={CFG.layer_group_name, "Sensor markers", ""})
        add_group_and_fit(m, icon_group, bounds, refs.did_fit_ref,
                          max_zoom=CFG.fit_bounds_max_zoom, padding=CFG.fit_bounds_padding)
    solara.use_effect(_sync_markers, [icon_group, bounds])

    # ---------- UI ----------
    with solara.Column(gap="0.75rem"):
        solara.Markdown("### 🌴 Geoportal for Date Palm Field Informatics")

        # GeoJSON controls
        with solara.Row(gap="0.75rem", style={"align-items": "flex-end"}):
            solara.InputText(label="GeoJSON path:", value=geojson_path, on_value=set_geojson_path, continuous_update=True)
        GeoJSONDrop(on_saved_path=set_geojson_path, label="...or drag & drop a .geojson to use it")

        # Raster overlay controls
        with solara.Card("Raster overlay (XYZ)"):
            with solara.Row(gap="0.75rem", style={"align-items": "center"}):
                solara.InputText(
                    label="Tiles folder (…/z/x/y.png)",
                    value=raster_dir, on_value=set_raster_dir, continuous_update=True,
                    style={"minWidth": "520px"}
                )
                solara.Switch(label="Visible", value=raster_visible, on_value=set_raster_visible)
                solara.Switch(label="TMS (flip Y)", value=raster_tms, on_value=set_raster_tms)
                with solara.Div(style={"width": "240px"}):
                    solara.SliderFloat(
                        label="Opacity",
                        value=raster_opacity,
                        min=0.0, max=1.0, step=0.01,
                        on_value=set_raster_opacity,
                    )

        # Map
        solara.display(m)

        # Optional timeseries panel
        if ts_df is not None:
            with solara.Column(style={"width": "100%"}):
                solara.Markdown(f"**{ts_title}**")
                TimeSeriesFigure(ts_df, title=ts_title)

        Toast(message=toast_state["message"], kind=toast_state["kind"], visible=toast_state["visible"], on_close=hide_toast)

    return
