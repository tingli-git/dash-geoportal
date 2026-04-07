#!/usr/bin/env python3
"""Extract every province MBTiles into XYZ directories for the HTTP server."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

TIPPECANOE_TILE_JOIN = Path(
    "/datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/tippecanoe/tile-join"
)
MBTILES_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_tile_cache"
)
OUTPUT_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_tiles"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export MBTiles to z/x/y.pbf directories for each province.")
    parser.add_argument(
        "--mbtiles-dir",
        type=Path,
        default=MBTILES_DIR,
        help="Directory containing built province MBTiles",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory where z/x/y.pbf folders will be created",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reexport tiles even if the output directory already exists",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not TIPPECANOE_TILE_JOIN.exists():
        raise SystemExit(f"tile-join tool not found at {TIPPECANOE_TILE_JOIN}")
    if not args.mbtiles_dir.is_dir():
        raise SystemExit(f"MBTiles directory missing: {args.mbtiles_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for mbtiles in sorted(args.mbtiles_dir.glob("*.mbtiles")):
        dest = args.out_dir / mbtiles.stem
        if dest.exists():
            if not args.force:
                print(f"Skipping {mbtiles.name}; {dest} already exists.")
                continue
            subprocess.run(["rm", "-rf", str(dest)], check=True)
        dest.mkdir(parents=True, exist_ok=True)

        cmd = [
                str(TIPPECANOE_TILE_JOIN),
                "--force",
                "--output-to-directory",
                str(dest),
                "--no-tile-compression",
                "--no-tile-size-limit",
                str(mbtiles),
            ]
        print(f"Exporting {mbtiles.name} to {dest}")
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
