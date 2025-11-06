from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

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
    time_col_candidates: tuple[str, ...] = ("timestamp", "time", "datetime", "date","Date Time")

CFG = Config()
