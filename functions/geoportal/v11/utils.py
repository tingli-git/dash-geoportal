from __future__ import annotations
from typing import Any, Iterable, Sequence
from ipywidgets import HTML

def padded_bounds(coords: Sequence[tuple[float, float]], min_span=0.05, pad=0.25):
    if not coords:
        return None
    lats = [lat for lat, lon in coords]
    lons = [lon for lat, lon in coords]
    south, west = min(lats), min(lons)
    north, east = max(lats), max(lons)
    lat_span = max(north - south, min_span)
    lon_span = max(east - west, min_span)
    south -= lat_span * pad
    north += lat_span * pad
    west  -= lon_span * pad
    east  += lon_span * pad
    return [[south, west], [north, east]]

def html_table_popup(props: dict | None) -> HTML:
    skip_keys = {"field_id", "province_id", "style"}
    label_mapping = {
        "province": "PROVINCE",
        "area_m2": "AREA (m2)",
        "area_ha": "AREA (Ha)",
        "esti_tree_number": "ESTIMATED TREE NUMBER",
    }

    def render_cell(key: str, value: Any) -> str:
        if isinstance(value, str) and value.startswith("http"):
            return f"<a href='{value}' target='_blank' rel='noopener'>{value}</a>"
        return str(value)

    def format_value(key: str, value: Any) -> Any:
        if key == "area_m2" and value is not None:
            try:
                return int(round(float(value)))
            except (ValueError, TypeError):
                return value
        if key == "area_ha" and value is not None:
            try:
                return f"{float(value):.2f}"
            except (ValueError, TypeError):
                return value
        return value

    rows = ""
    if props:
        ordered_keys = ["province", "area_m2", "area_ha", "esti_tree_number"]
        seen = set()
        def add_row(key: str, value: Any) -> None:
            label = label_mapping.get(key) or key.replace("_", " ").upper()
            formatted = format_value(key, value)
            rows_add = (
                f"<tr><th style='text-align:left;padding:4px 8px'>{label}</th>"
                f"<td style='padding:4px 0'>{render_cell(key, formatted)}</td></tr>"
            )
            nonlocal rows
            rows += rows_add

        for key in ordered_keys:
            if key in props and key not in skip_keys:
                add_row(key, props[key])
                seen.add(key)

        for key, value in props.items():
            if key in skip_keys or key in seen:
                continue
            add_row(key, value)
    else:
        rows = "<tr><td><i>No properties</i></td></tr>"

    return HTML(
        f"""
        <style>
        .leaflet-popup-content-wrapper {{ background: transparent !important; box-shadow: none !important; }}
        .leaflet-popup-tip {{ background: transparent !important; }}
        </style>
        <div style="
                    max-height:400px;
                    overflow:auto;
                    background-color: rgba(255, 255, 255, 0.75);
                    border-radius: 8px;
                    padding: 8px;
                    box-shadow: 0 1px 4px rgba(0,0,0,0.3);
                    min-width: 260px;
                    max-width: 320px;
        ">
        <table style="border-collapse:collapse;font-size:18px;width:100%">{rows}</table>
        </div>
        """
    )
