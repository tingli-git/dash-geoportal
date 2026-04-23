from __future__ import annotations
from typing import Any, Callable, Optional

import ipyleaflet
import ipywidgets as W
from IPython.display import display, HTML

from functions.geoportal.v14.utils import html_table_popup
from functions.geoportal.v14.config import CFG


_BADGE_CSS_INSTALLED = False


def _ensure_tree_health_badge_css() -> None:
    global _BADGE_CSS_INSTALLED
    if _BADGE_CSS_INSTALLED:
        return

    display(HTML("""
    <style>
    .tree-health-attr-badge {
        background: rgba(255, 255, 255, 0.20) !important;
        backdrop-filter: blur(0.1px);
        -webkit-backdrop-filter: blur(0.1px);
        border: 1px solid rgba(148, 163, 184, 0.25);
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.10);
        overflow: hidden;
    }
    </style>
    """))
    _BADGE_CSS_INSTALLED = True


_SENSOR_BADGE_CSS_INSTALLED = False


def _ensure_sensor_badge_css() -> None:
    global _SENSOR_BADGE_CSS_INSTALLED
    if _SENSOR_BADGE_CSS_INSTALLED:
        return

    display(HTML("""
    <style>
    .sensor-attr-badge {
        position: fixed !important;
        left: 24px !important;
        top: 20px !important;
        transform: none !important;
        z-index: 1000;
    }
    .sensor-timeseries-badge {
        position: fixed !important;
            left: 24px !important;
            top: 20px !important;
            transform: none !important;
            z-index: 9999 !important;   /* increase */
    }
    /* 👇 ADD THIS HERE */
    .leaflet-control:has(.sensor-timeseries-badge) {
        z-index: 9999 !important;
    }

    
    </style>
    """))
    _SENSOR_BADGE_CSS_INSTALLED = True


def _reset_active_marker_icon(active_marker_ref) -> None:
    marker = getattr(active_marker_ref, "current", None)
    if marker is None:
        return
    try:
        marker.icon = ipyleaflet.AwesomeIcon(
            name=CFG.icon_name,
            marker_color=CFG.icon_color_default,
            icon_color=CFG.icon_icon_color,
        )
    except Exception:
        pass
    active_marker_ref.current = None


def _activate_sensor_marker(marker: Optional[ipyleaflet.Marker], active_marker_ref) -> None:
    if marker is None:
        return
    try:
        if active_marker_ref.current and active_marker_ref.current is not marker:
            _reset_active_marker_icon(active_marker_ref)
        marker.icon = ipyleaflet.AwesomeIcon(
            name=CFG.icon_name,
            marker_color=CFG.icon_color_active,
            icon_color=CFG.icon_icon_color,
        )
        active_marker_ref.current = marker
    except Exception:
        pass


def clear_sensor_attribute_badge(m: ipyleaflet.Map) -> None:
    control = getattr(m, "_sensor_attr_badge_control", None)
    if control is not None:
        try:
            m.remove(control)
        except Exception:
            pass
    setattr(m, "_sensor_attr_badge_control", None)


def clear_sensor_timeseries_badge(m: ipyleaflet.Map) -> None:
    control = getattr(m, "_sensor_ts_badge_control", None)
    if control is not None:
        try:
            m.remove(control)
        except Exception:
            pass
    setattr(m, "_sensor_ts_badge_control", None)


def clear_sensor_badges(m: ipyleaflet.Map, active_marker_ref=None) -> None:
    clear_sensor_attribute_badge(m)
    clear_sensor_timeseries_badge(m)
    if active_marker_ref is not None:
        _reset_active_marker_icon(active_marker_ref)


def _ensure_sensor_badge_dismiss_listener(m: ipyleaflet.Map, active_marker_ref) -> None:
    if getattr(m, "_sensor_badge_listener_attached", False):
        return

    def _on_interaction(**event):
        if event.get("type") != "click":
            return
        if getattr(m, "_suppress_next_sensor_badge_close", False):
            setattr(m, "_suppress_next_sensor_badge_close", False)
            return
        clear_sensor_attribute_badge(m)

    try:
        m.on_interaction(_on_interaction)
        setattr(m, "_sensor_badge_listener_attached", True)
    except Exception:
        pass


