#!/usr/bin/env python3
"""Generate simplified GeoJSON files for each province so the dashboard can load them without runtime simplification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd

from functions.geoportal.v9.config import CFG


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build simplified GeoJSON for province date-palm fields.")
    parser.add_argument(
        "--province-dir",
        type=Path,
        default=CFG.datepalms_province_dir,
        help="Directory containing the source province GeoPackage files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=CFG.datepalms_province_simple_dir,
        help="Destination directory for simplified GeoJSONs.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=getattr(CFG, "datepalms_province_simplify_tolerance", 0.0015),
        help="Simplification tolerance (degrees) used when generating lightweight geometries.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing simplified GeoJSON files.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    province_dir = args.province_dir
    if not province_dir.is_dir():
        raise SystemExit(f"Province directory not found: {province_dir}")

    simplified_dir = args.output_dir
    simplified_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(province_dir.glob("*.gpkg")):
        target = simplified_dir / f"{path.stem}.geojson"
        if target.exists() and not args.force:
            print(f"Skipping {path.name} (already exists) -> {target.name}")
            continue

        try:
            gdf = gpd.read_file(path)
        except Exception as exc:
            print(f"Failed to read {path.name}: {exc}")
            continue

        if gdf.crs and gdf.crs.to_epsg() != 4326:
            try:
                gdf = gdf.to_crs(4326)
            except Exception as exc:
                print(f"Failed to reproject {path.name}: {exc}")
                continue

        simplified = gdf.copy()
        simplified["geometry"] = simplified.geometry.simplify(
            args.tolerance, preserve_topology=True
        )
        simplified = simplified[~(simplified.geometry.is_empty | simplified.geometry.isna())]

        if simplified.empty:
            print(f"{path.name} produced no simplified geometry, skipping.")
            continue

        geojson = json.loads(simplified.to_json())
        target.write_text(json.dumps(geojson), encoding="utf-8")
        print(f"Wrote simplified GeoJSON for {path.name} -> {target.name} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
