from __future__ import annotations
from pathlib import Path
import solara
import ipyleaflet
from functions.geoportal.v1.config import CFG
from functions.geoportal.v1.state import ReactiveRefs
from functions.geoportal.v1.basemap import create_base_map, osm_layer, esri_world_imagery_layer, ensure_controls, ensure_base_layers
from functions.geoportal.v1.geojson_loader import load_icon_group_from_geojson
from functions.geoportal.v1.layers import remove_prior_groups, add_group_and_fit

@solara.component
def Page():
    # ---- UI State ----
    geojson_path, set_geojson_path = solara.use_state(str(CFG.default_geojson))
    refs = ReactiveRefs()

    # ---- Map (memoized) ----
    m = solara.use_memo(
        lambda: create_base_map(CFG.map_center, CFG.map_zoom, CFG.map_width, CFG.map_height),
        [],
    )

    # ---- Base layers + controls ----
    osm = solara.use_memo(osm_layer, [])
    esri = solara.use_memo(esri_world_imagery_layer, [])
    solara.use_effect(lambda: (ensure_base_layers(m, osm, esri), ensure_controls(m)), [])

    # ---- Load data & build layer group (memoized on path) ----
    def _build_group():
        return load_icon_group_from_geojson(Path(geojson_path), m, refs.active_marker_ref)
    icon_group, bounds = solara.use_memo(_build_group, [geojson_path])

    # reset fit flag when path changes
    solara.use_effect(lambda: setattr(refs.did_fit_ref, "current", False), [geojson_path])

    # ---- Ensure group present & fit to bounds ----
    def _sync_group():
        if not icon_group:
            return
        remove_prior_groups(m, keep=icon_group, names_to_prune={CFG.layer_group_name, "Sensor markers", ""})
        add_group_and_fit(
            m, icon_group, bounds, refs.did_fit_ref,
            max_zoom=CFG.fit_bounds_max_zoom, padding=CFG.fit_bounds_padding
        )
    solara.use_effect(_sync_group, [icon_group, bounds])

    # ---- UI ----
    with solara.Column(gap="0.75rem"):
        solara.Markdown("### 🌴 Geoportal for Date Palm Field Informatics")
        solara.InputText(label="GeoJSON path:", value=geojson_path, on_value=set_geojson_path)
        solara.display(m)

    return
