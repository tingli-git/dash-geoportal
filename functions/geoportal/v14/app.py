# functions/geoportal/v14/app.py
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
"""
unset DATEPALMS_PROVINCE_HTTP_BASE
unset DATEPALMS_HTTP_BASE
unset DATEPALMS_HTTP_URL
unset DATEPALMS_TILE_BASE_URL
unset RASTER_TILES_HTTP_BASE
unset CENTER_PIVOT_HTTP_BASE
unset KSA_BOUNDS_HTTP_URL
export GEOPORTAL_AUTH_USERNAME=ksa_palmdash
export GEOPORTAL_AUTH_PASSWORD='kaust_palms!1'
"""
# solara run --production /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/functions/geoportal/v14/app.py 
## if solara not founded, run $ hash -r 
# solara application will be running at localhost:8765
# ------------------------------------
# in the third terminal 
# 

# cloudflared tunnel --url http://localhost:8765
# copy the url that can be shared to others
from __future__ import annotations
import json
import math
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple, List, Sequence
from urllib.parse import urlparse
from urllib.request import urlretrieve

import geopandas as gpd
import solara
import ipyleaflet
import ipywidgets as W
from fastapi import FastAPI

from starlette.responses import PlainTextResponse, Response
from solara.server.fastapi import app as solara_app
from solara.server import server as solara_server

from functions.geoportal.v14.config import CFG
from functions.geoportal.v14.state import ReactiveRefs
from functions.geoportal.v14.basemap import (
    create_base_map, osm_layer, esri_world_imagery_layer,
    ensure_controls, ensure_base_layers,
)
from functions.geoportal.v14.layers import (
    upsert_overlay_by_name, set_layer_opacity,
)
from functions.geoportal.v14.widgets import use_debounce
from functions.geoportal.v14.errors import Toast, use_toast
from functions.geoportal.v14.geojson_loader import load_icon_group_from_geojson
from functions.geoportal.v14.timeseries import resolve_csv_path, read_timeseries, build_plotly_widget
from functions.geoportal.v14.center_pivot_loader import build_center_pivot_layer
from shapely.geometry import mapping, box

from functions.geoportal.v14.datepalm_loader import build_datepalms_layer  # NEW
from functions.geoportal.v14.ksa_bounds_loader import build_ksa_bounds_layer
from functions.geoportal.v14.tree_health_loader import build_tree_health_layer, clear_tree_health_highlight
from functions.geoportal.v14.datepalm_province_loader import list_date_palm_provinces
from functions.geoportal.v14.field_density_loader import build_field_density_layer
from functions.geoportal.v14.lookup import FieldLookup
from functions.geoportal.v14.popups import show_popup, show_date_palm_field_province_badge, clear_tree_health_badge, clear_sensor_badges
from functions.geoportal.v14.utils import html_table_popup
from functions.geoportal.v14.cloud_assets import asset_url_for, ensure_local_asset, ensure_local_directory, read_asset_bytes, guess_content_type, gcs_enabled, force_gcs_enabled, set_force_gcs, last_fetch_info

_GPKG_TEMP_DIR = Path(tempfile.gettempdir()) / "geoportal_datepalm"
_GPKG_TEMP_DIR.mkdir(parents=True, exist_ok=True)
IS_PRODUCTION = getattr(CFG, "app_mode", "development") == "production"
_APP_SERVER_ROOT = getattr(CFG, "app_server_root", CFG.top_dir / "Datepalm" / "app_server")
_ORIGINAL_ASSET_DIRECTORIES = solara_server.asset_directories
_AUTH_IDLE_TIMEOUT_SECONDS = 60 * 60
_AUTH_SESSIONS: dict[str, float] = {}


def _asset_directories_with_app_server():
    directories = list(_ORIGINAL_ASSET_DIRECTORIES())
    if _APP_SERVER_ROOT not in directories:
        directories.insert(0, _APP_SERVER_ROOT)
    return directories


# Local mode depends on Solara serving files from app_server under /static/assets.
# Keep that mount available in all modes so the UI toggle can genuinely switch
# between local browser URLs and public/GCS browser URLs.
solara_server.asset_directories = _asset_directories_with_app_server


# -------------------------
# small API (health check)
# -------------------------
API_PREFIX = "/api"
backend_api = FastAPI()
GCS_ASSET_PROXY_PREFIX = "/gcs-assets"

@backend_api.get("/ping")
def ping():
    return PlainTextResponse("pong")


@backend_api.get("/assets/{asset_path:path}")
def serve_asset(asset_path: str):
    try:
        data = read_asset_bytes(asset_path)
    except Exception as exc:
        return PlainTextResponse(f"Not found: {asset_path} ({exc})", status_code=404)

    media_type = guess_content_type(asset_path)
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=3600",
    }
    return Response(data, media_type=media_type, headers=headers)


@solara_app.get(GCS_ASSET_PROXY_PREFIX + "/{asset_path:path}")
def serve_gcs_asset(asset_path: str):
    previous = force_gcs_enabled()
    try:
        set_force_gcs(True)
        data = read_asset_bytes(asset_path)
    except Exception as exc:
        return PlainTextResponse(f"Not found: {asset_path} ({exc})", status_code=404)
    finally:
        set_force_gcs(previous)

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=3600",
        "X-Geoportal-Route": "gcs-assets",
        "X-Geoportal-Asset-Path": asset_path,
        "X-Geoportal-Mode": "force-gcs",
    }
    media_type = guess_content_type(asset_path)
    return Response(data, media_type=media_type, headers=headers)

solara_app.mount(API_PREFIX, backend_api)


def _prioritize_api_mount() -> None:
    try:
        routes = list(solara_app.router.routes)
        front_paths = {
            API_PREFIX,
            GCS_ASSET_PROXY_PREFIX + "/{asset_path:path}",
        }
        priority_routes = [route for route in routes if getattr(route, "path", None) in front_paths]
        if not priority_routes:
            return
        remaining = [route for route in routes if getattr(route, "path", None) not in front_paths]
        solara_app.router.routes[:] = priority_routes + remaining
    except Exception:
        pass


_prioritize_api_mount()


# -------------------------
# External tiles server base (manual)
# -------------------------
TILES_HTTP_BASE: str = getattr(CFG, "tiles_http_base", "/static/assets/38RLQ_2024")

PRODUCT_TREE_VEGE = "tree_vege"
PRODUCT_DATEPALM = "datepalm"
PRODUCT_DATEPALM_FIELDS = "datepalm_fields"
PRODUCT_FIELD_DENSITY = "field_density"
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
    PRODUCT_TREE_VEGE: "Tree / Vege / Non-Vege CLASSIFICATION",
    PRODUCT_DATEPALM: "Qassim Manual Date Palm Fields",
    PRODUCT_DATEPALM_FIELDS: "Date Palm Fields",
    PRODUCT_FIELD_DENSITY: "Field Density",
    PRODUCT_TREE_HEALTH: "Tree Health",
    PRODUCT_SENSORS: "Sensors in AlDka",
    PRODUCT_CENTER_PIVOT: "Center-Pivot Fields",
}
PRODUCT_SHORT_LABELS = {
    PRODUCT_TREE_VEGE: "Tree / Vege / Non-Vege",
    PRODUCT_DATEPALM: "Qassim Manual Fields",
    PRODUCT_DATEPALM_FIELDS: "Date Palm Fields",
    PRODUCT_FIELD_DENSITY: "Field Density",
    PRODUCT_TREE_HEALTH: "Tree Health",
    PRODUCT_SENSORS: "Sensors",
    PRODUCT_CENTER_PIVOT: "Center-Pivot",
}

PROVINCE_NATIONAL = "__national__"
PROVINCE_LABELS = {
    PROVINCE_NATIONAL: "NATIONAL",
    "AL_BAHA": "Al Baha",
    "AL_JAWF": "Al Jawf",
    "AL_MADINAH": "Al Madinah",
    "AL_QUASSIM": "Al Quassim",

    "EASTERN_PROVINCE": "Eastern Province",
    "NORTHERN_BORDERS": "Northern Borders",
}

PRODUCT_DEFAULT_ZOOM = {
    PRODUCT_TREE_HEALTH: 16,
    PRODUCT_SENSORS: 16,
    PRODUCT_DATEPALM_FIELDS: 6,
    PRODUCT_FIELD_DENSITY: 6,
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


def _center_from_bounds(bounds: List[List[float]] | None) -> Tuple[float, float] | None:
    bbox = _bounds_to_bbox(bounds)
    if not bbox:
        return None
    west, south, east, north = bbox
    return ((south + north) / 2.0, (west + east) / 2.0)


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
                style={"marginRight": "8px", "whiteSpace": "nowrap", "fontSize": "var(--font-body)"},
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
            style={"margin": "0", "fontSize": "var(--font-body)", "whiteSpace": "nowrap", "marginRight": "10px"},
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
                style={"margin": "0", "fontSize": "var(--font-body)"},
            ),
            badge(infested_color),
            solara.Markdown(
                f"Infested{f' ({infested_count})' if infested_count is not None else ''}",
                style={"margin": "0", "fontSize": "var(--font-body)"},
            ),
        ],
        gap="0.35rem",
        style={"alignItems": "center", "marginTop": "0.6rem"},
    )


