# 🏠 Should I buy a home?

A rent-vs-buy / total-cost-of-ownership (TCO) model with an interactive
[Streamlit](https://streamlit.io) front end. It weighs buying against renting
over a chosen holding period, accounting for opportunity cost, leverage, tax
shields (itemized-vs-standard with the $750k mortgage-interest and SALT caps),
and symmetric capital-gains treatment.

Adjust the parameters in the sidebar and everything — the verdict, cost curves,
break-evens, and sensitivity analysis — updates live.

> Defaults are illustrative and **not financial advice**.

## Run locally

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12+).

```bash
uv run streamlit run app.py
```

The app is served under a friendly local hostname, **<http://home-tco.local:8502>**
(configured via `browser.serverAddress` in `.streamlit/config.toml`). For your
machine to resolve that name, add it to your hosts file once:

```bash
# Linux/macOS (needs sudo):
echo '127.0.0.1 home-tco.local' | sudo tee -a /etc/hosts
# Windows: add the same line to C:\Windows\System32\drivers\etc\hosts (as admin)
```

After that, `uv run streamlit run app.py` prints and opens
<http://home-tco.local:8502>. (Skip the hosts entry and it still works at
<http://localhost:8502>.)

To let others **on the same network** reach it, share your machine's LAN
address instead — e.g. `http://192.168.x.x:8502`. The server binds to all
interfaces by default (see `.streamlit/config.toml`).

## Deploy (public, free)

The easiest always-on option is **[Streamlit Community Cloud](https://share.streamlit.io)**:

1. Push this repo to GitHub (already the case for the canonical repo).
2. Sign in to <https://share.streamlit.io> with your GitHub account.
3. Click **New app**, pick this repo/branch, and set the main file to `app.py`.
4. Deploy. You'll get a permanent `https://<name>.streamlit.app` link to share.

It auto-redeploys on every push to the selected branch. No secrets or
configuration are required.

## Project layout

| Path | What's there |
|---|---|
| `app.py` | Streamlit entry point; wires inputs → model → results/charts. |
| `lib/model.py` | Pure computation engine: `Params`, `simulate`, sensitivity, break-evens. |
| `ui/inputs.py` | Sidebar parameter form. |
| `ui/results.py` | Verdict banner, KPIs, tables. |
| `ui/charts.py` | Plotly chart builders. |
| `ui/theme.py` | Shared palette + Plotly layout. |
| `notebooks/` | Exploratory notebooks (dev only). |

## Development

```bash
uv sync            # install runtime + dev dependencies
uv run pytest      # run tests
uv run black .     # format
uv run isort .     # sort imports
```

Runtime dependencies are kept lean (Streamlit, NumPy, pandas, SciPy, Plotly);
tooling and notebook deps (`black`, `isort`, `matplotlib`, `jupyterlab`, …)
live in the `dev` dependency group.
