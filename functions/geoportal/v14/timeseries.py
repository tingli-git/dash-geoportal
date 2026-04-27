# functions/geoportal/v14/timeseries.py
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import ipywidgets as W
import solara

from functions.geoportal.v14.config import CFG
from functions.geoportal.v14.cloud_assets import ensure_local_asset


# ------------------------------
# Depth mapping legend
# ------------------------------
DEPTH_LEGENDS = {
    "A1(5)": "0–10 cm",
    "A2(15)": "10–20 cm",
    "A3(25)": "20–30 cm",
    "A4(35)": "30–40 cm",
    "A5(45)": "40–50 cm",
    "A6(55)": "50–60 cm",
    "A7(65)": "60–70 cm",
    "A8(75)": "70–80 cm",
    "A9(85)": "80–90 cm",
}


# ------------------------------
# Color palettes, color-blind friendly
# ------------------------------
_OKABE_ITO = [
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#999999",
]

_TOL_BRIGHT = [
    "#4477AA",
    "#66CCEE",
    "#228833",
    "#CCBB44",
    "#EE6677",
    "#AA3377",
    "#BBBBBB",
    "#000000",
    "#332288",
]

_KAARTEN_OVA = [
    "#0077BB",
    "#33BBEE",
    "#009988",
    "#EE7733",
    "#CC3311",
    "#EE3377",
    "#228833",
    "#AA4499",
    "#807A7A",
]

_PALETTES = {
    "okabe_ito": _OKABE_ITO,
    "tol_bright": _TOL_BRIGHT,
    "kaarten_ova": _KAARTEN_OVA,
}


# ------------------------------
# Timeseries parameter resolution
# ------------------------------
_DEFAULT_TS = SimpleNamespace(
    # Used when callers do not pass an explicit height.
    base_height=570,
    base_width = 1200,
    min_height=540,
    gap_frac=0.0,
    max_layers=9,
    reverse_depth=True,
    show_background_bands=True,
    palette_name="kaarten_ova",
    colors=None,
    # Typography. Override in CFG.timeseries if needed.
    font_family="Arial",
    font_size=14,
    title_font_size=20,
    axis_title_font_size=16,
    tick_font_size=14,
    annotation_font_size=14,
    hover_font_size=13,
    line_width=2,
    # Responsive Plotly layout settings.
    # Keep y-axis label annotations INSIDE the Plotly paper area.
    # The x-axis domain starts after this reserved label/tick zone, so
    # y-labels stay visible when the parent container is resized.
    plot_domain_left=0.1, # where you start the plot
    y_label_x=0.02, # from left edge print the ylabel
    margin_l=4,
    margin_r=24,
    margin_t=20,
    margin_b=45,
    # Soil moisture settings. These are fallbacks if CFG.timeseries lacks them.
    sm_column="soil_moisture_root_zone",
    sm_region_thresholds=(10, 20, 30),
    sm_region_colors=(
        "rgba(214, 39, 40, 0.25)",
        "rgba(255, 127, 14, 0.25)",
        "rgba(44, 160, 44, 0.20)",
        "rgba(31, 119, 180, 0.18)",
    ),
    sm_top_ylim_min=0,
    sm_top_min_ceiling=40,
    sm_top_ylim_pad=5,
    band_fill_rgba_even="rgba(148, 163, 184, 0.12)",
    band_fill_rgba_odd="rgba(226, 232, 240, 0.30)",
)


def _ts_param(name: str) -> Any:
    ts = getattr(CFG, "timeseries", None)
    if ts is not None and hasattr(ts, name):
        return getattr(ts, name)
    if hasattr(_DEFAULT_TS, name):
        return getattr(_DEFAULT_TS, name)
    raise AttributeError(
        f"timeseries param '{name}' missing on both CFG.timeseries and _DEFAULT_TS"
    )


def _resolve_palette(n: int) -> list[str]:
    cfg_colors = _ts_param("colors")
    if isinstance(cfg_colors, (list, tuple)) and len(cfg_colors) > 0:
        return [cfg_colors[i % len(cfg_colors)] for i in range(n)]

    name = _ts_param("palette_name")
    pal = _PALETTES.get(name, _KAARTEN_OVA)
    return [pal[i % len(pal)] for i in range(n)]


# ------------------------------
# CSV resolver and reader
# ------------------------------
def resolve_csv_path(props: dict) -> Path:
    """Choose CSV path based on popup props: csv_path, sensor_id, or id."""
    if "csv_path" in props and props["csv_path"]:
        return ensure_local_asset(Path(str(props["csv_path"])))

    sensor_id = props.get("sensor_id") or props.get("id")
    if not sensor_id:
        raise FileNotFoundError("No 'csv_path' or 'sensor_id'/'id' in properties.")

    return ensure_local_asset(CFG.sensor_csv_dir / f"{sensor_id}.csv")


