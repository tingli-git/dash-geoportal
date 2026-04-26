#!/usr/bin/env python3
"""Vectorize yearly CPF TIFF files and export a merged WGS84 GeoJSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape


DEFAULT_SOURCE_DIR = Path(
    "/datawaha/esom/Sentinel_2/HSL_deli_2layers_all/af_rmdup/RegionAll_all_fields"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Polygonize TIFF files for a target year, merge the polygons, "
            "reproject to EPSG:4326, and write one GeoJSON output."
        )
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing source TIFF files.",
    )
    parser.add_argument(
        "--year",
        default="2024",
        help="Year token extracted from file names via split('_')[-2].",
    )
    parser.add_argument(
        "--pattern",
        default="*.tif",
        help="Glob pattern used to find TIFF files.",
    )
    parser.add_argument(
        "--target-crs",
        default="EPSG:4326",
        help="Target CRS for the merged GeoJSON.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output GeoJSON if it already exists.",
    )
    return parser.parse_args()


def _extract_year(path: Path) -> str | None:
    parts = path.stem.split("_")
    if len(parts) < 2:
        return None
    return parts[-2]


def _select_files(source_dir: Path, pattern: str, year: str) -> list[Path]:
    matches: list[Path] = []
    for path in sorted(source_dir.glob(pattern)):
        extracted = _extract_year(path)
        if extracted == year:
            matches.append(path)
    return matches


def _polygonize_tiff(path: Path) -> gpd.GeoDataFrame:
    with rasterio.open(path) as src:
        band = src.read(1)
        nodata = src.nodata

        valid_mask = band != 0
        if nodata is not None:
            valid_mask &= band != nodata

        features = []
        for geom, value in shapes(band, mask=valid_mask, transform=src.transform):
            if value == 0:
                continue
            features.append(
                {
                    "geometry": shape(geom),
                    "raster_value": int(value) if float(value).is_integer() else float(value),
                    "source_file": path.name,
                }
            )

        if not features:
            return gpd.GeoDataFrame(geometry=[], crs=src.crs)

        gdf = gpd.GeoDataFrame(features, geometry="geometry", crs=src.crs)
        gdf = gdf[~(gdf.geometry.is_empty | gdf.geometry.isna())].copy()
        return gdf


def _merge_year(files: list[Path]) -> gpd.GeoDataFrame:
    chunks: list[gpd.GeoDataFrame] = []
    for path in files:
        print(f"Polygonizing {path.name}")
        gdf = _polygonize_tiff(path)
        if gdf.empty:
            print(f"  Skipping {path.name}: no valid polygons")
            continue
        chunks.append(gdf)

    if not chunks:
        return gpd.GeoDataFrame(geometry=[], crs=None)

    base_crs = chunks[0].crs
    normalized: list[gpd.GeoDataFrame] = []
    for gdf in chunks:
        current = gdf
        if current.crs is None and base_crs is not None:
            current = current.set_crs(base_crs)
        elif current.crs is not None and base_crs is not None and current.crs != base_crs:
            current = current.to_crs(base_crs)
        normalized.append(current)

    merged = gpd.GeoDataFrame(
        pd.concat(normalized, ignore_index=True),
        geometry="geometry",
        crs=normalized[0].crs,
    )
    merged = merged[~(merged.geometry.is_empty | merged.geometry.isna())].copy()
    return merged


def _write_geojson(gdf: gpd.GeoDataFrame, output_path: Path, target_crs: str) -> None:
    if gdf.empty:
        raise ValueError("No polygons were generated for the requested year")
    if gdf.crs is None:
        raise ValueError("Merged polygons have no CRS; cannot reproject to EPSG:4326")

    output = gdf.to_crs(target_crs).copy()
    geojson = json.loads(output.to_json())
    output_path.write_text(json.dumps(geojson), encoding="utf-8")


def main() -> None:
    args = _parse_args()
    source_dir = args.source_dir
    if not source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {source_dir}")

    files = _select_files(source_dir, args.pattern, args.year)
    if not files:
        raise SystemExit(f"No TIFF files found for year {args.year} in {source_dir}")

    output_path = source_dir / f"CPF_fields_{args.year}_simpl.geojson"
    if output_path.exists() and not args.force:
        raise SystemExit(
            f"Output already exists: {output_path}. Use --force to overwrite."
        )

    merged = _merge_year(files)
    _write_geojson(merged, output_path, args.target_crs)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
