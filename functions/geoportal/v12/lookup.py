"""Field lookup helpers for interactive Date Palm field highlighting."""
from __future__ import annotations

import json
from dataclasses import dataclass
from math import isnan
from pathlib import Path
from typing import Any, Dict, List, Tuple

import geopandas as gpd
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree


@dataclass
class FieldRecord:
    field_id: str
    province_id: int | None
    province_name: str | None
    attributes: Dict[str, Any]
    geometry: BaseGeometry


class FieldLookup:
    """In-memory index of Date Palm field polygons by province."""

    def __init__(self, province_dir: Path | str, lookup_json: Path | str):
        self.province_dir = Path(province_dir)
        if not self.province_dir.is_dir():
            raise FileNotFoundError(f"Province directory not found: {self.province_dir}")

        self._province_id_to_name, self._province_name_to_id = self._load_lookup_mapping(lookup_json)
        self._records: List[FieldRecord] = []
        self._strtree: STRtree | None = None
        self._geom_to_record: Dict[int, FieldRecord] = {}

        self._load_records()

    def _load_lookup_mapping(self, lookup_json: Path | str) -> Tuple[Dict[int, str], Dict[str, int]]:
        if not lookup_json:
            return {}, {}
        path = Path(lookup_json)
        if not path.exists():
            return {}, {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}, {}

        id_map: Dict[int, str] = {}
        name_map: Dict[str, int] = {}
        for key, name in data.items():
            try:
                province_id = int(key)
            except Exception:
                continue
            label = str(name).strip()
            if not label:
                continue
            id_map[province_id] = label
            name_map[label] = province_id
        return id_map, name_map

    def _load_records(self) -> None:
        paths = sorted(self.province_dir.glob("*.gpkg"))
        if not paths:
            raise FileNotFoundError(f"No GeoPackages found in {self.province_dir}")

        geometries: List[BaseGeometry] = []
        for path in paths:
            province = path.stem
            try:
                gdf = gpd.read_file(path)
            except Exception:
                continue
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                try:
                    gdf = gdf.to_crs(4326)
                except Exception:
                    pass

            gdf = gdf[~(gdf.geometry.isna() | gdf.geometry.is_empty)]
            if gdf.empty:
                continue

            for idx, row in gdf.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty:
                    continue

                row_data = dict(row)
                row_data.pop("geometry", None)
                raw_field_id = row_data.pop("field_id", None)
                raw_province_id = row_data.pop("province_id", None)
                raw_province_name = row_data.pop("province_name", None)

                field_id = str(raw_field_id) if raw_field_id is not None else f"{province}_{idx}"
                province_id = _as_int(raw_province_id)
                if province_id is None:
                    province_id = self._province_name_to_id.get(raw_province_name or province)
                province_name = (
                    str(raw_province_name)
                    if raw_province_name
                    else self._province_id_to_name.get(province_id)
                    if province_id is not None
                    else province
                )
                attributes = _filter_nan(row_data)
                record = FieldRecord(
                    field_id=field_id,
                    province_id=province_id,
                    province_name=province_name,
                    attributes=attributes,
                    geometry=geom,
                )
                self._records.append(record)
                geometries.append(geom)

        if not self._records:
            raise ValueError("No field records loaded for lookup")

        self._strtree = STRtree(geometries)
        self._geom_to_record = {id(geom): rec for rec, geom in zip(self._records, geometries)}

    def lookup(self, lon: float, lat: float) -> FieldRecord | None:
        if self._strtree is None:
            return None
        try:
            point = Point(float(lon), float(lat))
        except Exception:
            return None

        candidates = self._strtree.query(point)
        for geom in candidates:
            if geom is None:
                continue
            if geom.contains(point) or geom.touches(point):
                return self._geom_to_record.get(id(geom))
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, str) and value.strip() == "":
            return None
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _filter_nan(source: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in source.items():
        if value is None:
            continue
        if isinstance(value, float) and isnan(value):
            continue
        result[key] = value
    return result
