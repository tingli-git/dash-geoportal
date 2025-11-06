from __future__ import annotations
from pathlib import Path
import solara
import ipyleaflet
from functions.geoportal.v2.config import CFG
from functions.geoportal.v2.state import ReactiveRefs
from functions.geoportal.v2.basemap import create_base_map, osm_layer, esri_world_imagery_layer, ensure_controls, ensure_base_layers
from functions.geoportal.v2.layers import remove_prior_groups, add_group_and_fit
from functions.geoportal.v2.widgets import use_debounce, GeoJSONDrop
from functions.geoportal.v2.errors import Toast, use_toast
from functions.geoportal.v2.geojson_loader import load_icon_group_from_geojson   # <-- use loader directly
from functions.geoportal.v2.timeseries import resolve_csv_path, read_timeseries, build_plotly_widget,TimeSeriesFigure
import ipywidgets as W

@solara.component
def Page():
    show_toast, hide_toast, toast_state = use_toast()

    # UI state
    geojson_path, set_geojson_path = solara.use_state(str(CFG.default_geojson))
    debounced_path = use_debounce(geojson_path, delay_ms=500)
    refs = ReactiveRefs()

    # time-series reactive state
    ts_title, set_ts_title = solara.use_state("")
    ts_df, set_ts_df = solara.use_state(None)

    # Map
    m = solara.use_memo(lambda: create_base_map(CFG.map_center, CFG.map_zoom, CFG.map_width, CFG.map_height), [])
    osm = solara.use_memo(osm_layer, [])
    esri = solara.use_memo(esri_world_imagery_layer, [])
    solara.use_effect(lambda: (ensure_base_layers(m, osm, esri), ensure_controls(m)), [])

    # ---- callback used by popup button ----
    def on_show_timeseries(props: dict):
        try:
            csv_path = resolve_csv_path(props)
            df = read_timeseries(csv_path)                 # will raise on problems
            title = f"Sensor time series — {props.get('name') or props.get('sensor_id') or props.get('id') or csv_path.stem}"

            # (optional) big panel below the map
            set_ts_df(df)
            set_ts_title(title)

            show_toast(f"Loaded {csv_path}", "success")
            #print("CSV path:", csv_path)
            #print("DF shape:", df.shape)
            #print("Cols:", list(df.columns)[:10])
            return build_plotly_widget(df, title)          # <-- return widget for popup
        except Exception as e:
            # (optional) clear big panel
            set_ts_df(None); set_ts_title("")
            show_toast(str(e), "error")
            return W.HTML(f"<pre>{e}</pre>")               # <-- show error in popup
    # Build marker layer from GeoJSON (debounced)
    def _build():
        try:
            group, bounds = load_icon_group_from_geojson(Path(debounced_path), m, refs.active_marker_ref, on_show_timeseries)  # <-- pass callback
            return group, bounds, None
        except Exception as e:
            return None, None, str(e)

    icon_group, bounds, load_err = solara.use_memo(_build, [debounced_path])
    solara.use_effect(lambda: setattr(refs.did_fit_ref, "current", False), [debounced_path])
    solara.use_effect(lambda: show_toast(load_err, "error") if load_err else None, [load_err])

    def _sync():
        if not icon_group:
            return
        remove_prior_groups(m, keep=icon_group, names_to_prune={CFG.layer_group_name, "Sensor markers", ""})
        add_group_and_fit(m, icon_group, bounds, refs.did_fit_ref, max_zoom=CFG.fit_bounds_max_zoom, padding=CFG.fit_bounds_padding)
    solara.use_effect(_sync, [icon_group, bounds])

    # UI
    with solara.Column(gap="0.75rem"):
        solara.Markdown("### 🌴 Geoportal for Date Palm Field Informatics")
        with solara.Row(gap="0.75rem", style={"align-items": "flex-end"}):
            solara.InputText(label="GeoJSON path:", value=geojson_path, on_value=set_geojson_path, continuous_update=True)
        GeoJSONDrop(on_saved_path=set_geojson_path, label="...or drag & drop a .geojson to use it")
        solara.display(m)

        if ts_df is not None:
            with solara.Column(style={"width": "100%"}):   # ← ensure the container spans full width
                solara.Markdown(f"**{ts_title}**")
                TimeSeriesFigure(ts_df, title=ts_title)

        Toast(message=toast_state["message"], kind=toast_state["kind"], visible=toast_state["visible"], on_close=hide_toast)

    return
