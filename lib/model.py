"""Core rent-vs-buy / total-cost-of-ownership engine.

A faithful port of ``notebooks/home_cost_model.ipynb``. This module is pure
computation — no Streamlit, no plotting — so it can be unit-tested, reused, and
called many times by the sensitivity analyses.

Two headline outputs:
  A) NPV cost of ownership (today's dollars) + equivalent annual cost.
  B) Rent-vs-buy terminal net worth, with break-even appreciation & holding period.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

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


@dataclass(frozen=True)
class Params:
    """All model inputs. Defaults are illustrative (~a Cook County condo)."""

    # ---- Purchase ----
    house_price: float = 1_000_000
    down_payment_pct: float = 0.20  # 20% avoids PMI
    closing_cost_pct: float = 0.03  # buyer-side closing costs, % of price (~2-4%)

    # ---- Financing ----
    mortgage_rate: float = 0.0675  # annual nominal APR
    loan_term_years: int = 30

    # ---- Recurring carry ----
    property_tax_rate: float = 0.025  # effective, % of assessed value / yr
    property_tax_basis: str = (
        "capped"  # "market" | "purchase" | "capped" (see _assessed_value)
    )
    hoa_monthly: float = 300.0  # grows with inflation
    insurance_rate: float = 0.0025  # % of home value / yr
    maintenance_rate: float = 0.0025  # % of home value / yr
    pmi_rate: float = 0.006  # % of ORIGINAL loan / yr, while LTV > 80% of orig price

    # ---- Growth / macro ----
    home_appreciation_rate: float = 0.035  # nominal home price growth / yr
    inflation_rate: float = 0.025  # grows HOA
    market_return: float = 0.07  # equity/portfolio return (opportunity cost of capital)
    discount_rate: float = (
        0.043  # NPV discount rate; default ≈ 30Y zero rate (swap curve)
    )

    # ---- Taxes (deductions) ----
    marginal_income_tax_rate: float = (
        0.42  # fed+state marginal, for itemized deductions
    )
    salt_cap: float = 10_000  # SALT deduction cap
    salt_headroom: float = (
        0.0  # $ of SALT cap left for PROPERTY tax (0 => income tax exhausts it)
    )
    mortgage_deduction_principal_cap: float = (
        750_000  # interest deductible only on first $750k of debt
    )
    other_itemized_deductions: float = 0.0  # charitable, etc. (raises itemized total)
    standard_deduction: float = 29_200  # MFJ; only deductions ABOVE this have value
    cap_gains_tax_rate: float = 0.238  # LTCG 20% + 3.8% NIIT (investments & home sale)
    home_sale_exclusion: float = 500_000  # MFJ primary-residence gain exclusion

    # ---- Sale / exit ----
    selling_cost_pct: float = 0.06  # realtor + transfer taxes at sale (~5-6%)

    # ---- Horizon ----
    holding_period_years: int = 7

    # ---- Rent counterfactual (only used in the rent-vs-buy section) ----
    monthly_rent: float = 4_800.0
    rent_growth_rate: float = 0.03  # annual rent escalation, independent of home price


def _assessed_value(p: Params, year0, hv):
    """Assessed value used for property tax, per the chosen `property_tax_basis`.

    ``year0`` is the 0-based year index (array) and ``hv`` the market-value path.

      - "market":   assessed = current market value (taxes rise with the home).
      - "purchase": assessed frozen at the purchase price (CA Prop-13 style, no
                    reassessment while you hold).
      - "capped":   assessed grows off the purchase price at max(2%, inflation)
                    per year — the annual reassessment cap.
      - "ptell":    assessed grows off the purchase price at min(5%, inflation)
                    per year — the Illinois PTELL extension-limitation cap.
    """
    basis = p.property_tax_basis
    if basis == "purchase":
        return np.full(np.shape(hv), p.house_price, dtype=float)
    if basis == "capped":
        growth = max(0.02, p.inflation_rate)
        return p.house_price * (1.0 + growth) ** year0
    if basis == "ptell":
        growth = min(0.05, p.inflation_rate)
        return p.house_price * (1.0 + growth) ** year0
    if basis != "market":
        raise ValueError(f"unknown property_tax_basis: {basis!r}")
    return hv


def simulate(p: Params) -> dict:
    """Run the monthly engine and return all intermediate + headline results."""
    r_m = p.mortgage_rate / 12.0
    n_tot = p.loan_term_years * 12
    loan0 = p.house_price * (1 - p.down_payment_pct)
    down = p.house_price * p.down_payment_pct
    closing = p.house_price * p.closing_cost_pct

    # Fixed monthly payment (P&I)
    pmt = loan0 * r_m / (1 - (1 + r_m) ** (-n_tot)) if r_m > 0 else loan0 / n_tot

    # Fraction of interest that is deductible (first $750k of principal)
    int_factor = (
        min(1.0, p.mortgage_deduction_principal_cap / loan0) if loan0 > 0 else 0.0
    )

    months = p.holding_period_years * 12

    # ---- Vectorized monthly schedule (no Python loop) --------------------
    # k is the 0-based month index; month number m = k + 1.
    k = np.arange(months)
    m_idx = k + 1
    year0 = k // 12  # 0-based year index (HOA inflation, tax escalators)

    # Closed-form amortization. Balance after (k+1) payments follows the
    # recurrence bal_j = bal_{j-1}(1+r) - pmt, solved directly; clamped at 0 so
    # holding past the loan term leaves a paid-off (zero) balance.
    if r_m > 0:
        g_m = (1.0 + r_m) ** m_idx
        bal_end = loan0 * g_m - pmt * (g_m - 1.0) / r_m
    else:
        bal_end = loan0 - pmt * m_idx
    bal_end = np.maximum(bal_end, 0.0)
    bal_start = np.concatenate(([loan0], bal_end[:-1]))

    # principal = bal_start - bal_end reproduces min(pmt - interest, balance):
    # it equals pmt - interest while the loan is live and the exact remaining
    # balance in the payoff month, then 0 once bal_start hits 0.
    interest = np.where(bal_start > 0, bal_start * r_m, 0.0)
    principal = bal_start - bal_end
    pi = interest + principal

    hv = p.house_price * (1 + p.home_appreciation_rate) ** (m_idx / 12.0)
    assessed = _assessed_value(p, year0, hv)

    prop_tax = p.property_tax_rate * assessed / 12.0
    ins = p.insurance_rate * hv / 12.0
    maint = p.maintenance_rate * hv / 12.0
    hoa = p.hoa_monthly * (1 + p.inflation_rate) ** year0
    if p.house_price > 0:
        pmi = np.where(bal_end / p.house_price > 0.80, p.pmi_rate * loan0 / 12.0, 0.0)
    else:
        pmi = np.zeros(months)

    mdf = pd.DataFrame(
        dict(
            month=m_idx,
            year=year0 + 1,
            home_value=hv,
            balance=bal_end,
            interest=interest,
            principal=principal,
            pi=pi,
            prop_tax=prop_tax,
            insurance=ins,
            maintenance=maint,
            hoa=hoa,
            pmi=pmi,
        )
    )

    # ---- Annual tax shield (itemized vs standard) ----
    ann = (
        mdf.groupby("year")
        .agg(interest=("interest", "sum"), prop_tax=("prop_tax", "sum"))
        .reset_index()
    )
    ded_interest = ann["interest"] * int_factor
    ded_prop_tax = np.minimum(ann["prop_tax"], p.salt_headroom)
    itemized = ded_interest + ded_prop_tax + p.other_itemized_deductions
    ann["tax_benefit"] = (
        np.maximum(0.0, itemized - p.standard_deduction) * p.marginal_income_tax_rate
    )
    benefit_by_year = dict(zip(ann["year"], ann["tax_benefit"]))
    mdf["tax_benefit"] = mdf["year"].map(benefit_by_year) / 12.0

    # Monthly all-in owner cost (cash outflow, net of tax shield)
    mdf["owner_cost"] = (
        mdf["pi"]
        + mdf["prop_tax"]
        + mdf["insurance"]
        + mdf["maintenance"]
        + mdf["hoa"]
        + mdf["pmi"]
        - mdf["tax_benefit"]
    )
    # Monthly rent path — escalates at its own `rent_growth_rate`, independent of
    # home-price appreciation. (Historically rents track incomes/inflation, which
    # can diverge markedly from home-price growth over a holding period.)
    mdf["rent"] = p.monthly_rent * (1 + p.rent_growth_rate) ** (
        (mdf["month"] - 1) // 12
    )

    # ---- Sale at horizon ----
    T = p.holding_period_years

    # Sale price: the purchase price compounded at the annual appreciation rate
    # for the whole holding period. (Equals the last month's home value, since
    # months = T*12 and hv uses (1+appr)**(m/12).)
    sale_price = p.house_price * (1 + p.home_appreciation_rate) ** T

    # Loan payoff: the mortgage balance still owed at the horizon, taken from the
    # last row of the monthly amortization schedule (0 once the loan is paid off).
    rem_bal = mdf["balance"].iloc[-1]

    # Selling costs: realtor commission + transfer taxes, as a % of the sale
    # price (not the original price — they scale with what you actually sell for).
    sell_costs = sale_price * p.selling_cost_pct

    # Home capital-gains tax: tax the appreciation (sale price - original price),
    # but only the portion ABOVE the primary-residence exclusion, at the cap-gains
    # rate. max(0, ...) means no tax when the gain fits under the exclusion.
    home_gain = sale_price - p.house_price
    home_cg_tax = max(0.0, home_gain - p.home_sale_exclusion) * p.cap_gains_tax_rate

    # Net proceeds: cash in hand after selling — the sale price less the three
    # things that come out of it (selling costs, remaining loan payoff, and the
    # home cap-gains tax). This is the buyer's recovered equity at the horizon.
    net_proceeds = sale_price - sell_costs - rem_bal - home_cg_tax

    # ---- (A) NPV cost of ownership (discount at the discount_rate) ----
    # These are fairly certain, debt-like housing cash flows, so they are
    # discounted at the (safer) discount rate — NOT the risky equity return used
    # for the invested portfolios in section (B).
    annual_out = mdf.groupby("year")["owner_cost"].sum()
    npv = down + closing
    for y, out in annual_out.items():
        npv += out / (1 + p.discount_rate) ** y
    npv -= net_proceeds / (1 + p.discount_rate) ** T
    crf = (
        (p.discount_rate * (1 + p.discount_rate) ** T)
        / ((1 + p.discount_rate) ** T - 1)
        if p.discount_rate > 0
        else 1.0 / T
    )
    eac = npv * crf  # equivalent annual cost

    # NPV cost of renting: PV of the rent path over the same horizon, discounted
    # at the same discount rate. Symmetric to owning, but with no down/closing to
    # sink up front and no sale proceeds to recover at the end.
    annual_rent = mdf.groupby("year")["rent"].sum()
    npv_rent = 0.0
    for y, out in annual_rent.items():
        npv_rent += out / (1 + p.discount_rate) ** y
    eac_rent = npv_rent * crf

    # ---- (B) Rent-vs-buy terminal wealth (symmetric, cap-gains-taxed) ----
    # Invested surpluses compound at the risky equity return (market_return), not
    # the discount rate — this is the opportunity cost of capital actually earned.
    # Vectorized equivalent of the notebook's month-by-month compounding loop:
    # a surplus invested in month m compounds for (months - m + 1) monthly steps.
    mret_m = (1 + p.market_return) ** (1 / 12.0) - 1
    diff = (
        mdf["owner_cost"] - mdf["rent"]
    ).to_numpy()  # +: owning costs more this month
    rent_add = np.where(diff > 0, diff, 0.0)  # renter invests the surplus
    buy_add = np.where(diff <= 0, -diff, 0.0)  # buyer invests the surplus
    i = np.arange(months)  # 0-based month index
    growth = (1 + mret_m) ** (months - i)  # months remaining incl. current step

    port_buy = float((buy_add * growth).sum())
    port_rent = (down + closing) * (1 + mret_m) ** months + float(
        (rent_add * growth).sum()
    )
    basis_buy = float(buy_add.sum())
    basis_rent = (down + closing) + float(rent_add.sum())

    port_buy_at = port_buy - max(0.0, port_buy - basis_buy) * p.cap_gains_tax_rate
    port_rent_at = port_rent - max(0.0, port_rent - basis_rent) * p.cap_gains_tax_rate
    buyer_nw = port_buy_at + net_proceeds
    renter_nw = port_rent_at
    buy_minus_rent = buyer_nw - renter_nw

    return dict(
        p=p,
        monthly=mdf,
        annual=ann,
        pmt=pmt,
        loan0=loan0,
        down=down,
        closing=closing,
        sale_price=sale_price,
        rem_bal=rem_bal,
        sell_costs=sell_costs,
        home_cg_tax=home_cg_tax,
        net_proceeds=net_proceeds,
        npv_cost=npv,
        eac=eac,
        npv_cost_rent=npv_rent,
        eac_rent=eac_rent,
        buyer_nw=buyer_nw,
        renter_nw=renter_nw,
        buy_minus_rent=buy_minus_rent,
    )


def summarize(res: dict) -> dict:
    """Flatten a result into the scalar headline numbers the UI displays."""
    p = res["p"]
    m = res["monthly"]
    return dict(
        yr1_monthly_cost=m[m["year"] == 1]["owner_cost"].sum() / 12.0,
        avg_monthly_cost=m["owner_cost"].mean(),
        npv_cost=res["npv_cost"],
        eac=res["eac"],
        npv_cost_rent=res["npv_cost_rent"],
        eac_rent=res["eac_rent"],
        eac_pct_price=(res["eac"] / p.house_price if p.house_price else 0.0),
        sale_price=res["sale_price"],
        sell_costs=res["sell_costs"],
        rem_bal=res["rem_bal"],
        home_cg_tax=res["home_cg_tax"],
        net_proceeds=res["net_proceeds"],
        buyer_nw=res["buyer_nw"],
        renter_nw=res["renter_nw"],
        buy_minus_rent=res["buy_minus_rent"],
        buying_wins=res["buy_minus_rent"] > 0,
        down=res["down"],
        closing=res["closing"],
        loan0=res["loan0"],
        pmt=res["pmt"],
    )


def annual_table(res: dict) -> pd.DataFrame:
    """Per-year cost breakdown, end balance, home value and equity."""
    m = res["monthly"]
    g = m.groupby("year").agg(
        P_and_I=("pi", "sum"),
        interest=("interest", "sum"),
        principal=("principal", "sum"),
        prop_tax=("prop_tax", "sum"),
        hoa=("hoa", "sum"),
        insurance=("insurance", "sum"),
        maintenance=("maintenance", "sum"),
        pmi=("pmi", "sum"),
        tax_shield=("tax_benefit", "sum"),
        net_cost=("owner_cost", "sum"),
        end_balance=("balance", "last"),
        home_value=("home_value", "last"),
    )
    g["equity"] = g["home_value"] - g["end_balance"]
    return g


def breakeven_appreciation(p: Params):
    """Annual appreciation at which Buy - Rent == 0, at the current horizon."""
    from scipy.optimize import brentq

    f = lambda a: simulate(replace(p, home_appreciation_rate=a))["buy_minus_rent"]
    try:
        return brentq(f, -0.05, 0.20)
    except ValueError:
        return None


def breakeven_hold(p: Params):
    """Smallest whole-year holding period (>= 2) where buying wins, else None.

    Starts at 2 years: below that the primary-residence cap-gains exclusion and
    long-term rate don't apply, so those holds are out of the model's scope.
    """
    for h in range(2, p.loan_term_years + 1):
        if simulate(replace(p, holding_period_years=h))["buy_minus_rent"] > 0:
            return h
    return None


def sensitivity_grid(p: Params, appr_grid=None, hold_grid=None):
    """Buy - Rent terminal net worth ($k) over appreciation x holding period.

    Returns (appr_grid, hold_grid, Z) where Z[i, j] uses appr_grid[i], hold_grid[j].
    """
    appr_grid = np.arange(0.00, 0.0651, 0.01) if appr_grid is None else appr_grid
    hold_grid = np.arange(2, 16, 1) if hold_grid is None else hold_grid
    Z = np.zeros((len(appr_grid), len(hold_grid)))
    for i, a in enumerate(appr_grid):
        for j, h in enumerate(hold_grid):
            r = simulate(
                replace(p, home_appreciation_rate=float(a), holding_period_years=int(h))
            )
            Z[i, j] = r["buy_minus_rent"] / 1e3
    return appr_grid, hold_grid, Z


def tornado(p: Params) -> pd.DataFrame:
    """One-factor sensitivity of NPV cost of owning to +/- shocks per parameter."""
    base = simulate(p)["npv_cost"]
    shocks = {
        "mortgage_rate": ("mortgage_rate", p.mortgage_rate, 0.01),
        "home_appreciation_rate": (
            "home_appreciation_rate",
            p.home_appreciation_rate,
            0.01,
        ),
        "discount_rate": ("discount_rate", p.discount_rate, 0.01),
        "property_tax_rate": ("property_tax_rate", p.property_tax_rate, 0.005),
        "maintenance_rate": ("maintenance_rate", p.maintenance_rate, 0.005),
        "hoa_monthly": ("hoa_monthly", p.hoa_monthly, 200),
        "holding_period_years": ("holding_period_years", p.holding_period_years, 2),
    }
    rows = []
    for name, (attr, val, d) in shocks.items():
        lo_val = val - d
        if attr == "holding_period_years":
            lo_val = max(2, lo_val)  # respect the 2-year minimum hold
        lo = simulate(replace(p, **{attr: type(val)(lo_val)}))["npv_cost"]
        hi = simulate(replace(p, **{attr: type(val)(val + d)}))["npv_cost"]
        rows.append((name, lo - base, hi - base, abs(hi - lo)))
    return (
        pd.DataFrame(rows, columns=["param", "low_shock", "high_shock", "range"])
        .sort_values("range")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# UI metadata: how to render each parameter as an input widget. Grouped to
# mirror the notebook's parameter sections. Tuple = (attr, label, kind, step,
# min, max, help). `kind` is "pct" (shown as %), "dollar", or "int".
# ---------------------------------------------------------------------------
PARAM_GROUPS = {
    "Purchase": [
        (
            "house_price",
            "House price ($)",
            "dollar",
            10_000,
            10_000,
            None,
            "Purchase price of the home.",
        ),
        (
            "down_payment_pct",
            "Down payment (%)",
            "pct",
            0.01,
            0.0,
            1.0,
            "20% or more lets you skip PMI — the extra insurance lenders charge "
            "when you put down less than 20%.",
        ),
        (
            "closing_cost_pct",
            "Closing costs (% of price)",
            "pct",
            0.005,
            0.0,
            0.1,
            "Buyer-side closing costs, typically 2-4%.",
        ),
    ],
    "Financing": [
        (
            "mortgage_rate",
            "Mortgage rate (APR %)",
            "pct",
            0.00125,
            0.0,
            0.2,
            "Your mortgage's yearly interest rate. Default 6.75% ≈ roughly "
            "today's 30-year rate.",
        ),
        (
            "loan_term_years",
            "Loan term (years)",
            "int",
            1,
            1,
            40,
            "How many years to pay off the loan, e.g. 15 or 30.",
        ),
    ],
    "Recurring carry": [
        (
            "property_tax_rate",
            "Property tax (% of value/yr)",
            "pct",
            0.001,
            0.0,
            0.1,
            'Yearly property tax as a % of the taxable ("assessed") value of '
            "the home.",
        ),
        (
            "property_tax_basis",
            "Property tax assessed on",
            "choice",
            (
                ("market", "Current market value (rises with the home)"),
                ("purchase", "Frozen at the price you paid (California-style)"),
                ("capped", "Price you paid, rising up to max(2%, inflation)/yr"),
                (
                    "ptell",
                    "Price you paid, rising up to min(5%, inflation)/yr (Illinois)",
                ),
            ),
            None,
            None,
            "What your property tax is figured on: the home's current value, the "
            "price you paid (frozen), or the price you paid rising by a capped "
            "amount each year (the California and Illinois rules).",
        ),
        (
            "hoa_monthly",
            "HOA ($/mo)",
            "dollar",
            50,
            0,
            None,
            "Monthly HOA/condo fee; grows with inflation.",
        ),
        (
            "insurance_rate",
            "Insurance (% of value/yr)",
            "pct",
            0.001,
            0.0,
            0.05,
            "Annual homeowners insurance rate.",
        ),
        (
            "maintenance_rate",
            "Maintenance (% of value/yr)",
            "pct",
            0.001,
            0.0,
            0.05,
            "Often forgotten; ~1% is typical and large.",
        ),
        (
            "pmi_rate",
            "PMI (% of orig. loan/yr)",
            "pct",
            0.001,
            0.0,
            0.03,
            "Extra insurance you pay while you still owe more than 80% of the "
            "home's original price.",
        ),
    ],
    "Growth / macro": [
        (
            "home_appreciation_rate",
            "Home appreciation (%/yr)",
            "pct",
            0.005,
            -0.1,
            0.3,
            "How fast you expect the home's price to rise each year. Default "
            "3.5% ≈ a long-run average.",
        ),
        (
            "inflation_rate",
            "Inflation (%/yr)",
            "pct",
            0.005,
            0.0,
            0.2,
            "General inflation; nudges up HOA dues over time.",
        ),
        (
            "market_return",
            "Market return (equity, %/yr)",
            "pct",
            0.005,
            0.0,
            0.3,
            "What your money could earn if you invested it instead — the return "
            "you give up by tying cash up in a home. Default 7%, about what a "
            "typical stock-and-bond mix has returned.",
        ),
        (
            "discount_rate",
            "Discount rate (%/yr)",
            "pct",
            0.005,
            0.0,
            0.3,
            "How much future dollars are marked down when we compare them with "
            "money today (a dollar next year is worth a little less than a dollar "
            "now). Default 4.3% — a safe long-term interest rate from the 30-year "
            "swap curve. It's a single rate, not the whole curve.",
        ),
    ],
    "Taxes": [
        (
            "marginal_income_tax_rate",
            "Marginal income tax (%)",
            "pct",
            0.01,
            0.0,
            0.6,
            "Your top combined federal + state income tax rate — used to value "
            "the deductions from owning.",
        ),
        (
            "salt_headroom",
            "SALT headroom for property tax ($)",
            "dollar",
            500,
            0,
            None,
            "How much of the $10k state-and-local-tax deduction cap is left for "
            "property tax (0 if your income/sales taxes already use it up).",
        ),
        (
            "mortgage_deduction_principal_cap",
            "Mortgage deduction principal cap ($)",
            "dollar",
            50_000,
            0,
            None,
            "Mortgage interest is only deductible on the first $750k you borrow.",
        ),
        (
            "other_itemized_deductions",
            "Other itemized deductions ($)",
            "dollar",
            1_000,
            0,
            None,
            "Charitable, etc. Raises itemized total.",
        ),
        (
            "standard_deduction",
            "Standard deduction ($)",
            "dollar",
            500,
            0,
            None,
            "The flat deduction everyone can take. Only deductions above this "
            "amount actually save you extra tax (shown for a married couple).",
        ),
        (
            "cap_gains_tax_rate",
            "Capital gains tax (%)",
            "pct",
            0.005,
            0.0,
            0.5,
            "Tax rate on profits from investments and from selling the home.",
        ),
        (
            "home_sale_exclusion",
            "Home sale gain exclusion ($)",
            "dollar",
            50_000,
            0,
            None,
            "Profit on your main home that's tax-free when you sell — $500k for "
            "a married couple, $250k single.",
        ),
    ],
    "Sale / exit": [
        (
            "selling_cost_pct",
            "Selling costs (% of price)",
            "pct",
            0.005,
            0.0,
            0.15,
            "Realtor + transfer taxes at sale (~5-6%).",
        ),
    ],
    "Horizon": [
        (
            "holding_period_years",
            "Holding period (years)",
            "int",
            1,
            2,
            100,
            "How long you hold before selling. Minimum 2 years — the primary-"
            "residence capital-gains exclusion requires living in the home at "
            "least 2 of the last 5 years, and gains held under a year are taxed "
            "as ordinary income.",
        ),
    ],
    "Rent counterfactual": [
        (
            "monthly_rent",
            "Monthly rent ($)",
            "dollar",
            100,
            0,
            None,
            "All-in monthly cost of renting the equivalent home — include "
            "renter's insurance, deposits, broker fees, and moving costs, since "
            "the model treats this as the renter's total housing outlay.",
        ),
        (
            "rent_growth_rate",
            "Rent growth (%/yr)",
            "pct",
            0.005,
            -0.05,
            0.3,
            "How fast rent rises each year — set separately from home prices.",
        ),
    ],
}
