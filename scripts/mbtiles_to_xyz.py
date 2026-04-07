"""Convert MBTiles to an XYZ directory so python -m http.server can serve raw tiles."""

from pathlib import Path
import sqlite3


def export_mbtiles(mbtiles_path: Path, out_dir: Path) -> None:
    print(f"Exporting {mbtiles_path.stem} -> {out_dir}")
    conn = sqlite3.connect(mbtiles_path)
    cur = conn.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles")
    for z, x, y, blob in cur:
        xyz_y = (1 << z) - 1 - y
        tile_dir = out_dir / str(z) / str(x)
        tile_dir.mkdir(parents=True, exist_ok=True)
        tile_path = tile_dir / f"{xyz_y}.pbf"
        tile_path.write_bytes(blob)
    conn.close()


def main() -> None:
    base_dir = Path("/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_tile_cache")
    output_dir = Path("/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_tiles")
    output_dir.mkdir(parents=True, exist_ok=True)

    mbtiles = sorted(base_dir.glob("*.mbtiles"))
    if not mbtiles:
        raise SystemExit("No MBTiles files found in {base_dir}")

    for mb in mbtiles:
        export_mbtiles(mb, output_dir / mb.stem)


if __name__ == "__main__":
    main()
