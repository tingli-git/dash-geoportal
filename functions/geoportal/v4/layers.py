# functions/geoportal/v2/layers.py
from __future__ import annotations
from typing import Iterable, Sequence, Tuple, Optional, Union, List
from pathlib import Path
import ipyleaflet
import ipywidgets as W

# 👉 bring in your utils / config
from functions.geoportal.v4.utils import padded_bounds
from functions.geoportal.v4.config import CFG

# Use BOTH loaders with clear names:
#   - URL-based (fast; browser fetches from your HTTP server)
#   - DATA-based (fallback; Python loads JSON)
from functions.geoportal.v4.geojson_loader import (
    load_cpf_layer_for_year_url,      # URL mode
    load_cpf_layer_for_year as load_cpf_layer_for_year_data,  # DATA mode
    available_cpf_years,
)

Bounds = List[List[float]]  # [[south, west], [north, east]]
CoordSeq = Sequence[tuple[float, float]]

# Rough KSA bounds (instant fit without scanning GeoJSON)
KSA_BOUNDS: Bounds = [[16.0, 34.0], [33.0, 56.0]]


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
        return list(map(list, bounds_or_coords))  # shallow copy

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


# ============================
# CPF: slider + lazy URL layer
# ============================
def make_cpf_year_slider() -> W.IntSlider:
    years = available_cpf_years()
    return W.IntSlider(
        description="Year",
        min=min(years),
        max=max(years),
        step=1,
        value=max(years) if getattr(CFG, "cpf_start_latest", True) else min(years),
        readout=True,
        continuous_update=False,  # no redraw while dragging
        layout=W.Layout(width=getattr(CFG, "cpf_slider_width", "420px")),
    )


def attach_cpf_layer_with_slider(
    m: ipyleaflet.Map,
    *,
    insert_below_markers: bool = True,
    auto_load_initial: bool = False,          # keep fast startup by default
) -> tuple[ipyleaflet.GeoJSON, W.IntSlider]:
    """
    Create a placeholder CPF layer and a year slider.
    The actual GeoJSON is loaded from URL only when the user moves the slider
    (or when auto_load_initial=True).
    Returns (layer, slider).
    """
    slider = make_cpf_year_slider()
    year = int(slider.value)

    # Start with an empty FC (so nothing heavy is sent at startup)
    layer = ipyleaflet.GeoJSON(
        data={"type": "FeatureCollection", "features": []},
        name=getattr(CFG, "cpf_layer_name", "Center-Pivot Fields"),
        style=getattr(CFG, "cpf_style", {"color": "#6BBF59", "weight": 1, "opacity": 0.8, "fillColor": "#90EE90", "fillOpacity": 0.35}),
        hover_style=getattr(CFG, "cpf_hover_style", {"weight": 2, "opacity": 1.0, "fillOpacity": 0.5}),
    )

    # insert below markers/groups (above base)
    if insert_below_markers:
        insert_at = _base_layer_count(m)
        m.layers = tuple(list(m.layers[:insert_at]) + [layer] + list(m.layers[insert_at:]))
    else:
        m.add_layer(layer)

    # Fit once to a static bbox (instant, avoids scanning)
    try:
        m.fit_bounds(KSA_BOUNDS,
                     max_zoom=getattr(CFG, "cpf_fit_bounds_max_zoom", 12),
                     padding=getattr(CFG, "cpf_fit_bounds_padding", (20, 20)))
    except TypeError:
        m.fit_bounds(KSA_BOUNDS)

    # Loader to replace the placeholder with a real URL-backed layer
    def _load_year(y: int):
        nonlocal layer
        # Try URL (fast). If it fails, fall back to DATA.
        try:
            new_layer, _ = load_cpf_layer_for_year_url(
                y, name=f"{getattr(CFG, 'cpf_layer_name', 'Center-Pivot Fields')} {y}"
            )
        except Exception:
            new_layer, _ = load_cpf_layer_for_year_data(
                y, name=f"{getattr(CFG, 'cpf_layer_name', 'Center-Pivot Fields')} {y}"
            )

        mlayers = list(m.layers)
        try:
            idx = mlayers.index(layer)
            mlayers[idx] = new_layer
            m.layers = tuple(mlayers)
        except ValueError:
            m.add_layer(new_layer)
        layer = new_layer  # keep reference up to date

    # Optionally auto-load the first year AFTER map is visible
    if auto_load_initial:
        _load_year(year)

    # Wire slider → lazy load selected year on demand
    def _on_change(change):
        nonlocal layer
        if change.get("name") != "value":
            return
        new_year = int(change["new"])
        _load_year(new_year)

    slider.observe(_on_change, names="value")
    return layer, slider


