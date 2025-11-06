# functions/geoportal/v2/layers.py
from __future__ import annotations
from typing import Iterable, Sequence, Tuple, Optional, Union, List
import ipyleaflet

# 👉 bring in your utils
from functions.geoportal.v2.utils import padded_bounds  # html_table_popup is UI-level; not needed here

Bounds = List[List[float]]  # [[south, west], [north, east]]
CoordSeq = Sequence[tuple[float, float]]


# -----------------------------
# Helpers
# -----------------------------
def _is_bounds_like(obj) -> bool:
    """Rudimentary check for Leaflet-style bounds [[s,w],[n,e]]."""
    try:
        return (
            isinstance(obj, (list, tuple)) and len(obj) == 2
            and isinstance(obj[0], (list, tuple)) and len(obj[0]) == 2
            and isinstance(obj[1], (list, tuple)) and len(obj[1]) == 2
        )
    except Exception:
        return False


def bounds_from_group(group: ipyleaflet.LayerGroup, *, min_span: float = 0.05, pad: float = 0.25) -> Optional[Bounds]:
    """
    Compute a padded bounds box from marker-like children (Marker, CircleMarker).
    Falls back to None if no locations found.
    """
    coords: list[tuple[float, float]] = []
    for lyr in getattr(group, "layers", []):
        # ipyleaflet.Marker has 'location' = (lat, lon)
        # ipyleaflet.Circle/Rectangle/Polygon could be handled here if needed
        loc = getattr(lyr, "location", None)
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            coords.append((float(loc[0]), float(loc[1])))
    return padded_bounds(coords, min_span=min_span, pad=pad) if coords else None


def _coerce_bounds(
    bounds_or_coords: Optional[Union[Bounds, CoordSeq]],
    fallback_group: Optional[ipyleaflet.LayerGroup],
    *,
    min_span: float,
    pad: float
) -> Optional[Bounds]:
    """
    Accept either a Leaflet-style bounds, a sequence of (lat, lon) coords, or None.
    - If bounds-like, return as-is.
    - If coords-like, convert via padded_bounds.
    - If None, try to derive from group.
    """
    if bounds_or_coords is None:
        if fallback_group is not None:
            return bounds_from_group(fallback_group, min_span=min_span, pad=pad)
        return None

    if _is_bounds_like(bounds_or_coords):
        # looks like [[s,w],[n,e]]
        return list(map(list, bounds_or_coords))  # shallow copy

    # Otherwise assume coords
    try:
        return padded_bounds(bounds_or_coords, min_span=min_span, pad=pad)  # type: ignore[arg-type]
    except Exception:
        return None


def _base_layer_count(m: ipyleaflet.Map) -> int:
    """Count contiguous base layers (TileLayer with base=True) at the bottom."""
    count = 0
    for lyr in m.layers:
        if isinstance(lyr, (ipyleaflet.TileLayer, ipyleaflet.LocalTileLayer)) and getattr(lyr, "base", False):
            count += 1
        else:
            break
    return count


# -----------------------------
# Existing utilities (kept + enhanced)
# -----------------------------
def remove_prior_groups(
    m: ipyleaflet.Map,
    keep: ipyleaflet.LayerGroup | None,
    names_to_prune: set[str] | None = None,
    *,
    also_remove_overlays: bool = False,
) -> None:
    """
    Remove older marker/groups with certain names to avoid duplicates.
    Optionally remove overlays (e.g., LocalTileLayer) whose .name matches names_to_prune.
    """
    names_to_prune = names_to_prune or set()
    for layer in list(m.layers):
        if keep is not None and layer is keep:
            continue

        if isinstance(layer, (ipyleaflet.Marker, ipyleaflet.LayerGroup)):
            name = getattr(layer, "name", "")
            if name in names_to_prune or isinstance(layer, ipyleaflet.Marker):
                m.remove_layer(layer)
            continue

        if also_remove_overlays and isinstance(layer, (ipyleaflet.TileLayer, ipyleaflet.LocalTileLayer)):
            is_base = bool(getattr(layer, "base", False))
            if not is_base:
                name = getattr(layer, "name", "")
                if name in names_to_prune:
                    m.remove_layer(layer)


