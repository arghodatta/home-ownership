"""Business-logic invariants for the rent-vs-buy / TCO engine.

These lock in the properties the UI relies on: a self-consistent amortization
schedule, the sale-bridge identity, monotonic responses to the headline
drivers, break-even self-consistency, and graceful handling of edge inputs.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from lib import model
from lib.model import Params


@pytest.fixture
def p() -> Params:
    return Params()


# --------------------------------------------------------------------------
# Amortization
# --------------------------------------------------------------------------
def test_principal_sums_to_paydown_over_horizon(p):
    """Principal paid over the horizon equals the drop in loan balance."""
    res = model.simulate(p)
    m = res["monthly"]
    paid = m["principal"].sum()
    assert paid == pytest.approx(res["loan0"] - res["rem_bal"], rel=1e-9)


def test_loan_fully_amortizes_at_term(p):
    """Holding to the full loan term drives the balance to ~0."""
    full = replace(p, holding_period_years=p.loan_term_years)
    res = model.simulate(full)
    assert res["rem_bal"] == pytest.approx(0.0, abs=1e-3)


def test_balance_never_goes_negative(p):
    res = model.simulate(replace(p, holding_period_years=p.loan_term_years))
    assert (res["monthly"]["balance"] >= -1e-6).all()


def test_zero_rate_uses_straight_line_payment(p):
    """With a 0% rate the payment is just principal / n_payments."""
    z = replace(p, mortgage_rate=0.0)
    res = model.simulate(z)
    expected_pmt = res["loan0"] / (z.loan_term_years * 12)
    assert res["pmt"] == pytest.approx(expected_pmt, rel=1e-12)


# --------------------------------------------------------------------------
# PMI
# --------------------------------------------------------------------------
def test_pmi_charged_below_20pct_equity_and_stops_after(p):
    """PMI is on while balance > 80% of original price, off once it isn't."""
    low_down = replace(p, down_payment_pct=0.05, holding_period_years=p.loan_term_years)
    m = model.simulate(low_down)["monthly"]
    charged = m[m["pmi"] > 0]
    uncharged = m[m["pmi"] == 0]
    assert not charged.empty  # a 5%-down loan starts with PMI
    assert (charged["balance"] / low_down.house_price > 0.80).all()
    if not uncharged.empty:
        assert (uncharged["balance"] / low_down.house_price <= 0.80).all()


def test_no_pmi_with_20pct_down(p):
    """20% down means LTV starts at 80%, so PMI never triggers."""
    m = model.simulate(replace(p, down_payment_pct=0.20))["monthly"]
    assert (m["pmi"] == 0).all()


# --------------------------------------------------------------------------
# Property tax basis
# --------------------------------------------------------------------------
def test_property_tax_purchase_basis_is_constant(p):
    """On the 'purchase' basis the assessed value is frozen at the price."""
    m = model.simulate(replace(p, property_tax_basis="purchase"))["monthly"]
    monthly_tax = p.property_tax_rate * p.house_price / 12.0
    assert np.allclose(m["prop_tax"], monthly_tax)


def test_property_tax_capped_grows_at_reassessment_cap(p):
    """'capped' grows off the purchase price at max(2%, inflation)/yr, and the
    first year is assessed at the purchase price."""
    q = replace(p, property_tax_basis="capped", inflation_rate=0.01)
    m = model.simulate(q)["monthly"]
    yr1_assessed = m[m["year"] == 1]["prop_tax"].sum() / q.property_tax_rate
    yr2_assessed = m[m["year"] == 2]["prop_tax"].sum() / q.property_tax_rate
    assert yr1_assessed == pytest.approx(q.house_price)
    # inflation is 1% < 2%, so the cap (2%) binds.
    assert yr2_assessed == pytest.approx(q.house_price * 1.02)


