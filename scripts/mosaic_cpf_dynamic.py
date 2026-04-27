#!/usr/bin/env python3
"""Mosaic dynamic CPF rasters by trend, reproject to EPSG:4326, and renumber by year class."""


from __future__ import annotations
"""Example of usage: 
python mosaic_dynamic_cpf.py
python mosaic_dynamic_cpf.py --force
python mosaic_dynamic_cpf.py --force-classified
"""

import argparse
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.shutil import copy as rio_copy
from rasterio.vrt import WarpedVRT


DEFAULT_SOURCE_DIR = Path(
    "/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic"
)

TARGET_CRS = "EPSG:4326"

MOSAIC_OUTPUT_NAMES = {
    "expanding": "KSA_cpf_expanding.tif",
    "contraction": "KSA_cpf_contraction.tif",
}

CLASSIFIED_OUTPUT_NAMES = {
    "expanding": "KSA_cpf_expanding_classified.tif",
    "contraction": "KSA_cpf_contraction_classified.tif",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find dynamic CPF TIFF files, group them by expanding/contraction, "
            "mosaic each group, reproject to EPSG:4326, and renumber year values."
        )
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument(
        "--resampling",
        choices=("nearest", "bilinear", "cubic"),
        default="nearest",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuilding the mosaic even if it already exists.",
    )
    parser.add_argument(
        "--force-classified",
        action="store_true",
        help="Force rebuilding the classified output even if it already exists.",
    )
    return parser.parse_args()


def _list_group_files(source_dir: Path, keyword: str) -> list[Path]:
    tif_paths = sorted(source_dir.glob("*.tif")) + sorted(source_dir.glob("*.tiff"))

    outputs = set(MOSAIC_OUTPUT_NAMES.values()) | set(CLASSIFIED_OUTPUT_NAMES.values())

    return [
        path
        for path in tif_paths
        if keyword in path.stem.lower()
        and path.name not in outputs
        and ".tmp" not in path.name
    ]


def _resampling_mode(name: str) -> Resampling:
    return {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
    }[name]


def _copy_as_cog(tmp_path: Path, output_path: Path) -> None:
    rio_copy(
        tmp_path,
        output_path,
        driver="COG",
        compress="deflate",
        predictor=2,
        blocksize=512,
        overview_resampling="nearest",
        BIGTIFF="IF_SAFER",
    )


def _build_mosaic(
    keyword: str,
    input_paths: list[Path],
    mosaic_path: Path,
    resampling: Resampling,
    force: bool,
) -> None:
    if mosaic_path.exists() and not force:
        print(f"Mosaic already exists, skipping mosaic step: {mosaic_path}")
        return

    if not input_paths:
        raise SystemExit(f"No TIFF files found for '{keyword}' in {mosaic_path.parent}")

    if mosaic_path.exists() and force:
        print(f"Force enabled. Rebuilding mosaic: {mosaic_path}")
        mosaic_path.unlink()

    print(f"Mosaicking {keyword} rasters into {mosaic_path.name}")
    for path in input_paths:
        print(f"  - {path.name}")

    tmp_path = mosaic_path.with_suffix(".tmp.tif")

    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(path)) for path in input_paths]
        first = datasets[0]

        nodata = first.nodata if first.nodata is not None else 0

        vrt_kwargs = {
            "crs": TARGET_CRS,
            "resampling": resampling,
            "nodata": nodata,
        }

        vrts = [
            stack.enter_context(WarpedVRT(dataset, **vrt_kwargs))
            for dataset in datasets
        ]

        mosaic, transform = merge(vrts, nodata=nodata)

        profile = first.profile.copy()
        profile.update(
            driver="GTiff",
            crs=TARGET_CRS,
            transform=transform,
            width=mosaic.shape[2],
            height=mosaic.shape[1],
            count=mosaic.shape[0],
            dtype=str(mosaic.dtype),
            nodata=nodata,
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress="deflate",
            predictor=2,
            zlevel=6,
            BIGTIFF="IF_SAFER",
        )

        with rasterio.open(tmp_path, "w", **profile) as dst:
            dst.write(mosaic)
            dst.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
            dst.update_tags(ns="rio_overview", resampling="nearest")

    _copy_as_cog(tmp_path, mosaic_path)
    tmp_path.unlink(missing_ok=True)

    print(f"Wrote mosaic COG: {mosaic_path}")


def _classify_years(year: np.ndarray, nodata: float | int | None) -> np.ndarray:
    classified = np.zeros(year.shape, dtype="uint8")

    if nodata is None:
        valid = np.isfinite(year)
    else:
        valid = year != nodata

    classified[(year < 1990) & valid] = 1
    classified[(year >= 1990) & (year <= 2000) & valid] = 2
    classified[(year > 2000) & (year <= 2010) & valid] = 3
    classified[(year > 2010) & (year <= 2020) & valid] = 4
    classified[(year > 2020) & valid] = 5

    return classified


def _renumber_mosaic(
    mosaic_path: Path,
    classified_path: Path,
    force_classified: bool,
) -> None:
    if classified_path.exists() and not force_classified:
        print(f"Classified output already exists, skipping: {classified_path}")
        return

    if classified_path.exists() and force_classified:
        print(f"Force enabled. Rebuilding classified output: {classified_path}")
        classified_path.unlink()

    print(f"Renumbering year values from {mosaic_path.name} into {classified_path.name}")

    tmp_path = classified_path.with_suffix(".tmp.tif")

    with rasterio.open(mosaic_path) as src:
        year = src.read(1)
        nodata = src.nodata

        classified = _classify_years(year, nodata)

        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            count=1,
            dtype="uint8",
            nodata=0,
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress="deflate",
            predictor=2,
            zlevel=6,
            BIGTIFF="IF_SAFER",
        )

        with rasterio.open(tmp_path, "w", **profile) as dst:
            dst.write(classified, 1)
            dst.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
            dst.update_tags(ns="rio_overview", resampling="nearest")

            dst.update_tags(
                class_0="nodata/background",
                class_1="<1990",
                class_2="1990-2000",
                class_3="2000-2010",
                class_4="2010-2020",
                class_5=">2020",
            )

    _copy_as_cog(tmp_path, classified_path)
    tmp_path.unlink(missing_ok=True)

    print(f"Wrote classified COG: {classified_path}")


def main() -> None:
    args = _parse_args()
    source_dir = args.source_dir

    if not source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {source_dir}")

    resampling = _resampling_mode(args.resampling)

    for keyword in MOSAIC_OUTPUT_NAMES:
        input_paths = _list_group_files(source_dir, keyword)

        mosaic_path = source_dir / MOSAIC_OUTPUT_NAMES[keyword]
        classified_path = source_dir / CLASSIFIED_OUTPUT_NAMES[keyword]

        _build_mosaic(
            keyword=keyword,
            input_paths=input_paths,
            mosaic_path=mosaic_path,
            resampling=resampling,
            force=args.force,
        )

        if not mosaic_path.exists():
            raise SystemExit(f"Mosaic file was not created or found: {mosaic_path}")

        _renumber_mosaic(
            mosaic_path=mosaic_path,
            classified_path=classified_path,
            force_classified=args.force_classified,
        )


if __name__ == "__main__":
    main()