def attach_cpf_lazy(
    m: ipyleaflet.Map,
    *,
    insert_below_markers: bool = True,
    auto_load_initial: bool = False,
) -> Tuple[W.IntSlider, W.Button, dict]:
    """
    Slider + 'Load year' button with status; loads via URL and falls back to DATA.
    Returns (slider, button, refs_dict) where refs_dict contains:
      - "layer": current ipyleaflet.GeoJSON layer
      - "status": ipywidgets.HTML status line
      - "loaded_year": lambda -> current year or None
    """
    slider = make_cpf_year_slider()
    btn = W.Button(description="Load year", button_style="success")
    status = W.HTML("", layout=W.Layout(margin="4px 0 0 0"))

    # placeholder (keeps ordering stable)
    placeholder = ipyleaflet.GeoJSON(
        data={"type": "FeatureCollection", "features": []},
        name=getattr(CFG, "cpf_layer_name", "Center-Pivot Fields"),
        style=getattr(CFG, "cpf_style", {"color": "#6BBF59", "weight": 1, "opacity": 0.8,
                                         "fillColor": "#90EE90", "fillOpacity": 0.35}),
        hover_style=getattr(CFG, "cpf_hover_style", {"weight": 2, "opacity": 1.0, "fillOpacity": 0.5}),
    )
    if insert_below_markers:
        insert_at = _base_layer_count(m)
        m.layers = tuple(list(m.layers[:insert_at]) + [placeholder] + list(m.layers[insert_at:]))
    else:
        m.add_layer(placeholder)

    refs = {"layer": placeholder, "loaded_year": None, "fitted_once": False}

    # fit once fast to a static bbox
    try:
        m.fit_bounds(KSA_BOUNDS,
                     max_zoom=getattr(CFG, "cpf_fit_bounds_max_zoom", 12),
                     padding=getattr(CFG, "cpf_fit_bounds_padding", (20, 20)))
    except TypeError:
        m.fit_bounds(KSA_BOUNDS)
    refs["fitted_once"] = True

    def _swap_layer(new_layer: ipyleaflet.GeoJSON):
        mlayers = list(m.layers)
        try:
            idx = mlayers.index(refs["layer"])
            mlayers[idx] = new_layer
            m.layers = tuple(mlayers)
        except ValueError:
            m.add_layer(new_layer)
        refs["layer"] = new_layer

    def _load_year(y: int):
        base = Path(CFG.cpf_geojson_dir)
        candidates = [
            base / f"CPF_fields_{y}_simpl.geojson",
            base / f"CPF_fileds_{y}_simpl.geojson",
            base / f"CPF_fields_{y}.geojson",
            base / f"CPF_fileds_{y}.geojson",
        ]
        disk_path = next((p for p in candidates if p.exists()), None)
        if not disk_path:
            btn.description = f"No file for {y}"
            btn.button_style = "warning"
            status.value = f"<i>Missing file for {y}</i>"
            return

        # 1) try URL-based layer (fast path)
        try:
            lyr_url, _ = load_cpf_layer_for_year_url(
                y, name=f"{getattr(CFG, 'cpf_layer_name', 'Center-Pivot Fields')} {y}"
            )
            _swap_layer(lyr_url)
            btn.description = f"Loaded {y}"
            btn.button_style = "info"
            status.value = f"<small>URL mode • {disk_path.name}</small>"
            refs["loaded_year"] = y
            return
        except Exception as e:
            # 2) fallback to DATA-based layer
            try:
                lyr_data, _ = load_cpf_layer_for_year_data(
                    y, name=f"{getattr(CFG, 'cpf_layer_name', 'Center-Pivot Fields')} {y}"
                )
                _swap_layer(lyr_data)
                btn.description = f"Loaded {y}"
                btn.button_style = "info"
                status.value = f"<small>DATA mode • {disk_path.name}<br/>{e}</small>"
                refs["loaded_year"] = y
                return
            except Exception as e2:
                btn.description = "Load failed"
                btn.button_style = "danger"
                status.value = f"<pre>Failed to load {y}:\n{e}\n{e2}</pre>"
                return

    def _on_click(_):
        _load_year(int(slider.value))

    def _on_change(change):
        if change.get("name") != "value":
            return
        if refs["loaded_year"] is not None:
            _load_year(int(change["new"]))

    btn.on_click(_on_click)
    slider.observe(_on_change, names="value")

    if auto_load_initial:
        _load_year(int(slider.value))

    return slider, btn, {"layer": refs["layer"], "status": status, "loaded_year": lambda: refs["loaded_year"]}
