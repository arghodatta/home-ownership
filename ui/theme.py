"""Chart theme: validated palette + a shared Plotly layout.

Colors are the data-viz reference palette (light mode), validated for CVD safety.
Categorical slots are used in fixed order; the heatmap uses the blue<->red
diverging pair with a neutral gray midpoint at zero.
"""

from __future__ import annotations

import plotly.graph_objects as go

# ---- Categorical slots (fixed order — never cycled) ----
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

# ---- Diverging pair (polarity: buying wins <-> renting wins) ----
DIVERGING = [
    [0.0, "#e34948"],  # red  — renting wins
    [0.5, "#f0efec"],  # neutral gray midpoint
    [1.0, "#2a78d6"],  # blue — buying wins
]

# ---- Chart chrome & ink (light surface) ----
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def base_layout(**overrides) -> dict:
    """A shared Plotly layout dict; pass overrides to extend per-chart."""
    layout = dict(
        template="plotly_white",
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT_FAMILY, color=TEXT_SECONDARY, size=13),
        title=dict(font=dict(color=TEXT_PRIMARY, size=16)),
        margin=dict(l=60, r=24, t=56, b=48),
        xaxis=dict(
            gridcolor=GRID, linecolor=BASELINE, zerolinecolor=BASELINE, tickcolor=MUTED
        ),
        yaxis=dict(gridcolor=GRID, linecolor=BASELINE, zerolinecolor=BASELINE),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT_SECONDARY)),
        colorway=SERIES,
        hoverlabel=dict(font=dict(family=FONT_FAMILY)),
    )
    layout.update(overrides)
    return layout


def apply(fig: go.Figure, **overrides) -> go.Figure:
    fig.update_layout(**base_layout(**overrides))
    return fig
