"""Plotly chart builders — the interactive replacements for the notebook's
matplotlib figures. Each takes a ``simulate`` result (or params) and returns a
``go.Figure`` ready for ``st.plotly_chart``.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from lib import model

from . import theme

# Stacked cost-breakdown categories, in fixed palette order.
_COST_COMPONENTS = [
    ("interest", "Interest"),
    ("principal", "Principal"),
    ("prop_tax", "Property tax"),
    ("hoa", "HOA"),
    ("insurance", "Insurance"),
    ("maintenance", "Maintenance"),
    ("pmi", "PMI"),
]


def cost_vs_equity(res: dict) -> go.Figure:
    """Cumulative cash cost (incl. down + closing) vs home equity, by year."""
    m = res["monthly"]
    g = m.groupby("year").agg(
        net_cost=("owner_cost", "sum"),
        end_balance=("balance", "last"),
        home_value=("home_value", "last"),
    )
    equity = g["home_value"] - g["end_balance"]
    cum_cost = g["net_cost"].cumsum() + res["down"] + res["closing"]
    years = g.index

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=cum_cost,
            name="Cumulative cash cost",
            mode="lines+markers",
            line=dict(color=theme.SERIES[0], width=2),
            marker=dict(size=8),
            hovertemplate="Year %{x}<br>Cost: $%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=equity,
            name="Home equity",
            mode="lines+markers",
            line=dict(color=theme.SERIES[1], width=2),
            marker=dict(size=8, symbol="square"),
            hovertemplate="Year %{x}<br>Equity: $%{y:,.0f}<extra></extra>",
        )
    )
    theme.apply(
        fig,
        title="Cumulative cost vs equity built",
        hovermode="x unified",
        xaxis=dict(
            title="Year", gridcolor=theme.GRID, linecolor=theme.BASELINE, dtick=1
        ),
        yaxis=dict(
            title="", gridcolor=theme.GRID, linecolor=theme.BASELINE, tickformat="$,.0s"
        ),
    )
    return fig


def annual_cost_breakdown(res: dict) -> go.Figure:
    """Stacked bar of annual gross cost components."""
    m = res["monthly"]
    comp = m.groupby("year").agg(**{k: (k, "sum") for k, _ in _COST_COMPONENTS})
    years = comp.index

    fig = go.Figure()
    for i, (col, label) in enumerate(_COST_COMPONENTS):
        fig.add_trace(
            go.Bar(
                x=years,
                y=comp[col],
                name=label,
                marker=dict(
                    color=theme.SERIES[i], line=dict(color=theme.SURFACE, width=2)
                ),
                hovertemplate=f"{label}<br>Year %{{x}}: $%{{y:,.0f}}<extra></extra>",
            )
        )
    theme.apply(
        fig,
        title="Annual gross cost breakdown",
        barmode="stack",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(
            title="Year", gridcolor=theme.GRID, linecolor=theme.BASELINE, dtick=1
        ),
        yaxis=dict(
            title="", gridcolor=theme.GRID, linecolor=theme.BASELINE, tickformat="$,.0s"
        ),
    )
    return fig


def sensitivity_heatmap(p: model.Params, grid=None) -> go.Figure:
    """Diverging heatmap of Buy - Rent terminal net worth ($k).

    ``grid`` may be a precomputed ``(appr_grid, hold_grid, Z)`` tuple (so the
    caller can cache the expensive sweep); otherwise it is computed here.
    """
    appr_grid, hold_grid, Z = grid if grid is not None else model.sensitivity_grid(p)
    lim = float(np.abs(Z).max()) or 1.0
    y_labels = [f"{a:.0%}" for a in appr_grid]

    fig = go.Figure(
        go.Heatmap(
            z=Z,
            x=hold_grid,
            y=y_labels,
            colorscale=theme.DIVERGING,
            zmid=0,
            zmin=-lim,
            zmax=lim,
            xgap=2,
            ygap=2,
            colorbar=dict(title="$k", outlinewidth=0),
            hovertemplate="Hold %{x}y · appr %{y}<br>Buy − Rent: $%{z:,.0f}k<extra></extra>",
        )
    )

    # Direct value labels (relief for a value-encoded surface).
    fig.add_trace(
        go.Scatter(
            x=np.repeat(hold_grid, len(appr_grid)),
            y=np.tile(y_labels, len(hold_grid)),
            mode="text",
            text=[
                f"{Z[i, j]:.0f}"
                for j in range(len(hold_grid))
                for i in range(len(appr_grid))
            ],
            textfont=dict(size=9, color=theme.TEXT_PRIMARY),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    theme.apply(
        fig,
        title="Buy − Rent terminal net worth ($k)  ·  blue = buying wins",
        xaxis=dict(
            title="Holding period (years)",
            dtick=1,
            showgrid=False,
            linecolor=theme.BASELINE,
        ),
        yaxis=dict(
            title="Home appreciation / yr", showgrid=False, linecolor=theme.BASELINE
        ),
    )
    return fig


def tornado(p: model.Params) -> go.Figure:
    """Horizontal tornado: change in NPV cost of owning vs base, per +/- shock."""
    t = model.tornado(p)
    lo = t["low_shock"].to_numpy()
    hi = t["high_shock"].to_numpy()
    left = np.minimum(lo, hi)
    width = np.abs(hi - lo)

    fig = go.Figure(
        go.Bar(
            y=t["param"],
            x=width,
            base=left,
            orientation="h",
            marker=dict(color=theme.SERIES[0], line=dict(color=theme.SURFACE, width=1)),
            hovertemplate="%{y}<br>NPV swing: $%{x:,.0f}<extra></extra>",
        )
    )
    fig.add_vline(x=0, line=dict(color=theme.TEXT_PRIMARY, width=1))
    theme.apply(
        fig,
        title="Tornado: change in NPV cost of owning (vs base)",
        xaxis=dict(
            title="Δ NPV cost",
            gridcolor=theme.GRID,
            linecolor=theme.BASELINE,
            tickformat="$,.0s",
        ),
        yaxis=dict(title="", gridcolor=theme.GRID, linecolor=theme.BASELINE),
    )
    return fig
