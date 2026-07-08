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

    if kind == "choice":
        # `step` holds the option list: a tuple of (value, display label) pairs.
        options = [v for v, _ in step]
        labels = dict(step)
        kwargs = dict(
            options=options,
            format_func=lambda v: labels[v],
            help=help_txt,
            key=key,
        )
        if not seeded:
            kwargs["index"] = options.index(default)
        return st.selectbox(label, **kwargs)

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


def _seed_from_query_params() -> None:
    """On first render, seed widget session_state from URL query params so a
    shared/bookmarked scenario link reproduces its parameters. Only fills keys
    not already set, so it never fights a user's live edits."""
    qp = st.query_params
    if not qp:
        return
    for specs in PARAM_GROUPS.values():
        for attr, _label, kind, step, *_rest in specs:
            key = f"param_{attr}"
            if attr not in qp or key in st.session_state:
                continue
            if kind == "choice":
                valid = {v for v, _ in step}
                if qp[attr] in valid:
                    st.session_state[key] = qp[attr]
                continue
            try:
                raw = float(qp[attr])
            except (TypeError, ValueError):
                continue
            if kind == "pct":
                st.session_state[key] = raw * 100.0  # widgets store % display value
            elif kind == "int":
                st.session_state[key] = int(raw)
            else:
                st.session_state[key] = raw


def _sync_query_params(params: Params) -> None:
    """Write the current parameters into the URL so the scenario is shareable."""

    def _fmt(v):
        return f"{v:.10g}" if isinstance(v, (int, float)) else str(v)

    st.query_params.from_dict(
        {
            attr: _fmt(getattr(params, attr))
            for specs in PARAM_GROUPS.values()
            for attr, *_ in specs
        }
    )


def render_sidebar() -> Params:
    """Draw the full parameter form in the sidebar and return the Params."""
    defaults = Params()
    _seed_from_query_params()
    with st.sidebar:
        st.header("Parameters")
        st.caption(
            "All inputs are editable. Defaults are illustrative "
            "(≈ a Cook County condo)."
        )
        col_reset, col_pin = st.columns(2)
        if col_reset.button("↺ Reset", width="stretch", help="Restore all defaults"):
            for group in PARAM_GROUPS.values():
                for attr, *_ in group:
                    st.session_state.pop(f"param_{attr}", None)
            st.query_params.clear()
            st.rerun()
        pin_clicked = col_pin.button(
            "📌 Pin as A",
            width="stretch",
            help="Pin the current scenario to compare against in the Compare tab.",
        )

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

    params = Params(**values)
    _sync_query_params(params)
    if pin_clicked:
        st.session_state["pinned_params"] = params
    return params
