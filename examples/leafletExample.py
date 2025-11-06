# leafletExample.py
import os
import json
import solara
import ipyleaflet
from ipywidgets import Layout, HTML

# ------------------------------
# CONFIGURATION
# ------------------------------
TOP_DIR = "/datawaha/esom/DatePalmCounting/Geoportal"
GEOJSON_PATH_DEFAULT = f"{TOP_DIR}/Sensors/SensorInfos/AldakaSensors.geojson"


@solara.component
def Page():
    # --- UI state ---
    geojson_path, set_geojson_path = solara.use_state(GEOJSON_PATH_DEFAULT)
    active_marker_ref = solara.use_ref(None)  # track the selected marker

    # --- Create the map once ---
    m = solara.use_memo(
        lambda: ipyleaflet.Map(
            center=[29, 40],
            zoom=5,
            scroll_wheel_zoom=True,
            layout=Layout(height="90vh", width="100%"),
        ),
        [],
    )

    # --- Base maps ---
    osm = solara.use_memo(
        lambda: ipyleaflet.TileLayer(
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            attribution="© OpenStreetMap contributors",
            name="OpenStreetMap",
            base=True,
            max_zoom=19,
        ),
        [],
    )
    esri_sat = solara.use_memo(
        lambda: ipyleaflet.TileLayer(
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attribution="© Esri, Maxar, Earthstar Geographics",
            name="ESRI World Imagery",
            max_zoom=19,
        ),
        [],
    )

    def ensure_base_layers():
        if osm not in m.layers:
            m.add_layer(osm)
        if esri_sat not in m.layers:
            m.add_layer(esri_sat)
        if not any(isinstance(c, ipyleaflet.LayersControl) for c in m.controls):
            m.add_control(ipyleaflet.LayersControl(position="topright"))
        if not any(isinstance(c, ipyleaflet.ScaleControl) for c in m.controls):
            m.add_control(ipyleaflet.ScaleControl(position="bottomleft"))

    solara.use_effect(ensure_base_layers, [])

    # ------------------------------
    # Load GeoJSON and create icon LayerGroup
    # ------------------------------
    def load_icon_group():
        if not geojson_path or not os.path.exists(geojson_path):
            return None, None

        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # --- compute padded bounds from points ---
        coords = []
        for feat in data.get("features", []):
            geom = feat.get("geometry", {})
            if geom.get("type") == "Point":
                xy = geom.get("coordinates", [None, None])
                if xy and xy[0] is not None and xy[1] is not None:
                    coords.append(xy)

        bounds = None
        if coords:
            lons, lats = zip(*coords)
            south, west = min(lats), min(lons)
            north, east = max(lats), max(lons)
            lat_span = max(north - south, 0.05)
            lon_span = max(east - west, 0.05)
            pad = 0.25
            south -= lat_span * pad
            north += lat_span * pad
            west -= lon_span * pad
            east += lon_span * pad
            bounds = [[south, west], [north, east]]

        # --- popup renderer ---
        def make_html_table(props):
            def render_cell(v):
                if isinstance(v, str) and v.startswith("http"):
                    return f"<a href='{v}' target='_blank' rel='noopener'>{v}</a>"
                return str(v)
            rows = ""
            if props:
                for k, v in props.items():
                    rows += (
                        f"<tr><th style='text-align:left;padding:4px 8px'>{k}</th>"
                        f"<td style='padding:4px 0'>{render_cell(v)}</td></tr>"
                    )
            else:
                rows = "<tr><td><i>No properties</i></td></tr>"
            return HTML(
                f"""
                <style>
                .leaflet-popup-content-wrapper {{
                    background: transparent !important;
                    box-shadow: none !important;
                }}
                .leaflet-popup-tip {{
                    background: transparent !important;
                }}
                </style>
                <div style="
                    max-height:400px;
                    overflow:auto;
                    background-color: rgba(255, 255, 255, 0.75);
                    border-radius: 8px;
                    padding: 6px;
                    box-shadow: 0 1px 4px rgba(0,0,0,0.3);
                ">
                  <table style="border-collapse:collapse;font-size:13px;width:100%">
                    {rows}
                  </table>
                </div>
                """
            )

        def show_popup(lat, lon, props, marker):
            prev_center, prev_zoom = tuple(m.center), m.zoom

            # reset previous marker color if any
            if active_marker_ref.current and active_marker_ref.current is not marker:
                active_marker_ref.current.icon = ipyleaflet.AwesomeIcon(
                    name="tint", marker_color="blue", icon_color="white"
                )

            # highlight current marker
            marker.icon = ipyleaflet.AwesomeIcon(
                name="tint", marker_color="lightred", icon_color="white"
            )
            active_marker_ref.current = marker

            html = make_html_table(props)
            popup = ipyleaflet.Popup(
                location=(lat, lon),
                child=html,
                close_button=True,
                auto_close=True,
                close_on_escape_key=True,
                auto_pan=False,
            )
            # remove existing popups
            for layer in list(m.layers):
                if isinstance(layer, ipyleaflet.Popup):
                    m.remove_layer(layer)
            m.add_layer(popup)
            m.center, m.zoom = prev_center, prev_zoom

        # --- build the named icon group ---
        icon_group = ipyleaflet.LayerGroup(name="Sensors in Al Daka")
        base_icon = ipyleaflet.AwesomeIcon(
            name="tint",
            marker_color="blue",
            icon_color="white",
        )

        for feat in data.get("features", []):
            geom = feat.get("geometry", {})
            props = feat.get("properties", {})
            if geom.get("type") != "Point":
                continue
            lon, lat = geom.get("coordinates", [None, None])
            if lat is None or lon is None:
                continue
            marker = ipyleaflet.Marker(location=(lat, lon), icon=base_icon)
            marker.on_click(lambda props=props, lat=lat, lon=lon, mk=marker, **_: show_popup(lat, lon, props, mk))
            icon_group.add_layer(marker)

        return icon_group, bounds

    icon_group, bounds = solara.use_memo(load_icon_group, [geojson_path])

    # ------------------------------
    # Add icon group to map
    # ------------------------------
    did_fit = solara.use_ref(False)
    solara.use_effect(lambda: setattr(did_fit, "current", False), [geojson_path])

    def ensure_group_added():
        if not icon_group:
            return
        # remove old markers or groups
        for layer in list(m.layers):
            if isinstance(layer, (ipyleaflet.Marker, ipyleaflet.LayerGroup)):
                if getattr(layer, "name", "") in ("Sensors in Al Daka", "Sensor markers", "") and layer is not icon_group:
                    m.remove_layer(layer)
        if icon_group not in m.layers:
            m.add_layer(icon_group)
        if bounds and not did_fit.current:
            try:
                m.fit_bounds(bounds, max_zoom=14, padding=(20, 20))
            except TypeError:
                m.fit_bounds(bounds)
                if m.zoom > 14:
                    m.zoom = 14
            did_fit.current = True

    solara.use_effect(ensure_group_added, [icon_group, bounds])

    # ------------------------------
    # UI layout
    # ------------------------------
    with solara.Column(gap="0.75rem"):
        solara.Markdown("### 🌴 Geoportal for Date Palm Field Informatics")
        solara.InputText("GeoJSON path:", value=geojson_path, on_value=set_geojson_path)
        solara.display(m)

    return
