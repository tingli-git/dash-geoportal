from __future__ import annotations
from typing import Any, Callable, Optional

import ipyleaflet
import ipywidgets as W
from IPython.display import display

from functions.geoportal.v12.utils import html_table_popup
from functions.geoportal.v12.config import CFG


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