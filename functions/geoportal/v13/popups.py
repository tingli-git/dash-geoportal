from __future__ import annotations
from typing import Any, Callable, Optional

import ipyleaflet
import ipywidgets as W
from IPython.display import display

from functions.geoportal.v13.utils import html_table_popup
from functions.geoportal.v13.config import CFG

def clear_tree_health_badge(m: ipyleaflet.Map) -> None:
    control = getattr(m, "_tree_health_badge_control", None)
    if control is not None:
        try:
            m.remove(control)
        except Exception:
            pass
    setattr(m, "_tree_health_badge_control", None)


def _ensure_tree_health_badge_dismiss_listener(m: ipyleaflet.Map) -> None:
    if getattr(m, "_tree_health_badge_listener_attached", False):
        return

    def _on_interaction(**event):
        if event.get("type") != "click":
            return
        if getattr(m, "_suppress_next_tree_health_badge_close", False):
            setattr(m, "_suppress_next_tree_health_badge_close", False)
            return
        clear_tree_health_badge(m)

    try:
        m.on_interaction(_on_interaction)
        setattr(m, "_tree_health_badge_listener_attached", True)
    except Exception:
        pass


def show_tree_health_badge(
    m: ipyleaflet.Map,
    props: Optional[dict[str, Any]],
) -> None:
    _ensure_tree_health_badge_dismiss_listener(m)
    clear_tree_health_badge(m)

    rows = []
    for key, value in (props or {}).items():
        label = str(key).replace("_", " ").upper()
        rows.append(
            "<tr>"
            f"<th style='text-align:left;padding:0.28rem 0.7rem 0.28rem 0;font-weight:700;color:#334155;white-space:nowrap'>{label}</th>"
            f"<td style='padding:0.28rem 0;color:#0f172a;word-break:break-word'>{value}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td style='color:#475569'><i>No properties</i></td></tr>")

    title = W.HTML(
        value=(
            "<div style='"
            "font-weight: 800;"
            "font-size: clamp(0.95rem, 0.8rem + 0.55vw, 1.2rem);"
            "line-height: 1.2;"
            "color: #0f172a;"
            "margin: 0 2.2rem 0 0;"
            "'>Tree Health Attributes</div>"
        )
    )
    close_btn = W.Button(
        description="×",
        tooltip="Close",
        layout=W.Layout(width="2rem", height="2rem", min_width="2rem", padding="0"),
    )
    close_btn.style.button_color = "rgba(255,255,255,0)"
    close_btn.style.font_weight = "700"
    table = W.HTML(
        value=(
            "<div style='"
            "width:100%;"
            "max-width:min(36rem, 42vw);"
            "max-height:min(58vh, 32rem);"
            "overflow:auto;"
            "background:rgba(255,255,255,0.40);"
            "backdrop-filter:blur(1px);"
            "-webkit-backdrop-filter:blur(1px);"
            "border-radius:12px;"
            "padding:0.55rem 0.75rem;"
            "box-shadow:0 8px 24px rgba(15,23,42,0.12);"
            "border:1px solid rgba(148,163,184,0.40);"
            "font-size:clamp(0.72rem, 0.6rem + 0.38vw, 0.98rem);"
            "line-height:1.35;"
            "'>"
            "<table style='border-collapse:collapse;width:100%'>"
            f"{''.join(rows)}"
            "</table>"
            "</div>"
        )
    )
    body = W.VBox(
        [
            W.HBox([title, close_btn], layout=W.Layout(justify_content="space-between", align_items="center")),
            table,
        ],
        layout=W.Layout(
            width="min(38rem, 44vw)",
            min_width="16rem",
            max_width="44vw",
            max_height="min(62vh, 36rem)",
            overflow="hidden",
            padding="0",
            border="0",
            border_radius="0",
        ),
    )

    wrapper = W.Box(
        [body],
        layout=W.Layout(
            padding="0",
            margin="0",
        ),
    )
    try:
        wrapper.add_class("tree-health-attr-badge")
    except Exception:
        pass

    control = ipyleaflet.WidgetControl(
        widget=wrapper,
        position="topleft",
        transparent_bg=True,
    )
    setattr(m, "_tree_health_badge_control", control)

    def _close(*_):
        clear_tree_health_badge(m)

    close_btn.on_click(_close)
    setattr(m, "_suppress_next_tree_health_badge_close", True)
    try:
        m.add(control)
    except Exception:
        pass


