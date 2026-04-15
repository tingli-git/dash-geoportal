from __future__ import annotations

import base64
from contextlib import ExitStack
from functools import lru_cache
from io import BytesIO

import ipyleaflet
import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.transform import array_bounds
from rasterio.vrt import WarpedVRT

from functions.geoportal.v12.config import CFG


def _hex_to_rgba(color: str) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid RGB color: {color}")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4)) + (255,)


@lru_cache(maxsize=1)
def _build_density_asset() -> tuple[str, list[list[float]]]:
    tif_paths = sorted(CFG.field_density_dir.glob("*.tif"))
    if not tif_paths:
        raise FileNotFoundError(f"No density TIFFs found in {CFG.field_density_dir}")

    with ExitStack() as stack:
        vrts = []
        for path in tif_paths:
            dataset = stack.enter_context(rasterio.open(path))
            vrt = stack.enter_context(
                WarpedVRT(
                    dataset,
                    crs="EPSG:4326",
                    resampling=Resampling.nearest,
                    nodata=0,
                )
            )
            vrts.append(vrt)

        mosaic, transform = merge(vrts, nodata=0)

    values = np.nan_to_num(mosaic[0].astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    height, width = values.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)

    for item in CFG.field_density_legend:
        lower = float(item["min"])
        upper = item.get("max")
        if upper is None:
            mask = values > lower
        elif lower <= 0:
            mask = (values > 0) & (values <= float(upper))
        else:
            mask = (values > lower) & (values <= float(upper))
        rgba[mask] = _hex_to_rgba(str(item["color"]))

    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    west, south, east, north = array_bounds(height, width, transform)
    bounds = [[float(south), float(west)], [float(north), float(east)]]
    return f"data:image/png;base64,{encoded}", bounds


def build_field_density_layer(opacity: float | None = None) -> tuple[ipyleaflet.ImageOverlay | None, list[list[float]] | None, str | None]:
    try:
        data_url, bounds = _build_density_asset()
    except Exception as exc:
        return None, None, str(exc)

    layer = ipyleaflet.ImageOverlay(
        url=data_url,
        bounds=bounds,
        name=str(getattr(CFG, "field_density_layer_name", "Field density")),
        opacity=float(opacity if opacity is not None else getattr(CFG, "field_density_default_opacity", 0.78)),
    )
    setattr(layer, "_bounds", bounds)
    return layer, bounds, None
