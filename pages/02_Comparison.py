"""
pages/02_Comparison.py
----------------------
Dedicated Year-over-Year comparison page for the SSL Dashboard.

Features:
  • Multi-year selector (pick any years available in BigQuery)
  • Vendor / Brand / Category filters
  • Combined monthly comparison table (PO, Rec, SSL% per year + growth)
  • SSL % trend line chart (one line per year)
  • PO vs Received grouped bar chart (one group per year)
  • Excel export
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

for _key in ("SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN", "SF_DOMAIN"):
    try:
        if _key in st.secrets and not os.getenv(_key):
            os.environ[_key] = st.secrets[_key]
    except Exception:
        pass

pd.set_option("styler.render.max_elements", 5_000_000)

import bigquery_client as bq
import config

# ──────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Comparison | SSL Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────
# THEME / CSS (mirrors main dashboard, same adaptive light/dark system)
# ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── SIDEBAR ─────────────────────────────────────────── */
[data-testid="stSidebar"] { background-color: #e8f0ec; }
[data-testid="stSidebar"] * { color: #1a3a2a !important; }
@media (prefers-color-scheme: dark) {
    [data-testid="stSidebar"] { background-color: #0f1f17; }
    [data-testid="stSidebar"] * { color: #FAF6EF !important; }
}
[data-theme="dark"] [data-testid="stSidebar"] { background-color: #0f1f17 !important; }
[data-theme="dark"] [data-testid="stSidebar"] * { color: #FAF6EF !important; }
[data-theme="light"] [data-testid="stSidebar"] { background-color: #e8f0ec !important; }
[data-theme="light"] [data-testid="stSidebar"] * { color: #1a3a2a !important; }

/* ── METRIC CARDS ────────────────────────────────────── */
div[data-testid="metric-container"] {
    background: rgba(201,168,76,0.10);
    border: 1px solid #C9A84C;
    border-radius: 10px;
    padding: 16px 20px;
}
div[data-testid="metric-container"] label { color: #856404 !important; font-size:13px; }
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: #1a3a2a !important; font-size:28px; font-weight:700;
}
div[data-testid="metric-container"] div[data-testid="stMetricDelta"] {
    color: #555 !important; font-size:13px;
}
@media (prefers-color-scheme: dark) {
    div[data-testid="metric-container"] { background: #1a3a2a; }
    div[data-testid="metric-container"] label { color: #C9A84C !important; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #FAF6EF !important; }
    div[data-testid="metric-container"] div[data-testid="stMetricDelta"] { color: #FAF6EF !important; }
}
[data-theme="dark"] div[data-testid="metric-container"] { background: #1a3a2a; }
[data-theme="dark"] div[data-testid="metric-container"] label { color: #C9A84C !important; }
[data-theme="dark"] div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #FAF6EF !important; }
[data-theme="dark"] div[data-testid="metric-container"] div[data-testid="stMetricDelta"] { color: #FAF6EF !important; }

/* ── HEADER ──────────────────────────────────────────── */
.ssl-header {
    background: linear-gradient(90deg, #e8f0ec, #f0f8f0);
    border-bottom: 2px solid #C9A84C;
    padding: 18px 28px 14px;
    border-radius: 10px;
    margin-bottom: 10px;
}
.ssl-header h1 { color: #1a3a2a; margin:0; font-size:26px; }
.ssl-header p  { color: #555;    margin:4px 0 0; font-size:13px; }
.ssl-header strong { color: #C9A84C; }
@media (prefers-color-scheme: dark) {
    .ssl-header { background: linear-gradient(90deg, #0f1f17, #1a3a2a); }
    .ssl-header h1 { color: #FAF6EF; }
    .ssl-header p  { color: #C9A84C; }
}
[data-theme="dark"] .ssl-header { background: linear-gradient(90deg, #0f1f17, #1a3a2a); }
[data-theme="dark"] .ssl-header h1 { color: #FAF6EF; }
[data-theme="dark"] .ssl-header p  { color: #C9A84C; }
[data-theme="light"] .ssl-header { background: linear-gradient(90deg, #e8f0ec, #f0f8f0); }
[data-theme="light"] .ssl-header h1 { color: #1a3a2a; }
[data-theme="light"] .ssl-header p  { color: #555; }

/* ── FILTER PILLS ────────────────────────────────────── */
.filter-bar {
    background: rgba(201,168,76,0.12);
    border: 1px solid #C9A84C;
    border-radius: 8px;
    padding: 8px 16px;
    margin-bottom: 16px;
    font-size: 13px;
    color: #C9A84C;
    display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
}
.filter-pill {
    background: #C9A84C; color: #0f1f17 !important;
    font-weight:700; border-radius:20px;
    padding:2px 10px; font-size:12px; white-space:nowrap;
}

/* ── SECTION TITLE ───────────────────────────────────── */
.section-title {
    color: #C9A84C; font-weight:700; font-size:15px;
    border-left:4px solid #C9A84C; padding-left:10px;
    margin:18px 0 10px;
}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────
# DATA LOADING
# ──────────────────────────────────────────────────────────────────────
def _bq_ts() -> str:
    try:
        return bq.get_last_updated(bq.TABLE_SSL) or "no-bq"
    except Exception:
        return "no-bq"


@st.cache_data(show_spinner="Loading SSL data…")
def _load_ssl(cache_key: str):
    try:
        if bq.table_exists(bq.TABLE_SSL):
            df = bq.read_table(bq.TABLE_SSL)
            for col in ("PO_Qty", "Rec_Qty", "SSL_QTY", "PO_Value", "Rec_Value", "SSL_VALUE"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df["Month_dt"] = pd.to_datetime(df["Month"].astype(str) + "-01", errors="coerce")
            return df, None
    except Exception as e:
        return None, str(e)
    return None, "No BigQuery data available. Run main.py first."


_ts = _bq_ts()
df_full, _err = _load_ssl(_ts)

# ──────────────────────────────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────────────────────────────
_refresh = f"Last refreshed: <strong>{_ts}</strong>" if _ts != "no-bq" else "Refresh time unavailable"
st.markdown(f"""
<div class="ssl-header">
  <h1>📊 Year-over-Year Comparison</h1>
  <p>Drops Group · Demand Planning · {_refresh}</p>
