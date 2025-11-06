
# pip install -r requirements.txt
import os, json
import pandas as pd
from flask import send_from_directory
from dash import Dash, html, dcc, Output, Input, State
import dash_leaflet as dl
import plotly.graph_objects as go

DATA_DIR = "data"
SENSOR_GEOJSON_PATH = os.path.join(DATA_DIR, "sensors.geojson")
SENSOR_TIMESERIES_DIR = os.path.join(DATA_DIR, "sensors")
RASTER_TILES_ROOT = os.path.join(DATA_DIR, "rasters")
YEARS = [2021, 2024]  # add more as you generate tiles

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

# Route for local XYZ tiles: /tiles/<year>/<z>/<x>/<y>.png
@server.route("/tiles/<year>/<int:z>/<int:x>/<int:y>.png")
def serve_tile(year, z, x, y):
    folder = f"tiles_{year}"
    tile_folder = os.path.join(RASTER_TILES_ROOT, folder, str(z), str(x))
    tile_path = os.path.join(tile_folder, f"{y}.png")
    if not os.path.exists(tile_path):
        # Helpful error if no tiles yet
        # You can comment this out in production
        from flask import abort
        abort(404, description=f"Tile not found: {tile_path}. Did you run gdal2tiles to create data/rasters/{folder}?")
    return send_from_directory(tile_folder, f"{y}.png", cache_timeout=0)

with open(SENSOR_GEOJSON_PATH, "r", encoding="utf-8") as f:
    sensors_geojson = json.load(f)

app.layout = html.Div(style={"height":"100vh","display":"grid","gridTemplateColumns":"1fr 360px","gap":"8px","padding":"8px"}, children=[
    dl.Map(id="map", center=[24.7136,46.6753], zoom=6, style={"height":"100%","width":"100%"}, children=[
        dl.TileLayer(url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                     attribution="&copy; OpenStreetMap contributors"),
        dl.TileLayer(id="raster-layer",
                     url=f"/tiles/{YEARS[-1]}/{{z}}/{{x}}/{{y}}.png",
                     opacity=0.85, attribution="Classification © your org"),
        dl.GeoJSON(id="sensors-layer", data=sensors_geojson, zoomToBounds=True,
                   options=dict(pointToLayer=dict(**{"function":"function(f, ll){return L.circleMarker(ll,{radius:6})}"}))),
        dl.ScaleControl(position="bottomleft"),
    ]),
    html.Div(style={"height":"100%","overflow":"auto"}, children=[
        html.H3("Controls"),
        html.Label("Year"),
        dcc.Slider(id="year-slider", min=min(YEARS), max=max(YEARS), step=1, value=max(YEARS),
                   marks={y:str(y) for y in YEARS}),
        html.Br(),
        html.Div([html.Div("Selected sensor:", style={"fontWeight":600}),
                  html.Div(id="sensor-id", children="—"),
                  html.Div(["Installed since: ", html.Span(id="sensor-installed", children="—")],
                           style={"fontSize":"12px","color":"#555","marginTop":"4px"})],
                 style={"marginBottom":"10px"}),
        html.Label("Variable"),
        dcc.Dropdown(id="var-select",
                     options=[{"label":"soil_moisture","value":"soil_moisture"},
                              {"label":"soil_temp","value":"soil_temp"}],
                     value="soil_moisture", clearable=False),
        html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr","gap":"6px","marginTop":"8px"}, children=[
            html.Div([html.Label("Start (UTC)"), html.Input(id="tstart", type="datetime-local")]),
            html.Div([html.Label("End (UTC)"), html.Input(id="tend", type="datetime-local")]),
        ]),
        html.Button("Load series", id="load-series", n_clicks=0, style={"marginTop":"8px"}),
        dcc.Graph(id="ts-graph", style={"height":"280px","marginTop":"8px"})
    ])
])

@app.callback(Output("raster-layer","url"), Input("year-slider","value"))
def set_year(year):
    return f"/tiles/{int(year)}/{{z}}/{{x}}/{{y}}.png"

@app.callback(Output("sensor-id","children"),
              Output("sensor-installed","children"),
              Input("sensors-layer","click_feature"))
def select_sensor(click_feature):
    if not click_feature:
        return "—","—"
    p = click_feature.get("properties", {}) or {}
    return p.get("sensor_id","unknown"), p.get("installed_since","n/a")

@app.callback(Output("ts-graph","figure"),
              Input("load-series","n_clicks"),
              State("sensor-id","children"),
              State("var-select","value"),
              State("tstart","value"),
              State("tend","value"))
def plot_series(n, sensor_id, var_name, tstart, tend):
    fig = go.Figure()
    if not n:
        return fig.update_layout(margin=dict(l=40,r=10,t=10,b=30))
    if sensor_id in (None,"—","unknown"):
        return fig.update_layout(title="Click a sensor on the map, then Load.")
    csv_path = os.path.join(SENSOR_TIMESERIES_DIR, f"{sensor_id}.csv")
    if not os.path.exists(csv_path):
        return fig.update_layout(title=f"No CSV found for {sensor_id}")
    df = pd.read_csv(csv_path)
    if "timestamp" not in df.columns:
        return fig.update_layout(title="CSV missing 'timestamp' column")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    if tstart:
        df = df[df["timestamp"] >= pd.to_datetime(tstart, utc=True)]
    if tend:
        df = df[df["timestamp"] <= pd.to_datetime(tend, utc=True)]
    if var_name not in df.columns:
        return fig.update_layout(title=f"Column '{var_name}' not found")
    fig.add_trace(go.Scatter(x=df["timestamp"], y=df[var_name], mode="lines", name=var_name))
    fig.update_layout(title=f"{sensor_id} – {var_name}", xaxis_title="Time (UTC)", yaxis_title=var_name,
                      margin=dict(l=40,r=10,t=30,b=30))
    return fig

if __name__ == "__main__":
    app.run_server(debug=True)
