from __future__ import annotations

import math
from pathlib import Path

import ipyleaflet

from functions.geoportal.v14.config import CFG
from functions.geoportal.v14.cloud_assets import ensure_local_directory


def _detect_zoom_range(tiles_folder: Path) -> tuple[int | None, int | None]:
    try:
        z_levels = sorted(int(p.name) for p in tiles_folder.iterdir() if p.is_dir() and p.name.isdigit())
    except FileNotFoundError:
        return None, None
    return (z_levels[0], z_levels[-1]) if z_levels else (None, None)


def _leaflet_bounds_from_xyz(tiles_folder: Path, z: int) -> list[list[float]] | None:
    zdir = tiles_folder / str(z)
    if not zdir.exists():
        return None

    xs = sorted(int(p.name) for p in zdir.iterdir() if p.is_dir() and p.name.isdigit())
    if not xs:
        return None

    ys: list[int] = []
    for xdir in zdir.iterdir():
        if xdir.is_dir() and xdir.name.isdigit():
            ys.extend(int(p.stem) for p in xdir.glob("*.png"))

    if not ys:
        return None

    x_min, x_max = xs[0], xs[-1]
    y_min, y_max = min(ys), max(ys)

    def num2lat(y: int, z: int) -> float:
        n = math.pi - 2.0 * math.pi * y / (2 ** z)
        return math.degrees(math.atan(math.sinh(n)))

    def num2lon(x: int, z: int) -> float:
        return x / (2 ** z) * 360.0 - 180.0

    return [
        [num2lat(y_max + 1, z), num2lon(x_min, z)],
        [num2lat(y_min, z), num2lon(x_max + 1, z)],
    ]


def _resolve_change_tiles_dir(tiles_dir: Path) -> Path:
    tiles_dir = Path(tiles_dir)

    if tiles_dir.exists():
        return tiles_dir

    return ensure_local_directory(
        tiles_dir,
        suffixes=(".png",),
    )


def build_cpf_change_layer(
    tiles_dir: Path,
    *,
    layer_name: str,
    opacity: float | None = None,
    url_base: str | None = None,
) -> tuple[ipyleaflet.TileLayer | None, list[list[float]] | None, str | None]:
    try:
        tiles_dir = _resolve_change_tiles_dir(Path(tiles_dir))
        zmin, zmax = _detect_zoom_range(tiles_dir)
        bounds = _leaflet_bounds_from_xyz(tiles_dir, zmax) if zmax is not None else None

        if url_base is None:
            url_base = str(tiles_dir)

        layer = ipyleaflet.TileLayer(
            url=f"{url_base.rstrip('/')}/{{z}}/{{x}}/{{y}}.png",
            name=layer_name,
            opacity=float(opacity if opacity is not None else getattr(CFG, "cpf_change_default_opacity", 0.82)),
            min_zoom=4,
            max_zoom=13,
            no_wrap=True,
            tile_size=256,
            tms=False,  # XYZ
            attribution="© CPF change tiles",
        )
        setattr(layer, "_bounds", bounds)
        return layer, bounds, None

    except Exception as exc:
        return None, None, str(exc)