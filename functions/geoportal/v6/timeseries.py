# functions/geoportal/v6/timeseries.py
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import ipywidgets as W
import solara
from functions.geoportal.v6.config import CFG

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
_OKABE_ITO = [
    "#E69F00", "#56B4E9", "#009E73",
    "#F0E442", "#0072B2", "#D55E00",
    "#CC79A7", "#999999",
]

_TOL_BRIGHT = [
    "#4477AA", "#66CCEE", "#228833",
    "#CCBB44", "#EE6677", "#AA3377",
    "#BBBBBB", "#000000", "#332288",
]

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
    cfg_colors = _ts_param("colors")
    if isinstance(cfg_colors, (list, tuple)) and len(cfg_colors) > 0:
        return [cfg_colors[i % len(cfg_colors)] for i in range(n)]
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

    time_col = None
    for cand in getattr(
        CFG, "time_col_candidates", ("Date Time", "Datetime", "Timestamp", "Date", "date")
    ):
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


def _ensure_percent(series: pd.Series) -> pd.Series:
    """If values look like 0–1, convert to %, else pass-through."""
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().max() is not None and s.dropna().max() <= 1.00001:
        return s * 100.0
    return s


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
    # Typography fallbacks
    font_family="Arial",
    font_size=14,
    title_font_size=20,
    # NEW: safe default
    line_width=2,
)


def _ts_param(name: str):
    ts = getattr(CFG, "timeseries", None)
    if ts is not None and hasattr(ts, name):
        return getattr(ts, name)
    if hasattr(_DEFAULT_TS, name):
        return getattr(_DEFAULT_TS, name)
    raise AttributeError(f"timeseries param '{name}' missing on both CFG.timeseries and _DEFAULT_TS")


# ------------------------------
# Common layout helpers
# ------------------------------
def _apply_common_layout_dual(
    fig: go.Figure,
    *,
    title: str,
    width: int | None,
    height: int | None,
    band_height_px: int,
    gap_frac: float,
    labels_bottom: list[str],
):
    n = len(labels_bottom) if labels_bottom else 1
    if height is None:
        # Two rows: top (soil moisture) + bottom (stacked)
        height = max(720, int(n * band_height_px + 200))

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
        hovermode="x unified",
        transition_duration=0,
        font=dict(family=font_family, size=font_size),
        title_font=dict(size=title_font_size),
    )

    # x-axis (shared) — keep grid ON for bottom subplot only
    fig.update_xaxes(
        row=2, col=1,
        type="date",
        tickformat="%Y-%m-%d %H",
        showgrid=True,
        title_text="Time",
        title_font=dict(size=title_font_size),
        tickfont=dict(size=font_size),
    )

    # y-axis for TOP (root zone %) — grid OFF handled per-axes in plotting block
    fig.update_yaxes(
        row=1, col=1,
        title_text="Soil moisture (root zone, %)",
        title_font=dict(size=title_font_size),
        tickfont=dict(size=font_size),
        rangemode="tozero",
        zeroline=False,
    )

    # y-axis for BOTTOM (stacked normalized)
    tick_positions = [i * (1 + gap_frac) + 0.5 for i in range(n)]
    fig.update_yaxes(
        row=2, col=1,
        tickmode="array",
        tickvals=tick_positions,
        ticktext=labels_bottom or [f"Layer {i+1}" for i in range(n)],
        showgrid=False,
        title_text="Soil moisture (per depth layer, %)",
        title_font=dict(size=title_font_size),
        tickfont=dict(size=font_size),
        zeroline=False,
    )