def test_property_tax_ptell_grows_at_min_5pct_inflation(p):
    """IL PTELL grows the assessed value off the purchase price at min(5%, CPI)."""
    for infl, exp_growth in [(0.07, 0.05), (0.01, 0.01)]:
        q = replace(p, property_tax_basis="ptell", inflation_rate=infl)
        m = model.simulate(q)["monthly"]
        yr1 = m[m["year"] == 1]["prop_tax"].sum() / q.property_tax_rate
        yr2 = m[m["year"] == 2]["prop_tax"].sum() / q.property_tax_rate
        assert yr1 == pytest.approx(q.house_price)
        assert yr2 == pytest.approx(q.house_price * (1 + exp_growth))


def test_property_tax_basis_ordering_when_home_outgrows_cap(p):
    """With appreciation above the cap: purchase < capped < market total tax."""
    kw = dict(home_appreciation_rate=0.05, inflation_rate=0.02)
    tax = lambda b: model.simulate(replace(p, property_tax_basis=b, **kw))["monthly"][
        "prop_tax"
    ].sum()
    assert tax("purchase") < tax("capped") < tax("market")


# --------------------------------------------------------------------------
# Rent path
# --------------------------------------------------------------------------
def test_rent_escalates_with_rent_growth_only(p):
    """Rent grows at rent_growth_rate and is independent of appreciation."""
    flat = model.simulate(replace(p, rent_growth_rate=0.0))["monthly"]["rent"]
    assert np.allclose(flat, p.monthly_rent)  # 0% growth => level rent
    lo = model.simulate(replace(p, home_appreciation_rate=0.01))["monthly"][
        "rent"
    ].sum()
    hi = model.simulate(replace(p, home_appreciation_rate=0.09))["monthly"][
        "rent"
    ].sum()
    assert lo == pytest.approx(hi)  # appreciation must not move rent


# --------------------------------------------------------------------------
# Sale bridge
# --------------------------------------------------------------------------
def test_net_proceeds_identity(p):
    """Net proceeds = sale price − selling costs − payoff − home cap-gains tax."""
    res = model.simulate(p)
    expected = (
        res["sale_price"] - res["sell_costs"] - res["rem_bal"] - res["home_cg_tax"]
    )
    assert res["net_proceeds"] == pytest.approx(expected, rel=1e-12)