def show_popup(
    m: ipyleaflet.Map,
    lat: float,
    lon: float,
    props: Optional[dict[str, Any]],
    marker: Optional[ipyleaflet.Marker],
    active_marker_ref,
    on_show_timeseries: Optional[Callable[[dict], W.Widget | None]] = None,
    timeseries_button_label: Optional[str] = None,
    min_width: int | None = None,
    max_width: int | None = None,
) -> None:
    """
    Open a Leaflet popup at (lat, lon) showing a key/value table from `props`,
    and optionally a time-series widget under a button.
    """
    # Marker icon highlight (for sensors only)
    if marker is not None:
        try:
            if active_marker_ref.current and active_marker_ref.current is not marker:
                active_marker_ref.current.icon = ipyleaflet.AwesomeIcon(
                    name=CFG.icon_name,
                    marker_color=CFG.icon_color_default,
                    icon_color=CFG.icon_icon_color,
                )

            marker.icon = ipyleaflet.AwesomeIcon(
                name=CFG.icon_name,
                marker_color=CFG.icon_color_active,
                icon_color=CFG.icon_icon_color,
            )
            active_marker_ref.current = marker
        except Exception:
            pass

    table = html_table_popup(props or {})
    child: W.Widget = table

    if on_show_timeseries is not None:
        btn = W.Button(
            description=timeseries_button_label or "Show Soil Moisture Sensor Reads",
            button_style="primary",
            layout=W.Layout(margin="6px 0 0 0"),
            tooltip="Load and display the related time series below",
        )
        out = W.Output(layout=W.Layout(display="block"))

        def _on_click(_):
            out.clear_output(wait=True)
            try:
                widget = on_show_timeseries(props or {})
                with out:
                    if widget is not None:
                        display(widget)
                    else:
                        display(W.HTML("<i>No figure to show.</i>"))
            except Exception as e:
                with out:
                    display(W.HTML(f"<pre>Failed to load time series: {e}</pre>"))

        btn.on_click(_on_click)
        child = W.VBox([table, btn, out])

    suppress_attr = "_suppress_popup_clear"
    suppress_owned = False
    if not getattr(m, suppress_attr, False):
        setattr(m, suppress_attr, True)
        suppress_owned = True

    try:
        for layer in list(m.layers):
            if isinstance(layer, ipyleaflet.Popup):
                m.remove_layer(layer)

        if on_show_timeseries is not None:
            popup = ipyleaflet.Popup(
                location=(float(lat), float(lon)),
                child=child,
                close_button=True,
                auto_close=True,
                close_on_escape_key=True,
                auto_pan=False,
                keep_in_view=False,
                min_width=min_width or 1800,
                max_width=max_width or 3000,
            )
        else:
            popup = ipyleaflet.Popup(
                location=(float(lat), float(lon)),
                child=child,
                close_button=True,
                auto_close=True,
                close_on_escape_key=True,
                auto_pan=False,
                keep_in_view=False,
                min_width=min_width or 280,
                max_width=max_width or 420,
            )
                
      #offset_ratio = getattr(CFG, "popup_offset_ratio", 0.0) or 0.0
      #offset_pct = int(round(offset_ratio * 100))
      #if offset_pct:
      #    try:
      #        popup.layout.transform = f"translateY(-{offset_pct}vh)"
      #        popup.layout.margin = f"0 0 {offset_pct}vh 0"
      #    except Exception:
      #        pass
       
 
        m.add_layer(popup)
    finally:
        if suppress_owned:
            setattr(m, suppress_attr, False)

    print(f"[POPUP] showing {props.get('sensor_id') or props.get('name') or 'feature'}")
