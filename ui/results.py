"""Results rendering: headline verdict, KPI tiles, sale bridge, and the annual
cost table. Kept separate from charts so the layout logic is easy to follow.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import model


def _fmt_money(v, decimals=0):
    return f"${v:,.{decimals}f}"


def verdict_banner(s: dict) -> None:
    """Big rent-vs-buy verdict headline."""
    delta = s["buy_minus_rent"]
    if s["buying_wins"]:
        st.success(
            f"### 🏠 Buying wins by {_fmt_money(delta)}\n"
            f"Over the holding period, the buyer's terminal net worth exceeds the "
            f"renter's by **{_fmt_money(delta)}** (cap-gains-taxed, symmetric)."
        )
    else:
        st.warning(
            f"### 🔑 Renting wins by {_fmt_money(-delta)}\n"
            f"Over the holding period, renting and investing the difference leaves "
            f"you **{_fmt_money(-delta)}** ahead of buying (cap-gains-taxed, symmetric)."
        )


def kpi_row(s: dict) -> None:
    """Top-line KPI tiles."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "All-in monthly cost (yr 1)",
        _fmt_money(s["yr1_monthly_cost"]),
        help="Cash outflow incl. P&I, taxes, HOA, insurance, maintenance, PMI, net of tax shield.",
    )
    c2.metric(
        "NPV cost of owning",
        _fmt_money(s["npv_cost"]),
        help="Economic cost in today's dollars, discounted at the market return.",
    )
    c3.metric(
        "Equivalent annual cost",
        _fmt_money(s["eac"]),
        help=f"{s['eac_pct_price']:.2%} of home price per year.",
    )
    c4.metric(
        "Buy − Rent (terminal)",
        _fmt_money(s["buy_minus_rent"]),
        delta=("Buying wins" if s["buying_wins"] else "Renting wins"),
        delta_color=("normal" if s["buying_wins"] else "inverse"),
    )


def sale_bridge(s: dict) -> None:
    """Sale-at-horizon waterfall as a small table."""
    st.markdown("**Sale at horizon**")
    rows = [
        ("Sale price", s["sale_price"]),
        ("− Selling costs", -s["sell_costs"]),
        ("− Loan payoff", -s["rem_bal"]),
        ("− Home cap gains tax", -s["home_cg_tax"]),
        ("= Net proceeds", s["net_proceeds"]),
    ]
    df = pd.DataFrame(rows, columns=["", "Amount"])
    st.dataframe(
        df.style.format({"Amount": "${:,.0f}"}), hide_index=True, width="stretch"
    )


def networth_compare(s: dict) -> None:
    st.markdown("**Terminal net worth**")
    df = pd.DataFrame(
        [("Buyer", s["buyer_nw"]), ("Renter", s["renter_nw"])],
        columns=["", "Net worth"],
    )
    st.dataframe(
        df.style.format({"Net worth": "${:,.0f}"}), hide_index=True, width="stretch"
    )


def annual_cost_table(res: dict) -> None:
    """Full per-year breakdown table."""
    g = model.annual_table(res).reset_index()
    g = g.rename(
        columns={
            "year": "Year",
            "P_and_I": "P&I",
            "interest": "Interest",
            "principal": "Principal",
            "prop_tax": "Prop tax",
            "hoa": "HOA",
            "insurance": "Insurance",
            "maintenance": "Maint",
            "pmi": "PMI",
            "tax_shield": "Tax shield",
            "net_cost": "Net cost",
            "end_balance": "End balance",
            "home_value": "Home value",
            "equity": "Equity",
        }
    )
    money_cols = [c for c in g.columns if c != "Year"]
    st.dataframe(
        g.style.format({c: "${:,.0f}" for c in money_cols}),
        hide_index=True,
        width="stretch",
    )


_UNSET = object()


def breakevens(p, ba=_UNSET, bh=_UNSET) -> None:
    """Break-even appreciation and holding period.

    ``ba``/``bh`` may be precomputed (so the caller can cache them); otherwise
    they are computed here. Note ``None`` is a valid result (no break-even).
    """
    if ba is _UNSET:
        ba = model.breakeven_appreciation(p)
    if bh is _UNSET:
        bh = model.breakeven_hold(p)
    c1, c2 = st.columns(2)
    if ba is not None:
        c1.metric(
            f"Break-even appreciation @ {p.holding_period_years}y hold",
            f"{ba:.2%}/yr",
            delta=f"you assumed {p.home_appreciation_rate:.2%}",
            delta_color="off",
        )
    else:
        c1.metric("Break-even appreciation", "none in range")
    if bh is not None:
        c2.metric(
            f"Break-even holding period @ {p.home_appreciation_rate:.2%} appr",
            f"{bh} years",
        )
    else:
        c2.metric("Break-even holding period", "buying never wins in term")
