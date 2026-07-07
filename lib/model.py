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
    property_tax_rate: float = (
        0.021  # effective, % of home value / yr (Cook County ~2%)
    )
    hoa_monthly: float = 400.0  # grows with inflation
    insurance_rate: float = 0.005  # % of home value / yr
    maintenance_rate: float = (
        0.010  # % of home value / yr (~1%; often forgotten, large)
    )
    pmi_rate: float = 0.006  # % of ORIGINAL loan / yr, while LTV > 80% of orig price

    # ---- Growth / macro ----
    home_appreciation_rate: float = 0.035  # nominal home price growth / yr
    inflation_rate: float = 0.025  # grows HOA
    market_return: float = (
        0.040  # opportunity cost of capital = discount rate (pre-tax)
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
    balance = loan0
    recs = []
    for m in range(1, months + 1):
        year = (m - 1) // 12  # 0-based year index for HOA inflation
        hv = p.house_price * (1 + p.home_appreciation_rate) ** (
            m / 12.0
        )  # end-of-month value

        interest_m = balance * r_m
        principal_m = min(pmt - interest_m, balance)
        pay_m = interest_m + principal_m
        balance -= principal_m

        prop_tax_m = p.property_tax_rate * hv / 12.0
        ins_m = p.insurance_rate * hv / 12.0
        maint_m = p.maintenance_rate * hv / 12.0
        hoa_m = p.hoa_monthly * (1 + p.inflation_rate) ** year
        pmi_m = (p.pmi_rate * loan0 / 12.0) if (balance / p.house_price) > 0.80 else 0.0

        recs.append(
            dict(
                month=m,
                year=year + 1,
                home_value=hv,
                balance=balance,
                interest=interest_m,
                principal=principal_m,
                pi=pay_m,
                prop_tax=prop_tax_m,
                insurance=ins_m,
                maintenance=maint_m,
                hoa=hoa_m,
                pmi=pmi_m,
            )
        )

    mdf = pd.DataFrame(recs)

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
    # Monthly rent path — tracks the home's value (a stable rent yield) rather
    # than a separate, slower escalator. Over long horizons this keeps rent and
    # ownership cost linked, so a paid-off home stays cheap *relative to rent*
    # instead of the two diverging unboundedly.
    mdf["rent"] = p.monthly_rent * (1 + p.home_appreciation_rate) ** (
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

    # ---- (A) NPV cost of ownership (discount at market_return) ----
    annual_out = mdf.groupby("year")["owner_cost"].sum()
    npv = down + closing
    for y, out in annual_out.items():
        npv += out / (1 + p.market_return) ** y
    npv -= net_proceeds / (1 + p.market_return) ** T
    crf = (
        (p.market_return * (1 + p.market_return) ** T)
        / ((1 + p.market_return) ** T - 1)
        if p.market_return > 0
        else 1.0 / T
    )
    eac = npv * crf  # equivalent annual cost

    # ---- (B) Rent-vs-buy terminal wealth (symmetric, cap-gains-taxed) ----
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
        eac_pct_price=res["eac"] / p.house_price,
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
    """Smallest whole-year holding period where buying wins, else None."""
    for h in range(1, p.loan_term_years + 1):
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
        "market_return": ("market_return", p.market_return, 0.01),
        "property_tax_rate": ("property_tax_rate", p.property_tax_rate, 0.005),
        "maintenance_rate": ("maintenance_rate", p.maintenance_rate, 0.005),
        "hoa_monthly": ("hoa_monthly", p.hoa_monthly, 200),
        "holding_period_years": ("holding_period_years", p.holding_period_years, 2),
    }
    rows = []
    for name, (attr, val, d) in shocks.items():
        lo = simulate(replace(p, **{attr: type(val)(val - d)}))["npv_cost"]
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
            0,
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
            "20% or more avoids PMI.",
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
            "Annual nominal mortgage APR.",
        ),
        (
            "loan_term_years",
            "Loan term (years)",
            "int",
            1,
            1,
            40,
            "Amortization term, e.g. 15 or 30.",
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
            "Effective annual property tax rate.",
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
            "Charged while LTV > 80% of original price.",
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
            "Nominal annual home price growth.",
        ),
        (
            "inflation_rate",
            "Inflation (%/yr)",
            "pct",
            0.005,
            0.0,
            0.2,
            "Escalates HOA.",
        ),
        (
            "market_return",
            "Market return / discount rate (%/yr)",
            "pct",
            0.005,
            0.0,
            0.3,
            "Opportunity cost of capital (pre-tax).",
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
            "Fed+state marginal rate for itemized deductions.",
        ),
        (
            "salt_headroom",
            "SALT headroom for property tax ($)",
            "dollar",
            500,
            0,
            None,
            "$ of SALT cap left for property tax (0 if income tax exhausts it).",
        ),
        (
            "mortgage_deduction_principal_cap",
            "Mortgage deduction principal cap ($)",
            "dollar",
            50_000,
            0,
            None,
            "Interest deductible only on first $750k of debt.",
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
            "Only deductions above this have value (MFJ).",
        ),
        (
            "cap_gains_tax_rate",
            "Capital gains tax (%)",
            "pct",
            0.005,
            0.0,
            0.5,
            "LTCG + NIIT on investments & home sale.",
        ),
        (
            "home_sale_exclusion",
            "Home sale gain exclusion ($)",
            "dollar",
            50_000,
            0,
            None,
            "Primary-residence gain exclusion ($500k MFJ).",
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
            1,
            100,
            "How long you hold before selling.",
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
            "Rent for the equivalent home you would otherwise rent.",
        ),
    ],
}
