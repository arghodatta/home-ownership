"""Sidebar input form: renders every model parameter as a widget, grouped to
mirror the notebook's parameter sections, and returns a populated ``Params``.
"""

from __future__ import annotations

import streamlit as st

from lib.model import PARAM_GROUPS, Params


def _widget(attr, label, kind, step, lo, hi, help_txt, default):
    """Render one parameter widget and return its raw model value."""
    key = f"param_{attr}"
    # When the key is already in session_state (e.g. from a prior interaction)
    # the widget reads that value; passing `value` too would trigger a Streamlit
    # warning, so we only pass it on first render.
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
            st.rerun()

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
