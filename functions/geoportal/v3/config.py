# functions/geoportal/v3/config.py
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

    # --- Local XYZ tiles (filesystem source) ---
    default_tiles_dir: Path = Path(
        "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/tile_rasters/38RLQ_2024"
    )
    raster_layer_name: str = "Tree-Vege-NonVege Classification"
    raster_opacity_default: float = 0.75
    raster_max_zoom: int = 14  # 10 m → ~14 native; 15 looks smoother (oversample)

    # Manual external tiles server (run yourself, e.g. `python -m http.server 8766` in the tiles dir)
    # NOTE: no trailing slash to avoid double slashes in TileLayer URL.
    tiles_http_base: str = "http://127.0.0.1:8766"

    # -----------------------------
    # Raster Legend Configuration
    # -----------------------------
    raster_legend_title: str = "Tree–Vege–Bare"
    raster_legend_enabled: bool = True
    raster_legend: list[dict] = field(
        default_factory=lambda: [
            {"name": "Non-vegetation",        "color": "#FDAE61"},  # 253,174,97
            {"name": "Non-tree vegetation",   "color": "#FFFFBF"},  # 255,255,191
            {"name": "Trees",                 "color": "#ABDDA4"},  # 171,221,164
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
            # Zebra bands
            band_fill_rgba_even="rgba(0,0,0,0.02)",
            band_fill_rgba_odd="rgba(0,0,0,0.05)",
        )
    )

CFG = Config()
