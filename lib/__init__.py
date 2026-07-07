"""Library functions: the pure rent-vs-buy / total-cost-of-ownership engine."""

from .model import (
    PARAM_GROUPS,
    Params,
    annual_table,
    breakeven_appreciation,
    breakeven_hold,
    sensitivity_grid,
    simulate,
    summarize,
    tornado,
)

__all__ = [
    "Params",
    "simulate",
    "summarize",
    "annual_table",
    "breakeven_appreciation",
    "breakeven_hold",
    "sensitivity_grid",
    "tornado",
    "PARAM_GROUPS",
]
