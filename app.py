"""Should I buy a home? — Streamlit front end for the rent-vs-buy / TCO model.

Run with:  uv run streamlit run app.py

The heavy computations (the full sensitivity sweep, tornado, and break-even
solves) are cached on the parameter set so re-runs on widget changes stay snappy.
"""

from __future__ import annotations

from dataclasses import astuple

import streamlit as st

from lib import model
from lib.model import Params
from ui import charts, inputs, results

st.set_page_config(page_title="Should I buy a home?", page_icon="🏠", layout="wide")

# --- Cached compute boundary (keyed on the full Params tuple) ---------------
_HASH = {Params: astuple}


@st.cache_data(hash_funcs=_HASH, show_spinner=False)
def run(p: Params) -> dict:
    return model.simulate(p)


@st.cache_data(hash_funcs=_HASH, show_spinner=False)
def grid(p: Params):
    return model.sensitivity_grid(p)


@st.cache_data(hash_funcs=_HASH, show_spinner=False)
def breakeven_pair(p: Params):
    return model.breakeven_appreciation(p), model.breakeven_hold(p)


def main() -> None:
    p = inputs.render_sidebar()
    res = run(p)
    s = model.summarize(res)
    base = model.summarize(run(Params()))  # cached default-scenario baseline

    st.title("🏠 Should I buy a home?")
    st.caption(
        "Compares buying a home with renting the same place and investing the "
        "difference — weighing the investment growth you give up on your down "
        "payment, the boost (and risk) a mortgage's leverage adds, the tax breaks "
        "of owning, and the taxes you pay when you sell. Adjust the numbers in the "
        "sidebar; everything updates live."
    )

    results.methodology()
    st.markdown("")
    results.verdict_banner(s)
    st.markdown("")
    results.kpi_row(s, base=base)
    st.divider()

    tab_overview, tab_breakdown, tab_sensitivity, tab_compare = st.tabs(
        ["Overview", "Cost breakdown", "Sensitivity & break-evens", "Compare (A/B)"]
    )

    with tab_overview:
        left, right = st.columns([3, 2])
        with left:
            st.plotly_chart(charts.cost_vs_equity(res), width="stretch")
        with right:
            st.plotly_chart(charts.sale_bridge(s), width="stretch")
            results.sale_table(s)
            results.networth_compare(s)

    with tab_breakdown:
        st.plotly_chart(charts.annual_cost_breakdown(res), width="stretch")
        st.markdown("**Annual cost detail**")
        results.annual_cost_table(res)
        st.download_button(
            "⬇ Download annual detail (CSV)",
            data=model.annual_table(res).to_csv().encode("utf-8"),
            file_name="home_ownership_annual_detail.csv",
            mime="text/csv",
        )

    with tab_compare:
        pinned = st.session_state.get("pinned_params")
        if pinned is None:
            st.info(
                "No scenario pinned yet. Set your inputs, then click "
                "**📌 Pin as A** in the sidebar. Change the inputs and this tab "
                "will show the current scenario (B) against the pinned one (A)."
            )
        else:
            pin_s = model.summarize(run(pinned))
            results.scenario_compare(p, pinned, s, pin_s)

    with tab_sensitivity:
        ba, bh = breakeven_pair(p)
        results.breakevens(p, ba=ba, bh=bh)
        st.markdown("")
        st.plotly_chart(charts.sensitivity_heatmap(p, grid=grid(p)), width="stretch")
        st.plotly_chart(charts.tornado(p), width="stretch")

    st.divider()
    st.caption(
        "The starting numbers are just an example, not financial advice. Buying is "
        "a leveraged bet and money in a home is hard to get at — the single answer "
        "on screen understates both risks; see “How this simulation works” for why. "
        "Future dollars are marked down to today's value using the discount rate "
        "(default ≈ 4.3%, a safe long-term rate from the 30-year swap curve — one "
        "rate, not the full curve), while invested money grows at the 7% market "
        "return. Insurance and upkeep rise with the home's value; property tax "
        "follows the option you pick; HOA and rent rise at their own rates; the tax "
        "break follows the standard IRS deduction rules and limits."
    )


if __name__ == "__main__":
    main()
