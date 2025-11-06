#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from pathlib import Path

def gdal2tiles_py_available():
    try:
        from osgeo_utils.gdal2tiles import main as g2t
        return g2t
    except Exception:
        try:
            from osgeo.gdal2tiles import main as g2t
            return g2t
        except Exception:
            return None


def apply_color_table(input_tif: str, color_table: str, output_tif: str):
    """Apply color-relief table using gdaldem (e.g. NDVI or class palette)."""
    cmd = ["gdaldem", "color-relief", input_tif, color_table, output_tif, "-alpha"]
    print("🎨 Applying color palette:", color_table)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gdaldem color-relief failed:\n{proc.stdout}")
    return output_tif


def raster_to_xyz_tiles(
    input_tif: str,
    out_dir: str,
    minzoom: int = 8,
    maxzoom: int = 14,
    resampling: str = "bilinear",
    band: int | None = None,
    threads: int = 1,
    xyz: bool = True,
    color_table: str | None = None
):
    """Convert GeoTIFF to XYZ tiles using gdal2tiles, with optional color map."""
    input_tif = str(Path(input_tif).expanduser().resolve())
    out_dir = str(Path(out_dir).expanduser().resolve())
    os.makedirs(out_dir, exist_ok=True)

    # 🎨 If color table provided, create a temporary colored TIFF
    if color_table:
        colorized_tif = str(Path(out_dir) / "colored_tmp.tif")
        apply_color_table(input_tif, color_table, colorized_tif)
        input_tif = colorized_tif

    args = [
        "-z", f"{minzoom}-{maxzoom}",
        "--resampling", resampling,
        "--processes", str(threads),
        "--webviewer", "none",
    ]
    if xyz:
        args.append("--xyz")
    if band is not None:
        args.extend(["-b", str(band)])
    args.extend([input_tif, out_dir])

    g2t = gdal2tiles_py_available()
    if g2t is not None:
        sys_argv_backup = sys.argv
        try:
            sys.argv = ["gdal2tiles.py"] + args
            try:
                g2t()
            except SystemExit as e:
                if int(getattr(e, "code", 0)) != 0:
                    raise RuntimeError(f"gdal2tiles failed with exit code {e.code}")
        finally:
            sys.argv = sys_argv_backup
    else:
        cmd = ["gdal2tiles.py"] + args
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"gdal2tiles failed:\n{proc.stdout}")

    print(f"✅ Tiles written to: {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Convert a GeoTIFF raster to XYZ tiles for ipyleaflet.")
    parser.add_argument("input_tif", help="Path to input GeoTIFF")
    parser.add_argument("out_dir", help="Output directory for XYZ tiles")
    parser.add_argument("--minzoom", type=int, default=8)
    parser.add_argument("--maxzoom", type=int, default=14)
    parser.add_argument("--resampling", type=str, default="bilinear")
    parser.add_argument("--band", type=int, default=None)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--no-xyz", dest="xyz", action="store_false")
    parser.add_argument("--color-table", type=str, default=None,
                        help="Path to a GDAL color table (.txt) to colorize before tiling")
    args = parser.parse_args()

    raster_to_xyz_tiles(
        input_tif=args.input_tif,
        out_dir=args.out_dir,
        minzoom=args.minzoom,
        maxzoom=args.maxzoom,
        resampling=args.resampling,
        band=args.band,
        threads=args.threads,
        xyz=args.xyz,
        color_table=args.color_table,
    )


if __name__ == "__main__":
    main()

# End of raster2tile.py
# example usage:
# cd /datawaha/esom/DatePalmCounting/AncillaryData/Deeplearning/predictions/RF/predi_raster
# gdalwarp -t_srs EPSG:3857 -multi -wo NUM_THREADS=ALL_CPUS -co TILED=YES -dstalpha three_class_raster.tif three_class_wm.tif
# gdaldem color-relief /datawaha/esom/DatePalmCounting/AncillaryData/Deeplearning/predictions/RF/predi_raster/three_class_wm.tif /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/tile_rasters/Tree_notree_bare.txt /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/tile_rasters/38RLQ_2024/colored.tif
# cd /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/tile_rasters
# python /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/functions/preprocess/raster2tile.py 38RLQ_2024/colored.tif 38RLQ_2024 --minzoom 5 --maxzoom 15 --resampling near