"""
dashboard.py
-------------
Interactive Streamlit SSL dashboard.
Run with:  streamlit run dashboard.py

Reads the two latest CSVs from downloads/ and reprocesses them live,
so it always reflects the most recent data without needing to open Excel.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Allow imports from same folder
sys.path.insert(0, str(Path(__file__).parent))

# Bridge Streamlit secrets → env vars so config.py picks them up.
# Works for both Streamlit Cloud (st.secrets) and local .env (dotenv).
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass
for _key in ("SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN", "SF_DOMAIN"):
    if _key in st.secrets and not os.getenv(_key):
        os.environ[_key] = st.secrets[_key]

import config
import data_processor

# ──────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SSL Dashboard | Drops",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────
# THEME / CSS
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

/* ── FILTER BAR ──────────────────────────────────────── */
.filter-bar {
    background: rgba(201,168,76,0.12);
    border: 1px solid #C9A84C;
    border-radius: 8px;
    padding: 8px 16px;
    margin-bottom: 16px;
    font-size: 13px;
    color: #C9A84C;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
}
.filter-bar strong { color: #C9A84C; margin-right: 4px; }
.filter-pill {
    background: #C9A84C;
    color: #0f1f17 !important;
    font-weight: 700;
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 12px;
    white-space: nowrap;
}

/* ── COMPARE CTA BANNER ──────────────────────────────── */
.compare-cta {
    background: linear-gradient(90deg, #e8f0ec, #f0f8f0);
    border: 2px solid #C9A84C;
    border-radius: 12px;
    padding: 18px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    margin: 4px 0 16px;
}
.compare-cta-icon { font-size: 32px; line-height: 1; }
.compare-cta-text h3 { color: #1a3a2a; margin:0 0 4px; font-size:16px; }
.compare-cta-text p  { color: #555; margin:0; font-size:13px; }
@media (prefers-color-scheme: dark) {
    .compare-cta { background: linear-gradient(90deg, #0f1f17, #1a3a2a); }
    .compare-cta-text h3 { color: #C9A84C; }
    .compare-cta-text p  { color: #FAF6EF; }
}
[data-theme="dark"] .compare-cta { background: linear-gradient(90deg, #0f1f17, #1a3a2a); }
[data-theme="dark"] .compare-cta-text h3 { color: #C9A84C; }
[data-theme="dark"] .compare-cta-text p  { color: #FAF6EF; }
[data-theme="light"] .compare-cta { background: linear-gradient(90deg, #e8f0ec, #f0f8f0); }
[data-theme="light"] .compare-cta-text h3 { color: #1a3a2a; }
[data-theme="light"] .compare-cta-text p  { color: #555; }

/* section headers — gold works on both light and dark backgrounds */
.section-title {
    color: #C9A84C;
    font-weight: 700;
    font-size: 15px;
    border-left: 4px solid #C9A84C;
    padding-left: 10px;
    margin: 18px 0 10px;
}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────
# DATA LOADING
# ──────────────────────────────────────────────────────────────────────
def _ssl_bq_timestamp() -> str:
    """Uncached — called on every page load to detect new data pushes."""
    try:
        import bigquery_client as bq
        return bq.get_last_updated(bq.TABLE_SSL) or "no-bq"
    except Exception:
        return "no-bq"


@st.cache_data(ttl=3600)
def _get_months_meta(cache_key: str) -> list[str]:
    """Cheap one-column query — returns all distinct Month values for date-picker
    bounds. Avoids loading 1.5 M rows just to know the min/max date."""
    try:
        import bigquery_client as bq
        if bq.table_exists(bq.TABLE_SSL):
            return bq.get_distinct_months(bq.TABLE_SSL)
    except Exception:
        pass
    # Fallback: scan local CSV (fast — only Month column)
    cache_path = config.DOWNLOADS_DIR / "raw_merged.csv"
    if cache_path.exists():
        df = pd.read_csv(cache_path, usecols=["Month"], dtype=str)
        return sorted(df["Month"].dropna().unique().tolist())
    return []


@st.cache_data(show_spinner="Loading data…")
def load_data(from_month: str, to_month: str, cache_key: str):
    """Load only the selected date range — avoids pulling 1.5 M rows every load."""
    try:
        import bigquery_client as bq
        if bq.table_exists(bq.TABLE_SSL):
            df = bq.read_table_range(bq.TABLE_SSL, from_month, to_month)
            for col in ("PO_Qty", "Rec_Qty", "SSL_QTY", "PO_Value", "Rec_Value", "SSL_VALUE"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["Month_dt"] = pd.to_datetime(df["Month"].astype(str) + "-01", errors="coerce")
            return df, None
    except Exception as e:
        import traceback
        return None, f"{e}\n\n{traceback.format_exc()}"

    # Fallback: local CSV filtered to requested range
    cache_path = config.DOWNLOADS_DIR / "raw_merged.csv"
    if cache_path.exists():
        df = pd.read_csv(cache_path, dtype=str, low_memory=False)
        for col in ("PO_Qty", "Rec_Qty", "SSL_QTY", "PO_Value", "Rec_Value", "SSL_VALUE"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["Month_dt"] = pd.to_datetime(df["Month"].astype(str) + "-01", errors="coerce")
        df = df[(df["Month"] >= from_month) & (df["Month"] <= to_month)]
        return df, None
    return None, "No data found. Run main.py to populate the database."


_bq_ts     = _ssl_bq_timestamp()
_all_months = _get_months_meta(_bq_ts)   # ~10 rows, very fast

if not _all_months:
    st.error("No data found. Run `python main.py` to populate the database.")
    st.stop()

_min_date    = pd.to_datetime(_all_months[0] + "-01").date()
_max_date    = (pd.to_datetime(_all_months[-1] + "-01") + pd.offsets.MonthEnd(0)).date()
_default_from = max(
    _min_date,
    (pd.Timestamp(_max_date) - pd.DateOffset(months=5)).replace(day=1).date(),
)

# ──────────────────────────────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────────────────────────────
# ── Sidebar part 1: date pickers — shown before data loads ────────────
with st.sidebar:
    st.markdown("## 🔍 Filters")
    _sc1, _sc2 = st.columns(2)
    with _sc1:
        date_from = st.date_input("From", value=_default_from,
                                  min_value=_min_date, max_value=_max_date)
    with _sc2:
        date_to = st.date_input("To", value=_max_date,
                                min_value=_min_date, max_value=_max_date)
    st.markdown("---")

# Load only the selected date range (cached per range + BQ timestamp)
_from_month = date_from.strftime("%Y-%m")
_to_month   = date_to.strftime("%Y-%m")
df_full, load_error = load_data(_from_month, _to_month, _bq_ts)

# ── Header (shown after date picker so refresh timestamp is live) ──────
_refresh_html = f"Last refreshed: <strong>{_bq_ts}</strong>" if _bq_ts != "no-bq" else "Refresh time unavailable"
st.markdown(f"""
<div class="ssl-header">
  <h1>📦 Supplier Service Level (SSL) Dashboard</h1>
  <p>Drops Group · Demand Planning · {_refresh_html}</p>