def _props_table_html(props: Optional[dict[str, Any]]) -> str:
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
    return "".join(rows)


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


def show_sensor_timeseries_badge(
    m: ipyleaflet.Map,
    widget: Optional[W.Widget],
    *,
    title: str,
) -> None:
    _ensure_sensor_badge_css()
    clear_sensor_timeseries_badge(m)

    close_btn = W.Button(
        description="×",
        tooltip="Close",
        layout=W.Layout(width="2rem", height="2rem", min_width="2rem", padding="0"),
    )
    close_btn.style.button_color = "rgba(255,255,255,0)"
    close_btn.style.font_weight = "700"

    title_widget = W.HTML(
        value=(
            "<div style='"
            "font-weight:800;"
            "font-size:clamp(1rem, 0.85rem + 0.55vw, 1.25rem);"
            "line-height:1.2;"
            "color:#0f172a;"
            "margin:0 2.2rem 0 0;"
            f"'>{title}</div>"
        )
    )

    header = W.HBox(
        [title_widget, close_btn],
        layout=W.Layout(
            justify_content="space-between",
            align_items="center",
            padding="0.75rem 0.9rem 0.35rem 0.9rem",
            margin="0",
        ),
    )

    content = W.Box(
        [widget or W.HTML("<i>No figure to show.</i>")],
        layout=W.Layout(
            width="100%",
            height="100%",
            overflow="auto",
            padding="0 0.6rem 0.8rem 0.6rem",
            box_sizing="border-box",
        ),
    )

    body = W.VBox(
        [header, content],
        layout=W.Layout(
            width="min(96vw, 1800px)",
            min_width="320px",
            max_width="96vw",
            height="72vh",
            min_height="50vh",
            max_height="80vh",
            overflow="hidden",
            background="rgba(255,255,255,0.20)",
            border="1px solid rgba(148,163,184,0.25)",
            border_radius="14px",
            box_shadow="0 8px 24px rgba(15,23,42,0.22)",
        ),
    )

    wrapper = W.Box([body], layout=W.Layout(padding="0", margin="0"))
    try:
        wrapper.add_class("sensor-timeseries-badge")
    except Exception:
        pass

    control = ipyleaflet.WidgetControl(
        widget=wrapper,
        position="topleft",
        transparent_bg=True,
    )
    setattr(m, "_sensor_ts_badge_control", control)

    def _close(*_):
        clear_sensor_timeseries_badge(m)

    close_btn.on_click(_close)
    setattr(m, "_suppress_next_sensor_badge_close", True)
    try:
        m.add(control)
    except Exception:
        pass


