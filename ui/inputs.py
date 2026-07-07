"""Sidebar input form: renders every model parameter as a widget, grouped to
mirror the notebook's parameter sections, and returns a populated ``Params``.

A ZIP code field at the top pulls locale-specific estimates (property tax rate,
market rent) from a trusted public source (U.S. Census ACS) and seeds the
matching widgets. Anything the source can't provide falls back to the user's
own value, and every seeded field remains freely editable.
"""

from __future__ import annotations

import streamlit as st

from lib import estimate
from lib.model import PARAM_GROUPS, Params

# attr -> (kind, lo, hi), used to clamp/convert seeded estimates to widget units.
_SPEC = {
    attr: (kind, lo, hi)
    for specs in PARAM_GROUPS.values()
    for (attr, _label, kind, _step, lo, hi, _help) in specs
}


def _widget(attr, label, kind, step, lo, hi, help_txt, default):
    """Render one parameter widget and return its raw model value."""
    key = f"param_{attr}"
    # When the key is already in session_state (e.g. seeded from a ZIP estimate
    # or a prior interaction) the widget reads that value; passing `value` too
    # would trigger a Streamlit warning, so we only pass it on first render.
    seeded = key in st.session_state

    if kind == "pct":
        kwargs = dict(
            min_value=(None if lo is None else float(lo * 100)),
            max_value=(None if hi is None else float(hi * 100)),
            step=float(step * 100),
            help=help_txt,
            key=key,
            format="%.3f",
        )
        if not seeded:
            kwargs["value"] = float(default * 100)
        return st.number_input(label, **kwargs) / 100.0

    if kind == "int":
        kwargs = dict(
            min_value=(None if lo is None else int(lo)),
            max_value=(None if hi is None else int(hi)),
            step=int(step),
            help=help_txt,
            key=key,
        )
        if not seeded:
            kwargs["value"] = int(default)
        return int(st.number_input(label, **kwargs))

    # dollar / raw float
    kwargs = dict(
        min_value=(None if lo is None else float(lo)),
        max_value=(None if hi is None else float(hi)),
        step=float(step),
        help=help_txt,
        key=key,
    )
    if not seeded:
        kwargs["value"] = float(default)
    return float(st.number_input(label, **kwargs))


@st.cache_data(show_spinner=False)
def _lookup(zip_code: str):
    """Cached ZIP -> ZipEstimate lookup (None when unavailable)."""
    return estimate.fetch_zip_estimate(zip_code)


def _to_widget_value(attr: str, value: float) -> float:
    """Convert a model-unit estimate to the widget's display units, clamped."""
    kind, lo, hi = _SPEC[attr]
    if lo is not None:
        value = max(value, lo)
    if hi is not None:
        value = min(value, hi)
    return value * 100.0 if kind == "pct" else value


def _seed_from_estimate(est) -> None:
    """Seed matching widget values from a fresh estimate, once per ZIP change.

    Only runs when the ZIP has changed since the last seed, so manual edits made
    afterwards are preserved until the user picks a different ZIP.
    """
    if est is None:
        return
    if st.session_state.get("_zip_seeded_for") == est.zip_code:
        return
    params = est.estimated_params()
    if not params:
        return
    for attr, value in params.items():
        st.session_state[f"param_{attr}"] = _to_widget_value(attr, float(value))
    st.session_state["_zip_seeded_for"] = est.zip_code


def _render_estimate_panel(zip_code: str, est) -> None:
    """Tell the user what was estimated and from where (or why nothing was)."""
    if not zip_code:
        st.caption(
            "Enter a 5-digit ZIP to auto-fill local property tax and market rent "
            "from U.S. Census data. Leave blank to use your own values."
        )
        return
    if len(zip_code) != 5 or not zip_code.isdigit():
        st.caption("Enter a valid 5-digit ZIP code.")
        return
    if est is None:
        st.info(
            f"No trusted ZIP-level estimate available for **{zip_code}** — using "
            "your own values below. (Set a free `CENSUS_API_KEY` to enable "
            "estimates.)"
        )
        return

    params = est.estimated_params()
    if not params:
        st.info(
            f"{est.source} has no matching data for **{zip_code}** — using your "
            "own values below."
        )
        return

    lines = [f"**Estimated for {est.zcta_name}**"]
    if "property_tax_rate" in params:
        lines.append(
            f"- Property tax: **{params['property_tax_rate']:.2%}/yr** "
            f"(median ${est.median_taxes:,.0f} tax on ${est.median_home_value:,.0f} value)"
        )
    if "monthly_rent" in params:
        lines.append(f"- Market rent: **${params['monthly_rent']:,.0f}/mo**")
    st.success("\n".join(lines))
    st.caption(f"Source: {est.source}. Seeded fields below — override any freely.")


def render_sidebar() -> Params:
    """Draw the full parameter form in the sidebar and return the Params."""
    defaults = Params()
    with st.sidebar:
        st.header("Parameters")
        st.caption(
            "All inputs are editable. Defaults are illustrative "
            "(≈ a Cook County condo)."
        )
        if st.button("↺ Reset to defaults", width="stretch"):
            for group in PARAM_GROUPS.values():
                for attr, *_ in group:
                    st.session_state.pop(f"param_{attr}", None)
            st.session_state.pop("param_zip_code", None)
            st.session_state.pop("_zip_seeded_for", None)
            st.rerun()

        # --- Locale estimates from ZIP (must run before the numeric widgets) --
        zip_code = st.text_input(
            "ZIP code",
            key="param_zip_code",
            max_chars=5,
            placeholder="e.g. 60601",
            help="Used to estimate local property tax and market rent from "
            "U.S. Census ACS data. Optional.",
        ).strip()
        est = _lookup(zip_code) if (len(zip_code) == 5 and zip_code.isdigit()) else None
        _seed_from_estimate(est)
        _render_estimate_panel(zip_code, est)

        values = {}
        for group_name, specs in PARAM_GROUPS.items():
            with st.expander(group_name, expanded=(group_name == "Purchase")):
                for attr, label, kind, step, lo, hi, help_txt in specs:
                    values[attr] = _widget(
                        attr,
                        label,
                        kind,
                        step,
                        lo,
                        hi,
                        help_txt,
                        getattr(defaults, attr),
                    )

    return Params(**values)
