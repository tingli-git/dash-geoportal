from __future__ import annotations
import asyncio
from pathlib import Path
import io
import json
import time
import solara
from typing import Callable, Optional

# ---------- Debounce ----------
def use_debounce(value: str, delay_ms: int = 500) -> str:
    """
    Debounce a reactive string value using asyncio's event loop.
    Returns the debounced value after delay_ms of inactivity.
    """
    debounced, set_debounced = solara.use_state(value)
    last_stamp, set_last_stamp = solara.use_state(0.0)
    handle_ref = solara.use_ref(None)  # store asyncio timer handle

    # when upstream value changes, record a new timestamp
    solara.use_effect(lambda: set_last_stamp(time.time()), [value])

    def schedule():
        # cancel previous scheduled call if any
        if handle_ref.current is not None:
            try:
                handle_ref.current.cancel()
            except Exception:
                pass

        loop = asyncio.get_event_loop()

        def commit():
            # set the latest value when the timer fires
            set_debounced(value)

        # schedule new call
        handle_ref.current = loop.call_later(delay_ms / 1000.0, commit)

        # cleanup: cancel if effect is re-run/disposed
        def cleanup():
            if handle_ref.current is not None:
                try:
                    handle_ref.current.cancel()
                except Exception:
                    pass
                handle_ref.current = None
        return cleanup

    # re-schedule whenever the stamp changes (i.e., the input changed)
    solara.use_effect(schedule, [last_stamp])

    return debounced


# ---------- File drop (drag & drop) ----------
@solara.component
def GeoJSONDrop(on_saved_path: Callable[[str], None], label: str = "Drop .geojson here"):
    """
    Drag-and-drop a GeoJSON file; we save it under /tmp and return the path via on_saved_path.
    """
    files, set_files = solara.use_state([])

    def on_file(file):
        # file is an object with attributes: name, content (bytes)
        try:
            if not file.name.lower().endswith(".geojson"):
                raise ValueError("Only .geojson is supported here.")
            content = file.content if isinstance(file.content, (bytes, bytearray)) else file.content.read()
            # Validate JSON
            _ = json.load(io.BytesIO(content))
            # Persist
            path = Path("/tmp") / file.name
            path.write_bytes(content)
            on_saved_path(str(path))
            set_files([file.name])
        except Exception as e:
            # Re-raise so app-level toast can show the message via an error boundary if used;
            # or you can lift an error callback prop. For simplicity we just print.
            print("GeoJSONDrop error:", e)
            # no on_saved_path call on error

    with solara.Row(gap="0.5rem", style={"align-items": "center"}):
        solara.FileDrop(on_file=on_file)
        solara.Markdown(f"**{label}**")
        if files:
            solara.Markdown(f"✔️ Loaded: `{files[0]}`")