</div>
""", unsafe_allow_html=True)

if _err:
    st.error(_err)
    st.stop()

# ──────────────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────────────
_all_years_str = sorted(df_full["Month"].str[:4].unique(), reverse=True)
_all_years_int = [int(y) for y in _all_years_str]

with st.sidebar:
    st.markdown("## 📅 Year Selector")
    _default_years = _all_years_int[:2] if len(_all_years_int) >= 2 else _all_years_int
    selected_years = st.multiselect(
        "Compare years",
        options=_all_years_int,
        default=_default_years,
        help="Select 2–4 years to compare side by side",
    )

    st.markdown("---")
    st.markdown("## 🔍 Filters")

    all_vendors = sorted(df_full["Vendor"].dropna().unique())
    sel_vendors = st.multiselect("Vendor", all_vendors, placeholder="All vendors")

    all_brands = sorted(df_full["Brand"].dropna().unique())
    sel_brands = st.multiselect("Brand", all_brands, placeholder="All brands")

    all_cats = sorted(df_full["Category"].dropna().unique())
    sel_cats = st.multiselect("Category", all_cats, placeholder="All categories")

if not selected_years:
    st.info("Select at least one year from the sidebar to get started.")
    st.stop()

# ──────────────────────────────────────────────────────────────────────
# APPLY FILTERS
# ──────────────────────────────────────────────────────────────────────
df = df_full[df_full["Month"].str[:4].astype(int).isin(selected_years)].copy()
if sel_vendors: df = df[df["Vendor"].isin(sel_vendors)]
if sel_brands:  df = df[df["Brand"].isin(sel_brands)]
if sel_cats:    df = df[df["Category"].isin(sel_cats)]

# Active filter pills
_active = []
if sel_vendors:
    _pills = " ".join(f'<span class="filter-pill">{v}</span>' for v in sel_vendors)
    _active.append(f"<strong>Vendor:</strong> {_pills}")
if sel_brands:
    _pills = " ".join(f'<span class="filter-pill">{b}</span>' for b in sel_brands)
    _active.append(f"<strong>Brand:</strong> {_pills}")
if sel_cats:
    _pills = " ".join(f'<span class="filter-pill">{c}</span>' for c in sel_cats)
    _active.append(f"<strong>Category:</strong> {_pills}")
if _active:
    st.markdown(
        f'<div class="filter-bar">🔍 &nbsp; {"&nbsp;&nbsp;|&nbsp;&nbsp;".join(_active)}</div>',
        unsafe_allow_html=True,
    )

# ──────────────────────────────────────────────────────────────────────
# AGGREGATE BY YEAR × MONTH
# ──────────────────────────────────────────────────────────────────────
df["_yr"] = df["Month"].str[:4].astype(int)
df["_mn"] = df["Month"].str[5:7].astype(int)

ya = (
    df.groupby(["_yr", "_mn"], as_index=False)
    .agg(PO=("PO_Value", "sum"), Rec=("Rec_Value", "sum"))
)

_sorted_years = sorted(selected_years)
_MN = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# ──────────────────────────────────────────────────────────────────────
# SUMMARY CARDS — one per selected year
# ──────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Year Summary</div>', unsafe_allow_html=True)
_card_cols = st.columns(len(_sorted_years))
for i, yr in enumerate(_sorted_years):
    _d = ya[ya["_yr"] == yr]
    _po = _d["PO"].sum(); _rec = _d["Rec"].sum()
    _ssl = _rec / _po * 100 if _po else 0
    _delta = f"PO {_po/1e3:,.0f}K · Rec {_rec/1e3:,.0f}K KD"
    _card_cols[i].metric(str(yr), f"{_ssl:.1f}%", delta=_delta, delta_color="off")

st.markdown("---")

# ──────────────────────────────────────────────────────────────────────
# BUILD PIVOT TABLES
# ──────────────────────────────────────────────────────────────────────
_pp = ya.pivot_table(index="_mn", columns="_yr", values="PO",  aggfunc="sum")
_rp = ya.pivot_table(index="_mn", columns="_yr", values="Rec", aggfunc="sum")


def _v(piv, mn, yr):
    try:
        val = piv.at[mn, yr]
        return float(val) if pd.notna(val) else np.nan
    except KeyError:
        return np.nan


# Determine "growth" comparison pair (last two selected years)
_show_growth = len(_sorted_years) >= 2
_yp = _sorted_years[-2] if _show_growth else None
_yc = _sorted_years[-1] if _show_growth else None

# ──────────────────────────────────────────────────────────────────────
# MONTHLY COMPARISON TABLE
# ──────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Monthly Comparison Table</div>', unsafe_allow_html=True)

if len(_sorted_years) > 2:
    st.caption(f"Growth columns compare the two most recent selected years: {_yp} → {_yc}")

_rows = []
for mn in range(1, 13):
    row = {"Month": _MN[mn - 1]}

    # PO columns for each year
    for yr in _sorted_years:
        po = _v(_pp, mn, yr)
        row[f"{yr} PO (KD)"] = f"{po:,.0f}" if pd.notna(po) else "—"

    # PO Growth (last two years only)
    if _show_growth:
        po_p = _v(_pp, mn, _yp); po_c = _v(_pp, mn, _yc)
        row["PO Growth"] = (
            f"{(po_c/po_p - 1)*100:+.0f}%"
            if (pd.notna(po_p) and po_p > 0 and pd.notna(po_c)) else "—"
        )

    # Rec columns for each year
    for yr in _sorted_years:
        rec = _v(_rp, mn, yr)
        row[f"{yr} Rec (KD)"] = f"{rec:,.0f}" if pd.notna(rec) else "—"

    # Rec Growth
    if _show_growth:
        rc_p = _v(_rp, mn, _yp); rc_c = _v(_rp, mn, _yc)
        row["Rec Growth"] = (
            f"{(rc_c/rc_p - 1)*100:+.0f}%"
            if (pd.notna(rc_p) and rc_p > 0 and pd.notna(rc_c)) else "—"
        )

    # SSL% columns for each year
    for yr in _sorted_years:
        po = _v(_pp, mn, yr); rec = _v(_rp, mn, yr)
        ssl = rec / po * 100 if (pd.notna(po) and po > 0 and pd.notna(rec)) else np.nan
        row[f"{yr} SSL %"] = f"{ssl:.1f}%" if pd.notna(ssl) else "—"

    # SSL Delta
    if _show_growth:
        po_p = _v(_pp, mn, _yp); po_c = _v(_pp, mn, _yc)
        rc_p = _v(_rp, mn, _yp); rc_c = _v(_rp, mn, _yc)
        ssl_p = rc_p / po_p * 100 if (pd.notna(po_p) and po_p > 0 and pd.notna(rc_p)) else np.nan
        ssl_c = rc_c / po_c * 100 if (pd.notna(po_c) and po_c > 0 and pd.notna(rc_c)) else np.nan
        row["SSL Δ"] = (
            f"{ssl_c - ssl_p:+.1f}pp"
            if (pd.notna(ssl_p) and pd.notna(ssl_c)) else "—"
        )

    _rows.append(row)

# TOTAL row
_tot = {"Month": "TOTAL"}
for yr in _sorted_years:
    _d = ya[ya["_yr"] == yr]
    _po = _d["PO"].sum(); _rec = _d["Rec"].sum()
    _tot[f"{yr} PO (KD)"]  = f"{_po:,.0f}"
    _tot[f"{yr} Rec (KD)"] = f"{_rec:,.0f}"
    _ssl = _rec / _po * 100 if _po else np.nan
    _tot[f"{yr} SSL %"] = f"{_ssl:.1f}%" if pd.notna(_ssl) else "—"

if _show_growth:
    _dp = ya[ya["_yr"] == _yp]; _dc = ya[ya["_yr"] == _yc]
    _po_p = _dp["PO"].sum(); _po_c = _dc["PO"].sum()
    _rc_p = _dp["Rec"].sum(); _rc_c = _dc["Rec"].sum()
    _tot["PO Growth"]  = f"{(_po_c/_po_p - 1)*100:+.0f}%" if _po_p else "—"
    _tot["Rec Growth"] = f"{(_rc_c/_rc_p - 1)*100:+.0f}%" if _rc_p else "—"
    _ssl_p = _rc_p / _po_p * 100 if _po_p else np.nan
    _ssl_c = _rc_c / _po_c * 100 if _po_c else np.nan
    _tot["SSL Δ"] = (
        f"{_ssl_c - _ssl_p:+.1f}pp"
        if (pd.notna(_ssl_p) and pd.notna(_ssl_c)) else "—"
    )

_rows.append(_tot)
_tbl = pd.DataFrame(_rows)


def _style_growth(val):
    s = str(val)
    if s.startswith("+"): return "color:#155724; font-weight:700"
    if s.startswith("-"): return "color:#cc0000; font-weight:700"
    return ""


def _style_ssl(val):
    s = str(val)
    if "%" not in s or "pp" in s:
        return ""
    try:
        n = float(s.replace("%", ""))
    except ValueError:
        return ""
    if n >= 95: return "background-color:#d4edda; color:#155724; font-weight:700"
    if n >= 80: return "background-color:#fff3cd; color:#856404; font-weight:700"
    return "background-color:#ffd7d7; color:#cc0000; font-weight:700"


_ssl_cols    = [c for c in _tbl.columns if "SSL %" in c]
_growth_cols = [c for c in _tbl.columns if c in ("PO Growth", "Rec Growth", "SSL Δ")]

_styled = _tbl.style.map(_style_ssl, subset=_ssl_cols)
if _growth_cols:
    _styled = _styled.map(_style_growth, subset=_growth_cols)

st.dataframe(_styled, use_container_width=True, hide_index=True)

# ──────────────────────────────────────────────────────────────────────
# CHARTS
# ──────────────────────────────────────────────────────────────────────
_COLORS = ["#C9A84C", "#63BE7B", "#6fa8dc", "#E06C75"]
_yc_map = {yr: _COLORS[i % len(_COLORS)] for i, yr in enumerate(_sorted_years)}

_CHART_CFG = {
    "scrollZoom": False,
    "modeBarButtonsToRemove": [
        "zoom2d", "pan2d", "select2d", "lasso2d",
        "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d",
    ],
}

st.markdown("---")

# ── Chart 1: SSL % Trend ──
st.markdown('<div class="section-title">SSL % Trend by Month</div>', unsafe_allow_html=True)
fig_ssl = go.Figure()
for yr in _sorted_years:
    _d = ya[ya["_yr"] == yr].sort_values("_mn")
    _ssl_vals = np.where(
        _d["PO"] > 0,
        (_d["Rec"] / _d["PO"] * 100).round(1),
        np.nan,
    )
    fig_ssl.add_trace(go.Scatter(
        x=[_MN[mn - 1] for mn in _d["_mn"]],
        y=_ssl_vals,
        name=str(yr),
        mode="lines+markers+text",
        line=dict(color=_yc_map[yr], width=2),
        marker=dict(size=8),
        text=[f"{v:.0f}%" if pd.notna(v) else "" for v in _ssl_vals],
        textposition="top center",
        textfont=dict(size=10),
    ))
fig_ssl.add_hline(y=80, line_dash="dot", line_color="#C9A84C",
                  annotation_text="Target 80%", annotation_position="right")
fig_ssl.update_layout(
    plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
    font_color="#FAF6EF",
    legend=dict(orientation="h", y=1.10),
    margin=dict(l=0, r=40, t=50, b=10), height=340,
    yaxis=dict(title="SSL %", ticksuffix="%", range=[0, 115]),
    xaxis_title="",
    dragmode=False,
)
st.plotly_chart(fig_ssl, use_container_width=True, config=_CHART_CFG)

st.markdown("---")

# ── Charts 2 & 3: PO and Received side by side ──
_c1, _c2 = st.columns(2)

with _c1:
    st.markdown('<div class="section-title">PO Value by Month (KD)</div>', unsafe_allow_html=True)
    fig_po = go.Figure()
    for yr in _sorted_years:
        _d = ya[ya["_yr"] == yr].sort_values("_mn")
        fig_po.add_trace(go.Bar(
            x=[_MN[mn - 1] for mn in _d["_mn"]],
            y=_d["PO"],
            name=str(yr),
            marker_color=_yc_map[yr],
        ))
    fig_po.update_layout(
        barmode="group",
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF",
        legend=dict(orientation="h", y=1.10),
        margin=dict(l=0, r=20, t=50, b=10), height=320,
        yaxis_title="Value (KD)", xaxis_title="",
        dragmode=False,
    )
    st.plotly_chart(fig_po, use_container_width=True, config=_CHART_CFG)

with _c2:
    st.markdown('<div class="section-title">Received Value by Month (KD)</div>', unsafe_allow_html=True)
    fig_rec = go.Figure()
    for yr in _sorted_years:
        _d = ya[ya["_yr"] == yr].sort_values("_mn")
        fig_rec.add_trace(go.Bar(
            x=[_MN[mn - 1] for mn in _d["_mn"]],
            y=_d["Rec"],
            name=str(yr),
            marker_color=_yc_map[yr],
        ))
    fig_rec.update_layout(
        barmode="group",
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF",
        legend=dict(orientation="h", y=1.10),
        margin=dict(l=0, r=20, t=50, b=10), height=320,
        yaxis_title="Value (KD)", xaxis_title="",
        dragmode=False,
    )
    st.plotly_chart(fig_rec, use_container_width=True, config=_CHART_CFG)

st.markdown("---")

# ── Chart 4: PO vs SSL% heatmap by vendor (top 15 by PO) ──
st.markdown('<div class="section-title">Vendor SSL % Heatmap (top 15 by PO value)</div>',
            unsafe_allow_html=True)

_heat = (
    df.groupby(["Vendor", "_yr"], as_index=False)
    .agg(PO=("PO_Value", "sum"), Rec=("Rec_Value", "sum"))
)
_heat["SSL"] = np.where(_heat["PO"] > 0, (_heat["Rec"] / _heat["PO"] * 100).round(1), np.nan)
_top_vendors = (
    _heat.groupby("Vendor")["PO"].sum()
    .sort_values(ascending=False)
    .head(15)
    .index.tolist()
)
_heat = _heat[_heat["Vendor"].isin(_top_vendors)]
_heat_piv = _heat.pivot_table(index="Vendor", columns="_yr", values="SSL", aggfunc="mean")
_heat_piv = _heat_piv.reindex(index=_top_vendors)

_z = _heat_piv.values
_x = [str(c) for c in _heat_piv.columns]
_y = _heat_piv.index.tolist()
_text = [[f"{v:.1f}%" if pd.notna(v) else "—" for v in row] for row in _z]

fig_heat = go.Figure(go.Heatmap(
    z=_z, x=_x, y=_y,
    text=_text, texttemplate="%{text}",
    colorscale=[[0, "#cc0000"], [0.4, "#FFEB84"], [0.5, "#FFEB84"], [1, "#63BE7B"]],
    zmin=0, zmax=100,
    showscale=True,
    colorbar=dict(title="SSL %", ticksuffix="%", len=0.8),
))
fig_heat.update_layout(
    plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
    font_color="#FAF6EF",
    margin=dict(l=0, r=20, t=10, b=10), height=400,
    xaxis_title="", yaxis_title="",
    dragmode=False,
)
st.plotly_chart(fig_heat, use_container_width=True, config=_CHART_CFG)

# ──────────────────────────────────────────────────────────────────────
# EXCEL EXPORT
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-title">Export</div>', unsafe_allow_html=True)

_buf = io.BytesIO()
with pd.ExcelWriter(_buf, engine="xlsxwriter") as _writer:
    # Sheet 1: Comparison table
    _tbl.to_excel(_writer, index=False, sheet_name="Monthly Comparison")

    # Sheet 2: Year totals
    _totals_rows = []
    for yr in _sorted_years:
        _d = ya[ya["_yr"] == yr]
        _po = _d["PO"].sum(); _rec = _d["Rec"].sum()
        _totals_rows.append({
            "Year": yr,
            "Total PO (KD)":  round(_po, 0),
            "Total Rec (KD)": round(_rec, 0),
            "SSL % (Value)":  round(_rec / _po * 100, 1) if _po else None,
        })
    pd.DataFrame(_totals_rows).to_excel(_writer, index=False, sheet_name="Year Totals")

    # Sheet 3: Vendor heatmap data
    _heat_piv.reset_index().rename(columns={"Vendor": "Vendor"}).to_excel(
        _writer, index=False, sheet_name="Vendor SSL by Year"
    )

_buf.seek(0)
_year_label = "_".join(str(y) for y in _sorted_years)
st.download_button(
    label="📥 Download Excel Report",
    data=_buf,
    file_name=f"ssl_comparison_{_year_label}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.caption(f"Filtered: {len(df):,} rows · Years: {', '.join(str(y) for y in _sorted_years)} · Drops Group Demand Planning")
