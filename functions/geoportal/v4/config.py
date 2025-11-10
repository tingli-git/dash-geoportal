# functions/geoportal/v3/config.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any  # <-- needed for cpf_style/hover_style types

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

    # --- Local XYZ tiles (filesystem source) ---
    # This is the folder you are already serving with: `python -m http.server 8766`
    default_tiles_dir: Path = Path(
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server"
    )
    raster_layer_name: str = "Tree-Vege-NonVege Classification"
    raster_opacity_default: float = 0.75
    raster_max_zoom: int = 14  # 10 m → ~14 native; 15 looks smoother (oversample)

    # Manual external tiles server (like your existing Python HTTP server)
    # NOTE: no trailing slash; this value is used as a full base for XYZ (z/x/y) tiles.
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

    # --- Timeseries plotting parameters ---
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
            palette_name="kaarten_ova",
            colors=[],
            line_width=2.0,
            # Zebra bands
            band_fill_rgba_even="rgba(0,0,0,0.02)",
            band_fill_rgba_odd="rgba(0,0,0,0.05)",
        )
    )

    # ============================================================
    # Center-Pivot Fields (CPF) – Yearly GeoJSON configuration
    # ============================================================
    # Directory on disk with CPF GeoJSONs
    cpf_geojson_dir: Path = Path("/datawaha/esom/DatePalmCounting/Geoportal/Center_pivot/year_base_consistent")

    # Serve CPF over the SAME Python HTTP server as XYZ tiles:
    # Put a folder (e.g., "center_pivot") under the same server root and point here.
    # Example URL you can open in browser to test:
    #   http://127.0.0.1:8766/center_pivot/CPF_fields_2023_simpl.geojson
    cpf_http_base: str = "http://127.0.0.1:8766/center_pivot"

    # Years available for the slider
    cpf_years: list[int] = field(
        default_factory=lambda: [1990, 1995, 2000, 2005, 2010, 2015, 2016, 2017, 2018, 2019,
                                 2020, 2021, 2022, 2023]
    )

    # Filename templates to try (prefer simplified; accept the historical "fileds" typo)
    cpf_filename_templates: list[str] = field(
        default_factory=lambda: [
            "CPF_fields_{year}_simpl.geojson",
            "CPF_fileds_{year}_simpl.geojson",
            "CPF_fields_{year}.geojson",
            "CPF_fileds_{year}.geojson",
        ]
    )

    # Layer/UI options
    cpf_layer_name: str = "Center-Pivot Fields"
    cpf_slider_width: str = "420px"
    cpf_start_latest: bool = True

    # Light green polygon styling
    cpf_style: dict[str, Any] = field(
        default_factory=lambda: {
            "color": "#6BBF59",      # stroke
            "weight": 1,
            "opacity": 0.8,
            "fillColor": "#90EE90",  # light green
            "fillOpacity": 0.35,
        }
    )
    cpf_hover_style: dict[str, Any] = field(
        default_factory=lambda: {
            "weight": 2,
            "opacity": 1.0,
            "fillOpacity": 0.5,
        }
    )

    # Fit bounds behavior for CPF (if/when used)
    cpf_fit_bounds_max_zoom: int = 12
    cpf_fit_bounds_padding: tuple[int, int] = (20, 20)

CFG = Config()
