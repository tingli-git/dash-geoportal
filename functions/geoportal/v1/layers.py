from __future__ import annotations
import ipyleaflet

def remove_prior_groups(m: ipyleaflet.Map, keep: ipyleaflet.LayerGroup | None, names_to_prune: set[str] | None = None):
    """
    Remove older marker/groups with certain names to avoid duplicates.
    """
    names_to_prune = names_to_prune or set()
    for layer in list(m.layers):
        if isinstance(layer, (ipyleaflet.Marker, ipyleaflet.LayerGroup)):
            name = getattr(layer, "name", "")
            if keep is not None and layer is keep:
                continue
            if (name in names_to_prune) or isinstance(layer, ipyleaflet.Marker):
                m.remove_layer(layer)

def add_group_and_fit(m: ipyleaflet.Map, group: ipyleaflet.LayerGroup | None, bounds, did_fit_ref, *, max_zoom: int, padding: tuple[int, int] | None = None):
    if not group:
        return
    if group not in m.layers:
        m.add_layer(group)
    if bounds and not did_fit_ref.current:
        try:
            m.fit_bounds(bounds, max_zoom=max_zoom, padding=padding or (0, 0))
        except TypeError:
            m.fit_bounds(bounds)
            if m.zoom > max_zoom:
                m.zoom = max_zoom
        did_fit_ref.current = True
