# functions/geoportal/v2/config.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

@dataclass(frozen=True)
class Config:
    top_dir: Path = Path("/datawaha/esom/DatePalmCounting/Geoportal")
    default_geojson: Path = Path("/datawaha/esom/DatePalmCounting/Geoportal/Sensors/SensorInfos/AldakaSensors.geojson")
    map_center: tuple[float, float] = (29.0, 40.0)
    map_zoom: int = 5
    map_height: str = "90vh"
    map_width: str = "100%"
    icon_name: str = "tint"
    icon_color_default: str = "blue"
    icon_color_active: str = "lightred"
    icon_icon_color: str = "white"
    layer_group_name: str = "Sensors in AlDka"
    fit_bounds_max_zoom: int = 14
    fit_bounds_padding: tuple[int, int] = (20, 20)

    sensor_csv_dir: Path = Path("/datawaha/esom/DatePalmCounting/Geoportal/Sensors/SensorReads/")
    time_col_candidates: tuple[str, ...] = ("timestamp", "time", "datetime", "date", "Date Time")
    
    # ✅  local XYZ tiles defaults 
    default_tiles_dir: Path = Path("/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/tile_rasters/38RLQ_2024")
    raster_layer_name: str = "Tree-Vege-NonVege Classification"
    raster_opacity_default: float = 0.75
    raster_max_zoom: int = 14   # 10m → 14 matches native; 15 is nice oversample for smooth zoom


    # ✅ Timeseries plotting parameters (single source of truth)
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
            # ---- Palette settings ----
            # Use a named palette OR provide your own list in `colors`.
            palette_name="kaarten_ova",   # options: "kaarten_ova", "okabe_ito", "tol_bright"
            colors=[],                    # if non-empty, overrides palette_name
            line_width=2.0,

            # Zebra bands (keep subtle so lines pop)
            band_fill_rgba_even="rgba(0,0,0,0.02)",
            band_fill_rgba_odd="rgba(0,0,0,0.05)",
                
        )
    )

CFG = Config()
