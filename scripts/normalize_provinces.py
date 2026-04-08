#!/usr/bin/env python3
"""Normalize province GeoPackages before loading v10."""

from __future__ import annotations

import json
from pathlib import Path
import argparse

import geopandas as gpd


def load_province_files(src_dir: Path) -> list[Path]:
    return sorted(src_dir.glob("*.gpkg"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize per-province GPKGs")
    parser.add_argument("--dir", "-d", type=Path, required=True, help="Directory containing province GPKGs")
    parser.add_argument("--mapping", "-m", type=Path, default=Path("province_mapping.json"), help="Output JSON mapping file")
    args = parser.parse_args()

    if not args.dir.is_dir():
        raise SystemExit(f"Directory does not exist: {args.dir}")

    files = load_province_files(args.dir)
    if not files:
        raise SystemExit(f"No GeoPackages found in {args.dir}")

    mapping: dict[int, str] = {}
    for province_id, path in enumerate(files, start=1):
        province_name = path.stem
        mapping[province_id] = province_name

        gdf = gpd.read_file(path)
        layer_name = getattr(gdf, "_layer", None) or province_name

        row_ids = gdf.index.to_series().reset_index(drop=True)
        gdf["field_id"] = (
            row_ids.astype(str).radd(f"{province_id}_")
        )
        gdf["province_id"] = province_id
        if "area_m2" in gdf.columns:
            gdf["esti_tree_number"] = (
                (gdf["area_m2"] / 100.0 * 0.73).round().astype(int)
            )

        tmp_file = path.with_suffix(".tmp.gpkg")
        gdf.to_file(tmp_file, driver="GPKG", layer=layer_name, index=False)
        tmp_file.replace(path)

    with open(args.mapping, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=2)

    print(f"Normalized {len(files)} provinces and wrote mapping to {args.mapping}")


if __name__ == "__main__":
    main()
