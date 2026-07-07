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
        "A rent-vs-buy / total-cost-of-ownership model with opportunity cost, "
        "leverage, tax shields, and symmetric cap-gains treatment. "
        "Adjust the parameters in the sidebar; everything updates live."
    )

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
        "Defaults are illustrative and not financial advice. Property tax, "
        "insurance, and maintenance scale with home value; HOA grows with "
        "inflation; the tax shield uses itemized-vs-standard with the $750k "
        "mortgage-interest and SALT caps."
    )


if __name__ == "__main__":
    main()
