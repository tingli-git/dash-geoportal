from __future__ import annotations
import solara
from typing import Literal

ToastType = Literal["info", "success", "warning", "error"]

@solara.component
def Toast(message: str, kind: ToastType = "info", on_close=None, visible: bool = True):
    """
    Simple toast-like banner. Absolutely positioned, fades after close.
    """
    if not visible or not message:
        return

    colors = {
        "info":    ("#1e3a8a", "#e0e7ff"),  # indigo
        "success": ("#065f46", "#d1fae5"),  # emerald
        "warning": ("#92400e", "#fef3c7"),  # amber
        "error":   ("#7f1d1d", "#fee2e2"),  # rose
    }
    fg, bg = colors.get(kind, colors["info"])

    with solara.Card(
        elevation=3,
        style={
            "position": "fixed",
            "right": "16px",
            "bottom": "16px",
            "zIndex": "9999",
            "background": bg,
            "border": f"1px solid {fg}",
            "minWidth": "280px",
            "maxWidth": "420px",
        },
    ):
        with solara.Row(justify="space-between", style={"align-items": "center"}):
            solara.Markdown(f"<div style='color:{fg};font-weight:600'>• {kind.title()}</div>")
            solara.Button("✕", text=True, on_click=on_close)
        solara.Markdown(f"<div style='color:{fg}'>{message}</div>")


def use_toast():
    """
    Hook returning (show, hide, state_dict)
    show(msg, kind='info'), hide()
    """
    msg, set_msg = solara.use_state("")
    kind, set_kind = solara.use_state("info")

    def show(m: str, k: ToastType = "info"):
        set_kind(k)
        set_msg(m)

    def hide():
        set_msg("")

    return show, hide, {"message": msg, "kind": kind, "visible": bool(msg)}
