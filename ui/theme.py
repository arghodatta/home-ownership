"""Chart theme: validated palette + a shared, theme-aware Plotly layout.

The categorical SERIES colors are the data-viz reference palette, validated for
CVD safety, and are shared across light and dark. Chart *chrome* (surface, grid,
ink) resolves to a light or dark set based on the viewer's active Streamlit
theme, so charts never render as a bright rectangle inside a dark page. The
heatmap uses a blue<->red diverging pair whose neutral midpoint tracks the
surface color of the active theme.

Call ``theme.current()`` inside a chart builder to get the resolved palette, or
use ``theme.apply(fig, ...)`` which resolves it for you.
"""

from __future__ import annotations

from types import SimpleNamespace

import plotly.graph_objects as go

try:  # theme resolution needs Streamlit, but the module must import without it
    import streamlit as st
except Exception:  # pragma: no cover - Streamlit always present in the app
    st = None

# ---- Categorical slots (fixed order — never cycled; shared across themes) ----
SERIES = [
    "#2a78d6",  # 1 blue
    "#1baf7a",  # 2 aqua
    "#eda100",  # 3 yellow
    "#008300",  # 4 green
    "#4a3aa7",  # 5 violet
    "#e34948",  # 6 red
    "#e87ba4",  # 7 magenta
    "#eb6834",  # 8 orange
]

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# ---- Per-theme chrome & ink -------------------------------------------------
# `diverging` polarity is fixed: red = renting wins, blue = buying wins, with a
# neutral midpoint that blends into the theme's surface.
_LIGHT = dict(
    template="plotly_white",
    surface="#fcfcfb",
    text_primary="#0b0b0b",
    text_secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    baseline="#c3c2b7",
    diverging=[
        [0.0, "#e34948"],  # red  — renting wins
        [0.5, "#f0efec"],  # neutral (light surface)
        [1.0, "#2a78d6"],  # blue — buying wins
    ],
)
_DARK = dict(
    template="plotly_dark",
    surface="#0e1117",  # Streamlit's default dark background
    text_primary="#fafafa",
    text_secondary="#c9c9c9",
    muted="#8b8b8b",
    grid="#2b2f3a",
    baseline="#3d4250",
    diverging=[
        [0.0, "#e34948"],  # red  — renting wins
        [0.5, "#1c2029"],  # neutral (dark surface)
        [1.0, "#2a78d6"],  # blue — buying wins
    ],
)

# Backward-compatible module-level constants (light defaults). Prefer
# ``current()`` in new code so charts follow the active theme.
SURFACE = _LIGHT["surface"]
TEXT_PRIMARY = _LIGHT["text_primary"]
TEXT_SECONDARY = _LIGHT["text_secondary"]
MUTED = _LIGHT["muted"]
GRID = _LIGHT["grid"]
BASELINE = _LIGHT["baseline"]
DIVERGING = _LIGHT["diverging"]


def _active_mode() -> str:
    """The app is locked to a light palette, so charts always render light
    regardless of the viewer's browser/system theme. See ``.streamlit/config.toml``
    ``[theme] base = "light"`` for the matching page chrome."""
    return "light"


def current() -> SimpleNamespace:
    """Palette for the active theme: ``.series``, ``.surface``, ``.grid``, etc."""
    chrome = _DARK if _active_mode() == "dark" else _LIGHT
    return SimpleNamespace(series=SERIES, font_family=FONT_FAMILY, **chrome)


def base_layout(**overrides) -> dict:
    """A shared, theme-aware Plotly layout dict; pass overrides to extend it."""
    pal = current()
    layout = dict(
        template=pal.template,
        paper_bgcolor=pal.surface,
        plot_bgcolor=pal.surface,
        font=dict(family=pal.font_family, color=pal.text_secondary, size=13),
        title=dict(font=dict(color=pal.text_primary, size=16)),
        margin=dict(l=60, r=24, t=56, b=48),
        xaxis=dict(
            gridcolor=pal.grid,
            linecolor=pal.baseline,
            zerolinecolor=pal.baseline,
            tickcolor=pal.muted,
        ),
        yaxis=dict(
            gridcolor=pal.grid, linecolor=pal.baseline, zerolinecolor=pal.baseline
        ),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=pal.text_secondary)),
        colorway=pal.series,
        hoverlabel=dict(font=dict(family=pal.font_family)),
    )
    layout.update(overrides)
    return layout


def apply(fig: go.Figure, **overrides) -> go.Figure:
    fig.update_layout(**base_layout(**overrides))
    return fig