def test_home_cap_gains_respects_exclusion(p):
    """No home cap-gains tax while the gain fits under the exclusion."""
    # Modest appreciation over a short hold keeps the gain small.
    small = replace(p, home_appreciation_rate=0.01, holding_period_years=3)
    res = model.simulate(small)
    gain = res["sale_price"] - small.house_price
    assert gain < small.home_sale_exclusion
    assert res["home_cg_tax"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Discount rate vs equity return (separated)
# --------------------------------------------------------------------------
def test_npv_cost_uses_discount_rate_not_market_return(p):
    """The NPV cost of owning depends on the discount rate, not the equity return."""
    base = model.simulate(p)["npv_cost"]
    # Changing the equity/portfolio return must not move the cost NPV...
    same = model.simulate(replace(p, market_return=p.market_return + 0.03))["npv_cost"]
    assert same == pytest.approx(base)
    # ...but changing the discount rate must.
    moved = model.simulate(replace(p, discount_rate=p.discount_rate + 0.02))["npv_cost"]
    assert moved != pytest.approx(base)


def test_buy_vs_rent_uses_market_return_not_discount_rate(p):
    """Terminal buy-vs-rent wealth depends on the equity return, not the discount rate."""
    base = model.simulate(p)["buy_minus_rent"]
    same = model.simulate(replace(p, discount_rate=p.discount_rate + 0.02))[
        "buy_minus_rent"
    ]
    assert same == pytest.approx(base)
    moved = model.simulate(replace(p, market_return=p.market_return + 0.03))[
        "buy_minus_rent"
    ]
    assert moved != pytest.approx(base)


# --------------------------------------------------------------------------
# Monotonicity of the headline verdict
# --------------------------------------------------------------------------
def test_buy_minus_rent_increases_with_appreciation(p):
    vals = [
        model.simulate(replace(p, home_appreciation_rate=a))["buy_minus_rent"]
        for a in (0.00, 0.03, 0.06, 0.09)
    ]
    assert vals == sorted(vals)


def test_buy_minus_rent_increases_with_rent(p):
    """Higher rent makes buying relatively more attractive."""
    lo = model.simulate(replace(p, monthly_rent=3_000))["buy_minus_rent"]
    hi = model.simulate(replace(p, monthly_rent=6_000))["buy_minus_rent"]
    assert hi > lo


# --------------------------------------------------------------------------
# Break-evens
# --------------------------------------------------------------------------
def test_breakeven_appreciation_is_a_root(p):
    a = model.breakeven_appreciation(p)
    assert a is not None
    at_root = model.simulate(replace(p, home_appreciation_rate=a))["buy_minus_rent"]
    assert at_root == pytest.approx(0.0, abs=1.0)


def test_breakeven_hold_is_first_winning_year(p):
    h = model.breakeven_hold(p)
    if h is None:
        # Buying never wins within the loan term (search starts at the 2y minimum).
        for y in range(2, p.loan_term_years + 1):
            assert (
                model.simulate(replace(p, holding_period_years=y))["buy_minus_rent"]
                <= 0
            )
    else:
        assert h >= 2
        assert model.simulate(replace(p, holding_period_years=h))["buy_minus_rent"] > 0
        if h > 2:
            prev = model.simulate(replace(p, holding_period_years=h - 1))
            assert prev["buy_minus_rent"] <= 0


# --------------------------------------------------------------------------
# Aggregations used by the UI
# --------------------------------------------------------------------------
def test_summarize_exposes_expected_keys(p):
    s = model.summarize(model.simulate(p))
    expected = {
        "yr1_monthly_cost",
        "avg_monthly_cost",
        "npv_cost",
        "eac",
        "eac_pct_price",
        "sale_price",
        "sell_costs",
        "rem_bal",
        "home_cg_tax",
        "net_proceeds",
        "buyer_nw",
        "renter_nw",
        "buy_minus_rent",
        "buying_wins",
        "down",
        "closing",
        "loan0",
        "pmt",
    }
    assert expected <= set(s)
    assert s["buying_wins"] == (s["buy_minus_rent"] > 0)


def test_annual_table_equity_is_value_minus_balance(p):
    g = model.annual_table(model.simulate(p))
    assert np.allclose(g["equity"], g["home_value"] - g["end_balance"])


def test_sensitivity_grid_shape_and_orientation(p):
    appr, hold, Z = model.sensitivity_grid(p)
    assert Z.shape == (len(appr), len(hold))
    # Along a fixed holding period, more appreciation never hurts the buyer.
    for j in range(Z.shape[1]):
        col = Z[:, j]
        assert np.all(np.diff(col) >= -1e-6)


def test_tornado_sorted_by_range_and_covers_shocks(p):
    t = model.tornado(p)
    assert list(t["range"]) == sorted(t["range"])
    assert (t["range"] >= 0).all()
    assert len(t) == 7


# --------------------------------------------------------------------------
# Edge inputs — must never raise for anything the UI can produce
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kw",
    [
        {"house_price": 0},  # degenerate, but must not crash
        {"down_payment_pct": 1.0},  # all cash, no loan
        {"down_payment_pct": 0.0},  # fully financed
        {"mortgage_rate": 0.0},  # zero-rate branch
        {"market_return": 0.0},  # zero equity-return branch
        {"discount_rate": 0.0},  # zero-discount branch (CRF fallback)
        {"holding_period_years": 100},  # far beyond the loan term
        {"home_appreciation_rate": -0.10},
        {"property_tax_basis": "purchase"},
        {"property_tax_basis": "capped"},
        {"property_tax_basis": "ptell"},
        {"rent_growth_rate": -0.02},
    ],
)
def test_edge_inputs_do_not_raise(p, kw):
    s = model.summarize(model.simulate(replace(p, **kw)))
    assert np.isfinite(s["buy_minus_rent"])
    assert np.isfinite(s["npv_cost"])