</div>
""", unsafe_allow_html=True)

if load_error:
    st.error(load_error)
    st.info("Run `python main.py` from the project folder to fetch and process data first.")
    st.stop()

# ── Sidebar part 2: dimension filters — needs loaded data ──────────────
with st.sidebar:
    all_vendors = sorted(df_full["Vendor"].dropna().unique())
    selected_vendors = st.multiselect("Vendor", all_vendors, placeholder="All vendors")
    all_brands = sorted(df_full["Brand"].dropna().unique())
    selected_brands = st.multiselect("Brand", all_brands, placeholder="All brands")
    all_cats = sorted(df_full["Category"].dropna().unique())
    selected_cats = st.multiselect("Category", all_cats, placeholder="All categories")
    st.markdown("---")
    ssl_threshold = st.slider("⚠️ Flag SSL below (%)", 0, 100, 80)


# ──────────────────────────────────────────────────────────────────────
# APPLY FILTERS
# ──────────────────────────────────────────────────────────────────────
df = df_full.copy()

# Date range
df = df[
    (df["Month_dt"].dt.date >= date_from) &
    (df["Month_dt"].dt.date <= date_to)
]
if selected_vendors: df = df[df["Vendor"].isin(selected_vendors)]
if selected_brands:  df = df[df["Brand"].isin(selected_brands)]
if selected_cats:    df = df[df["Category"].isin(selected_cats)]

# ──────────────────────────────────────────────────────────────────────
# ACTIVE FILTER BAR — shown below header only when filters are active
# ──────────────────────────────────────────────────────────────────────
active_filters = []
if selected_vendors:
    pills = " ".join(f'<span class="filter-pill">{v}</span>' for v in selected_vendors)
    active_filters.append(f"<strong>Vendor:</strong> {pills}")
if selected_brands:
    pills = " ".join(f'<span class="filter-pill">{b}</span>' for b in selected_brands)
    active_filters.append(f"<strong>Brand:</strong> {pills}")
if selected_cats:
    pills = " ".join(f'<span class="filter-pill">{c}</span>' for c in selected_cats)
    active_filters.append(f"<strong>Category:</strong> {pills}")

if active_filters:
    st.markdown(
        f'<div class="filter-bar">🔍 Filtered by &nbsp; {"&nbsp;&nbsp;|&nbsp;&nbsp;".join(active_filters)}</div>',
        unsafe_allow_html=True,
    )

# Global search — filters by Vendor, Brand, or Item No.
item_search = st.text_input(
    "🔎 Search Vendor / Brand / Item No.",
    placeholder="Type to search e.g. KW005004 or vendor name",
    label_visibility="collapsed",
)
if item_search:
    q = item_search.strip().upper()
    df = df[
        df["Vendor"].str.upper().str.contains(q, na=False) |
        df["Brand"].str.upper().str.contains(q, na=False) |
        df["Item_No"].str.upper().str.contains(q, na=False)
    ]

# ──────────────────────────────────────────────────────────────────────
# SUMMARY TABLE (matches your screenshot layout exactly)
# Vendor | Category | Brand | date range | PO Value | Received Value | SSL
# ──────────────────────────────────────────────────────────────────────
date_label = f"{date_from.strftime('%#m/%#d/%Y')}  →  {date_to.strftime('%#m/%#d/%Y')}"

summary = (
    df.groupby(["Vendor", "Category", "Brand"], dropna=False)
    .agg(
        PO_Value=("PO_Value", "sum"),
        Rec_Value=("Rec_Value", "sum"),
        PO_Qty=("PO_Qty", "sum"),
        Rec_Qty=("Rec_Qty", "sum"),
    )
    .reset_index()
)
import numpy as np
summary["SSL_VALUE"] = np.where(
    summary["PO_Value"] > 0,
    (summary["Rec_Value"] / summary["PO_Value"] * 100).round(1),
    np.nan,
)
summary["SSL_QTY"] = np.where(
    summary["PO_Qty"] > 0,
    (summary["Rec_Qty"] / summary["PO_Qty"] * 100).round(1),
    np.nan,
)

# ──────────────────────────────────────────────────────────────────────
# KPI CARDS
# ──────────────────────────────────────────────────────────────────────
total_po_val  = summary["PO_Value"].sum()
total_rec_val = summary["Rec_Value"].sum()
overall_ssl_v = (total_rec_val / total_po_val * 100) if total_po_val else 0

below_threshold = (summary["SSL_VALUE"] < ssl_threshold).sum()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Overall SSL (Value)", f"{overall_ssl_v:.1f}%",
          delta="▲ On track" if overall_ssl_v >= ssl_threshold else "▼ Below target",
          delta_color="normal" if overall_ssl_v >= ssl_threshold else "inverse")
k2.metric("PO Value",  f"{total_po_val:,.0f} KD")
k3.metric("Received",  f"{total_rec_val:,.0f} KD")
k4.metric(f"⚠️ Below {ssl_threshold}%", str(int(below_threshold)),
          delta="vendors/brands", delta_color="off")

st.markdown("---")

# ──────────────────────────────────────────────────────────────────────
# MAIN TABLE — mirrors your screenshot
# ──────────────────────────────────────────────────────────────────────
st.markdown(f'<div class="section-title">Vendor / Brand SSL Summary &nbsp;·&nbsp; {date_label}</div>',
            unsafe_allow_html=True)

display = summary.rename(columns={
    "PO_Value":  "PO Value (KD)",
    "Rec_Value": "Received Value (KD)",
    "SSL_VALUE": "SSL % (Value)",
}).sort_values("SSL % (Value)", ascending=True)[["Vendor", "Category", "Brand", "PO Value (KD)", "Received Value (KD)", "SSL % (Value)"]]

def color_ssl(val):
    if pd.isna(val): return ""
    if val < ssl_threshold:      return "background-color:#ffd7d7; color:#cc0000; font-weight:700"
    elif val < 95:               return "background-color:#fff3cd; color:#856404; font-weight:700"
    else:                        return "background-color:#d4edda; color:#155724; font-weight:700"

styled = (
    display.style
    .map(color_ssl, subset=["SSL % (Value)"])
    .format({
        "PO Value (KD)":       "{:,.2f}",
        "Received Value (KD)": "{:,.2f}",
        "SSL % (Value)":       lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
    })
)
st.dataframe(styled, width="stretch", height=400)

# ──────────────────────────────────────────────────────────────────────
# CHARTS ROW
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")

_CHART_CFG = {
    "scrollZoom": False,
    "modeBarButtonsToRemove": [
        "zoom2d", "pan2d", "select2d", "lasso2d",
        "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d",
    ],
}

# Chart 1 — SSL by Vendor (full width)
st.markdown('<div class="section-title">SSL % by Vendor (Value)</div>', unsafe_allow_html=True)
vendor_ssl = (
    df.groupby("Vendor", dropna=False)
    .agg(PO_Value=("PO_Value","sum"), Rec_Value=("Rec_Value","sum"))
    .reset_index()
)
vendor_ssl["SSL"] = np.where(vendor_ssl["PO_Value"] > 0, (vendor_ssl["Rec_Value"] / vendor_ssl["PO_Value"] * 100).round(1), np.nan)
vendor_ssl = vendor_ssl.sort_values("SSL")
fig1 = px.bar(
    vendor_ssl, x="SSL", y="Vendor", orientation="h",
    color="SSL",
    color_continuous_scale=["#F8696B","#FFEB84","#63BE7B"],
    range_color=[0,100],
    text=vendor_ssl["SSL"].apply(lambda x: f"{x:.1f}%"),
)
fig1.add_vline(x=ssl_threshold, line_dash="dash", line_color="#C9A84C",
               annotation_text=f"Target {ssl_threshold}%")
fig1.update_layout(
    plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
    font_color="#FAF6EF", coloraxis_showscale=False,
    margin=dict(l=0,r=20,t=10,b=10), height=420,
    yaxis_title="", xaxis_title="SSL %", dragmode=False,
)
fig1.update_traces(textposition="inside", insidetextanchor="middle", textfont_color="#FAF6EF")
st.plotly_chart(fig1, width="stretch", config=_CHART_CFG)

# ──────────────────────────────────────────────────────────────────────
# SECOND CHARTS ROW
# ──────────────────────────────────────────────────────────────────────
c3, c4 = st.columns(2)

# Chart 3 — SSL by Brand
with c3:
    st.markdown('<div class="section-title">SSL % by Brand (Value)</div>', unsafe_allow_html=True)
    brand_ssl = (
        df.groupby("Brand", dropna=False)
        .agg(PO_Value=("PO_Value","sum"), Rec_Value=("Rec_Value","sum"))
        .reset_index()
    )
    brand_ssl["SSL"] = np.where(brand_ssl["PO_Value"] > 0, (brand_ssl["Rec_Value"] / brand_ssl["PO_Value"] * 100).round(1), np.nan)
    brand_ssl = brand_ssl.sort_values("SSL").head(20)
    fig3 = px.bar(
        brand_ssl, x="SSL", y="Brand", orientation="h",
        color="SSL",
        color_continuous_scale=["#F8696B","#FFEB84","#63BE7B"],
        range_color=[0,100],
        text=brand_ssl["SSL"].apply(lambda x: f"{x:.1f}%"),
    )
    fig3.add_vline(x=ssl_threshold, line_dash="dash", line_color="#C9A84C",
                   annotation_text=f"Target {ssl_threshold}%")
    fig3.update_layout(
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF", coloraxis_showscale=False,
        margin=dict(l=0,r=20,t=10,b=10), height=400,
        yaxis_title="", xaxis_title="SSL %", dragmode=False,
    )
    fig3.update_traces(textposition="inside", insidetextanchor="middle", textfont_color="#FAF6EF")
    st.plotly_chart(fig3, width="stretch", config=_CHART_CFG)

# Chart 4 — PO Value vs Received Value by Category (grouped bar)
with c4:
    st.markdown('<div class="section-title">PO vs Received by Category (KD)</div>', unsafe_allow_html=True)
    cat_data = (
        df.groupby("Category", dropna=False)
        .agg(PO_Value=("PO_Value","sum"), Rec_Value=("Rec_Value","sum"))
        .reset_index()
        .sort_values("PO_Value", ascending=False)
    )
    fig4 = go.Figure()
    fig4.add_trace(go.Bar(name="PO Value", x=cat_data["Category"], y=cat_data["PO_Value"],
                          marker_color="#1a3a2a", marker_line_color="#C9A84C", marker_line_width=1,
                          text=cat_data["PO_Value"].apply(lambda x: f"{x:,.0f}"),
                          textposition="inside", insidetextanchor="middle",
                          textfont=dict(color="#FAF6EF")))
    fig4.add_trace(go.Bar(name="Received", x=cat_data["Category"], y=cat_data["Rec_Value"],
                          marker_color="#C9A84C",
                          text=cat_data["Rec_Value"].apply(lambda x: f"{x:,.0f}"),
                          textposition="inside", insidetextanchor="middle",
                          textfont=dict(color="#0f1f17")))
    fig4.update_layout(
        barmode="group",
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF", legend=dict(orientation="h", y=1.05),
        margin=dict(l=0,r=20,t=30,b=10), height=400,
        yaxis_title="Value (KD)", xaxis_title="", dragmode=False,
    )
    st.plotly_chart(fig4, width="stretch", config=_CHART_CFG)

# ──────────────────────────────────────────────────────────────────────
# COMPARE CTA — links to dedicated comparison page
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div class="compare-cta">
  <div class="compare-cta-icon">📊</div>
  <div class="compare-cta-text">
    <h3>Year-over-Year Comparison</h3>
    <p>Pick any years, filter by vendor / brand / category, explore SSL trends, PO &amp; Received charts, and export to Excel.</p>
  </div>
</div>
""", unsafe_allow_html=True)
st.page_link("pages/02_Comparison.py", label="Open Comparison Page", icon="📊")