def read_timeseries(csv_path: Path) -> pd.DataFrame:
    """Read sensor CSV and set the time column as datetime index."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)

    time_col = None
    for cand in getattr(
        CFG,
        "time_col_candidates",
        ("Date Time", "Datetime", "Timestamp", "Date", "date"),
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
    """If values look like 0-1, convert to %, else pass through."""
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().max() is not None and s.dropna().max() <= 1.00001:
        return s * 100.0
    return s


def _selected_depth_columns(num_df: pd.DataFrame) -> list[str]:
    cols_all = [c for c in num_df.columns if isinstance(c, str)]
    cols = [c for c in cols_all if c.startswith("A")] or cols_all
    max_layers = int(_ts_param("max_layers"))
    return cols[:max_layers] if len(cols) > max_layers else cols


# ------------------------------
# Common layout helper
# ------------------------------
def _apply_common_layout_dual(
    fig: go.Figure,
    *,
    height: int,
    gap_frac: float,
    labels_bottom: list[str],
) -> None:
    n = len(labels_bottom) if labels_bottom else 1
    height = int(height) if height is not None else int(_ts_param("base_height"))

    # clamp to reasonable bounds
    #height = max(500, min(height, 1200))
    font_family = _ts_param("font_family")
    font_size = int(_ts_param("font_size"))
    axis_title_font_size = int(_ts_param("axis_title_font_size"))
    tick_font_size = int(_ts_param("tick_font_size"))
    hover_font_size = int(_ts_param("hover_font_size"))

    fig.update_layout(
        title=None,
        autosize=True,
        width=None,
        height=None,
        margin=dict(
            l=int(_ts_param("margin_l")),
            r=int(_ts_param("margin_r")),
            t=int(_ts_param("margin_t")),
            b=int(_ts_param("margin_b")),
        ),
        showlegend=False,
        hovermode="x unified",
        transition_duration=0,
        font=dict(family=font_family, size=font_size),
        hoverlabel=dict(font_size=hover_font_size, font_family=font_family),
        paper_bgcolor="rgba(255,255,255,0.65)",
        plot_bgcolor="rgba(255,255,255,0.565)",
        )

    # Reserve a stable internal column on the left for rotated y-label annotations
    # and y tick labels. This avoids negative paper coordinates, which can be
    # clipped by responsive containers.
    plot_domain_left = float(_ts_param("plot_domain_left"))
    plot_domain_left = min(max(plot_domain_left, 0.08), 0.35)
    fig.update_xaxes(domain=[plot_domain_left, 1.0])

    fig.update_xaxes(
        row=2,
        col=1,
        type="date",
        title_text="Time",
        title_font=dict(size=axis_title_font_size),
        tickfont=dict(size=tick_font_size),
        tickangle=0,
        automargin=True,   # ← THIS is key
    )

    # Remove native y-axis titles. They shift because the two panels have
    # different tick-label widths. Fixed paper annotations below keep the two
    # y-labels aligned to the same position relative to the plot area.
    fig.update_yaxes(
        row=1,
        col=1,
        title_text=None,
        tickfont=dict(size=tick_font_size),
        rangemode="tozero",
        zeroline=False,
    )

    tick_positions = [i * (1 + gap_frac) + 0.5 for i in range(n)]
    fig.update_yaxes(
        row=2,
        col=1,
        tickmode="array",
        tickvals=tick_positions,
        ticktext=labels_bottom or [f"Layer {i + 1}" for i in range(n)],
        showgrid=False,
        title_text=None,
        tickfont=dict(size=tick_font_size),
        zeroline=False,
    )

    top_domain = fig.layout.yaxis.domain
    bottom_domain = fig.layout.yaxis2.domain
    y_label_x = float(_ts_param("y_label_x"))  # must stay inside [0, plot_domain_left)
    y_label_x = min(max(y_label_x, 0.0), max(0.0, plot_domain_left - 0.02))

    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=y_label_x,
        y=(top_domain[0] + top_domain[1]) / 2,
        text=" % (root zone)",
        showarrow=False,
        textangle=-90,
        font=dict(size=axis_title_font_size, family=font_family),
        xanchor="center",
        yanchor="middle",
    )

    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=y_label_x,
        y=(bottom_domain[0] + bottom_domain[1]) / 2,
        text="% (per depth layer)",
        showarrow=False,
        textangle=-90,
        font=dict(size=axis_title_font_size, family=font_family),
        xanchor="center",
        yanchor="middle",
    )


# ------------------------------
# Main figure builder
# ------------------------------
def build_timeseries_figure(
    df: pd.DataFrame,
    title: str = "Soil moisture time series",
    *,
    width: int | None = None,
    height: int | None = None,
) -> go.Figure:
    """Build a responsive Plotly figure for Solara FigurePlotly."""
    if df is None or df.empty:
        raise ValueError("No data to plot.")

    num_df = df.select_dtypes("number")
    cols = _selected_depth_columns(num_df)
    if not cols:
        raise ValueError("No numeric columns available for plotting.")

    x = pd.to_datetime(num_df.index, errors="coerce")
    x_str = _to_time_strings(x, fmt="%Y-%m-%d %H:%M")

    labels = [DEPTH_LEGENDS.get(c, c) for c in cols]

    gap_frac = float(_ts_param("gap_frac"))
    reverse_depth = bool(_ts_param("reverse_depth"))
    show_bands = bool(_ts_param("show_background_bands"))
    line_width = float(_ts_param("line_width"))
    annotation_font_size = int(_ts_param("annotation_font_size"))

    sm_column = _ts_param("sm_column")
    t0, t1, t2 = _ts_param("sm_region_thresholds")
    c_warn, c_stress, c_normal, c_sat = _ts_param("sm_region_colors")
    sm_min = float(_ts_param("sm_top_ylim_min"))
    sm_min_ceiling = float(_ts_param("sm_top_min_ceiling"))
    sm_pad = float(_ts_param("sm_top_ylim_pad"))
    band_even = _ts_param("band_fill_rgba_even")
    band_odd = _ts_param("band_fill_rgba_odd")

    if reverse_depth:
        cols = list(reversed(cols))
        labels = list(reversed(labels))

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.85, 1.5],
    )

    # ---------- TOP subplot: root-zone soil moisture ----------
    if sm_column in num_df.columns:
        sm = _ensure_percent(num_df[sm_column])
        ymax = float(max(sm_min_ceiling, (sm.max(skipna=True) or 0) + sm_pad))
        ymin = sm_min

        if len(x_str) >= 2:
            x0, x1 = x_str[0], x_str[-1]
            region_shapes = [
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=0, y1=t0, fillcolor=c_warn, line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t0, y1=t1, fillcolor=c_stress, line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t1, y1=t2, fillcolor=c_normal, line=dict(width=0), layer="below", opacity=0.35),
                dict(type="rect", xref="x1", yref="y1", x0=x0, x1=x1, y0=t2, y1=ymax, fillcolor=c_sat, line=dict(width=0), layer="below", opacity=0.35),
            ]
            fig.update_layout(shapes=region_shapes)

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
            fig.add_hline(
                y=thr,
                line_width=1,
                line_dash=dash,
                line_color="#555",
                row=1,
                col=1,
            )

        labels_top = ["Warning", "Stress", "Refill", "Full"]
        y_lines = [ymin, t0, t1, t2]
        dy = max(0.5, 0.02 * (ymax - ymin))
        for txt, yline in zip(labels_top, y_lines):
            fig.add_annotation(
                xref="paper",
                x=float(_ts_param("plot_domain_left")) + 0.01,
                yref="y1",
                y=yline + dy,
                text=txt,
                showarrow=False,
                font=dict(size=annotation_font_size, color="#333"),
                align="left",
                xanchor="left",
            )

    # ---------- BOTTOM subplot: stacked depth bands ----------
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
                    type="rect",
                    xref="x2",
                    yref="y2",
                    x0=x0,
                    x1=x1,
                    y0=y0,
                    y1=y1,
                    fillcolor=fill,
                    line=dict(width=0),
                    layer="below",
                )
            )
        cur_shapes = list(fig.layout.shapes) if fig.layout.shapes else []
        fig.update_layout(shapes=tuple(cur_shapes + zebra))

    for i, c in enumerate(cols):
        y_raw = pd.Series(num_df[c].astype("float64"), index=num_df.index)
        ymin = y_raw.min(skipna=True)
        ymax = y_raw.max(skipna=True)
        rng = (ymax - ymin) if pd.notnull(ymax) and pd.notnull(ymin) else 0.0
        y_norm = (
            ((y_raw - ymin) / rng).fillna(0.5)
            if rng > 0
            else pd.Series(0.5, index=y_raw.index)
        )

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
            line=dict(width=line_width, color=colors[i]),
            row=2,
            col=1,
        )

    max_band_top = (len(cols) - 1) * (1 + gap_frac) + 1
    fig.update_yaxes(
        row=2,
        col=1,
        range=[-0.2, max_band_top + 0.2],
        showgrid=False,
        zeroline=False,
    )

    _apply_common_layout_dual(
        fig,
        height=int(height) if height is not None else int(_ts_param("base_height")),
        gap_frac=gap_frac,
        labels_bottom=labels,
    )

    return fig


# ------------------------------
# Solara component, optional bottom-of-page figure
# ------------------------------
@solara.component
def TimeSeriesFigure(df: pd.DataFrame, title: str = "Soil moisture time series"):
    if df is None or df.empty:
        with solara.Alert("No data to plot.", type="warning"):
            return

    try:
        fig = build_timeseries_figure(df, title)
    except Exception as exc:
        with solara.Alert(str(exc), type="warning"):
            return

    solara.FigurePlotly(fig)


# ------------------------------
# Backward-compatible wrapper for older callers
# ------------------------------
def build_plotly_widget(df: pd.DataFrame, title: str):
    """
    Deprecated compatibility wrapper.

    Do not create go.FigureWidget here because it can leave orphan ipywidget
    comms in Solara/ipyleaflet.
    """
    if df is None or df.empty:
        return None

    return build_timeseries_figure(df, title)