#!/usr/bin/env python3
"""Dump GeoJSON copies of every province GeoPackage used by Geoportal v11."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pyogrio

from functions.geoportal.v11.config import CFG


def _preferred_layer(path: Path) -> str | None:
    try:
        layers = pyogrio.list_layers(str(path))
    except Exception:
        return None

    if len(layers) == 0:
        return None

    for row in layers:
        name = str(row[0])
        if not name.lower().startswith("layer_styles"):
            return name

    return str(layers[0][0])


def _scalar_epsg(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        if hasattr(value, "item"):
            value = value.item()
        return int(value)
    except (ValueError, TypeError):
        return None


def convert_gpkg_to_geojson(
    src: Path,
    dest: Path,
    *,
    layer: str | None = None,
    force: bool = False,
    reproject_epsg: int = 4326,
) -> bool:
    """Read a single province GeoPackage and write GeoJSON to the target path.

    Returns True if the file was written, False if it was skipped because it already exists
    and --force was not provided.
    """

    if not src.exists():
        raise FileNotFoundError(f"Missing GeoPackage: {src}")

    if dest.exists() and not force:
        print(f"Skipping existing GeoJSON {dest.name} (use --force to overwrite)")
        return False

    layer_name = layer or _preferred_layer(src)
    read_kwargs = {"layer": layer_name} if layer_name else {}
    gdf = gpd.read_file(src, **read_kwargs)

    if gdf.empty:
        raise ValueError(f"GeoPackage {src.name} contains no features")

    if gdf.crs is not None:
        epsg = _scalar_epsg(gdf.crs.to_epsg())
        if epsg is not None and epsg != reproject_epsg:
            gdf = gdf.to_crs(reproject_epsg)

    dest.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(dest, driver="GeoJSON")
    print(f"Converted {src.name} → {dest.name} ({dest.stat().st_size} bytes)")
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert every province GeoPackage in the configured v11 directory into GeoJSON."
    )
    parser.add_argument(
        "--province-dir",
        "-d",
        type=Path,
        default=CFG.datepalms_province_dir,
        help="Directory that holds the per-province GeoPackage files",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="Where to write the GeoJSON files; defaults to the province directory",
    )
    parser.add_argument(
        "--province",
        action="append",
        help="Optional list of province file stems to convert; repeat this flag to target multiple provinces",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite GeoJSON outputs even if they already exist",
    )
    parser.add_argument(
        "--layer",
        help="Manually specify the layer name within the GeoPackage",
    )
    return parser.parse_args()


def _enumerate_sources(directory: Path, provinces: Iterable[str] | None) -> list[Path]:
    candidates = sorted(directory.glob("*.gpkg"))
    if provinces:
        wanted = {name.lower() for name in provinces}
        return [path for path in candidates if path.stem.lower() in wanted]
    return candidates


def main() -> None:
    args = _parse_args()
    province_dir = args.province_dir
    if not province_dir.is_dir():
        raise SystemExit(f"Province directory not found: {province_dir}")

    output_dir = args.output_dir or province_dir

    province_files = _enumerate_sources(province_dir, args.province)
    if not province_files:
        raise SystemExit("No GeoPackage files found to convert")

    for path in province_files:
        target = output_dir / f"{path.stem}.geojson"
        try:
            convert_gpkg_to_geojson(
                path,
                target,
                layer=args.layer,
                force=args.force,
            )
        except Exception as exc:
            print(f"Failed to convert {path.name}: {exc}")


if __name__ == "__main__":
    main()