def _tree_health_legend_widget():
    healthy_color = str(getattr(CFG, "tree_health_color_healthy", "#66C2A5"))
    infested_color = str(getattr(CFG, "tree_health_color_infested", "#D1495B"))
    healthy_count = getattr(CFG, "tree_health_healthy_count", None)
    infested_count = getattr(CFG, "tree_health_infested_count", None)
    total_count = getattr(CFG, "tree_health_total_count", None)

    healthy_label = f"Healthy{f' ({healthy_count})' if healthy_count is not None else ''}"
    infested_label = f"Infested{f' ({infested_count})' if infested_count is not None else ''}"

    html = f"""
    <div style="
        margin-top: 0px;
        background: rgba(255,255,255,0.40);
        backdrop-filter: blur(6px);
        border: 1px solid rgba(148,163,184,0.4);
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(15,23,42,0.12);
        padding: 12px 14px;
        min-width: 190px;
        display: inline-block;
    ">
        <div style="font-size:var(--font-section-title);font-weight:700;color:#0f172a;line-height:1.35;">
            Tree Health
        </div>

        <div style="display:flex;align-items:center;gap:8px;margin-top:8px;">
            <span style="width:16px;height:16px;border-radius:999px;border:1px solid rgba(15,23,42,0.18);background:{healthy_color};display:inline-block;"></span>
            <span style="font-size:var(--font-body);color:#0f172a;">{healthy_label}</span>
        </div>

        <div style="display:flex;align-items:center;gap:8px;margin-top:6px;">
            <span style="width:16px;height:16px;border-radius:999px;border:1px solid rgba(15,23,42,0.18);background:{infested_color};display:inline-block;"></span>
            <span style="fontSize: var(--font-body);color:#0f172a;">{infested_label}</span>
        </div>

        {f'<div style="fontSize: var(--font-body);font-weight:600;color:#0f172a;margin-top:10px;">Total number of trees: {total_count}</div>' if total_count is not None else ''}
    </div>
    """

    panel = W.Box(
        [W.HTML(value=html)],
        layout=W.Layout(padding="0", margin="0")
    )
    panel.add_class("tree-health-legend-panel")
    return panel


def _field_density_legend_widget() -> W.HTML:
    rows = []
    for item in getattr(CFG, "field_density_legend", []):
        color = str(item.get("color", "#000000"))
        label = str(item.get("label", ""))
        rows.append(
            (
                "<div style='display:flex;align-items:center;gap:8px;margin-top:6px;'>"
                f"<span style='width:16px;height:16px;border-radius:4px;border:1px solid rgba(15,23,42,0.18);background:{color};display:inline-block;'></span>"
                f"<span style='fontSize: var(--font-small);color:#0f172a;'>{label}</span>"
                "</div>"
            )
        )
    title = str(getattr(CFG, "field_density_legend_title", "Field density"))
    html = (
        #"<div style='padding-top:180px;background:transparent;'>"
        "<div style='margin-top:1px;background:rgba(255,255,255,0.4);backdrop-filter: blur(6px);border:1px solid rgba(148,163,184,0.4);"
        "border-radius:12px;box-shadow:0 10px 28px rgba(15,23,42,0.14);padding:12px 14px;min-width:190px;display:inline-block;'>"
        f"<div style='fontSize: var(--font-section-title);font-weight:700;color:#0f172a;line-height:1.35;'>{title}</div>"
        #"<div style='font-size:11px;color:#475569;margin-top:4px;'>0 values remain transparent.</div>"
        f"{''.join(rows)}</div>"
        "</div>"
    )
    panel = W.Box(
    [W.HTML(value=html)],
    layout=W.Layout(padding="0", margin="0")
    )
    panel.add_class("field-density-legend-panel")
    return panel

def _raster_legend_widget() -> W.HTML:
    if not getattr(CFG, "raster_legend_enabled", True):
        return W.HTML(value="<div></div>")

    rows = []
    for item in getattr(CFG, "raster_legend", []):
        color = str(item.get("color", "#000000"))
        label = str(item.get("name", ""))
        rows.append(
            (
                "<div style='display:flex;align-items:center;gap:8px;margin-top:6px;'>"
                f"<span style='width:16px;height:16px;border-radius:4px;border:1px solid rgba(15,23,42,0.18);background:{color};display:inline-block;'></span>"
                f"<span style='fontSize: var(--font-body);font-weight:600,color:#0f172a;'>{label}</span>"
                "</div>"
            )
        )
    title = str(getattr(CFG, "raster_legend_title", "Tree–Vege–Bare"))
    html = (
        "<div style='margin-top:1px;background:rgba(255,255,255,0.40);backdrop-filter: blur(6px);border:1px solid rgba(148,163,184,0.40);"
        "border-radius:1px;box-shadow:0 10px 28px rgba(15,23,42,0.14);padding:12px 14px;min-width:190px;display:inline-block;'>"
        f"<div style='fontSize: var(--font-section-title);font-weight:700;color:#0f172a;line-height:1.35;'>{title}</div>"
        f"{''.join(rows)}</div>"
    )
    panel = W.Box(
    [W.HTML(value=html)],
    layout=W.Layout(padding="0", margin="0")
    )
    panel.add_class("raster-legend-panel")
    return panel


def _product_legend(product: str):
    if product == PRODUCT_DATEPALM_FIELDS:
        return solara.Div()
    if product == PRODUCT_FIELD_DENSITY:
        return solara.Div()
    if product == PRODUCT_DATEPALM:
        return solara.Markdown(
            "Date Palm Fields Qassim Manual — filled polygons representing Qassim farms, clipped to the current ROI.",
            style={"fontSize": "var(--font-body)", "color": "#444", "marginTop": "0.5rem"},
        )
    if product == PRODUCT_CENTER_PIVOT:
        return solara.Markdown(
            "Center-Pivot Fields — yearly polygons rendered from the CPF archive.",
            style={"fontSize": "var(--font-body)", "color": "#444", "marginTop": "0.5rem"},
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
                    style={"margin": "0", "fontSize": "var(--font-body)"},
                ),
            ],
            gap="0.35rem",
            style={"alignItems": "center", "marginTop": "0.5rem"},
        )
    return solara.Div()


def _product_summary(product: str):
    return solara.Div()


def _auth_enabled() -> bool:
    return bool(getattr(CFG, "auth_username", "")) and bool(getattr(CFG, "auth_password", ""))


def _touch_auth_session(session_id: str):
    if session_id:
        _AUTH_SESSIONS[session_id] = time.time()


def _clear_auth_session(session_id: str):
    if session_id:
        _AUTH_SESSIONS.pop(session_id, None)


def _auth_session_is_valid(session_id: str) -> bool:
    if not session_id:
        return False
    last_seen = _AUTH_SESSIONS.get(session_id)
    if last_seen is None:
        return False
    if (time.time() - last_seen) > _AUTH_IDLE_TIMEOUT_SECONDS:
        _AUTH_SESSIONS.pop(session_id, None)
        return False
    return True


@solara.component
def _LoginGate(on_success, session_id: str):
    username, set_username = solara.use_state("")
    password, set_password = solara.use_state("")
    error_message, set_error_message = solara.use_state("")

    def _submit():
        expected_username = getattr(CFG, "auth_username", "")
        expected_password = getattr(CFG, "auth_password", "")
        if username == expected_username and password == expected_password:
            set_error_message("")
            _touch_auth_session(session_id)
            on_success()
            return
        set_error_message("Invalid username or password.")

    with solara.Column(
        gap="1rem",
        style={
            "minHeight": "80vh",
            "alignItems": "center",
            "justifyContent": "center",
            "padding": "2rem 1rem",
        },
    ):
        with solara.Card(
            "Sign In",
            style={
                "width": "100%",
                "maxWidth": "420px",
                "padding": "1.25rem",
                "background": "rgba(255,255,255,0.92)",
            },
        ):
            solara.Markdown(
                "Enter your username and password to access the geoportal.",
                style={"fontSize": "var(--font-body)", "color": "#475569", "marginBottom": "0.75rem"},
            )
            solara.InputText(
                "Username",
                value=username,
                on_value=set_username,
                continuous_update=True,
                autofocus=True,
                placeholder="Enter username",
                classes=["geoportal-login-field"],
                style={"width": "100%"},
            )
            solara.InputText(
                "Password",
                value=password,
                on_value=set_password,
                continuous_update=True,
                password=True,
                placeholder="Enter password",
                classes=["geoportal-login-field"],
                style={"width": "100%"},
            )
            if error_message:
                solara.Markdown(
                    error_message,
                    style={"fontSize": "var(--font-body)", "color": "#b91c1c", "marginTop": "0.5rem"},
                )
            solara.Button(
                label="Sign In",
                on_click=_submit,
                color="success",
                classes=["geoportal-login-button"],
                style={"width": "100%", "marginTop": "0.75rem"},
            )