def show_sensor_attribute_badge(
    m: ipyleaflet.Map,
    props: Optional[dict[str, Any]],
    marker: Optional[ipyleaflet.Marker],
    active_marker_ref,
    on_show_timeseries: Optional[Callable[[dict], W.Widget | None]] = None,
) -> None:
    _ensure_sensor_badge_css()
    _ensure_sensor_badge_dismiss_listener(m, active_marker_ref)
    clear_sensor_attribute_badge(m)
    _activate_sensor_marker(marker, active_marker_ref)

    title = W.HTML(
        value=(
            "<div style='"
            "font-weight:800;"
            "font-size:clamp(0.95rem, 0.8rem + 0.55vw, 1.2rem);"
            "line-height:1.2;"
            "color:#0f172a;"
            "margin:0 2.2rem 0 0;"
            "'>Sensor Attributes</div>"
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
            "max-height:min(54vh, 30rem);"
            "overflow:auto;"
            "background:transparent;"
            "border-radius:12px;"
            "padding:0.55rem 0.75rem 0.55rem 0.75rem;"
            "font-size:clamp(0.72rem, 0.6rem + 0.38vw, 0.98rem);"
            "line-height:1.35;"
            "'>"
            "<table style='border-collapse:collapse;width:100%'>"
            f"{_props_table_html(props)}"
            "</table>"
            "</div>"
        )
    )

    button_row = []
    if on_show_timeseries is not None:
        ts_btn = W.Button(
            description="Show Soil Moisture Sensor Reads",
            button_style="primary",
            layout=W.Layout(width="auto", margin="0.15rem 0.75rem 0.75rem 0.75rem"),
            tooltip="Open the related time series",
        )

        def _show_series(*_):
            widget = on_show_timeseries(props or {})
            title_text = (
                f"Sensor time series — "
                f"{(props or {}).get('name') or (props or {}).get('sensor_id') or (props or {}).get('id') or 'Sensor'}"
            )
            show_sensor_timeseries_badge(m, widget, title=title_text)

        ts_btn.on_click(_show_series)
        button_row.append(ts_btn)

    header = W.HBox(
        [title, close_btn],
        layout=W.Layout(
            justify_content="space-between",
            align_items="center",
            padding="0.55rem 0.75rem 0.1rem 0.75rem",
            margin="0",
        ),
    )

    body = W.VBox(
        [header, table, *button_row],
        layout=W.Layout(
            width="min(24rem, 28vw)",
            min_width="16rem",
            max_width="28vw",
            max_height="min(68vh, 40rem)",
            overflow="hidden",
            background="rgba(255,255,255,0.20)",
            border="1px solid rgba(148,163,184,0.25)",
            border_radius="12px",
            box_shadow="0 8px 24px rgba(15,23,42,0.18)",
            padding="0",
        ),
    )

    wrapper = W.Box([body], layout=W.Layout(padding="0", margin="0"))
    try:
        wrapper.add_class("sensor-attr-badge")
    except Exception:
        pass
    control = ipyleaflet.WidgetControl(
        widget=wrapper,
        position="topleft",
        transparent_bg=True,
    )
    setattr(m, "_sensor_attr_badge_control", control)

    def _close(*_):
        clear_sensor_badges(m, active_marker_ref)

    close_btn.on_click(_close)
    setattr(m, "_suppress_next_sensor_badge_close", True)
    try:
        m.add(control)
    except Exception:
        pass


def show_tree_health_badge(
    m: ipyleaflet.Map,
    props: Optional[dict[str, Any]],
) -> None:
    _ensure_tree_health_badge_css()
    _ensure_tree_health_badge_dismiss_listener(m)
    clear_tree_health_badge(m)

    title = W.HTML(
        value=(
            "<div style='"
            "font-weight:800;"
            "font-size:clamp(0.95rem, 0.8rem + 0.55vw, 1.2rem);"
            "line-height:1.2;"
            "color:#0f172a;"
            "margin:0 2.2rem 0 0;"
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
            "background:transparent;"
            "border-radius:12px;"
            "padding:0.55rem 0.75rem 0.7rem 0.75rem;"
            "font-size:clamp(0.72rem, 0.6rem + 0.38vw, 0.98rem);"
            "line-height:1.35;"
            "'>"
            "<table style='border-collapse:collapse;width:100%'>"
            f"{_props_table_html(props)}"
            "</table>"
            "</div>"
        )
    )

    header = W.HBox(
        [title, close_btn],
        layout=W.Layout(
            justify_content="space-between",
            align_items="center",
            padding="0.55rem 0.75rem 0.1rem 0.75rem",
            margin="0",
        ),
    )

    body = W.VBox(
        [header, table],
        layout=W.Layout(
            width="min(21rem, 25vw)",   # 20% narrower
            min_width="16rem",
            max_width="25vw",
            max_height="min(62vh, 36rem)",
            overflow="hidden",
            padding="0",
        ),
    )

    wrapper = W.Box(
        [body],
        layout=W.Layout(
            padding="0",
            margin="0",
            background="rgba(255,255,255,0.20)",
            border="1px solid rgba(148,163,184,0.25)",
            border_radius="12px",
            box_shadow="0 8px 24px rgba(15,23,42,0.40)",
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

        m.add_layer(popup)
    finally:
        if suppress_owned:
            setattr(m, suppress_attr, False)

    print(f"[POPUP] showing {props.get('sensor_id') or props.get('name') or 'feature'}")
