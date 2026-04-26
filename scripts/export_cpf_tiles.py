#!/usr/bin/env python3
"""Export yearly center-pivot MBTiles into XYZ PBF directories."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

TIPPECANOE_TILE_JOIN = Path(
    "/datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/tippecanoe/tile-join"
)
DEFAULT_MBTILES_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_mbfiles"
)
DEFAULT_OUTPUT_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_tiles"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export yearly center-pivot MBTiles to z/x/y.pbf directories."
    )
    parser.add_argument(
        "--mbtiles-dir",
        type=Path,
        default=DEFAULT_MBTILES_DIR,
        help="Directory containing center-pivot MBTiles files.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where z/x/y.pbf folders will be created.",
    )
    parser.add_argument(
        "--pattern",
        default="CPF_fields_*_simpl.mbtiles",
        help="Glob pattern used to select MBTiles files.",
    )
    parser.add_argument(
        "--year",
        help="Optional year filter, for example 2024.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-export tiles even if the target directory already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not TIPPECANOE_TILE_JOIN.exists():
        raise SystemExit(f"tile-join tool not found at {TIPPECANOE_TILE_JOIN}")
    if not args.mbtiles_dir.is_dir():
        raise SystemExit(f"MBTiles directory missing: {args.mbtiles_dir}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pattern = f"CPF_fields_{args.year}_simpl.mbtiles" if args.year else args.pattern
    inputs = sorted(args.mbtiles_dir.glob(pattern))
    if not inputs:
        raise SystemExit(f"No MBTiles files matched {pattern} in {args.mbtiles_dir}")

    for mbtiles in inputs:
        dest = args.out_dir / mbtiles.stem
        if dest.exists():
            if not args.force:
                print(f"Skipping {mbtiles.name}; {dest} already exists.")
                continue
            shutil.rmtree(dest)
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