# ------------------------------
# Solara component (Leaflet bottom-of-page figure)
# ------------------------------
@solara.component
def TimeSeriesFigure(df: pd.DataFrame, title: str = "Soil moisture time series"):
    if df is None or df.empty:
        with solara.Alert("No data to plot.", type="warning"):
            return

    num_df = df.select_dtypes("number")
    cols_all = [c for c in num_df.columns if isinstance(c, str)]
    # Prefer depth bands (A*) on bottom subplot; fallback to all numerics
    cols = [c for c in cols_all if c.startswith("A")] or cols_all

    max_layers = _ts_param("max_layers")
    cols = cols[:max_layers] if len(cols) > max_layers else cols
    if not cols:
        with solara.Alert("No numeric columns available for plotting.", type="warning"):
            return

    # X
    x = pd.to_datetime(num_df.index, errors="coerce")
    x_str = _to_time_strings(x)

    # Labels for stacked bands
    labels = [DEPTH_LEGENDS.get(c, c) for c in cols]

    gap_frac = _ts_param("gap_frac")
    band_height_px = _ts_param("band_height_px")
    manual_width = _ts_param("width")
    reverse_depth = _ts_param("reverse_depth")
    show_bands = _ts_param("show_background_bands")
    line_width = _ts_param("line_width")

    # NEW: read top-subplot config
    sm_column = _ts_param("sm_column")
    t0, t1, t2 = _ts_param("sm_region_thresholds")
    c_warn, c_stress, c_normal, c_sat = _ts_param("sm_region_colors")
    sm_min = _ts_param("sm_top_ylim_min")
    sm_min_ceiling = _ts_param("sm_top_min_ceiling")
    sm_pad = _ts_param("sm_top_ylim_pad")

    # Reverse depth (so 0–10 cm on top)
    if reverse_depth:
        cols = list(reversed(cols))
        labels = list(reversed(labels))

    # --- Build subplots: row1=soil moisture, row2=stacked bands ---
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.9, 1.6],  # top ~smaller, bottom larger
    )

    # ---------- TOP subplot: soil_moisture_root_zone with y-bands ----------
    if sm_column in num_df.columns:
        sm = _ensure_percent(num_df[sm_column])
        # Define y-limit to make top band visible even if data < t2
        ymax = float(max(sm_min_ceiling, (sm.max(skipna=True) or 0) + sm_pad))
        ymin = float(sm_min)

        # Region bands (use yref='y1', xref='x1')
        if len(x_str) >= 2:
            x0, x1 = x_str[0], x_str[-1]
            region_shapes = [
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=0,   y1=t0, fillcolor=c_warn,   line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t0,  y1=t1, fillcolor=c_stress, line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t1,  y1=t2, fillcolor=c_normal, line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t2,  y1=ymax, fillcolor=c_sat,  line=dict(width=0), layer="below", opacity=0.35),
            ]
            fig.update_layout(shapes=region_shapes)

        fig.add_scatter(
            x=x_str,
            y=sm,
            mode="lines",
            name="Soil Moisture (Root Zone)",
            line=dict(width=line_width, color="#4477AA"),
            hovertemplate="Time: %{x}<br>SM root zone: %{y:.2f}%<extra></extra>",
            row=1, col=1,
        )
        fig.update_yaxes(range=[ymin, ymax], row=1, col=1)

        # Turn OFF grid for the top subplot
        fig.update_yaxes(showgrid=False, row=1, col=1)
        fig.update_xaxes(showgrid=True, row=1, col=1)

        # Threshold lines
        for thr, dash in [(t0, "dot"), (t1, "dot"), (t2, "dash")]:
            fig.add_hline(y=thr, line_width=1, line_dash=dash, line_color="#555", row=1, col=1)

        # Annotations just ABOVE each lower threshold line: 0, t0, t1, t2
        labels_top = ["Warning", "Stress", "Refill", "Full"]  # bottom → top
        y_lines = [ymin, t0, t1, t2]
        dy = max(0.5, 0.02 * (ymax - ymin))  # small vertical offset
        for txt, yline in zip(labels_top, y_lines):
            fig.add_annotation(
                xref="paper", x=0.01,  # near left margin of the subplot
                yref="y1", y=yline + dy,
                text=txt,
                showarrow=False,
                font=dict(size=12, color="#333"),
                align="left",
            )

    # ---------- BOTTOM subplot: stacked depth bands (normalized) ----------
    colors = _resolve_palette(len(cols))
    band_even = _ts_param("band_fill_rgba_even")
    band_odd = _ts_param("band_fill_rgba_odd")

    if show_bands and len(x_str) >= 2:
        x0, x1 = x_str[0], x_str[-1]
        zebra = []
        for i, _ in enumerate(cols):
            y0 = i * (1 + gap_frac)
            y1 = y0 + 1
            fill = band_even if i % 2 == 0 else band_odd
            zebra.append(
                dict(
                    type="rect", xref="x2", yref="y2",
                    x0=x0, x1=x1, y0=y0, y1=y1,
                    fillcolor=fill, line=dict(width=0), layer="below",
                )
            )
        # keep existing region shapes for top; extend with zebra for bottom
        cur_shapes = list(fig.layout.shapes) if fig.layout.shapes else []
        fig.update_layout(shapes=tuple(cur_shapes + zebra))

    for i, c in enumerate(cols):
        y_raw = num_df[c].astype("float64")
        ymin = float(y_raw.min(skipna=True))
        ymax = float(y_raw.max(skipna=True))
        rng = ymax - ymin if pd.notnull(ymax) and pd.notnull(ymin) else 0.0
        if rng <= 0 or not pd.notnull(rng):
            y_norm = pd.Series(0.5, index=y_raw.index)
        else:
            y_norm = (y_raw - ymin) / rng

        offset = i * (1 + gap_frac)
        y_stack = (y_norm + offset)

        fig.add_scattergl(
            x=x_str,
            y=y_stack,
            mode="lines",
            name=labels[i],
            customdata=y_raw.to_numpy(),
            hovertemplate=(
                f"<b>{labels[i]}</b><br>"
                "Time: %{x}<br>"
                "Value: %{customdata:.3f}%<extra></extra>"
            ),
            line=dict(width=line_width, color=colors[i]),
            row=2, col=1,
        )

    _apply_common_layout_dual(
        fig,
        title=title,
        width=manual_width,
        height=None,
        band_height_px=band_height_px,
        gap_frac=gap_frac,
        labels_bottom=labels,
    )

    solara.Style(
        """
    .timeseries-stacked {
        overflow-x: auto;
        overflow-y: auto;
    }
    """
    )

    with solara.Div(classes=["timeseries-stacked"]):
        return solara.FigurePlotly(fig)


