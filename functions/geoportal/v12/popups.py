from __future__ import annotations
from typing import Any, Callable, Optional

import ipyleaflet
import ipywidgets as W
from IPython.display import display

from functions.geoportal.v12.utils import html_table_popup
from functions.geoportal.v12.config import CFG


def reset_active_marker_icon(active_marker_ref) -> None:
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
    try:
        active_marker_ref.current = None
    except Exception:
        pass


def _popup_container(child: W.Widget, *, is_timeseries: bool) -> W.Widget:
    width = "min(96vw, 1500px)" if is_timeseries else "min(92vw, 560px)"
    max_height = "min(80vh, 900px)" if is_timeseries else "min(70vh, 520px)"
    return W.Box(
        [child],
        layout=W.Layout(
            width=width,
            max_width=width,
            max_height=max_height,
            overflow_x="auto",
            overflow_y="auto",
        ),
    )


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

    try:
        setattr(m, "_pending_center_restore", None)
        setattr(m, "_pending_zoom_restore", None)
    except Exception:
        pass

    # highlight marker
    if marker is not None:
        try:
            if active_marker_ref.current and active_marker_ref.current is not marker:
                reset_active_marker_icon(active_marker_ref)

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
        )
        out = W.Output()

        def _on_click(_):
            out.clear_output(wait=True)
            try:
                widget = on_show_timeseries(props or {})
                with out:
                    display(widget if widget else W.HTML("<i>No figure</i>"))
            except Exception as e:
                with out:
                    display(W.HTML(f"<pre>{e}</pre>"))

        btn.on_click(_on_click)
        child = W.VBox([table, btn, out])

    child = _popup_container(child, is_timeseries=(on_show_timeseries is not None))

    # remove old popups
    for layer in list(m.layers):
        if isinstance(layer, ipyleaflet.Popup):
            m.remove_layer(layer)

    popup = ipyleaflet.Popup(
        location=(float(lat), float(lon)),
        child=child,
        close_button=True,
        auto_close=True,
        auto_pan=False,
        keep_in_view=True,
        offset=(0, -12),
    )

    m.add_layer(popup)
