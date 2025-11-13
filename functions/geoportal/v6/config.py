# functions/geoportal/v6/config.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

@dataclass(frozen=True)
class Config:
    # --- App & map basics ---
    top_dir: Path = Path("/datawaha/esom/DatePalmCounting/Geoportal")
    default_geojson: Path = Path("/datawaha/esom/DatePalmCounting/Geoportal/Sensors/SensorInfos/AldakaSensors.geojson")
    map_center: tuple[float, float] = (29.0, 40.0)
    map_zoom: int = 5
    map_height: str = "90vh"
    map_width: str = "100%"

    # Marker icon defaults
    icon_name: str = "tint"
    icon_color_default: str = "blue"
    icon_color_active: str = "lightred"
    icon_icon_color: str = "white"

    # Layers & fit options
    layer_group_name: str = "Sensors in AlDka"
    fit_bounds_max_zoom: int = 14
    fit_bounds_padding: tuple[int, int] = (20, 20)

    # --- Timeseries CSVs ---
    sensor_csv_dir: Path = Path("/datawaha/esom/DatePalmCounting/Geoportal/Sensors/SensorReads/")
    time_col_candidates: tuple[str, ...] = ("timestamp", "time", "datetime", "date", "Date Time")
    # --- NDVI time series for Date Palm polygons ---
    # CSVs named as <Field_id>.csv with 2 columns: [date, ndvi_median]
    ndvi_csv_dir: Path = Path(
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/ndvi_timeseries_csvs"
    )
    # Optional HTTP base if you prefer loading via http.server
    ndvi_http_base: str = "http://127.0.0.1:8766/ndvi_timeseries_csvs"

    # --- Local XYZ tiles (filesystem source) ---
    default_tiles_dir: Path = Path(
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/38RLQ_2024"
    )
    raster_layer_name: str = "Tree-Vege-NonVege Classification"
    raster_opacity_default: float = 0.75
    raster_max_zoom: int = 14  # 10 m → ~14 native; 15 looks smoother (oversample)

    # Manual external tiles server
    tiles_http_base: str = "http://127.0.0.1:8766/38RLQ_2024"

    # -----------------------------
    # Raster Legend Configuration
    # -----------------------------
    raster_legend_title: str = "Tree–Vege–Bare"
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

    # --- Center-Pivot (CPF) GeoJSONs ---
    center_pivot_dir: Path = Path(
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/center_pivot"
    )
    center_pivot_http_base: str = "http://127.0.0.1:8766/center_pivot"
    center_pivot_layer_name: str = "Center-Pivot Fields"
    center_pivot_years: tuple[int, ...] = (1995,2000,2005,2010,2015,2016,2017,2018,2019,2020,2021,2022,2023)
    center_pivot_default_year: int = 2023

    # Optional default ROI clipping (lat_min, lon_min, lat_max, lon_max)
    center_pivot_default_roi: tuple[float, float, float, float] = (24.0, 40.0, 28.0, 45.0)

    # --- Date Palm Fields (Qassim) — single GeoJSON file ---
    datepalms_geojson_file: Path = Path(
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms/Qassim_datepalm_fields_polygons.geojson"
    )
    datepalms_http_base: str = "http://127.0.0.1:8766/datepalms"
    datepalms_http_url: str = "http://127.0.0.1:8766/datepalms/Qassim_datepalm_fields_polygons.geojson"
    datepalms_layer_name: str = "Date Palm Fields"
    datepalms_enabled: bool = True


CFG = Config()
