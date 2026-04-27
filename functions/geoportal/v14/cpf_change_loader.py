from __future__ import annotations

import base64
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import ipyleaflet
import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from rasterio.vrt import WarpedVRT

from functions.geoportal.v14.config import CFG
from functions.geoportal.v14.cloud_assets import ensure_local_directory


def _hex_to_rgba(color: str) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid RGB color: {color}")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4)) + (255,)


def _legend_lookup() -> dict[int, tuple[int, int, int, int]]:
    return {
        int(item["value"]): _hex_to_rgba(str(item["color"]))
        for item in getattr(CFG, "cpf_change_legend", [])
    }


def _resolve_change_raster(raster_path: Path) -> Path:
    raster_path = Path(raster_path)

    if raster_path.exists():
        return raster_path

    change_dir = ensure_local_directory(
        Path(getattr(CFG, "cpf_change_dir", raster_path.parent)),
        suffixes=(".tif", ".tiff"),
    )

    candidate = change_dir / raster_path.name
    if candidate.exists():
        return candidate

    raise FileNotFoundError(f"Change-detection raster not found: {raster_path}")


@lru_cache(maxsize=2)
def _build_change_asset(raster_path_str: str) -> tuple[str, list[list[float]]]:
    raster_path = _resolve_change_raster(Path(raster_path_str))

    with rasterio.open(raster_path) as src:
        with WarpedVRT(
            src,
            crs="EPSG:4326",
            resampling=Resampling.nearest,
            nodata=0,
        ) as vrt:
            values = vrt.read(1)
            transform = vrt.transform

    values = np.nan_to_num(values, nan=0, posinf=0, neginf=0).astype(np.int16)

    height, width = values.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)

    for raster_value, rgba_color in _legend_lookup().items():
        rgba[values == raster_value] = rgba_color

    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    west, south, east, north = array_bounds(height, width, transform)
    bounds = [[float(south), float(west)], [float(north), float(east)]]

    return f"data:image/png;base64,{encoded}", bounds


def build_cpf_change_layer(
    raster_path: Path,
    *,
    layer_name: str,
    opacity: float | None = None,
) -> tuple[ipyleaflet.ImageOverlay | None, list[list[float]] | None, str | None]:
    try:
        data_url, bounds = _build_change_asset(str(raster_path))
    except Exception as exc:
        return None, None, str(exc)

    layer = ipyleaflet.ImageOverlay(
        url=data_url,
        bounds=bounds,
        name=layer_name,
        opacity=float(
            opacity
            if opacity is not None
            else getattr(CFG, "cpf_change_default_opacity", 0.82)
        ),
    )
    setattr(layer, "_bounds", bounds)
    return layer, bounds, None