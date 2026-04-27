from __future__ import annotations
import os
# functions/geoportal/v14/config.py
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

DEFAULT_TOP_DIR = Path("/datawaha/esom/DatePalmCounting/Geoportal")
TOP_DIR = Path(os.environ.get("GEOPORTAL_TOP_DIR", str(DEFAULT_TOP_DIR)))
APP_SERVER_ROOT = Path(
    os.environ.get("LOCAL_ASSET_ROOT", str(TOP_DIR / "Datepalm" / "app_server"))
)
APP_MODE = os.environ.get("GEOPORTAL_MODE", "development").strip().lower()
ASSET_BASE_URL = os.environ.get("APP_ASSET_BASE_URL", "/static/assets").rstrip("/")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "ksa_datepalm").strip()
GCS_ASSET_PREFIX = os.environ.get("GCS_ASSET_PREFIX", "app_server").strip("/")
PUBLIC_ASSET_BASE_URL = (
    f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{GCS_ASSET_PREFIX}"
    if GCS_ASSET_PREFIX
    else f"https://storage.googleapis.com/{GCS_BUCKET_NAME}"
)
PUBLIC_DATEPALMS_TILE_BASE_URL = (
    f"{PUBLIC_ASSET_BASE_URL}/datepalms_tiles"
)

