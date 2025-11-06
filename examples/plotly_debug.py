# debug_dash.py
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html

# Path to your CSV
CSV_PATH = Path("/datawaha/esom/DatePalmCounting/Geoportal/Sensors/SensorReads/DD091527.csv")

# --- Load and prepare data ---
df = pd.read_csv(CSV_PATH)
df["Date Time"] = pd.to_datetime(df["Date Time"], errors="coerce")
df = df.dropna(subset=["Date Time"]).set_index("Date Time").sort_index()
df = df.select_dtypes("number")

# Choose A* columns (or all numeric)
cols = [c for c in df.columns if isinstance(c, str) and c.startswith("A")] or list(df.columns)

fig = go.Figure()
for c in cols:
    fig.add_scattergl(
        x=df.index,
        y=df[c],
        mode="lines",
        name=c,
    )

fig.update_layout(
    title=f"Soil moisture time series — {CSV_PATH.name}",
    autosize=True,
    height=740,
    margin=dict(l=50, r=20, t=90, b=90),
    legend=dict(
        title="Soil depth",
        orientation="h",
        yanchor="bottom", y=1.16,
        xanchor="left", x=0.0,
        itemwidth=140, itemsizing="constant",
    ),
    xaxis_rangeslider_visible=False,
)
fig.update_xaxes(type="date", title="Time", tickformat="%Y-%m-%d %H", showgrid=True)
fig.update_yaxes(title="Soil moisture content (%)", showgrid=True)

# --- Dash app layout ---
app = Dash(__name__)
app.title = "Sensor Time Series Debugger"
app.layout = html.Div([
    html.H2("🌴 Soil Moisture Time Series Viewer"),
    html.P(f"Loaded file: {CSV_PATH.name}"),
    dcc.Graph(figure=fig, style={"height": "90vh", "width": "100%"}),
])

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
