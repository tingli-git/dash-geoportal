#!/usr/bin/env python3
"""Merge CPF shapefiles by year and export yearly GeoJSON files in WGS84."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd


DEFAULT_SOURCE_DIR = Path("/datawaha/esom/CPF_national_figures/CPF_polygons/shp_rsl_all")
YEAR_PREFIX_RE = re.compile(r"^(?P<year>\d{4})")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge all shapefiles whose names start with the same 4-digit year, "
            "reproject them to EPSG:4326, and export one GeoJSON per year."
        )
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing the CPF shapefiles.",
    )
    parser.add_argument(
        "--target-crs",
        default="EPSG:4326",
        help="Target CRS for the exported GeoJSON files.",
    )
    parser.add_argument(
        "--pattern",
        default="*.shp",
        help="Glob pattern used to discover source files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing yearly GeoJSON outputs.",
    )
    return parser.parse_args()


def _extract_year(path: Path) -> str | None:
    match = YEAR_PREFIX_RE.match(path.stem)
    if not match:
        return None
    return match.group("year")


def _discover_grouped_files(source_dir: Path, pattern: str) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(source_dir.glob(pattern)):
        year = _extract_year(path)
        if year is None:
            print(f"Skipping {path.name}: filename does not start with a 4-digit year")
            continue
        grouped[year].append(path)
    return dict(grouped)


def _load_and_merge(paths: list[Path]) -> gpd.GeoDataFrame:
    chunks: list[gpd.GeoDataFrame] = []
    for path in paths:
        gdf = gpd.read_file(path)
        if gdf.empty:
            print(f"Skipping {path.name}: no features")
            continue
        gdf = gdf.copy()
        gdf["source_file"] = path.name
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


def _write_geojson(gdf: gpd.GeoDataFrame, target: Path, target_crs: str) -> None:
    if gdf.empty:
        print(f"Skipping {target.name}: merged result has no valid geometries")
        return

    if gdf.crs is None:
        raise ValueError(
            f"Cannot export {target.name}: source CRS is undefined. "
            "Assign CRS in the source data first."
        )

    gdf_out = gdf.to_crs(target_crs)
    geojson = json.loads(gdf_out.to_json())
    target.write_text(json.dumps(geojson), encoding="utf-8")


def main() -> None:
    args = _parse_args()
    source_dir = args.source_dir
    if not source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {source_dir}")

    grouped = _discover_grouped_files(source_dir, args.pattern)
    if not grouped:
        raise SystemExit(f"No matching shapefiles found in {source_dir}")

    for year, paths in sorted(grouped.items()):
        target = source_dir / f"CPF_fields_{year}_simpl.geojson"
        if target.exists() and not args.force:
            print(f"Skipping {year}: {target.name} already exists")
            continue

        print(f"Merging {len(paths)} files for {year}")
        for path in paths:
            print(f"  - {path.name}")

        try:
            merged = _load_and_merge(paths)
            _write_geojson(merged, target, args.target_crs)
        except Exception as exc:
            print(f"Failed {year}: {exc}")
            continue

        print(f"Wrote {target.name}")


if __name__ == "__main__":
    main()
