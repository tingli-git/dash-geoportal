#!/usr/bin/env python3
"""Build Tippecanoe vector tiles for every province GeoPackage."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

import pyogrio

TIPPECANOE_BIN = Path("/datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/tippecanoe/tippecanoe")
DEFAULT_PROVINCE_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_per_province"
)
DEFAULT_TILE_CACHE_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_tile_cache"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MBTiles per province from the GN GPKG files.")
    parser.add_argument(
        "--province-dir",
        type=Path,
        default=DEFAULT_PROVINCE_DIR,
        help="Source directory containing province GeoPackage files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_TILE_CACHE_DIR,
        help="Destination directory for generated MBTiles.",
    )
    parser.add_argument("--min-zoom", type=int, default=5, help="Minimum zoom level for tiles.")
    parser.add_argument("--max-zoom", type=int, default=16, help="Maximum zoom level for tiles.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing MBTiles files if they exist.",
    )
    return parser.parse_args()


def _detect_layer_name(path: Path) -> str | None:
    try:
        raw = pyogrio.list_layers(str(path))
    except Exception:
        return None

    names: list[str] = []

    # pyogrio.list_layers returns a numpy array of layer metadata; the layer name
    # is typically in the first column. Handle a few common shapes safely.
    if hasattr(raw, "dtype") and raw.dtype == object:
        try:
            names = [str(item[0]) for item in raw]
        except Exception:
            try:
                # Some numpy arrays expose as nested tuples/arrays.
                names = [str(item[0]) for item in raw.tolist()]
            except Exception:
                names = [str(item) for item in raw]
    else:
        names = [str(layer) for layer in raw]

    # Filter out auxiliary layers such as "layer_styles".
    filtered = [layer for layer in names if not layer.lower().startswith("layer_styles")]
    if filtered:
        return filtered[0]
    if names:
        return names[0]
    return None


def main() -> None:
    args = _parse_args()
    if not TIPPECANOE_BIN.exists():
        raise SystemExit(f"Tippecanoe binary not found at {TIPPECANOE_BIN}")
    if not args.province_dir.is_dir():
        raise SystemExit(f"Province directory not found: {args.province_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(args.province_dir.glob("*.gpkg")):
        output_mbtiles = args.output_dir / f"{path.stem}.mbtiles"
        if output_mbtiles.exists():
            if args.force:
                try:
                    output_mbtiles.unlink()
                except Exception as exc:
                    print(f"Could not remove old {output_mbtiles.name}: {exc}")
                    continue
            else:
                print(f"Skipping {path.name} (already have {output_mbtiles.name}).")
                continue

        layer_name = _detect_layer_name(path)
        if not layer_name:
            print(f"Skipping {path.name} (no valid layer found).")
            continue

        fd, tmp_name = tempfile.mkstemp(suffix=".geojson")
        os.close(fd)
        geojson_path = Path(tmp_name)
        geojson_path.unlink(missing_ok=True)

        ogr_cmd = [
            "ogr2ogr",
            "-f",
            "GeoJSON",
            str(geojson_path),
            str(path),
            layer_name,
            "-t_srs",
            "EPSG:4326",
        ]
        try:
            print(f"Reprojecting and exporting {layer_name} from {path.name} to GeoJSON...")
            subprocess.run(ogr_cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to export GeoJSON for {path.name}: {exc}")
            geojson_path.unlink(missing_ok=True)
            continue

        if not geojson_path.exists() or geojson_path.stat().st_size == 0:
            print(f"Export produced empty GeoJSON for {path.name}, skipping.")
            geojson_path.unlink(missing_ok=True)
            continue

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
            str(geojson_path),
        ]
        if args.force:
            cmd.insert(3, "--force")

        try:
            print(f"Building {output_mbtiles.name} (layer={layer_name}) from reprojected GeoJSON...")
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to build {output_mbtiles.name}: {exc}")
        finally:
            geojson_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()