# -------------------------
# Main Solara page
# -------------------------
@solara.component
def Page():
    show_toast, hide_toast, toast_state = use_toast()
    session_id = solara.get_session_id()
    authenticated, set_authenticated = solara.use_state(
        (not _auth_enabled()) or _auth_session_is_valid(session_id)
    )

    def _sync_auth_session():
        if not _auth_enabled():
            if not authenticated:
                set_authenticated(True)
            return

        session_valid = _auth_session_is_valid(session_id)
        if session_valid != authenticated:
            set_authenticated(session_valid)

    solara.use_effect(_sync_auth_session, [session_id, authenticated])

    if not authenticated:
        _LoginGate(lambda: set_authenticated(True), session_id)
        return

    # UI state
    geojson_path, set_geojson_path = solara.use_state(str(CFG.default_geojson))
    force_gcs, set_force_gcs_state = solara.use_state(force_gcs_enabled())
    fetch_debug_tick, set_fetch_debug_tick = solara.use_state(0)
    debounced_geojson = use_debounce(geojson_path, delay_ms=500)
    refs = ReactiveRefs()
    ## turn off the below two line if not showing as page at the bottom of the map window
    #ts_title, set_ts_title = solara.use_state("")
    #ts_df, set_ts_df = solara.use_state(None)

    default_tiles_dir = str(getattr(CFG, "default_tiles_dir", _APP_SERVER_ROOT / "38RLQ_2024"))
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
    province_names, set_province_names = solara.use_state(list(getattr(CFG, "datepalms_province_names", ())))
    selected_date_palm_province, set_selected_date_palm_province = solara.use_state(None)
    date_palm_tile_layers, set_date_palm_tile_layers = solara.use_state({})
    field_lookup, set_field_lookup = solara.use_state(None)
    click_point, set_click_point = solara.use_state(None)
    hover_point, set_hover_point = solara.use_state(None)
    field_info, set_field_info = solara.use_state(None)
    hover_field_record, set_hover_field_record = solara.use_state(None)
    field_popup_ref = solara.use_ref(None)
    hover_layer_ref = solara.use_ref(None)
    selected_field_record, set_selected_field_record = solara.use_state(None)
    field_highlight_ref = solara.use_ref(None)
    highres_layer, set_highres_layer = solara.use_state(None)
    highres_request_ref = solara.use_ref(None)
    # --- Date Palms (Qassim) state ---
    dp_opacity, set_dp_opacity = solara.use_state(float(getattr(CFG, "datepalms_default_opacity", 0.55)))
    dp_layer_full, set_dp_layer_full = solara.use_state(None)
    dp_layer_simple, set_dp_layer_simple = solara.use_state(None)
    dp_active_layer_ref = solara.use_ref(None)
    field_density_opacity, set_field_density_opacity = solara.use_state(
        float(getattr(CFG, "field_density_default_opacity", 0.78))
    )

    # --- Tree Health state ---
    th_opacity, set_th_opacity = solara.use_state(float(getattr(CFG, "tree_health_fill_opacity", 0.75)))
    th_layer, set_th_layer = solara.use_state(None)

    # Map & base layers
    m = solara.use_memo(lambda: create_base_map(CFG.map_center, CFG.map_zoom, CFG.map_width, CFG.map_height), [])
    osm = solara.use_memo(osm_layer, [])
    esri = solara.use_memo(esri_world_imagery_layer, [])

    map_debug_attached = solara.use_ref(False)
    current_zoom, set_current_zoom = solara.use_state(getattr(CFG, "map_zoom", 6))
    popup_watchers_attached = solara.use_ref(False)
    layer_signature_ref = solara.use_ref(None)
    field_density_legend_control_ref = solara.use_ref(None)
    raster_legend_control_ref = solara.use_ref(None)
    tree_health_legend_control_ref = solara.use_ref(None)
    national_figure_control_ref = solara.use_ref(None)
    national_figure_closed, set_national_figure_closed = solara.use_state(False)
    loading_message, set_loading_message = solara.use_state(None)
    loading_product_ref = solara.use_ref(None)
    active_product_ref = solara.use_ref(None)


    def _loading_badge():
        if not loading_message:
            return solara.Div()

        return solara.Div(
            style={
                "position": "absolute",
                "top": "16px",
                "left": "50%",
                "transform": "translateX(-50%)",
                "zIndex": "1000",
                "background": "rgba(255,255,255,0.4)",
                "backdropFilter": "blur(6px)",
                "padding": "12px 21px",
                "borderRadius": "15px",
                "border": "1px solid rgba(148,163,184,0.65)",
                "boxShadow": "0 8px 20px rgba(15,23,42,0.16)",
                "fontWeight": "700",
                "fontSize": "var(--font-popup)",
                "color": "#0f172a",
                "textAlign": "center",
                "minWidth": "270px",
                "pointerEvents": "none",
            },
            children=[solara.Text(str(loading_message))],
        )

    def _sync_active_product_ref():
        active_product_ref.current = active_product

    solara.use_effect(_sync_active_product_ref, [active_product])

    def _sync_force_gcs():
        set_force_gcs(force_gcs)

    solara.use_effect(_sync_force_gcs, [force_gcs])

    def _refresh_fetch_debug():
        set_fetch_debug_tick(lambda current: current + 1)

    solara.use_effect(_refresh_fetch_debug, [active_product, force_gcs, selected_date_palm_province, current_zoom, loading_message])

    def _touch_authenticated_session():
        # Only extend sessions that are still valid. This prevents a stale
        # restored UI state from reviving an expired login on reconnect.
        if _auth_enabled() and authenticated and _auth_session_is_valid(session_id):
            _touch_auth_session(session_id)

    solara.use_effect(
        _touch_authenticated_session,
        [
            session_id,
            authenticated,
            active_product,
            force_gcs,
            geojson_path,
            raster_dir,
            selected_date_palm_province,
            current_zoom,
            click_point,
            hover_point,
            field_info,
            selected_field_record,
            loading_message,
        ],
    )

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

    def _ensure_product_metadata():
        if active_product == PRODUCT_DATEPALM_FIELDS and field_lookup is None:
            try:
                set_field_lookup(
                    FieldLookup(
                        CFG.datepalms_province_dir,
                        CFG.datepalms_province_lookup_json,
                    )
                )
            except Exception as exc:
                show_toast(str(exc), "error")

    solara.use_effect(_ensure_product_metadata, [active_product, province_names, field_lookup])

    # We derive bounds on demand from the map; no persistent state required

    def _attach_field_click():
        if getattr(m, "_field_click_attached", False):
            return

        def _on_map_interact(*args, **kwargs):
            if args:
                event = args[0]
            else:
                event = kwargs
            if active_product != PRODUCT_DATEPALM_FIELDS:
                return
            if not event:
                return
            event_type = event.get("type")
            if event_type in {
                "moveend",
                "zoomend",
                "dragend",
                "overlayadd",
                "overlayremove",
                "baselayerchange",
                "layeradd",
                "layerremove",
            }:
                _clear_popups()
                set_click_point(None)
                set_hover_point(None)
                return
            if event_type not in {"click", "mousemove", "mouseover", "mouseout"}:
                return
            coords = event.get("coordinates")
            if event_type == "mouseout":
                set_hover_point(None)
                return
            if not coords or len(coords) < 2:
                return
            lat, lon = coords[0], coords[1]
            point = (float(lat), float(lon))
            if event_type == "click":
                set_click_point(point)
            elif event_type in {"mousemove", "mouseover"}:
                if hover_point != point:
                    set_hover_point(point)

        try:
            m.on_interaction(_on_map_interact)
            m._field_click_attached = True
        except Exception:
            pass

    solara.use_effect(_attach_field_click, [m, active_product])

    def _lookup_field_info():
        if active_product != PRODUCT_DATEPALM_FIELDS:
            if field_info is not None:
                set_field_info(None)
            return
        if not click_point:
            return
        if field_lookup is None:
            return
        record = field_lookup.lookup(click_point[1], click_point[0])
        if not record:
            set_field_info(None)
            return
        info = {
            "field_id": record.field_id,
            "province_id": record.province_id,
            "province_name": record.province_name,
            **record.attributes,
            "click_lat": click_point[0],
            "click_lon": click_point[1],
        }
        set_field_info(info)

    solara.use_effect(_lookup_field_info, [click_point, active_product, field_lookup])

    def _lookup_hover_field_info():
        if active_product != PRODUCT_DATEPALM_FIELDS:
            if hover_field_record is not None:
                set_hover_field_record(None)
            return
        if not hover_point or field_lookup is None:
            if hover_field_record is not None:
                set_hover_field_record(None)
            return
        record = field_lookup.lookup(hover_point[1], hover_point[0])
        if record is hover_field_record:
            return
        set_hover_field_record(record)

    solara.use_effect(_lookup_hover_field_info, [hover_point, active_product, field_lookup])

    def _province_geojson_source(province: str) -> tuple[Path | None, str | None]:
        if not province:
            return None, None
        base_dir = Path(getattr(CFG, "datepalms_province_dir", ""))
        local = ensure_local_asset(base_dir / f"{province}.geojson") if base_dir else None
        http_base = getattr(
            CFG,
            "datepalms_province_public_http_base" if force_gcs else "datepalms_province_http_base",
            "",
        ).rstrip("/")
        remote = f"{http_base}/{province}.geojson" if http_base else None
        return (local if local and local.exists() else None), remote

    def _read_province_geojson(
        local_path: Path | None,
        remote_url: str | None,
    ) -> gpd.GeoDataFrame | None:
        sources = []
        if local_path and local_path.exists():
            sources.append(str(local_path))
        if remote_url:
            sources.append(remote_url)
        for src in sources:
            try:
                gdf = gpd.read_file(src)
                return gdf
            except Exception as exc:
                print(f"[HIGHRES] failed to read {src}: {exc}")
        return None

    def _tile_url_for_province(province: str) -> str:
        base_url = (
            getattr(CFG, "datepalms_tile_public_base_url", CFG.datepalms_tile_base_url)
            if force_gcs
            else CFG.datepalms_tile_base_url
        )
        return (
            CFG.datepalms_tile_url_template
            .replace("{base}", base_url)
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

    def _cleanup_highres_layer():
        _clear_popups()
        if highres_layer and (highres_layer in m.layers):
            try:
                m.remove_layer(highres_layer)
            except Exception:
                pass
        set_highres_layer(None)

    def _normalize_field_popup_props(info: dict[str, object] | None) -> dict[str, object]:
        if not info:
            return {}
        props: dict[str, object] = {}
        def add(key: str, value: object):
            props[key.replace("_", " ").title()] = value

        priority_keys = ("field_id", "province_name", "province_id", "esti_tree_number")
        for key in priority_keys:
            value = info.get(key)
            if value is None:
                continue
            add(key, value)

        for key, value in info.items():
            if key in priority_keys or key in ("click_lat", "click_lon"):
                continue
            if value is None:
                continue
            add(key, value)
        return props

    def _show_field_popup():
        popup = field_popup_ref.current
        if popup and (popup in m.layers):
            m.remove_layer(popup)
            field_popup_ref.current = None
        if not field_info:
            return

        props = _normalize_field_popup_props(field_info)
        if not props:
            return

        table = html_table_popup(props)
        popup = ipyleaflet.Popup(
            location=(field_info["click_lat"], field_info["click_lon"]),
            child=table,
            close_button=True,
            auto_close=True,
            keep_in_view=True,
            offset=(0, -1),
        )
        m.add_layer(popup)
        field_popup_ref.current = popup

    solara.use_effect(_show_field_popup, [field_info])

    def _zoom_to_national_level():
        if active_product != PRODUCT_DATEPALM_FIELDS:
            return
        if selected_date_palm_province != PROVINCE_NATIONAL:
            return
        target_zoom = PRODUCT_DEFAULT_ZOOM.get(PRODUCT_DATEPALM_FIELDS, 6)
        if target_zoom is None:
            target_zoom = 6
        try:
            current_zoom = getattr(m, "zoom", None)
            if current_zoom is None or current_zoom == target_zoom:
                return
            m.zoom = target_zoom
        except Exception:
            pass

    solara.use_effect(_zoom_to_national_level, [active_product, selected_date_palm_province])

    def _apply_product_zoom(product: str):
        if product == PRODUCT_TREE_HEALTH:
            return
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

    def _sync_field_density_legend():
        current = field_density_legend_control_ref.current
        if current is not None:
            try:
                m.remove_control(current)
            except Exception:
                pass
            field_density_legend_control_ref.current = None

        if active_product != PRODUCT_FIELD_DENSITY:
            return

        control = ipyleaflet.WidgetControl(
            widget=_field_density_legend_widget(),
            position="topright",
            transparent_bg=True,
        )
        try:
            m.add_control(control)
            field_density_legend_control_ref.current = control
        except Exception:
            pass

    solara.use_effect(_sync_field_density_legend, [m, active_product])

    def _sync_raster_legend():
        current = raster_legend_control_ref.current
        if current is not None:
            try:
                m.remove_control(current)
            except Exception:
                pass
            raster_legend_control_ref.current = None

        should_show = (
            active_product == PRODUCT_TREE_VEGE
            and getattr(CFG, "raster_legend_enabled", True)
        )
        if not should_show:
            return

        control = ipyleaflet.WidgetControl(
            widget=_raster_legend_widget(),
            position="topright",
            transparent_bg = True,
        )
        try:
            m.add_control(control)
            raster_legend_control_ref.current = control
        except Exception:
            pass

    solara.use_effect(_sync_raster_legend, [m, active_product])

    def _sync_tree_health_legend():
        current = tree_health_legend_control_ref.current
        if current is not None:
            try:
                m.remove_control(current)
                print("[TREE LEGEND] removed old control")
            except Exception as e:
                print("[TREE LEGEND] remove failed:", e)
            tree_health_legend_control_ref.current = None

        print("[TREE LEGEND] active_product =", active_product)

        if active_product != PRODUCT_TREE_HEALTH:
            print("[TREE LEGEND] skipped")
            return

        control = ipyleaflet.WidgetControl(
            widget=_tree_health_legend_widget(),
            position="topright",
            transparent_bg = True,
        )
        try:
            m.add_control(control)
            tree_health_legend_control_ref.current = control
            print("[TREE LEGEND] added control")
        except Exception as e:
            print("[TREE LEGEND] add failed:", e)

    solara.use_effect(_sync_tree_health_legend, [m, active_product])

    def _sync_national_figure():
        current = national_figure_control_ref.current
        if current is not None:
            try:
                m.remove_control(current)
            except Exception:
                pass
            national_figure_control_ref.current = None

        should_show = (
            active_product == PRODUCT_DATEPALM_FIELDS
            and selected_date_palm_province == PROVINCE_NATIONAL
            and not national_figure_closed
        )
        if not should_show:
            return

        figure_path = Path(getattr(CFG, "datepalms_national_figure_file", ""))
        try:
            image_bytes = read_asset_bytes(figure_path)
        except Exception:
            return

        close_button = W.Button(
            description="×",
            layout=W.Layout(width="32px", height="32px", min_width="32px", padding="0"),
            tooltip="Close figure",
        )
        #close_button.style.button_color = "#ffffff"
        close_button.style.button_color = "transparent"
        def _close(_event):
            set_national_figure_closed(True)

        close_button.on_click(_close)

        title = W.HTML(
            value="<div style='font-size:var(--font-small);font-weight:700;color:#0f172a;'>Field acreage by province</div>"
        )
        header = W.HBox(
            [title, close_button],
            layout=W.Layout(justify_content="space-between", align_items="center", width="100%"),
        )
        image = W.Image(
            value=image_bytes,
            format="png",
            layout=W.Layout(width="100%"),
        )
        panel_html = W.HTML(
            value="""
                <style>
                .national-figure-control.leaflet-control {
                    background: transparent !important;
                    border: none !important;
                    box-shadow: none !important;
                }
                .national-figure-panel {
                    width: 30vw;
                    min-width: 30vw;
                    max-width: 30vw;
                    padding: 10px;
                    border: 1px solid rgba(148,163,184,0.45);
                    background: rgba(255,255,255,0.20);
                    backdrop-filter: blur(6px);
                    border-radius: 10px;
                    box-sizing: border-box;
                }
                </style>
                <div class="national-figure-panel"></div>
                """
            )
        panel = W.VBox(
            [header, image],
            layout=W.Layout(
                width="30vw",
                min_width="30vw",
                max_width="30vw",
                padding="10px",
                border="1px solid rgba(148,163,184,0.45)",
                background_color="rgba(255,255,255,0.45)",
            ),
        )
        try:
            panel.add_class("national-figure-panel")
            panel.layout.overflow = "hidden"
        except Exception:
            pass

        control = ipyleaflet.WidgetControl(
            widget=panel,
            position="topleft",
            transparent_bg=True
        )
        try:
            m.add_control(control)
            national_figure_control_ref.current = control
        except Exception:
            pass
        try:
            control.widget.add_class("national-figure-panel")
        except Exception:
            pass

    solara.use_effect(
        _sync_national_figure,
        [m, active_product, selected_date_palm_province, national_figure_closed],
    )



    ksa_layer_normal, set_ksa_layer_normal = solara.use_state(None)
    ksa_layer_area, set_ksa_layer_area = solara.use_state(None)

    def _init_ksa_layers():
        if ksa_layer_normal is None:
            layer, err = build_ksa_bounds_layer(m=m, show_area=False)
            if err:
                show_toast(err, "error")
            else:
                set_ksa_layer_normal(layer)

        if ksa_layer_area is None:
            layer, err = build_ksa_bounds_layer(m=m, show_area=True)
            if err:
                show_toast(err, "error")
            else:
                set_ksa_layer_area(layer)

    solara.use_effect(_init_ksa_layers, [m])

    def _sync_ksa_layer():
        active_layer = ksa_layer_area if active_product == PRODUCT_DATEPALM_FIELDS else ksa_layer_normal
        inactive_layer = ksa_layer_normal if active_product == PRODUCT_DATEPALM_FIELDS else ksa_layer_area

        if inactive_layer and inactive_layer in m.layers:
            try:
                m.remove_layer(inactive_layer)
            except Exception:
                pass

        if active_layer and active_layer not in m.layers:
            _insert_after(active_layer, esri)

    solara.use_effect(_sync_ksa_layer, [m, esri, active_product, ksa_layer_normal, ksa_layer_area])


    def _cleanup_on_product_change():
        if active_product == PRODUCT_DATEPALM_FIELDS:
            return
        _cleanup_highres_layer()
        _clear_popups()

    solara.use_effect(_cleanup_on_product_change, [active_product])

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
    def _precenter_product(product: str):
        """
        Move the map immediately when a product is selected,
        before the new layer finishes loading.
        """
        try:
            if product == PRODUCT_TREE_HEALTH:
                center = getattr(CFG, "tree_health_default_center", None)
                zoom = PRODUCT_DEFAULT_ZOOM.get(PRODUCT_TREE_HEALTH, 16)
                if center:
                    m.center = center
                if zoom:
                    m.zoom = zoom
                return

            if product == PRODUCT_SENSORS:
                center = getattr(CFG, "sensors_default_center", None)
                zoom = PRODUCT_DEFAULT_ZOOM.get(PRODUCT_SENSORS, 16)
                if center:
                    m.center = center
                if zoom:
                    m.zoom = zoom
                return

            if product == PRODUCT_DATEPALM_FIELDS:
                center = getattr(CFG, "datepalms_fields_default_center", None)
                zoom = PRODUCT_DEFAULT_ZOOM.get(PRODUCT_DATEPALM_FIELDS, 6)
                if center:
                    m.center = center
                if zoom:
                    m.zoom = zoom
                return

            if product == PRODUCT_FIELD_DENSITY:
                center = getattr(CFG, "field_density_default_center", None)
                zoom = PRODUCT_DEFAULT_ZOOM.get(PRODUCT_FIELD_DENSITY, 6)
                if center:
                    m.center = center
                if zoom:
                    m.zoom = zoom
                return

            if product == PRODUCT_CENTER_PIVOT:
                bounds = _roi_to_bounds(getattr(CFG, "center_pivot_default_roi", None))
                if bounds:
                    _fit_bounds(bounds)
                return

            if product == PRODUCT_TREE_VEGE:
                if tile_bounds:
                    _fit_bounds(tile_bounds)
                return

        except Exception as exc:
            print(f"[PRECENTER] failed for {product}: {exc}")
    def _request_fit(product: str):
        pending_fit_product.current = product
        refs.did_fit_ref.current = False
        print(f"[DEBUG request_fit] product={product}")

    def _finish_loading(product: str):
        if loading_product_ref.current == product:
            set_loading_message(None)
            loading_product_ref.current = None


    def _finish_loading_date_palm_fields_when_ui_ready():
        if active_product != PRODUCT_DATEPALM_FIELDS:
            return
        if loading_product_ref.current != PRODUCT_DATEPALM_FIELDS:
            return
        # Default subproduct UI for Date Palm Fields is ready once the controls
        # are mounted: product controls can render and province names exist.
        controls_ready = bool(province_names)
        if controls_ready:
            _finish_loading(PRODUCT_DATEPALM_FIELDS)

    solara.use_effect(
        _finish_loading_date_palm_fields_when_ui_ready,
        [active_product, province_names],
    )

    def _maybe_fit_product(product: str, bounds):
        print(f"[DEBUG fit request] pending={pending_fit_product.current} active={active_product} target={product} bounds_set={bounds is not None}")
        if pending_fit_product.current != product:
            return
        if not bounds:
            return
        if product == PRODUCT_TREE_HEALTH:
            center = _center_from_bounds(bounds)
            target_zoom = PRODUCT_DEFAULT_ZOOM.get(PRODUCT_TREE_HEALTH, 14)
            try:
                if center is not None:
                    m.center = center
                if getattr(m, "zoom", None) is not None and target_zoom is not None:
                    m.zoom = target_zoom
            except Exception as exc:
                print(f"[DEBUG fit] failed to center Tree Health on {center}: {exc}")
        else:
            _fit_bounds(bounds)
        pending_fit_product.current = None

    def _clear_popups():
        try:
            for layer in list(m.layers):
                if isinstance(layer, ipyleaflet.Popup):
                    if getattr(layer, "_is_geojson_hint", False):
                        continue
                    if getattr(layer, "_is_tree_health_hint", False):
                        continue
                    m.remove_layer(layer)
        except Exception:
            pass
        try:
            clear_tree_health_badge(m)
        except Exception:
            pass
        try:
            clear_sensor_badges(m, refs.active_marker_ref)
        except Exception:
            pass
        field_popup_ref.current = None
        set_field_info(None)
        set_click_point(None)
        set_hover_point(None)
        set_hover_field_record(None)
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


    def _non_popup_layer_signature():
        signature = []
        for layer in list(m.layers):
            if isinstance(layer, ipyleaflet.Popup):
                continue
            try:
                name = getattr(layer, "name", None)
            except Exception:
                name = None
            signature.append((type(layer).__name__, name))
        return tuple(signature)

    def _attach_popup_watchers():
        if popup_watchers_attached.current:
            return

        def _on_center(change):
            if getattr(m, "_suppress_popup_clear", False):
                return
            if change.new is None or change.old is None:
                return
            if tuple(change.new) != tuple(change.old):
                _clear_popups()

        def _on_zoom(change):
            if getattr(m, "_suppress_popup_clear", False):
                return
            if change.new is None or change.old is None:
                return
            if change.new != change.old:
                _clear_popups()

        def _on_layers(change):
            if getattr(m, "_suppress_popup_clear", False):
                return
            new_sig = _non_popup_layer_signature()
            old_sig = layer_signature_ref.current
            layer_signature_ref.current = new_sig
            if old_sig is None:
                return
            if new_sig != old_sig:
                _clear_popups()

        try:
            layer_signature_ref.current = _non_popup_layer_signature()
            m.observe(_on_center, names="center")
            m.observe(_on_zoom, names="zoom")
            m.observe(_on_layers, names="layers")
            popup_watchers_attached.current = True
        except Exception:
            pass

    solara.use_effect(_attach_popup_watchers, [m])

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
                "fontSize": "var(--font-button)",
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

    NATIONAL_COVERAGE_HA = 192_041.41

    def _render_date_palm_subproduct_buttons():
        buttons = []
        for product, label in (
            (PRODUCT_DATEPALM_FIELDS, "Fields"),
            (PRODUCT_FIELD_DENSITY, "Field density"),
        ):
            is_active = active_product == product
            buttons.append(
                solara.Button(
                    label,
                    text=True,
                    on_click=lambda _event=None, target=product: _select_product(target),
                    style={
                        "padding": "0.35rem 0.8rem",
                        "borderRadius": "999px",
                        "border": "1px solid #cbd5f5",
                        "background": "#0f766e" if is_active else "#f8fafc",
                        "color": "#f8fafc" if is_active else "#0f172a",
                        "fontWeight": "600",
                        "fontSize": "var(--font-button)",
                        "margin": "0",
                    },
                )
            )
        return solara.Row(
            children=buttons,
            gap="0.45rem",
            style={"alignItems": "center", "flexWrap": "wrap", "marginBottom": "0.85rem"},
        )

    def _render_date_palm_province_buttons():
        if not province_names:
            return solara.Markdown(
                "Province GeoPackages missing. Check the datasource directory.",
                style={"fontSize": "var(--font-small)", "color": "#888"},
            )

        special_bottom_provinces = {"EASTERN_PROVINCE", "NORTHERN_BORDERS"}

        def _norm(name: str) -> str:
            return str(name).strip().upper().replace(" ", "_").replace("-", "_")
        
        all_provinces = [PROVINCE_NATIONAL] + list(province_names)

        national_button = None
        normal_buttons = []
        bottom_buttons = []

        for province in all_provinces:
            is_active = selected_date_palm_province == province
            is_national = province == PROVINCE_NATIONAL
            is_bottom = _norm(province) in special_bottom_provinces

            style_button = {
                "width": "100%",
                "padding": "0.45rem 0.85rem",
                "borderRadius": "999px",
                "border": "2px solid #0f766e" if is_national else "1px solid #cbd5f5",
                "background": (
                    "#0f766e" if is_active else
                    "#e6f4f1" if is_national else
                    "#f8fafc"
                ),
                "color": "#f8fafc" if is_active else "#0f172a",
                "fontWeight": "700" if is_national else "600",
                "fontSize": "var(--font-section-title)" if is_national else "var(--font-button)",
                "textAlign": "left",
                "transition": "all 0.2s ease",
                "boxShadow": "0 2px 6px rgba(15,118,110,0.15)" if is_national else "none",
                "whiteSpace": "normal",
                "lineHeight": "1.18",
                "overflowWrap": "anywhere",
                "wordBreak": "break-word",
            }

            def _pretty_name(name: str) -> str:
                return name.replace("_", " ").title()

            label = PROVINCE_LABELS.get(province, _pretty_name(province))

            if is_national:
                if is_active:
                    btn = solara.Div(
                        style={
                            "display": "flex",
                            "flexDirection": "column",
                            "gap": "0.25rem",
                            "width": "100%",
                        },
                        children=[
                            solara.Button(
                                label,
                                text=True,
                                style=style_button,
                                on_click=lambda event=None, target=province: _on_date_palm_fields_province_click(target),
                            ),
                            solara.Markdown(
                                f"Total mapped date palm field acreage is {NATIONAL_COVERAGE_HA:,.2f} ha",
                                style={
                                    "margin": "0",
                                    "fontSize": "var(--font-section-title)",
                                    "fontWeight": "600",
                                    "color": "#475569",
                                    "paddingLeft": "0.5rem",
                                    "whiteSpace": "normal",
                                },
                            ),
                        ],
                    )
                else:
                    btn = solara.Button(
                        label,
                        text=True,
                        style=style_button,
                        on_click=lambda event=None, target=province: _on_date_palm_fields_province_click(target),
                    )
                national_button = btn
            else:
                btn = solara.Button(
                    label,
                    text=True,
                    style=style_button,
                    on_click=lambda event=None, target=province: _on_date_palm_fields_province_click(target),
                )

                if is_bottom:
                    bottom_buttons.append(btn)
                else:
                    normal_buttons.append(btn)

        children = []

        if national_button:
            children.append(
                solara.Div(
                    children=[national_button],
                    style={"width": "100%"},
                )
            )

        children.append(
            solara.Div(
                children=normal_buttons,
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
                    "columnGap": "1rem",
                    "rowGap": "0.5rem",
                    "width": "100%",
                },
            )
        )

        if bottom_buttons:
            children.append(
                solara.Div(
                    style={
                        "display": "flex",
                        "flexDirection": "column",
                        "gap": "0.5rem",
                        "width": "100%",
                        "marginTop": "0.4rem",
                        "borderTop": "1px solid #e2e8f0",   # 👈 visual separation
                        "paddingTop": "0.4rem",
                    },
                    children=[
                        solara.Div(children=[btn], style={"width": "100%"})
                        for btn in bottom_buttons
                    ],
                )
            )

        return solara.Div(
            children=children,
            style={
                "display": "flex",
                "flexDirection": "column",
                "gap": "0.5rem",
                "width": "100%",
            },
        )
        
    def _on_date_palm_fields_province_click(target: str):
        _clear_popups()
        if target == PROVINCE_NATIONAL:
            set_national_figure_closed(False)
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
        if product in {PRODUCT_DATEPALM_FIELDS, PRODUCT_FIELD_DENSITY}:
            mode_details = []
            if product == PRODUCT_DATEPALM_FIELDS:
                mode_details.append(
                    solara.Markdown(
                        "Province – select a province to load the fields",
                        style={
                            "marginBottom": "0.35rem",
                            "fontSize": "var(--font-section-title)",
                            "fontWeight": "800",
                            "color": "#424345",
                        },)
                  
                )
                mode_details.append(_render_date_palm_province_buttons())
            else:
                mode_details.append(
                    solara.Div(
                        style={"width": "260px"},
                        children=[
                            _slider_float("Opacity", field_density_opacity, set_field_density_opacity, 0.0, 1.0, 0.01)
                        ],
                    )
                )
            return solara.Row(
                gap="0.5rem",
                style={**base_style, "width": "100%"},
                children=[
                    solara.Div(
                        style={"flex": "1 1 100%", "maxWidth": "100%", "width": "100%"},
                        children=[
                            solara.Markdown(
                                "Subproduct",
                                style={
                                    "marginBottom": "0.3rem",
                                    "fontSize": "var(--font-section-title)",
                                    "fontWeight": "800",
                                    "color": "#424345",
                                },
                            ),
                            _render_date_palm_subproduct_buttons(),
                            *mode_details,
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
                            solara.Markdown("Year",style={"fontSize": "var(--font-section-title)", "fontWeight": "700"},),
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
        if active_product != PRODUCT_TREE_VEGE:
            return
        folder = (
            Path(debounced_raster_dir).resolve()
            if IS_PRODUCTION
            else ensure_local_directory(Path(debounced_raster_dir), suffixes=(".png", ".jpg", ".jpeg")).resolve()
        )
        if folder.exists():
            ext = _detect_extension(folder) or "png"
            _zmin, _zmax = _detect_zoom_range(folder)
            bounds = _leaflet_bounds_from_xyz(folder, _zmax) if _zmax is not None else None
        elif IS_PRODUCTION:
            ext = getattr(CFG, "raster_tile_ext", "png")
            _zmin = int(getattr(CFG, "raster_tile_min_zoom", 0))
            _zmax = int(getattr(CFG, "raster_tile_max_zoom_default", 14))
            bounds = None
        else:
            if not gcs_enabled():
                show_toast(f"Tiles folder not found: {folder}", "warning")
                return
            ext = getattr(CFG, "raster_tile_ext", "png")
            _zmin = int(getattr(CFG, "raster_tile_min_zoom", 0))
            _zmax = int(getattr(CFG, "raster_tile_max_zoom_default", 14))
            bounds = None

        set_tile_ext(ext)
        set_zmin(_zmin)
        set_zmax(_zmax)
        set_tile_bounds(bounds)

        _maybe_fit_product(PRODUCT_TREE_VEGE, bounds)
        if _zmin is not None and m.zoom < _zmin:
            m.zoom = _zmin

    solara.use_effect(_on_tiles_folder_change, [debounced_raster_dir, active_product])

    # Raster overlay (single upsert)
    def _build_raster_layer():
        if active_product != PRODUCT_TREE_VEGE:
            return None
        cache_buster = abs(hash(debounced_raster_dir)) % (10**8)
        tile_base = (
            getattr(CFG, "tiles_public_http_base", TILES_HTTP_BASE)
            if force_gcs
            else TILES_HTTP_BASE
        )
        layer = ipyleaflet.TileLayer(
            url=f"{tile_base}/{{z}}/{{x}}/{{y}}.{tile_ext}?v={cache_buster}",
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

    raster_layer = solara.use_memo(_build_raster_layer, [debounced_raster_dir, tile_ext, raster_opacity, zmin, zmax, active_product, force_gcs])

    def _render_raster_layer():
        if raster_layer is None:
            return
        if active_product == PRODUCT_TREE_VEGE:
            upsert_overlay_by_name(m, raster_layer, below_markers=True)
            _maybe_fit_product(PRODUCT_TREE_VEGE, tile_bounds)
            _finish_loading(PRODUCT_TREE_VEGE)
        elif raster_layer in m.layers:
            try:
                m.remove_layer(raster_layer)
            except Exception:
                pass

    solara.use_effect(_render_raster_layer, [m, raster_layer, active_product, tile_bounds])
    solara.use_effect(lambda: (raster_layer and set_layer_opacity(raster_layer, raster_opacity)),
                      [raster_layer, raster_opacity])

    field_density_layer, field_density_bounds, field_density_error = solara.use_memo(
        lambda: build_field_density_layer(opacity=field_density_opacity)
        if active_product == PRODUCT_FIELD_DENSITY
        else (None, None, None),
        [field_density_opacity, active_product],
    )

    def _render_field_density_layer():
        layer_name = str(getattr(CFG, "field_density_layer_name", "Field density"))
        if active_product == PRODUCT_FIELD_DENSITY:
            if field_density_error:
                show_toast(field_density_error, "error")
                return
            if field_density_layer is None:
                return
            upsert_overlay_by_name(m, field_density_layer, below_markers=True)
            _maybe_fit_product(PRODUCT_FIELD_DENSITY, field_density_bounds)
            _finish_loading(PRODUCT_FIELD_DENSITY)
            return

        for layer in list(m.layers):
            if getattr(layer, "name", "") != layer_name:
                continue
            try:
                m.remove_layer(layer)
            except Exception:
                pass

    solara.use_effect(
        _render_field_density_layer,
        [m, active_product, field_density_layer, field_density_bounds, field_density_error],
    )
    solara.use_effect(
        lambda: (field_density_layer and set_layer_opacity(field_density_layer, field_density_opacity)),
        [field_density_layer, field_density_opacity],
    )

    def _build_tile_layer(province: str, style_config: dict[str, str]) -> ipyleaflet.VectorTileLayer:
        url = _tile_url_for_province(province)
        style_key = _vector_layer_id_from_mbtiles(province) or "*"
        name = f"{province} (tile)"
        layer = ipyleaflet.VectorTileLayer(
            url=url,
            name=name,
            min_zoom=5,
            max_zoom=17,
            attribution="© local tiles",
            renderer="svg",
            interactive=True,
            feature_id="field_id",
            vector_tile_layer_styles={style_key: style_config},
        )
        setattr(layer, "_province", province)
        try:
            layer.style = style_config
        except Exception:
            pass
        return layer

    def _should_use_highres():
        bbox = _bounds_to_bbox(getattr(m, "bounds", None))
        return (
            active_product == PRODUCT_DATEPALM_FIELDS
            and selected_date_palm_province
            and selected_date_palm_province != PROVINCE_NATIONAL
            and current_zoom > 14
            and bbox is not None
        )

    def _highres_province() -> str | None:
        if active_product != PRODUCT_DATEPALM_FIELDS:
            return None
        if not selected_date_palm_province or selected_date_palm_province == PROVINCE_NATIONAL:
            return None
        return selected_date_palm_province

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

        if selected_date_palm_province == PROVINCE_NATIONAL or current_zoom <= HIGHRES_ZOOM_THRESHOLD:
            _finish_loading(PRODUCT_DATEPALM_FIELDS)

    solara.use_effect(
        _ensure_date_palm_tile_layer,
        [
            selected_date_palm_province,
            active_product,
            cp_layer,
            raster_layer,
            date_palm_tile_layers,
            current_zoom,
            force_gcs,
        ],
    )

    HIGHRES_ZOOM_THRESHOLD = 15

    def _build_highres_display_style():
        return {
            "fillColor": getattr(CFG, "datepalms_province_fill_color", "#64ff11"),
            "fillOpacity": float(getattr(CFG, "datepalms_province_fill_opacity", 0.4)),
            "color": getattr(CFG, "datepalms_province_edge_color", "#5ea700"),
            "weight": float(getattr(CFG, "datepalms_province_edge_weight", 2.0)),
        }

    def _maybe_load_highres_layer():
        target_province = _highres_province()
        bbox = _bounds_to_bbox(getattr(m, "bounds", None))

        should_display = (
            bool(target_province)
            and current_zoom > 14
            and bbox is not None
        )

        if not should_display:
            _cleanup_highres_layer()
            highres_request_ref.current = None
            return

        province_to_load = target_province
        request_key = (province_to_load, bbox)
        if highres_request_ref.current == request_key and highres_layer:
            return

        _cleanup_highres_layer()

        local_path, remote_url = _province_geojson_source(province_to_load)
        if not local_path and not remote_url:
            show_toast(
                f"No GeoJSON configured for province {province_to_load}",
                "warning",
            )
            return

        gdf = _read_province_geojson(local_path, remote_url)
        if gdf is None:
            show_toast(f"Failed to load {province_to_load} features.", "error")
            return

        if gdf.crs and gdf.crs.to_epsg() != 4326:
            try:
                gdf = gdf.to_crs(4326)
            except Exception:
                pass

        if bbox:
            west, south, east, north = bbox
            try:
                gdf = gdf.cx[west:east, south:north]
            except Exception:
                gdf = gdf[gdf.intersects(box(west, south, east, north))]

        if gdf.empty:
            _cleanup_highres_layer()
            highres_request_ref.current = None
            return

        data = json.loads(gdf.to_json())
        style = _build_highres_display_style()
        layer = ipyleaflet.GeoJSON(
            data=data,
            name=f"{province_to_load} (geo)",
            style=style,
            hover_style={
                "fillColor": "salmon",
                "color": "salmon",
                "weight": style["weight"] + 0.75,
                "fillOpacity": 0.9,
                "opacity": 1.0,
            },
        )

        def _normalize_click_coords(coords: Sequence[float]) -> tuple[float, float] | None:
            if not coords or len(coords) < 2:
                return None
            lat, lon = coords[0], coords[1]
            if abs(lat) > 90 and abs(lon) <= 90:
                lat, lon = coords[1], coords[0]
            return lat, lon

        def _on_click(event, feature, **kwargs):
            props = feature.get("properties") if isinstance(feature, dict) else {}
            props = dict(props or {})

            props.pop("style", None)
            props.pop("_style", None)
            props.pop("visual_style", None)

            show_date_palm_field_province_badge(m, props)

        layer.on_click(_on_click)
        if layer not in m.layers:
            m.add_layer(layer)
        set_highres_layer(layer)
        highres_request_ref.current = request_key
        _finish_loading(PRODUCT_DATEPALM_FIELDS)

    solara.use_effect(  # noqa: SH104
        _maybe_load_highres_layer,
        [
            active_product,
            selected_date_palm_province,
            current_zoom,
            cp_layer,
            raster_layer,
        ],
    )

    geojson_hint_ref = solara.use_ref(None)
    geojson_hint_shown_ref = solara.use_ref(False)
    tree_health_hint_ref = solara.use_ref(None)
    tree_health_hint_shown_ref = solara.use_ref(False)
    tree_health_hint_listener_attached = solara.use_ref(False)

    def _remove_geojson_hint():
        popup = geojson_hint_ref.current
        if popup and (popup in m.layers):
            try:
                m.remove_layer(popup)
            except Exception:
                pass
        geojson_hint_ref.current = None

    def _maybe_show_geojson_hint():
        if active_product != PRODUCT_DATEPALM_FIELDS:
            geojson_hint_shown_ref.current = False
            _remove_geojson_hint()
            return
        if not selected_date_palm_province or selected_date_palm_province == PROVINCE_NATIONAL:
            geojson_hint_shown_ref.current = False
            _remove_geojson_hint()
            return
        zoom = getattr(m, "zoom", None)
        if zoom is None or zoom < 15:
            geojson_hint_shown_ref.current = False
            _remove_geojson_hint()
            return
        if geojson_hint_shown_ref.current:
            return
        bounds = getattr(m, "bounds", None)

        if bounds and len(bounds) == 2:
            south, west = bounds[0]
            north, east = bounds[1]
            lat = north - (north - south) * 0.08
            lon = (west + east) / 2
            location = (lat, lon)
        else:
            center = getattr(m, "center", None) or (25.0, 45.0)
            location = (center[0], center[1]) if len(center) >= 2 else (25.0, 45.0)

        message = W.HTML(
            value=(
                "<div style='"
                "background: rgba(255,255,255,0.2);"
                "backdrop-filter: blur(6px);"
                "padding: 12px 21px;"
                "border-radius: 15px;"
                "border: 1px solid rgba(148,163,184,0.65);"
                "box-shadow: 0 8px 20px rgba(15,23,42,0.16);"
                "font-weight: 700;"
                "font-size: var(--font-popup);"
                "color: #0f172a;"
                "text-align: center;"
                "min-width: 420px;"
                "'>"
                ""
                "</div>"
            )
        )
        popup = ipyleaflet.Popup(
            location=location,
            child=message,
            close_button=True,
            auto_close=False,
            keep_in_view=False,
            min_width=420,
            max_width=520,
            class_name="tree-health-top-center-popup",
        )
        setattr(popup, "_is_geojson_hint", True)

        def _on_hint_close(*_):
            geojson_hint_shown_ref.current = False
            geojson_hint_ref.current = None

        try:
            popup.on_close(_on_hint_close)
        except Exception:
            pass
        try:
            m.add_layer(popup)
        except Exception:
            pass
        geojson_hint_ref.current = popup
        geojson_hint_shown_ref.current = True

    solara.use_effect(  # noqa: SH104
        _maybe_show_geojson_hint,
        [active_product, selected_date_palm_province, current_zoom],
    )

    def _remove_tree_health_hint():
        popup = tree_health_hint_ref.current
        if popup and (popup in m.layers):
            try:
                m.remove_layer(popup)
            except Exception:
                pass
        tree_health_hint_ref.current = None

    #def _maybe_show_tree_health_hint():
    #    if active_product != PRODUCT_TREE_HEALTH:
    #        tree_health_hint_shown_ref.current = False
    #        _remove_tree_health_hint()
    #        return
    #    if loading_message:
    #        tree_health_hint_shown_ref.current = False
    #        _remove_tree_health_hint()
    #        return
    #    if th_layer is None:
    #        tree_health_hint_shown_ref.current = False
    #        _remove_tree_health_hint()
    #        return
    #    if tree_health_hint_shown_ref.current:
    #        return

    #    #center = getattr(m, "center", None) or (25.0, 45.0)
    #    #location = (center[0], center[1]) if len(center) >= 2 else (25.0, 45.0)
    #    bounds = getattr(m, "bounds", None)

    #    if bounds and len(bounds) == 2:
    #        south, west = bounds[0]
    #        north, east = bounds[1]
    #        # top center of current visible map
    #        lat = north - (north - south) * 0.08
    #        lon = (west + east) / 2
    #        location = (lat, lon)
    #    else:
    #        center = getattr(m, "center", None) or (25.0, 45.0)
    #        location = (center[0], center[1]) if len(center) >= 2 else (25.0, 45.0)
    #        
    #    message = W.HTML(
    #        value=(
    #            "<div style='"
    #            "background: rgba(255,255,255,0.4);"
    #            "backdrop-filter: blur(6px);"
    #            "padding: 12px 21px;"
    #            "border-radius: 15px;"
    #            "border: 1px solid rgba(148,163,184,0.65);"
    #            "box-shadow: 0 8px 20px rgba(15,23,42,0.16);"
    #            "font-weight: 700;"
    #            "font-size: 1.5rem;"
    #            "color: #0f172a;"
    #            "text-align: center;"
    #            "min-width: 420px;"
    #            "'>"
    #            "Tree HEALTH: Geojson loaded, please click the points to check attribute information."
    #            "</div>"
    #        )
    #    )

    #    popup = ipyleaflet.Popup(
    #        location=location,
    #        child=message,
    ##        close_button=True,
    ###        auto_close=False,
    ####        keep_in_view=False,
    ####        min_width=420,
    ####        max_width=520,
    ####    )
    ####    setattr(popup, "_is_tree_health_hint", True)
####
###    #    def _on_hint_close(*_):
##    ##        tree_health_hint_shown_ref.current = False
#    ###        tree_health_hint_ref.current = None
####
###    #    try:
##    ##        popup.on_close(_on_hint_close)
#    ###    except Exception:
    ####        pass
####
###    #    try:
##    ##        m.add_layer(popup)
#    ###    except Exception:
    ####        pass
####
###    #    tree_health_hint_ref.current = popup
##    ##    tree_health_hint_shown_ref.current = True
####
###    #solara.use_effect(
##    #    _maybe_show_tree_health_hint,
#    #    [active_product, loading_message, th_layer],
    #)

    def _attach_tree_health_hint_dismiss():
        if tree_health_hint_listener_attached.current:
            return

        def _on_map_interact(**event):
            if event.get("type") != "click":
                return
            if active_product_ref.current != PRODUCT_TREE_HEALTH:
                return
            if not tree_health_hint_shown_ref.current:
                return
            tree_health_hint_shown_ref.current = False
            _remove_tree_health_hint()

        try:
            m.on_interaction(_on_map_interact)
            tree_health_hint_listener_attached.current = True
        except Exception:
            pass

    solara.use_effect(_attach_tree_health_hint_dismiss, [m, active_product])
    
    def _date_palm_hover_style():
        weight = float(getattr(CFG, "datepalms_province_hover_weight", 2.8))
        return {
            "fillColor": "salmon",
            "color": "salmon",
            "weight": weight,
            "fillOpacity": 0.8,
            "opacity": 1.0,
        }

    def _render_hover_highlight():
        existing = hover_layer_ref.current
        if existing and (existing in m.layers):
            try:
                m.remove_layer(existing)
            except Exception:
                pass
        hover_layer_ref.current = None
        if active_product != PRODUCT_DATEPALM_FIELDS or not hover_field_record:
            return
        geom = hover_field_record.geometry
        if not geom or geom.is_empty:
            return
        try:
            payload = {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {"field_id": hover_field_record.field_id},
            }
        except Exception:
            return
        layer = ipyleaflet.GeoJSON(
            data=payload,
            style=_date_palm_hover_style(),
            name="Date Palm hover",
        )
        hover_layer_ref.current = layer
        anchor: ipyleaflet.Layer | None = None
        for tile_layer in reversed(list(date_palm_tile_layers.values())):
            if tile_layer in m.layers:
                anchor = tile_layer
                break
        _insert_after(layer, anchor)

    solara.use_effect(
        _render_hover_highlight,
        [hover_field_record, active_product, cp_layer, raster_layer],
    )

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
            # This widget is rendered inside the popup by show_popup()
            return build_plotly_widget(df, title)
        except Exception as e:
            show_toast(str(e), "error")
            return W.HTML(f"<pre>{e}</pre>")

    def _build_group():
        if active_product != PRODUCT_SENSORS:
            return None, None, None
        try:
            group, bounds = load_icon_group_from_geojson(Path(debounced_geojson), m, refs.active_marker_ref, on_show_timeseries)
            return group, bounds, None
        except Exception as e:
            return None, None, str(e)

    icon_group, bounds, load_err = solara.use_memo(_build_group, [debounced_geojson, active_product])
    sensor_layer_ref = solara.use_ref(None)
    solara.use_effect(lambda: show_toast(load_err, "error") if load_err else None, [load_err])

    def _sync_markers():
        current_sensor_layer = sensor_layer_ref.current
        if not icon_group:
            if active_product != PRODUCT_SENSORS and current_sensor_layer in m.layers:
                try:
                    m.remove_layer(current_sensor_layer)
                except Exception:
                    pass
            return
        if current_sensor_layer is not None and current_sensor_layer is not icon_group and current_sensor_layer in m.layers:
            try:
                m.remove_layer(current_sensor_layer)
            except Exception:
                pass
        sensor_layer_ref.current = icon_group
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
        _finish_loading(PRODUCT_SENSORS)

        try:
            if hasattr(icon_group, "z_index"):
                icon_group.z_index = 10_000
        except Exception:
            pass

    solara.use_effect(_sync_markers, [icon_group, bounds, active_product])

    def _cleanup_sensor_layer():
        if active_product == PRODUCT_SENSORS:
            return
        sensor_layer = sensor_layer_ref.current
        if not sensor_layer:
            return
        if sensor_layer in m.layers:
            try:
                m.remove_layer(sensor_layer)
            except Exception:
                pass

    solara.use_effect(_cleanup_sensor_layer, [active_product, icon_group])

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
        if active_product != PRODUCT_CENTER_PIVOT:
            if cp_layer is not None and cp_layer in m.layers:
                try:
                    m.remove_layer(cp_layer)
                except Exception:
                    pass
            return
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

        if cp_layer not in m.layers:
            _insert_after(cp_layer, raster_layer)
        roi_bounds = _roi_to_bounds(getattr(CFG, "center_pivot_default_roi", None))
        _maybe_fit_product(PRODUCT_CENTER_PIVOT, roi_bounds)
        _finish_loading(PRODUCT_CENTER_PIVOT)

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
            for layer in date_palm_tile_layers.values():
                _remove(layer)
            return

        print("[DEBUG date palm sync]", dict(
            active_product=active_product,
            selected_province=selected_date_palm_province,
            current_zoom=current_zoom,
            tile_layers=len(date_palm_tile_layers),
            layers=[type(layer).__name__ for layer in m.layers],
        ))

        for layer in date_palm_tile_layers.values():
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
        if active_product != PRODUCT_DATEPALM:
            return
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
            _finish_loading(PRODUCT_DATEPALM)

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
        if active_product != PRODUCT_TREE_HEALTH:
            if th_layer in m.layers:
                try:
                    m.remove_layer(th_layer)
                except Exception:
                    pass
            clear_tree_health_highlight()
            return
        layer_to_use = th_layer
        if th_layer is None:
            layer, err = build_tree_health_layer(m=m, active_marker_ref=refs.active_marker_ref, fill_opacity=th_opacity)
            if err:
                show_toast(err, "error")
                set_th_layer(None)
                return
            set_th_layer(layer)
            layer_to_use = layer

        if layer_to_use is None:
            return

        for marker in getattr(layer_to_use, "layers", []):
            try:
                marker.fill_opacity = float(th_opacity)
                marker.opacity = float(th_opacity)
            except Exception:
                pass

        anchor: ipyleaflet.Layer | None = cp_layer if (cp_layer and cp_layer in m.layers) else raster_layer
        for layer in (dp_layer_full, dp_layer_simple):
            if layer and (layer in m.layers):
                anchor = layer
                break
        if layer_to_use not in m.layers:
            _insert_after(layer_to_use, anchor)
        _maybe_fit_product(PRODUCT_TREE_HEALTH, getattr(layer_to_use, "_bounds", None))
        _finish_loading(PRODUCT_TREE_HEALTH)

    solara.use_effect(_ensure_th_layer, [active_product, dp_layer_full, dp_layer_simple, cp_layer, raster_layer, th_opacity])

    # -------------------------
    # Keep sensors on top whenever either overlay (CPF/DP) changes
    # -------------------------
    def _float_sensors_top():
        if active_product != PRODUCT_SENSORS:
            return
        sensor_layer = sensor_layer_ref.current
        if sensor_layer and (sensor_layer in m.layers):
            try:
                m.remove_layer(sensor_layer)
            except Exception:
                pass
            m.add_layer(sensor_layer)

    solara.use_effect(_float_sensors_top, [icon_group, cp_layer, dp_layer_full, dp_layer_simple, th_layer, active_product])

    def _select_product(product: str):
        if product == active_product:
            return

        _clear_popups()

        # 1. Move map immediately while the old layer is still visible.
        _precenter_product(product)

        # 2. Then show loading state.
        loading_product_ref.current = product
        set_loading_message("Data Loading ...")

        # 3. Still request final fit after data loads, in case exact bounds differ.
        if product != PRODUCT_DATEPALM_FIELDS:
            _request_fit(product)

        # 4. Trigger product/layer change.
        set_active_product(product)

    def _product_button_style(product: str):
        active = product == active_product or (
            product == PRODUCT_DATEPALM_FIELDS and active_product == PRODUCT_FIELD_DENSITY
        )
        base = {
            "borderRadius": "999px",
            "padding": "var(--panel-button-padding-y) var(--panel-button-padding-x)",
            "width": "100%",
            "textAlign": "left",
            "justifyContent": "flex-start",
            "fontWeight": "600",
            "fontSize": "var(--font-button)",
            "overflowWrap": "anywhere",
            "wordBreak": "break-word",
            "whiteSpace": "normal",
            "lineHeight": "1.25",
            "minHeight": "clamp(34px, 4.5vh, 52px)",
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

    # Main vertical layout for the geoportal page: header, controls, map, and notifications.
    # Main split layout: left controls, draggable divider, right map.
    with solara.Column(gap="0.75rem", style={"height": "100vh", "width": "100%"}):
        solara.Markdown(
            "### 🌴 Geoportal for Date Palm Field Informatics",
            style={
                "fontSize": "var(--font-page-title)",
                "fontWeight": "700",
                "color": "#272828",
                "lineHeight": "1.2",
            },
        )

        with solara.Div(
            style={
                "display": "flex",
                "flexDirection": "row",
                "width": "100%",
                "height": "calc(100vh - 70px)",
                "overflow": "hidden",
            }
        ):
            # LEFT PANEL: files/products/settings/buttons
            with solara.Div(
                classes=["geoportal-left-panel"],
                style={
                    "width": "var(--left-panel-width)",
                    "minWidth": "240px",
                    "maxWidth": "55vw",
                    "height": "100%",
                    "overflowY": "auto",
                    "resize": "horizontal",
                    "paddingRight": "0.75rem",
                    "boxSizing": "border-box",
                    "borderRight": "2px solid #cbd5e1",
                }
            ):
                with solara.Card("", style={"padding": "1px"}):
                    with solara.Column(
                        gap="0.05rem",  # 👈 controls vertical gap (reduce this)
                        style={
                            "marginBottom": "0px",
                        },
                    ):
                        solara.Switch(
                            label="Force GCS for server-side asset reads"
                            + (" (tiles stay external in production)" if IS_PRODUCTION else ""),
                            value=force_gcs,
                            on_value=set_force_gcs_state,
                        )

                        solara.Markdown(
                            f"Mode: {'GCS only for direct asset reads' if force_gcs else 'Local first, GCS fallback'}  \n"
                            f"Deploy: {'production' if IS_PRODUCTION else 'development'}",
                            style={
                                "fontSize": "var(--font-body)",
                                "color": "#475569",
                                "marginTop": "-20px",
                                "lineHeight": "1.05",  # 👈 tighter line spacing
                            },
                        )
                        
                        solara.Markdown(
                            "**Products**",
                            style={
                                "fontSize": "var(--font-panel-title)",
                                "marginTop": "0.75rem", 
                                "color": "#424345",
                            },
                        )

                    with solara.Column(
                        gap="0.45rem",
                        style={"width": "100%"},
                    ):
                        for product in PRODUCT_ORDER:
                            solara.Button(
                                PRODUCT_SHORT_LABELS.get(product, PRODUCT_LABELS.get(product, product)),
                                text=True,
                                classes=["geoportal-product-button"],
                                on_click=lambda event=None, product=product: _select_product(product),
                                style={**_product_button_style(product), "width": "100%"},
                            )

                    controls_widget = _product_controls(active_product) if active_product else None

                    legend_items = []
                    if active_product:
                        legend_extra = _product_legend(active_product)
                        if legend_extra:
                            legend_items.append(legend_extra)

                    legend_widget = solara.Column(children=legend_items) if legend_items else None

                    if controls_widget:
                        solara.Div(
                            style={"width": "100%", "marginTop": "0.75rem"},
                            children=[controls_widget],
                        )

                    if legend_widget:
                        solara.Div(
                            style={"width": "100%", "marginTop": "0.75rem"},
                            children=[legend_widget],
                        )

                    summary_widget = _product_summary(active_product)
                    if summary_widget:
                        summary_widget

            # RIGHT PANEL: map
            with solara.Div(
                style={
                    "flex": "1 1 auto",
                    "height": "100%",
                    "position": "relative",
                    "overflow": "hidden",
                    "paddingLeft": "0.75rem",
                    "boxSizing": "border-box",
                }
            ):
                solara.Style("""
                             
                             
                    :root {
                        --left-panel-width: clamp(260px, 30vw, 520px);

                        --font-page-title: clamp(1.1rem, 1.2vw + 0.6rem, 2rem);
                        --font-popup: clamp(1rem, 1vw + 0.6rem, 1.6rem);

                        --panel-button-padding-y: clamp(0.35rem, 0.35vw, 0.65rem);
                        --panel-button-padding-x: clamp(0.65rem, 0.75vw, 1.25rem);
                    }

                    .geoportal-left-panel {
                        width: var(--left-panel-width);
                        min-width: 240px;
                        max-width: 55vw;
                        container-type: inline-size;
                        --font-panel-title: clamp(1.05rem, 7cqw, 1.6rem);
                        --font-section-title: clamp(0.9rem, 4.2cqw, 1.15rem);
                        --font-body: clamp(0.78rem, 3.4cqw, 1rem);
                        --font-button: clamp(0.78rem, 3.7cqw, 1.08rem);
                        --font-small: clamp(0.7rem, 2.8cqw, 0.9rem);
                    }
                    

                    .geoportal-panel-title {
                        font-size: var(--font-panel-title) !important;
                    }

                    .geoportal-panel-text {
                        font-size: var(--font-body) !important;
                    }

                    .geoportal-product-button {
                        width: 100% !important;
                        font-size: var(--font-button) !important;
                        line-height: 1.18 !important;
                        white-space: normal !important;
                        overflow-wrap: anywhere !important;
                        word-break: break-word !important;
                        text-align: left !important;
                    }

                    /* 🔥 Force inner Solara/Vuetify button content */
                    .geoportal-product-button *,
                    .geoportal-product-button .v-btn__content,
                    .geoportal-product-button button,
                    .geoportal-product-button span {
                        font-size: var(--font-button) !important;
                        line-height: 1.18 !important;
                        white-space: normal !important;
                        overflow-wrap: anywhere !important;
                        word-break: break-word !important;
                    }

                    /* Align text properly inside button */
                    .geoportal-product-button .v-btn__content {
                        width: 100% !important;
                        justify-content: flex-start !important;
                    }

                    .geoportal-province-grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(clamp(120px, 45%, 220px), 1fr));
                        gap: clamp(0.35rem, 0.7vw, 1rem);
                        width: 100%;
                    }

                    @media (max-width: 900px) {
                        .geoportal-left-panel {
                            width: 38vw;
                            max-width: 65vw;
                        }
                    }

                    @media (max-width: 650px) {
                        .geoportal-left-panel {
                            width: 100%;
                            max-width: 100%;
                            resize: none;
                        }
                    }
                    
                    .leaflet-container {
                        width: 100% !important;
                        height: calc(100vh - 90px) !important;
                    }

                    .leaflet-control .tree-health-attr-badge,
                    .leaflet-control .widget-box.tree-health-attr-badge,
                    .leaflet-control .jupyter-widgets.tree-health-attr-badge,
                    .leaflet-control .datepalm-field-attr-badge,
                    .leaflet-control .widget-box.datepalm-field-attr-badge,
                    .leaflet-control .jupyter-widgets.datepalm-field-attr-badge {
                        background: rgba(255,255,255,0.20) !important;
                        backdrop-filter: blur(6px) !important;
                        -webkit-backdrop-filter: blur(6px) !important;
                        border: 1px solid rgba(148,163,184,0.25) !important;
                        border-radius: 12px !important;
                        box-shadow: 0 8px 24px rgba(15,23,42,0.10) !important;
                    }

                    .leaflet-control .sensor-attr-badge,
                    .leaflet-control .widget-box.sensor-attr-badge,
                    .leaflet-control .jupyter-widgets.sensor-attr-badge {
                        background: rgba(255,255,255,0.20) !important;
                        backdrop-filter: blur(4px) !important;
                        -webkit-backdrop-filter: blur(4px) !important;
                        border: 1px solid rgba(148,163,184,0.25) !important;
                        border-radius: 12px !important;
                        box-shadow: 0 8px 24px rgba(15,23,42,0.10) !important;
                    }

                    .leaflet-top.leaflet-right {
                        display: flex;
                        flex-direction: column;
                        align-items: flex-end;
                    }

                    .leaflet-top.leaflet-right .leaflet-control-layers {
                        order: 1;
                        margin-bottom: 8px;
                    }

                    .leaflet-top.leaflet-right .leaflet-control:has(.raster-legend-panel),
                    .leaflet-top.leaflet-right .leaflet-control:has(.field-density-legend-panel),
                    .leaflet-top.leaflet-right .leaflet-control:has(.tree-health-legend-panel) {
                        order: 2;
                    }

                    .leaflet-control .national-figure-panel {
                        background: rgba(255,255,255,0.20) !important;
                        backdrop-filter: blur(6px);
                        border-radius: 10px;
                        box-shadow: 0 8px 24px rgba(15,23,42,0.12);
                    }

                    .leaflet-control .widget-box.national-figure-panel,
                    .leaflet-control .jupyter-widgets.national-figure-panel {
                        background: rgba(255,255,255,0.20) !important;
                    }

                    .leaflet-popup.tree-health-top-center-popup {
                        margin-left: -210px !important;
                        margin-top: 0 !important;
                    }

                    .leaflet-popup.tree-health-top-center-popup .leaflet-popup-tip-container {
                        display: none !important;
                    }

                    .leaflet-popup.tree-health-top-center-popup .leaflet-popup-content-wrapper {
                        background: transparent !important;
                        box-shadow: none !important;
                        border: none !important;
                        padding: 0 !important;
                    }

                    .leaflet-popup.tree-health-top-center-popup .leaflet-popup-content {
                        margin: 0 !important;
                    }
                """)

                solara.display(m)
                _loading_badge()

        Toast(
            message=toast_state["message"],
            kind=toast_state["kind"],
            visible=toast_state["visible"],
            on_close=hide_toast,
        )
    return
