# functions/geoportal/v2/timeseries.py
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots  # (kept if you later need real subplots)
import ipywidgets as W
import solara
from functions.geoportal.v4.config import CFG

# ------------------------------
# Depth mapping legend
# ------------------------------
DEPTH_LEGENDS = {
    "A1(5)":  "0–10 cm",
    "A2(15)": "10–20 cm",
    "A3(25)": "20–30 cm",
    "A4(35)": "30–40 cm",
    "A5(45)": "40–50 cm",
    "A6(55)": "50–60 cm",
    "A7(65)": "60–70 cm",
    "A8(75)": "70–80 cm",
    "A9(85)": "80–90 cm",
}
# ---- Color palettes (color-blind friendly) ----
# Okabe–Ito: widely used, CB-safe
_OKABE_ITO = [
    "#E69F00", "#56B4E9", "#009E73",
    "#F0E442", "#0072B2", "#D55E00",
    "#CC79A7", "#999999",
]

# Paul Tol 'Bright' (CB-safe)
_TOL_BRIGHT = [
    "#4477AA", "#66CCEE", "#228833",
    "#CCBB44", "#EE6677", "#AA3377",
    "#BBBBBB", "#000000", "#332288",
]

# "Kaarten Ova": map-friendly, distinct, CB-safe leaning (curated from Tol + Okabe–Ito hues)
_KAARTEN_OVA = [
    "#0077BB", "#33BBEE", "#009988",
    "#EE7733", "#CC3311", "#EE3377",
    "#228833", "#AA4499", "#807A7A",
]

_PALETTES = {
    "okabe_ito": _OKABE_ITO,
    "tol_bright": _TOL_BRIGHT,
    "kaarten_ova": _KAARTEN_OVA,
}

def _resolve_palette(n: int) -> list[str]:
    # 1) explicit color list in config wins
    cfg_colors = _ts_param("colors")
    if isinstance(cfg_colors, (list, tuple)) and len(cfg_colors) > 0:
        return [cfg_colors[i % len(cfg_colors)] for i in range(n)]

    # 2) otherwise use named palette
    name = getattr(CFG.timeseries, "palette_name", "kaarten_ova")
    pal = _PALETTES.get(name, _KAARTEN_OVA)
    return [pal[i % len(pal)] for i in range(n)]
# ------------------------------
# CSV resolver and reader
# ------------------------------
def resolve_csv_path(props: dict) -> Path:
    """Choose CSV path based on popup props (id or sensor_id)."""
    if "csv_path" in props and props["csv_path"]:
        return Path(str(props["csv_path"]))
    sensor_id = props.get("sensor_id") or props.get("id")
    if not sensor_id:
        raise FileNotFoundError("No 'csv_path' or 'sensor_id'/'id' in properties.")
    return CFG.sensor_csv_dir / f"{sensor_id}.csv"


