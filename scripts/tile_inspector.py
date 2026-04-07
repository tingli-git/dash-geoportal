#!/usr/bin/env python3
"""Quick sanity check for generated MBTiles by decoding a few vector tiles."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
from pathlib import Path

TIPPECANOE_ROOT = Path(__file__).resolve().parents[1] / "tippecanoe"
TIPPECANOE_DECODE = TIPPECANOE_ROOT / "tippecanoe-decode"


def deg2tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, xtile), max(0, ytile)


def read_bounds(mbtiles: Path) -> tuple[float, float, float, float] | None:
    with sqlite3.connect(mbtiles) as conn:
        cursor = conn.execute("SELECT value FROM metadata WHERE name='bounds'")
        row = cursor.fetchone()
    if not row:
        return None
    values = row[0].split(",")
    if len(values) != 4:
        return None
    return tuple(float(v) for v in values)


def decode_tile(mbtiles: Path, z: int, x: int, y: int, decoder: Path) -> int:
    result = subprocess.run(
        [str(decoder), str(mbtiles), str(z), str(x), str(y)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tippecanoe-decode failed")
    payload = json.loads(result.stdout)
    total = 0
    for layer in payload.get("features", []):
        total += len(layer.get("features", []))
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a sample of vector tiles inside MBTiles files.")
    parser.add_argument("mbtiles", type=Path, help="Path to the MBTiles file to inspect.")
    parser.add_argument(
        "--decoder",
        type=Path,
        default=TIPPECANOE_DECODE,
        help="Path to tippecanoe-decode binary (fall back to repo sibling tippecanoe).",
    )
    parser.add_argument(
        "--zoom", "-z", type=int, nargs="+", default=[11, 13, 15], help="Zoom levels to spot-check.",
    )
    parser.add_argument(
        "--center",
        type=float,
        nargs=2,
        default=None,
        metavar=("LON", "LAT"),
        help="Optional lon/lat center to use instead of metadata bounds.",
    )
    args = parser.parse_args()

    if not args.mbtiles.exists():
        raise SystemExit(f"MBTiles not found: {args.mbtiles}")
    if not args.decoder.exists():
        raise SystemExit(f"tippecanoe-decode binary not found at {args.decoder}")

    center: tuple[float, float]
    if args.center:
        center = (args.center[0], args.center[1])
    else:
        bounds = read_bounds(args.mbtiles)
        if not bounds:
            raise SystemExit("Could not read bounds from MBTiles metadata; provide --center instead.")
        center = ((bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0)

    success = True
    for zoom in sorted(set(args.zoom)):
        x, y = deg2tile(center[0], center[1], zoom)
        try:
            count = decode_tile(args.mbtiles, zoom, x, y, args.decoder)
        except RuntimeError as exc:
            print(f"[{args.mbtiles.name}] Zoom {zoom} tile {x}/{y} failed: {exc}")
            success = False
            continue
        status = "pass" if count > 0 else "empty"
        print(f"[{args.mbtiles.name}] zoom {zoom} tile {x}/{y} -> features={count} ({status})")
        if count == 0:
            success = False

    if not success:
        raise SystemExit("Some tiles failed or were empty; see output above.")
