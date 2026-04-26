#!/usr/bin/env python3
"""Build Tippecanoe MBTiles for yearly center-pivot GeoJSON files."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

TIPPECANOE_BIN = Path("/datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/tippecanoe/tippecanoe")
DEFAULT_SOURCE_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/center_pivot"
)
DEFAULT_OUTPUT_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_mbfiles"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate MBTiles for yearly center-pivot GeoJSON files."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing yearly center-pivot GeoJSON files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Destination directory for generated MBTiles files.",
    )
    parser.add_argument("--min-zoom", type=int, default=5, help="Minimum zoom level.")
    parser.add_argument("--max-zoom", type=int, default=17, help="Maximum zoom level.")
    parser.add_argument(
        "--pattern",
        default="CPF_fields_*_simpl.geojson",
        help="Glob pattern used to select yearly GeoJSON files.",
    )
    parser.add_argument(
        "--year",
        help="Optional year filter, for example 2024.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing MBTiles files.",
    )
    return parser.parse_args()


def _layer_name_for(path: Path) -> str:
    return path.stem


def main() -> None:
    args = _parse_args()
    if not TIPPECANOE_BIN.exists():
        raise SystemExit(f"Tippecanoe binary not found at {TIPPECANOE_BIN}")
    if not args.source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {args.source_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pattern = f"CPF_fields_{args.year}_simpl.geojson" if args.year else args.pattern
    inputs = sorted(args.source_dir.glob(pattern))
    if not inputs:
        raise SystemExit(f"No GeoJSON files matched {pattern} in {args.source_dir}")

    for path in inputs:
        output_mbtiles = args.output_dir / f"{path.stem}.mbtiles"
        if output_mbtiles.exists():
            if not args.force:
                print(f"Skipping {path.name} (already have {output_mbtiles.name}).")
                continue
            output_mbtiles.unlink()

        layer_name = _layer_name_for(path)
        cmd = [
            str(TIPPECANOE_BIN),
            "--read-parallel",
            "--drop-densest-as-needed",
            "-Z",
            str(args.min_zoom),
            "-z",
            str(args.max_zoom),
            "-l",
            layer_name,
            "-o",
            str(output_mbtiles),
            str(path),
        ]
        if args.force:
            cmd.insert(3, "--force")

        print(f"Building {output_mbtiles.name} from {path.name}...")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to build {output_mbtiles.name}: {exc}")


if __name__ == "__main__":
    main()
