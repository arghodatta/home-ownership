"""Results rendering: headline verdict, KPI tiles, sale bridge, and the annual
cost table. Kept separate from charts so the layout logic is easy to follow.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import model


def _fmt_money(v, decimals=0):
    return f"${v:,.{decimals}f}"


def methodology() -> None:
    """Collapsible, plain-language explanation of what the simulation does."""
    with st.expander("📖 How this simulation works", expanded=False):
        st.markdown("""
This tool plays out **two lives side by side** — one where you **buy** the home
and one where you **rent** the same home and invest every dollar you'd have spent
buying. It steps through the whole holding period **month by month**, then tallies
up who comes out ahead. Here's exactly what happens under the hood.

#### 1. The money you put in up front
- **Down payment** = home price × down-payment %.
- **Closing costs** = home price × closing-cost % (inspection, title, lender fees).
- The rest is your **mortgage loan**, repaid in fixed monthly payments.

#### 2. Every month, for as long as you own
The simulation walks forward one month at a time and records:
- **Home value** grows steadily at the appreciation rate you set.
- **Mortgage payment (P&I)** stays fixed, but each month is split into
  **interest** (the bank's fee, largest early on) and **principal** (which chips
  away at the loan).
- **Insurance and maintenance** are charged as a % of the home's *current*
  value, so they rise as the home appreciates.
- **Property tax** is a % of the *assessed* value, which you can base on the
  home's current market value, freeze at the purchase price (California
  Prop-13 style), grow off the purchase price at the reassessment cap of
  max(2%, inflation) per year, or grow it at min(5%, inflation) per year
  (Illinois PTELL extension-limitation cap).
- **HOA dues** start at your input and grow with inflation each year.
- **PMI** (mortgage insurance) is charged only while you owe more than 80% of the
  home's original price, then automatically drops off.

#### 3. The tax break from owning
Each year the model checks whether your **mortgage interest + property tax** (plus
any other itemized deductions) beat the **standard deduction**. Only the amount
*above* the standard deduction actually saves you tax, at your marginal rate. It
also respects the real-world caps: interest is deductible on only the first
$750k of the loan, and property tax counts only up to your remaining SALT room.
This saving is subtracted from your costs — it's the **tax shield**.

#### 4. Your all-in monthly cost
For each month: mortgage payment + property tax + insurance + maintenance + HOA +
PMI − tax shield. That's the real out-of-pocket cost of owning.

#### 5. Selling at the end
When the holding period ends, the home is "sold":
- **Sale price** = purchase price grown at the appreciation rate.
- Subtract **selling costs** (agent commission + transfer taxes), the **remaining
  loan balance**, and any **capital-gains tax** on the profit above the
  primary-residence exclusion.
- What's left is your **net proceeds** — the cash you actually walk away with.

#### 6. The two headline answers
- **Cost of owning** — every cost above is added up and pulled back into *today's
  dollars* (future dollars count for a little less, because money kept today could
  be invested). Subtracting the net sale proceeds gives the **NPV cost of owning**,
  and spreading that over the years gives the **equivalent annual cost**.
- **Buy vs. rent** — this is the fair fight. Each month, whoever's housing is
  cheaper **invests the difference** in the market; the renter also invests the
  down payment and closing costs the buyer sank into the home. Both portfolios are
  taxed on their gains. At the end, the buyer's wealth (savings **+** home equity)
  is compared with the renter's wealth. Whoever has more **wins**.

#### A few things to keep in mind
- Rent escalates at its own **rent-growth rate**, set independently of home-price
  appreciation — historically rents track incomes/inflation, which can diverge
  from home prices over a holding period.
- **Every rate is assumed to hold constant for the whole horizon** — appreciation,
  inflation, the mortgage rate, market return, tax rates, and the property-tax
  escalators never change year to year. Reality is bumpier: rates move, markets
  have good and bad stretches, and tax law shifts. Treat the output as a smooth
  central estimate, not a forecast, and lean on the **Sensitivity** tab to see how
  much the verdict swings when the key assumptions are wrong.
- The comparison is deliberately **symmetric** — same starting cash, same market
  return, same capital-gains treatment on both sides — so it isn't rigged for
  either choice.
- Every number is only as good as the assumptions in the sidebar. Try nudging the
  appreciation rate, holding period, or rent to see how sensitive the verdict is.
""")


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


def _delta_vs(cur, base, decimals=0):
    """Money-formatted delta vs a baseline, or None when negligible (< $1)."""
    if base is None:
        return None
    d = cur - base
    if abs(d) < 1:
        return None
    return f"{'+' if d >= 0 else '−'}{_fmt_money(abs(d), decimals)} vs default"


def kpi_row(s: dict, base: dict | None = None) -> None:
    """Top-line KPI tiles. When ``base`` (the default-Params summary) is given,
    the cost tiles show a delta vs the defaults; lower cost is coloured good."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "All-in monthly cost (yr 1)",
        _fmt_money(s["yr1_monthly_cost"]),
        delta=_delta_vs(s["yr1_monthly_cost"], base and base["yr1_monthly_cost"]),
        delta_color="inverse",
        help=(
            "What you'd actually pay out of pocket each month in your first year: "
            "mortgage payment, property tax, HOA dues, home insurance, upkeep, and "
            "mortgage insurance (PMI) — minus the tax you save from deductions. "
            "Lower is better."
        ),
    )
    c2.metric(
        "NPV cost of owning",
        _fmt_money(s["npv_cost"]),
        delta=_delta_vs(s["npv_cost"], base and base["npv_cost"]),
        delta_color="inverse",
        help=(
            "The total lifetime cost of owning this home, boiled down to a single "
            "lump sum in today's dollars. It adds up every future cost and subtracts "
            "what you get back when you sell. Future dollars count for a bit less, "
            "because money you keep today could be invested and grow. Lower is better."
        ),
    )
    c3.metric(
        "Equivalent annual cost",
        _fmt_money(s["eac"]),
        delta=_delta_vs(s["eac"], base and base["eac"]),
        delta_color="inverse",
        help=(
            "The lifetime cost of owning spread out into a level yearly amount — the "
            "'true' yearly price of owning this home. That's "
            f"{s['eac_pct_price']:.2%} of the home's price per year. Easy to compare "
            f"against a year of rent, which here works out to {_fmt_money(s['eac_rent'])}/yr. "
            "Lower is better."
        ),
    )
    c4.metric(
        "Buy − Rent (terminal)",
        _fmt_money(s["buy_minus_rent"]),
        delta=("Buying wins" if s["buying_wins"] else "Renting wins"),
        delta_color=("normal" if s["buying_wins"] else "inverse"),
        help=(
            "How much richer buying leaves you compared with renting and investing "
            "the money you'd have saved, by the end of the holding period. A positive "
            "number means buying builds more wealth; negative means renting wins. "
            "Both paths are compared fairly — same starting cash, and each invests "
            "whatever the other spends on housing."
        ),
    )