# ── MoM chart data (reused below) ──
mom = (
    df.groupby("Month", dropna=False)
    .agg(PO_Value=("PO_Value","sum"), Rec_Value=("Rec_Value","sum"))
    .reset_index().sort_values("Month")
)
mom["SSL_Val"] = np.where(mom["PO_Value"] > 0, (mom["Rec_Value"] / mom["PO_Value"] * 100).round(1), np.nan)

# Bar chart — PO vs Received by month (side by side)
fig_mom = go.Figure()
fig_mom.add_trace(go.Bar(
    x=mom["Month"], y=mom["PO_Value"], name="PO Value",
    marker_color="#1a3a2a", marker_line_color="#4a7a5a", marker_line_width=1,
    text=mom["PO_Value"].map(lambda x: f"{x/1000:.0f}K"),
    textposition="outside", textfont=dict(color="#FAF6EF", size=10),
))
fig_mom.add_trace(go.Bar(
    x=mom["Month"], y=mom["Rec_Value"], name="Received",
    marker_color="#C9A84C",
    text=mom["Rec_Value"].map(lambda x: f"{x/1000:.0f}K"),
    textposition="outside", textfont=dict(color="#C9A84C", size=10),
))
fig_mom.add_trace(go.Scatter(
    x=mom["Month"], y=mom["SSL_Val"], name="SSL %",
    mode="lines+markers+text",
    line=dict(color="#FAF6EF", width=2), marker=dict(size=8),
    text=mom["SSL_Val"].map(lambda x: f"{x:.1f}%" if pd.notna(x) else ""),
    textposition="top center", textfont=dict(color="#FAF6EF", size=11),
    yaxis="y2",
))
fig_mom.update_layout(
    barmode="group",
    plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
    font_color="#FAF6EF",
    legend=dict(orientation="h", y=1.08),
    margin=dict(l=0, r=60, t=40, b=10), height=360,
    xaxis_title="",
    yaxis=dict(title="Value (KD)", showgrid=False),
    yaxis2=dict(title="SSL %", overlaying="y", side="right", range=[0,115], showgrid=False, ticksuffix="%"),
    dragmode=False,
)
st.plotly_chart(fig_mom, width="stretch", config=_CHART_CFG)