def read_timeseries(csv_path: Path) -> pd.DataFrame:
    """Read sensor CSV and set the time column as datetime index."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)

    # Find a datetime column using CFG candidates
    time_col = None
    for cand in getattr(CFG, "time_col_candidates", ("Date Time", "Datetime", "Timestamp", "Date", "date")):
        if cand in df.columns:
            time_col = cand
            break
    if not time_col:
        raise ValueError(f"No datetime column found in {csv_path}")

    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=[time_col]).set_index(time_col).sort_index()

    num = df.select_dtypes("number")
    if num.empty:
        raise ValueError(f"No numeric columns in {csv_path}")
    return num

# ------------------------------
# Utilities
# ------------------------------
def _to_time_strings(index_like, fmt: str = "%Y-%m-%d %H:%M:%S") -> pd.Index:
    """Convert an index/array-like of datetimes to strings for Plotly."""
    if isinstance(index_like, pd.DatetimeIndex):
        return index_like.strftime(fmt)
    ser = pd.to_datetime(index_like, errors="coerce")
    return pd.Series(ser).dt.strftime(fmt).to_numpy()

# ------------------------------
# Timeseries parameter resolution (single source of truth)
# ------------------------------
_DEFAULT_TS = SimpleNamespace(
    width=1800,
    band_height_px=100,
    gap_frac=0.0,
    max_layers=9,
    reverse_depth=True,
    show_background_bands=True,
    # Typography fallbacks (prevents AttributeError if config is older)
    font_family="Arial",
    font_size=14,
    title_font_size=20,
)

def _ts_param(name: str):
    ts = getattr(CFG, "timeseries", None)
    if ts is not None and hasattr(ts, name):
        return getattr(ts, name)
    if hasattr(_DEFAULT_TS, name):
        return getattr(_DEFAULT_TS, name)
    raise AttributeError(f"timeseries param '{name}' missing on both CFG.timeseries and _DEFAULT_TS")

# ------------------------------
# Plotly common layout
# ------------------------------
def _apply_common_layout_stacked(
    fig: go.Figure,
    *,
    title: str,
    width: int | None,
    height: int | None,
    band_height_px: int,
    gap_frac: float,
    labels: list[str] | None,
):
    n = len(labels) if labels else 1
    if height is None:
        height = max(700, int(n * band_height_px + 140))  # top/bottom margins

    # Typography from config
    font_family = _ts_param("font_family")
    font_size = _ts_param("font_size")
    title_font_size = _ts_param("title_font_size")

    fig.update_layout(
        title=title,
        autosize=(width is None),
        width=width,
        height=height,
        margin=dict(l=70, r=30, t=90, b=70),
        showlegend=False,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        transition_duration=0,
        font=dict(family=font_family, size=font_size),
        title_font=dict(size=title_font_size),
    )

    # x axis formatting
    fig.update_xaxes(
        type="date",
        tickformat="%Y-%m-%d %H",
        showgrid=True,
        tickfont=dict(size=font_size),
        title_text="Time",
        title_font=dict(size=title_font_size),
    )

    # y axis ticks at band centers
    tick_positions = [i * (1 + gap_frac) + 0.5 for i in range(n)]
    fig.update_yaxes(
        tickmode="array",
        tickvals=tick_positions,
        ticktext=labels or [f"Layer {i+1}" for i in range(n)],
        showgrid=False,
        title_text="Depth layers (stacked, normalized)",
        title_font=dict(size=title_font_size),
        tickfont=dict(size=font_size),
        zeroline=False,
    )

# ------------------------------
# Solara component (Leaflet popup figure)
# ------------------------------
@solara.component
def TimeSeriesFigure(df: pd.DataFrame, title: str = "Soil moisture time series"):
    if df is None or df.empty:
        with solara.Alert("No data to plot.", type="warning"):
            return

    num_df = df.select_dtypes("number")
    cols_all = [c for c in num_df.columns if isinstance(c, str)]
    cols = [c for c in cols_all if c.startswith("A")] or cols_all

    max_layers = _ts_param("max_layers")
    cols = cols[:max_layers] if len(cols) > max_layers else cols
    if not cols:
        with solara.Alert("No numeric columns available for plotting.", type="warning"):
            return

    x = pd.to_datetime(num_df.index, errors="coerce")
    x_str = _to_time_strings(x)

    labels = [DEPTH_LEGENDS.get(c, c) for c in cols]

    gap_frac = _ts_param("gap_frac")
    band_height_px = _ts_param("band_height_px")
    manual_width = _ts_param("width")
    reverse_depth = _ts_param("reverse_depth")
    show_bands = _ts_param("show_background_bands")

    # Reverse so 0–10 cm is on top if requested
    if reverse_depth:
        cols = list(reversed(cols))
        labels = list(reversed(labels))

    fig = go.Figure()
    # ✅ add these two lines here
    colors = _resolve_palette(len(cols))
    line_width = _ts_param("line_width")

    # Background zebra bands
    if show_bands and len(x_str) >= 2:
        x0, x1 = x_str[0], x_str[-1]
        shapes = []
        for i, _ in enumerate(cols):
            y0 = i * (1 + gap_frac)
            y1 = y0 + 1
            fill = "rgba(0,0,0,0.03)" if i % 2 == 0 else "rgba(0,0,0,0.06)"
            shapes.append(dict(
                type="rect", xref="x", yref="y",
                x0=x0, x1=x1, y0=y0, y1=y1,
                fillcolor=fill, line=dict(width=0), layer="below"
            ))
        if shapes:
            fig.update_layout(shapes=shapes)

    # Traces (normalize to [0,1] then vertically offset)
    for i, c in enumerate(cols):
        y_raw = num_df[c].to_numpy()
        s = pd.Series(y_raw, index=num_df.index, dtype="float64")
        ymin = float(s.min(skipna=True))
        ymax = float(s.max(skipna=True))
        rng = ymax - ymin if pd.notnull(ymax) and pd.notnull(ymin) else 0.0
        if rng <= 0 or not pd.notnull(rng):
            y_norm = pd.Series(0.5, index=s.index).to_numpy()
        else:
            y_norm = ((s - ymin) / rng).to_numpy()

        offset = i * (1 + gap_frac)
        y_stack = y_norm + offset

        fig.add_scattergl(
            x=x_str,
            y=y_stack,
            mode="lines",
            name=labels[i],
            customdata=y_raw,
            hovertemplate=(
                f"<b>{labels[i]}</b><br>"
                "Time: %{x}<br>"
                "Value: %{customdata:.3f}%<extra></extra>"
            ),
            # apply palette + width
            line=dict(width=line_width, color=colors[i]),
        )

    _apply_common_layout_stacked(
        fig,
        title=title,
        width=manual_width,
        height=None,
        band_height_px=band_height_px,
        gap_frac=gap_frac,
        labels=labels,
    )

    solara.Style("""
    .timeseries-stacked {
        overflow-x: auto;
        overflow-y: auto;
    }
    """)

    with solara.Div(classes=["timeseries-stacked"]):
        return solara.FigurePlotly(fig)

# ------------------------------
# Popup widget (ipywidgets)
# ------------------------------
def build_plotly_widget(df: pd.DataFrame, title: str) -> W.Widget:
    if df is None or df.empty:
        return W.HTML("<i>No data to plot.</i>")

    num_df = df.select_dtypes("number")
    cols_all = [c for c in num_df.columns if isinstance(c, str)]
    cols = [c for c in cols_all if c.startswith("A")] or cols_all
    if not cols:
        return W.HTML("<i>No numeric columns available for plotting.</i>")

    x = pd.to_datetime(num_df.index, errors="coerce")
    x_str = _to_time_strings(x)

    labels = [DEPTH_LEGENDS.get(c, c) for c in cols]

    manual_width = _ts_param("width")
    gap_frac = _ts_param("gap_frac")
    band_height_px = _ts_param("band_height_px")
    reverse_depth = _ts_param("reverse_depth")
    show_bands = _ts_param("show_background_bands")

    if reverse_depth:
        cols = list(reversed(cols))
        labels = list(reversed(labels))

    n = len(cols)
    fig = go.FigureWidget()
    # add these two lines
    colors = _resolve_palette(len(cols))
    line_width = _ts_param("line_width")

    if show_bands and len(x_str) >= 2:
        x0, x1 = x_str[0], x_str[-1]
        shapes = []
        for i in range(n):
            y0 = i * (1 + gap_frac)
            y1 = y0 + 1
            fill = "rgba(0,0,0,0.03)" if i % 2 == 0 else "rgba(0,0,0,0.06)"
            shapes.append(dict(
                type="rect", xref="x", yref="y",
                x0=x0, x1=x1, y0=y0, y1=y1,
                fillcolor=fill, line=dict(width=0), layer="below"
            ))
        fig.layout.shapes = tuple(shapes)

    for i, c in enumerate(cols):
        y_raw = pd.Series(num_df[c].astype("float64"), index=num_df.index)
        ymin, ymax = y_raw.min(skipna=True), y_raw.max(skipna=True)
        rng = (ymax - ymin) if pd.notnull(ymax) and pd.notnull(ymin) else 0.0
        y_norm = ((y_raw - ymin) / rng).fillna(0.5) if rng > 0 else pd.Series(0.5, index=y_raw.index)

        offset = i * (1 + gap_frac)
        y_stack = (y_norm + offset).to_numpy()

        fig.add_scattergl(
            x=x_str,
            y=y_stack,
            mode="lines",
            name=labels[i],
            showlegend=False,
            customdata=y_raw.to_numpy(),
            hovertemplate=(
                f"<b>{labels[i]}</b><br>"
                "Time: %{x}<br>"
                "Value: %{customdata:.3f}%<extra></extra>"
            ),
            # apply here too
            line=dict(width=line_width, color=colors[i]),
        )

    _apply_common_layout_stacked(
        fig,
        title=title,
        width=manual_width,
        height=None,
        band_height_px=band_height_px,
        gap_frac=gap_frac,
        labels=labels,
    )

    return W.Box([fig], layout=W.Layout(width="100%", overflow_x="auto"))