def sale_table(s: dict) -> None:
    """Sale-at-horizon bridge as a small table (companion to the waterfall)."""
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
    st.caption(
        "What you actually walk away with when you sell. Start from the sale price, "
        "then subtract agent and closing costs, whatever's left on the mortgage, and "
        "any tax on the profit. **Net proceeds** is the cash that lands in your pocket."
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
    st.caption(
        "Total wealth at the end of the period for two people who start with the same "
        "money — one buys, the other rents and invests the difference. The buyer's "
        "figure is their home equity plus savings; the renter's is their investment "
        "pot. Whoever's number is higher comes out ahead."
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
    st.caption(
        "Year-by-year detail. **P&I** is your mortgage payment, split into "
        "**Interest** (the bank's fee) and **Principal** (paying down the loan). "
        "**Prop tax**, **HOA**, **Insurance**, **Maint** (upkeep), and **PMI** "
        "(mortgage insurance) are the other carrying costs. **Tax shield** is the "
        "tax you save from deductions, and **Net cost** is the total after that "
        "saving. **End balance** is what's left on the loan, **Home value** is the "
        "estimated price that year, and **Equity** is the share you truly own "
        "(home value minus loan)."
    )


def _fmt_param(value, kind):
    """Format a raw model parameter value for display, per its widget kind."""
    if kind == "pct":
        return f"{value * 100:.3g}%"
    if kind == "int":
        return f"{int(value):,}"
    return _fmt_money(value)


def scenario_compare(cur_p, pin_p, cur_s, pin_s) -> None:
    """Side-by-side of a pinned scenario (A) vs the current one (B)."""
    st.markdown("**Outcomes — current (B) vs pinned (A)**")
    metrics = [
        (
            "Buy − Rent (terminal)",
            "buy_minus_rent",
            "normal",
            "How much richer buying leaves you versus renting-and-investing by the "
            "end. Positive = buying wins.",
        ),
        (
            "NPV cost of owning",
            "npv_cost",
            "inverse",
            "Total lifetime cost of owning as a single lump sum in today's dollars. "
            "Lower is better.",
        ),
        (
            "Equivalent annual cost",
            "eac",
            "inverse",
            "That lifetime cost spread into a level yearly amount — the 'true' yearly "
            "price of owning. Lower is better.",
        ),
        (
            "All-in monthly (yr 1)",
            "yr1_monthly_cost",
            "inverse",
            "What you'd pay out of pocket each month in year one, after tax savings. "
            "Lower is better.",
        ),
    ]
    cols = st.columns(len(metrics))
    for col, (label, key, color, help_txt) in zip(cols, metrics):
        d = _delta_vs(cur_s[key], pin_s[key])
        col.metric(
            label,
            _fmt_money(cur_s[key]),
            delta=d and d.replace(" vs default", " vs A"),
            delta_color=color,
            help=help_txt,
        )

    st.markdown("**Changed inputs**")
    rows = []
    for specs in model.PARAM_GROUPS.values():
        for attr, label, kind, *_ in specs:
            a, b = getattr(pin_p, attr), getattr(cur_p, attr)
            if a != b:
                rows.append((label, _fmt_param(a, kind), _fmt_param(b, kind)))
    if rows:
        df = pd.DataFrame(rows, columns=["Parameter", "Pinned (A)", "Current (B)"])
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.caption("No inputs differ — the current scenario matches the pinned one.")


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
    appr_help = (
        "The yearly home-price growth rate at which buying and renting come out "
        "exactly even. If you expect the home to grow faster than this, buying wins; "
        "slower, and renting-and-investing wins."
    )
    hold_help = (
        "How many years you'd need to stay put for buying to beat renting. Sell "
        "sooner than this and renting-and-investing would have left you richer — "
        "the up-front buying costs need time to pay off."
    )
    if ba is not None:
        c1.metric(
            f"Break-even appreciation @ {p.holding_period_years}y hold",
            f"{ba:.2%}/yr",
            delta=f"you assumed {p.home_appreciation_rate:.2%}",
            delta_color="off",
            help=appr_help,
        )
    else:
        c1.metric("Break-even appreciation", "none in range", help=appr_help)
    if bh is not None:
        c2.metric(
            f"Break-even holding period @ {p.home_appreciation_rate:.2%} appr",
            f"{bh} years",
            help=hold_help,
        )
    else:
        c2.metric(
            "Break-even holding period",
            "buying never wins in term",
            help=hold_help,
        )