def add_group_and_fit(
    m: ipyleaflet.Map,
    group: ipyleaflet.LayerGroup | None,
    bounds_or_coords,
    did_fit_ref,
    *,
    max_zoom: int,
    padding: Tuple[int, int] | None = None,
    min_span: float = 0.05,
    pad: float = 0.25,
) -> None:
    """
    Add group (if not present) and fit map:
      - bounds_or_coords can be:
          • Leaflet bounds [[s,w],[n,e]], or
          • Sequence of (lat, lon) coords, or
          • None (then we derive from group's markers).
    Uses utils.padded_bounds for coord → bounds with padding.
    """
    if not group:
        return
    if group not in m.layers:
        m.add_layer(group)

    if did_fit_ref.current:
        return

    bounds = _coerce_bounds(bounds_or_coords, group, min_span=min_span, pad=pad)
    if not bounds:
        return

    try:
        m.fit_bounds(bounds, max_zoom=max_zoom, padding=padding or (0, 0))
    except TypeError:
        # Older ipyleaflet: no padding kw
        m.fit_bounds(bounds)
        if m.zoom > max_zoom:
            m.zoom = max_zoom
    did_fit_ref.current = True


# -----------------------------
# NEW: overlay utilities
# -----------------------------
def add_overlay_layer(
    m: ipyleaflet.Map,
    overlay: ipyleaflet.TileLayer | ipyleaflet.LocalTileLayer,
    *,
    below_markers: bool = True
) -> None:
    """
    Add an overlay (e.g., LocalTileLayer with XYZ tiles) above base layers.
    If below_markers=True, keep it below markers/groups that follow.
    """
    if overlay in m.layers:
        return

    if below_markers:
        insert_at = _base_layer_count(m)
        m.layers = tuple(list(m.layers[:insert_at]) + [overlay] + list(m.layers[insert_at:]))
    else:
        m.add_layer(overlay)


def upsert_overlay_by_name(
    m: ipyleaflet.Map,
    overlay: ipyleaflet.TileLayer | ipyleaflet.LocalTileLayer,
    *,
    below_markers: bool = True
) -> None:
    """If an overlay with the same .name exists, replace it; else insert it."""
    name = getattr(overlay, "name", None)
    if not name:
        add_overlay_layer(m, overlay, below_markers=below_markers)
        return

    for lyr in _find_layers_by_name(m, {name}, overlay_only=True):
        m.remove_layer(lyr)
    add_overlay_layer(m, overlay, below_markers=below_markers)


def _find_layers_by_name(
    m: ipyleaflet.Map,
    names: Iterable[str],
    overlay_only: bool = False
) -> list[ipyleaflet.Layer]:
    """Return layers whose .name is in names. If overlay_only, only return non-base tile layers."""
    names = set(names)
    hits = []
    for lyr in m.layers:
        lname = getattr(lyr, "name", "")
        if lname not in names:
            continue
        if overlay_only and isinstance(lyr, (ipyleaflet.TileLayer, ipyleaflet.LocalTileLayer)):
            if getattr(lyr, "base", False):
                continue
        hits.append(lyr)
    return hits


def set_layer_visibility(
    m: ipyleaflet.Map,
    layer: ipyleaflet.Layer,
    visible: bool
) -> None:
    """Toggle visibility by add/remove."""
    if visible and layer not in m.layers:
        add_overlay_layer(m, layer, below_markers=True)
    if (not visible) and (layer in m.layers):
        m.remove_layer(layer)


def set_layer_opacity(layer: ipyleaflet.Layer, opacity: float) -> None:
    """Safely update a tile layer's opacity (if supported)."""
    try:
        if hasattr(layer, "opacity"):
            layer.opacity = float(opacity)
    except Exception:
        pass
