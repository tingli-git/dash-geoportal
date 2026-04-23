from __future__ import annotations
import solara

class ReactiveRefs:
    """Holds shared refs between hooks (selected marker, etc.)."""
    def __init__(self):
        self.active_marker_ref = solara.use_ref(None)
        self.did_fit_ref = solara.use_ref(False)