@dataclass(frozen=True)
class Config:
    # --- App & map basics ---
    top_dir: Path = TOP_DIR
    app_mode: str = APP_MODE
    app_server_root: Path = APP_SERVER_ROOT
    auth_username: str = os.environ.get("GEOPORTAL_AUTH_USERNAME", "").strip()
    auth_password: str = os.environ.get("GEOPORTAL_AUTH_PASSWORD", "").strip()
    default_geojson: Path = APP_SERVER_ROOT / "Aldka" / "SensorInfos" / "AldakaSensors.geojson"
    map_center: tuple[float, float] = (24.0, 45.0)
    map_zoom: int = 6
    map_height: str = "90vh"
    map_width: str = "100%"

    # Marker icon defaults
    icon_name: str = "tint"
    icon_color_default: str = "blue"
    icon_color_active: str = "lightred"
    icon_icon_color: str = "white"

    # Layers & fit options
    layer_group_name: str = "Sensors in AlDka"
    fit_bounds_max_zoom: int = 16
    fit_bounds_padding: tuple[int, int] = (20, 20)

    # --- Timeseries CSVs ---
    sensor_csv_dir: Path = APP_SERVER_ROOT / "Aldka" / "SensorReads"
    time_col_candidates: tuple[str, ...] = ("timestamp", "time", "datetime", "date", "Date Time")
    # --- NDVI time series for Date Palm polygons ---
    # CSVs named as <Field_id>.csv with 2 columns: [date, ndvi_median]
    ndvi_csv_dir: Path = APP_SERVER_ROOT / "ndvi_timeseries_csvs"
    # Optional HTTP base if you prefer loading via http.server
    ndvi_http_base: str = os.environ.get("NDVI_HTTP_BASE", f"{ASSET_BASE_URL}/ndvi_timeseries_csvs")
    ndvi_public_http_base: str = os.environ.get("NDVI_PUBLIC_HTTP_BASE", f"{PUBLIC_ASSET_BASE_URL}/ndvi_timeseries_csvs")

    # --- Local XYZ tiles (filesystem source) ---
    default_tiles_dir: Path = APP_SERVER_ROOT / "38RLQ_2024"
    raster_layer_name: str = "Tree-Vege-NonVege Classification"
    raster_opacity_default: float = 0.75
    raster_max_zoom: int = 14  # 10 m → ~14 native; 15 looks smoother (oversample)
    datepalms_default_opacity: float = 0.55

    # Manual external tiles server
    tiles_http_base: str = os.environ.get("RASTER_TILES_HTTP_BASE", f"{ASSET_BASE_URL}/38RLQ_2024")
    tiles_public_http_base: str = os.environ.get("RASTER_TILES_PUBLIC_HTTP_BASE", f"{PUBLIC_ASSET_BASE_URL}/38RLQ_2024")

    # -----------------------------
    # Raster Legend Configuration
    # -----------------------------
    raster_legend_title: str = "Tree–Vege–NonVege Classification"
    raster_legend_enabled: bool = True
    raster_legend: list[dict] = field(
        default_factory=lambda: [
            {"name": "Non-vegetation",        "color": "#FDAE61"},
            {"name": "Non-tree vegetation",   "color": "#FFFFBF"},
            {"name": "Trees",                 "color": "#ABDDA4"},
        ]
    )

    # --- Timeseries plotting parameters (single source of truth) ---
    timeseries: SimpleNamespace = field(
        default_factory=lambda: SimpleNamespace(
            width=1800,
            band_height_px=100,
            gap_frac=0.0,
            max_layers=9,
            reverse_depth=True,
            show_background_bands=True,
            # Typography
            font_family="Arial",
            font_size=14,
            title_font_size=20,
            # Palette
            palette_name="kaarten_ova",   # "kaarten_ova", "okabe_ito", "tol_bright"
            colors=[],                    # if non-empty, overrides palette_name
            line_width=2.0,
            # Zebra bands (bottom stacked subplot)
            band_fill_rgba_even="rgba(0,0,0,0.02)",
            band_fill_rgba_odd="rgba(0,0,0,0.05)",

            # -----------------------------
            # TOP SUBPLOT: Soil moisture config
            # -----------------------------
            # Column to use for the top single time-series
            sm_column="soil_moisture_root_zone",
            # Thresholds in PERCENT (ascending). Regions are:
            #   [0, t0) → warning, [t0, t1) → stress, [t1, t2) → normal, [t2, +inf) → saturated
            sm_region_thresholds=[26.0, 28.0, 40.0],
            # Region fill colors (CSS color names or rgba/hex), same order as regions above
            sm_region_colors=["#F076A9", "#F3D421", "#ADF69E", "#3E88E9"],

            # Optional labels for legend/tooling (not rendered by default)
            sm_region_labels=[
                "Warning (<26%)",
                "Stress (26–28%)",
                "Normal (28–40%)",
                "Water saturated (>40%)",
            ],
            # Axis behavior for the top subplot
            sm_top_ylim_min=0.0,          # lower y bound
            sm_top_min_ceiling=45.0,      # ensure top is at least this (so >40% band is visible)
            sm_top_ylim_pad=5.0,          # extra headroom above max
        )
    )

    # --- Center-Pivot (CPF) datasets ---
    center_pivot_dir: Path = APP_SERVER_ROOT / "center_pivot"
    center_pivot_http_base: str = os.environ.get("CENTER_PIVOT_HTTP_BASE", f"{ASSET_BASE_URL}/center_pivot")
    center_pivot_public_http_base: str = os.environ.get("CENTER_PIVOT_PUBLIC_HTTP_BASE", f"{PUBLIC_ASSET_BASE_URL}/center_pivot")
    center_pivot_tiles_dir: Path = APP_SERVER_ROOT / "cpf_tiles"
    center_pivot_tile_base_url: str = os.environ.get(
        "CENTER_PIVOT_TILE_BASE_URL",
        f"{ASSET_BASE_URL}/cpf_tiles",
    )
    center_pivot_tile_public_base_url: str = os.environ.get(
        "CENTER_PIVOT_TILE_PUBLIC_BASE_URL",
        f"{PUBLIC_ASSET_BASE_URL}/cpf_tiles",
    )
    center_pivot_tile_url_template: str = "{base}/{year}/{z}/{x}/{y}.pbf"
    center_pivot_layer_name: str = "Center-Pivot Fields"
    center_pivot_years: tuple[int, ...] = (1990,1995,2000,2005,2010,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024)
    center_pivot_default_year: int = 2024
    cpf_change_dir: Path = APP_SERVER_ROOT / "cpf_dynamic"
    cpf_change_expanding_raster: Path = APP_SERVER_ROOT / "cpf_dynamic" / "KSA_cpf_expanding_classified.tif"
    cpf_change_contraction_raster: Path = APP_SERVER_ROOT / "cpf_dynamic" / "KSA_cpf_contraction_classified.tif"
    cpf_change_expanding_layer_name: str = "CPF Expanding Dynamic"
    cpf_change_contraction_layer_name: str = "CPF Contraction Dynamic"
    cpf_change_default_opacity: float = 0.82
    cpf_change_legend_title: str = "Center-Pivot change detection"
    cpf_change_legend: list[dict] = field(
        default_factory=lambda: [
            {"label": "≤1990", "value": 1, "color": "#66C1A4"},
            {"label": "1990–2000", "value": 2, "color": "#785EF0"},
            {"label": "2000–2010", "value": 3, "color": "#DC267F"},
            {"label": "2010–2020", "value": 4, "color": "#FE6100"},
            {"label": ">2020", "value": 5, "color": "#FFB000"},
        ]
    )

    # Optional default ROI clipping (lat_min, lon_min, lat_max, lon_max)
    center_pivot_default_roi: tuple[float, float, float, float] = (24.0, 40.0, 28.0, 45.0)

    # --- Tree health points ---
    tree_health_geojson_file: Path = APP_SERVER_ROOT / "TreeHealth" / "tree_health.geojson"
    tree_health_layer_name: str = "Tree Health"
    tree_health_point_radius: float = 4.0
    tree_health_fill_opacity: float = 0.75
    tree_health_stroke_weight: float = 1.0
    tree_health_color_healthy: str = "#66C2A5"
    tree_health_color_infested: str = "#D1495B"
    tree_health_color_default: str = "#8C8C8C"
    tree_health_active_color: str = "#F97316"
    tree_health_healthy_count: int | None = 650
    tree_health_infested_count: int | None = 14
    tree_health_total_count: int | None = 664
    popup_offset_ratio: float = 0.1

    # --- Date Palm Fields Qassim Manual (Qassim) — single GeoPackage file ---
    datepalms_gpkg_file: Path = APP_SERVER_ROOT / "datepalms" / "Qassim_datepalm_fields_polygons.gpkg"
    datepalms_geojson_file: Path = APP_SERVER_ROOT / "datepalms" / "Qassim_datepalm_fields_polygons.geojson"
    datepalms_http_base: str = os.environ.get("DATEPALMS_HTTP_BASE", f"{ASSET_BASE_URL}/datepalms")
    datepalms_http_url: str = os.environ.get("DATEPALMS_HTTP_URL", f"{ASSET_BASE_URL}/datepalms/Qassim_datepalm_fields_polygons.geojson")
    datepalms_public_http_base: str = os.environ.get("DATEPALMS_PUBLIC_HTTP_BASE", f"{PUBLIC_ASSET_BASE_URL}/datepalms")
    datepalms_public_http_url: str = os.environ.get("DATEPALMS_PUBLIC_HTTP_URL", f"{PUBLIC_ASSET_BASE_URL}/datepalms/Qassim_datepalm_fields_polygons.geojson")
    datepalms_layer_name: str = "Date Palm Fields Qassim Manual"
    datepalms_enabled: bool = True
    sensor_opacity_default: float = 1.0
    datepalms_simplify_tolerance: float | None = 0.0008
    datepalms_province_dir: Path = APP_SERVER_ROOT / "datepalms_per_province"
    datepalms_province_http_base: str = os.environ.get("DATEPALMS_PROVINCE_HTTP_BASE", f"{ASSET_BASE_URL}/datepalms_per_province")
    datepalms_province_public_http_base: str = os.environ.get("DATEPALMS_PROVINCE_PUBLIC_HTTP_BASE", f"{PUBLIC_ASSET_BASE_URL}/datepalms_per_province")
    datepalms_tile_cache_dir: Path = APP_SERVER_ROOT / "datepalms_tile_cache"
    datepalms_province_fill_color: str = "#64ff11"
    datepalms_province_edge_color: str = "#5ea700"
    datepalms_province_edge_weight: float = 2.0
    datepalms_province_fill_opacity: float = 0.4
    datepalms_province_hover_weight: float = 2.8
    datepalms_province_simplify_tolerance: float = 0.0015
    datepalms_tile_zoom_threshold: int = 16
    datepalms_tile_layer_name: str = "Date Palm Fields"
    datepalms_tiles_dir: Path = APP_SERVER_ROOT / "datepalms_tiles"
    datepalms_province_lookup_json: Path = APP_SERVER_ROOT / "datepalms_provinces.json"
    datepalms_province_names: tuple[str, ...] = (
        "Al_Bahah",
        "Al_Jawf",
        "Al_Madinah",
        "Al_Quassim",
        "Ar_Riyad",
        "Asir",
        "Eastern_Province",
        "Hail",
        "Jizan",
        "Makkah",
        "Najran",
        "Northern_Borders",
        "Tabuk",
    )
    # --- KSA bounds polygon 
    ksa_bounds_gpkg: Path = APP_SERVER_ROOT / "ksa_bounds" / "KSA_provincebounds.gpkg"
    ksa_bounds_http_base: str = os.environ.get("KSA_BOUNDS_HTTP_BASE", f"{ASSET_BASE_URL}/ksa_bounds")
    ksa_bounds_http_url: str = os.environ.get("KSA_BOUNDS_HTTP_URL", f"{ASSET_BASE_URL}/ksa_bounds/KSA_provincebounds.gpkg")
    ksa_bounds_public_http_base: str = os.environ.get("KSA_BOUNDS_PUBLIC_HTTP_BASE", f"{PUBLIC_ASSET_BASE_URL}/ksa_bounds")
    ksa_bounds_public_http_url: str = os.environ.get("KSA_BOUNDS_PUBLIC_HTTP_URL", f"{PUBLIC_ASSET_BASE_URL}/ksa_bounds/KSA_provincebounds.gpkg")
    ksa_bounds_layer_source: str = "KSA_provincebounds"
    
    ksa_bounds_layer_name: str = "KSA bounds"
    ksa_bounds_edge_color: str = "#cbd5f5"
    ksa_bounds_edge_weight: float = 1.5
    ksa_bounds_hover_weight: float = 2.0
    # --- Date palm polygon 
    datepalms_tile_base_url: str = os.environ.get("DATEPALMS_TILE_BASE_URL", f"{ASSET_BASE_URL}/datepalms_tiles")
    datepalms_tile_public_base_url: str = os.environ.get(
        "DATEPALMS_TILE_PUBLIC_BASE_URL",
        PUBLIC_DATEPALMS_TILE_BASE_URL,
    )
    datepalms_tile_url_template: str = "{base}/{province}/{z}/{x}/{y}.pbf"
    datepalms_tiles_max_zoom: int = 17
    # --- Field density
    field_density_dir: Path = APP_SERVER_ROOT / "datepalms_density"
    field_density_layer_name: str = "Field density"
    field_density_default_opacity: float = 0.78
    field_density_legend_title: str = "Date palm coverage \n (km<sup>2</sup> per 25 km<sup>2</sup> cell)"
    field_density_legend: list[dict] = field(
        default_factory=lambda: [
            {"label": "0-0.1", "min": 0.0, "max": 0.1, "color": "#B7DBFF"},
            {"label": "0.1-0.2", "min": 0.1, "max": 0.2, "color": "#3E9CFE"},
            {"label": "0.2-0.3", "min": 0.2, "max": 0.3, "color": "#48F882"},
            {"label": "0.3-0.4", "min": 0.3, "max": 0.4, "color": "#E2DC38"},
            {"label": "0.4-0.5", "min": 0.4, "max": 0.5, "color": "#EF5908"},
            {"label": "> 0.5", "min": 0.5, "max": None, "color": "#FA60E4"},
        ]
    )
    raster_tile_ext: str = os.environ.get("RASTER_TILE_EXT", "png")
    raster_tile_min_zoom: int = int(os.environ.get("RASTER_TILE_MIN_ZOOM", "0"))
    raster_tile_max_zoom_default: int = int(os.environ.get("RASTER_TILE_MAX_ZOOM", "14"))

    datepalms_national_figure_file: Path = APP_SERVER_ROOT / "Figs" / "FieldAcreageByProvince.png"

CFG = Config()