# ──────────────────────────────────────────────────────────────────────
# DRILL-DOWN — Raw item level
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-title">🔎 Item-Level Drill Down</div>', unsafe_allow_html=True)

drill_vendor = st.selectbox("Select Vendor to drill down", ["(All)"] + sorted(df["Vendor"].dropna().unique().tolist()))
drill_df = df if drill_vendor == "(All)" else df[df["Vendor"] == drill_vendor]

drill_summary = (
    drill_df.groupby(["Item_No","Vendor","Brand","Category","Month"], dropna=False)
    .agg(PO_Value=("PO_Value","sum"), Rec_Value=("Rec_Value","sum"))
    .reset_index()
)
drill_summary["SSL % (Value)"] = (drill_summary["Rec_Value"] / drill_summary["PO_Value"] * 100).round(1).where(drill_summary["PO_Value"] > 0)
drill_summary = drill_summary.rename(columns={"PO_Value": "PO Value (KD)", "Rec_Value": "Received (KD)"})
drill_sorted = drill_summary.sort_values("SSL % (Value)", ascending=True)

_DRILL_LIMIT = 5000
if len(drill_sorted) > _DRILL_LIMIT:
    st.caption(f"Showing {_DRILL_LIMIT:,} worst-performing rows of {len(drill_sorted):,} total. Select a specific vendor to see all rows.")
    drill_sorted = drill_sorted.head(_DRILL_LIMIT)

st.dataframe(
    drill_sorted.style
        .map(color_ssl, subset=["SSL % (Value)"])
        .format({"PO Value (KD)": "{:,.2f}", "Received (KD)": "{:,.2f}",
                 "SSL % (Value)": lambda x: f"{x:.1f}%" if pd.notna(x) else "—"}),
    width="stretch", height=350
)

# ──────────────────────────────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"Data from: `downloads/po_latest.csv` & `downloads/warehouse_latest.csv`  ·  Filtered: {len(df):,} rows  ·  Drops Group Demand Planning")