# ------------------------------
# Popup widget (ipywidgets)
# ------------------------------
# ------------------------------
# Popup widget (ipywidgets)
# ------------------------------
def build_plotly_widget(df: pd.DataFrame, title: str) -> W.Widget:
    """
    Build the sensor time series for use INSIDE a popup (no bottom panel).
    """
    if df is None or df.empty:
        return W.HTML("<i>No data to plot.</i>")

    num_df = df.select_dtypes("number")
    cols_all = [c for c in num_df.columns if isinstance(c, str)]
    cols = [c for c in cols_all if c.startswith("A")] or cols_all
    if not cols:
        return W.HTML("<i>No numeric columns available for plotting.</i>")

    # X-axis as nice time strings (avoids 1e18-style ticks)
    x = pd.to_datetime(num_df.index, errors="coerce")
    x_str = _to_time_strings(x, fmt="%Y-%m-%d %H:%M")

    labels = [DEPTH_LEGENDS.get(c, c) for c in cols]

    # 👉 Popup-friendly but BIGGER size
    manual_width = 1800          # was 1100
    popup_height = 800           # was 650

    gap_frac = _ts_param("gap_frac")
    band_height_px = _ts_param("band_height_px")
    reverse_depth = _ts_param("reverse_depth")
    show_bands = _ts_param("show_background_bands")
    line_width = _ts_param("line_width")

    # Read config for top subplot & zebra
    sm_column = _ts_param("sm_column")
    t0, t1, t2 = _ts_param("sm_region_thresholds")
    c_warn, c_stress, c_normal, c_sat = _ts_param("sm_region_colors")
    sm_min = _ts_param("sm_top_ylim_min")
    sm_min_ceiling = _ts_param("sm_top_min_ceiling")
    sm_pad = _ts_param("sm_top_ylim_pad")
    band_even = _ts_param("band_fill_rgba_even")
    band_odd  = _ts_param("band_fill_rgba_odd")

    if reverse_depth:
        cols = list(reversed(cols))
        labels = list(reversed(labels))

    # FigureWidget + subplots
    base_fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.9, 1.6],
    )
    fig = go.FigureWidget(base_fig)

    # ---------- TOP subplot ----------
    if sm_column in num_df.columns:
        sm = _ensure_percent(num_df[sm_column])
        ymax = float(max(sm_min_ceiling, (sm.max(skipna=True) or 0) + sm_pad))
        ymin = float(sm_min)

        if len(x_str) >= 2:
            x0, x1 = x_str[0], x_str[-1]
            region_shapes = [
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=0,  y1=t0, fillcolor=c_warn,   line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t0, y1=t1, fillcolor=c_stress, line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t1, y1=t2, fillcolor=c_normal, line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t2, y1=ymax, fillcolor=c_sat,  line=dict(width=0), layer="below", opacity=0.35),
            ]
            fig.layout.shapes = tuple(region_shapes)

        fig.add_scatter(
            x=x_str,
            y=sm,
            mode="lines",
            name="Soil Moisture (Root Zone)",
            line=dict(width=line_width, color="#4477AA"),
            hovertemplate="Time: %{x}<br>SM root zone: %{y:.2f}%<extra></extra>",
            row=1,
            col=1,
        )
        fig.update_yaxes(range=[ymin, ymax], row=1, col=1)

        fig.update_yaxes(showgrid=False, row=1, col=1)
        fig.update_xaxes(showgrid=False, row=1, col=1)

        for thr, dash in [(t0, "dot"), (t1, "dot"), (t2, "dash")]:
            fig.add_hline(y=thr, line_width=1, line_dash=dash, line_color="#555", row=1, col=1)

        labels_top = ["Warning", "Stress", "Refill", "Full"]
        y_lines = [ymin, t0, t1, t2]
        dy = max(0.5, 0.02 * (ymax - ymin))
        for txt, yline in zip(labels_top, y_lines):
            fig.add_annotation(
                xref="paper", x=0.01,
                yref="y1", y=yline + dy,
                text=txt,
                showarrow=False,
                font=dict(size=12, color="#333"),
                align="left",
            )

    # ---------- BOTTOM subplot ----------
    colors = _resolve_palette(len(cols))
    if show_bands and len(x_str) >= 2:
        x0, x1 = x_str[0], x_str[-1]
        zebra = []
        for i in range(len(cols)):
            y0 = i * (1 + gap_frac)
            y1 = y0 + 1
            fill = band_even if i % 2 == 0 else band_odd
            zebra.append(
                dict(
                    type="rect", xref="x2", yref="y2",
                    x0=x0, x1=x1, y0=y0, y1=y1,
                    fillcolor=fill, line=dict(width=0), layer="below",
                )
            )
        cur_shapes = list(fig.layout.shapes) if fig.layout.shapes else []
        fig.layout.shapes = tuple(cur_shapes + zebra)

    for i, c in enumerate(cols):
        y_raw = pd.Series(num_df[c].astype("float64"), index=num_df.index)
        ymin, ymax = y_raw.min(skipna=True), y_raw.max(skipna=True)
        rng = (ymax - ymin) if pd.notnull(ymax) and pd.notnull(ymin) else 0.0
        y_norm = ((y_raw - ymin) / rng).fillna(0.5) if rng > 0 else pd.Series(0.5, index=y_raw.index)

        offset = i * (1 + gap_frac)
        y_stack = (y_norm + offset).to_numpy()

        fig.add_scatter(
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
            line=dict(width=line_width, color=colors[i]),
            row=2,
            col=1,
        )

    # Make sure all stacked bands are visible
    max_band_top = (len(cols) - 1) * (1 + gap_frac) + 1
    fig.update_yaxes(
        row=2,
        col=1,
        range=[-0.2, max_band_top + 0.2],
        showgrid=False,
        zeroline=False,
    )

    # Layout: use larger height for popup
    _apply_common_layout_dual(
        fig,
        title=title,
        width=manual_width,
        height=popup_height,
        band_height_px=band_height_px,
        gap_frac=gap_frac,
        labels_bottom=labels,
    )

    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    fig.update_xaxes(
        row=2,
        col=1,
        tickangle=-45,
    )

    # 👉 Make the widget itself large in the popup, with scroll if needed
    return W.Box(
        [fig],
        layout=W.Layout(
            width=f"{manual_width}px",     # match manual_width
            height="820px",     # a bit larger than figure height
            overflow_x="auto",
            overflow_y="auto",
        ),
    )
