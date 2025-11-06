import solara
import pathlib
from anywidget import AnyWidget
import ipyleaflet
import traitlets
from ipywidgets import Layout


class Map(AnyWidget):
    center = traitlets.List([51.505, -0.09]).tag(sync=True)  # lat, lng
    zoom = traitlets.Int(13).tag(sync=True)
    height = traitlets.Unicode("300px").tag(sync=True)
    _esm = str(pathlib.Path(__file__).parent / "map.js")

@solara.component
def Page():
    with solara.Columns([1,1,]):
        with solara.Column():
            solara.Markdown("## Using anywidget")
            solara.Markdown("Full JS flexibility")
            Map.element(
                center=[29,40], # lat,lng
                zoom=7,
                height="600px"
            )
        
        with solara.Column():
            solara.Markdown("## Using [ipyleaflet](https://ipyleaflet.readthedocs.io/)")
            solara.Markdown("More python friendly, but you lose flexibility")
            ipyleaflet.Map.element(
                center=[29,40],
                zoom=7,
                scroll_wheel_zoom=True,
                layout = Layout(height='600px')
            )

    return