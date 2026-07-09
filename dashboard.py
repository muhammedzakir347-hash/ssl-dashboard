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
/* dark sidebar */
[data-testid="stSidebar"] { background-color: #0f1f17; }
[data-testid="stSidebar"] * { color: #FAF6EF !important; }

/* metric cards */
div[data-testid="metric-container"] {
    background: #1a3a2a;
    border: 1px solid #C9A84C;
    border-radius: 10px;
    padding: 16px 20px;
}
div[data-testid="metric-container"] label { color: #C9A84C !important; font-size:13px; }
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: #FAF6EF !important; font-size:28px; font-weight:700;
}
div[data-testid="metric-container"] div[data-testid="stMetricDelta"] {
    color: #FAF6EF !important; font-size:13px;
}

/* header bar — always dark regardless of theme */
.ssl-header {
    background: linear-gradient(90deg,#0f1f17,#1a3a2a);
    border-bottom: 2px solid #C9A84C;
    padding: 18px 28px 14px;
    border-radius: 10px;
    margin-bottom: 10px;
}
.ssl-header h1 { color:#FAF6EF; margin:0; font-size:26px; }
.ssl-header p  { color:#C9A84C; margin:4px 0 0; font-size:13px; }

/* active filter pills shown below header */
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
@st.cache_data(show_spinner="Loading data…", ttl=43200)  # cache 12 hours
def load_data():
    cache_path = config.DOWNLOADS_DIR / "raw_merged.csv"
    po_path    = config.DOWNLOADS_DIR / "po_latest.csv"
    wh_path    = config.DOWNLOADS_DIR / "warehouse_latest.csv"

    try:
        if cache_path.exists():
            # Fast path: read pre-processed CSV written by the scheduled task.
            df = pd.read_csv(cache_path, dtype=str, low_memory=False)
            for col in ("PO_Qty", "Rec_Qty", "SSL_QTY", "PO_Value", "Rec_Value", "SSL_VALUE"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        elif po_path.exists() and wh_path.exists():
            # Medium path: raw CSVs exist, re-run pipeline.
            sheets = data_processor.run_pipeline(po_path, wh_path)
            df = sheets["Raw_Merged_Data"].copy()

        elif config.SF_USERNAME and config.SF_PASSWORD:
            # Cloud path: no local files — fetch directly from Salesforce.
            # First load takes ~4 minutes; then cached for 4 hours.
            import salesforce_fetcher
            with st.spinner("Connecting to Salesforce and fetching data (first load ~4 min)…"):
                frames = salesforce_fetcher.fetch_dataframes()
            sheets = data_processor.run_pipeline_from_dfs(frames["po"], frames["warehouse"])
            df = sheets["Raw_Merged_Data"].copy()

        else:
            return None, "No data found and no Salesforce credentials configured."

        df["Month_dt"] = pd.to_datetime(df["Month"].astype(str) + "-01", errors="coerce")
        return df, None
    except Exception as e:
        import traceback
        return None, f"{e}\n\n{traceback.format_exc()}"


df_full, load_error = load_data()

# ──────────────────────────────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="ssl-header">
  <h1>📦 Supplier Service Level (SSL) Dashboard</h1>
  <p>Drops Group · Demand Planning · Auto-refreshes with each new daily run</p>
</div>
""", unsafe_allow_html=True)

if load_error:
    st.error(load_error)
    st.info("Run `python main.py` from the project folder to fetch and process data first.")
    st.stop()

# ──────────────────────────────────────────────────────────────────────
# SIDEBAR FILTERS
# ──────────────────────────────────────────────────────────────────────
# (active filter bar is rendered AFTER sidebar so it can read selections)
with st.sidebar:
    st.markdown("## 🔍 Filters")

    # Date range — replicate the "6/1/2026 → 6/30/2026" picker from your screenshot
    min_date = df_full["Month_dt"].min().date()
    max_date = (df_full["Month_dt"].max() + pd.offsets.MonthEnd(0)).date()

    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From", value=min_date, min_value=min_date, max_value=max_date)
    with col2:
        date_to = st.date_input("To", value=max_date, min_value=min_date, max_value=max_date)

    st.markdown("---")

    # Vendor filter
    all_vendors = sorted(df_full["Vendor"].dropna().unique())
    selected_vendors = st.multiselect("Vendor", all_vendors, placeholder="All vendors")

    # Brand filter
    all_brands = sorted(df_full["Brand"].dropna().unique())
    selected_brands = st.multiselect("Brand", all_brands, placeholder="All brands")

    # Category filter
    all_cats = sorted(df_full["Category"].dropna().unique())
    selected_cats = st.multiselect("Category", all_cats, placeholder="All categories")

    st.markdown("---")
    # SSL threshold highlight
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

total_po_qty  = summary["PO_Qty"].sum()
total_rec_qty = summary["Rec_Qty"].sum()
overall_ssl_q = (total_rec_qty / total_po_qty * 100) if total_po_qty else 0

below_threshold = (summary["SSL_VALUE"] < ssl_threshold).sum()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Overall SSL (Value)", f"{overall_ssl_v:.1f}%",
          delta="▲ On track" if overall_ssl_v >= ssl_threshold else "▼ Below target",
          delta_color="normal" if overall_ssl_v >= ssl_threshold else "inverse")
k2.metric("Overall SSL (Qty)",   f"{overall_ssl_q:.1f}%")
k3.metric("PO Value",  f"{total_po_val:,.0f} KD")
k4.metric("Received",  f"{total_rec_val:,.0f} KD")
k5.metric(f"⚠️ Below {ssl_threshold}%", str(int(below_threshold)),
          delta="vendors/brands" , delta_color="off")

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
    "SSL_QTY":   "SSL % (Qty)",
    "PO_Qty":    "PO Qty",
    "Rec_Qty":   "Received Qty",
}).sort_values("SSL % (Value)", ascending=True)

def color_ssl(val):
    if pd.isna(val): return ""
    if val < ssl_threshold:      return "background-color:#ffd7d7; color:#cc0000; font-weight:700"
    elif val < 95:               return "background-color:#fff3cd; color:#856404; font-weight:700"
    else:                        return "background-color:#d4edda; color:#155724; font-weight:700"

styled = (
    display.style
    .map(color_ssl, subset=["SSL % (Value)", "SSL % (Qty)"])
    .format({
        "PO Value (KD)":       "{:,.2f}",
        "Received Value (KD)": "{:,.2f}",
        "PO Qty":              "{:,.0f}",
        "Received Qty":        "{:,.0f}",
        "SSL % (Value)":       lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
        "SSL % (Qty)":         lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
    })
)
st.dataframe(styled, use_container_width=True, height=400)

# ──────────────────────────────────────────────────────────────────────
# CHARTS ROW
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
c1, c2 = st.columns(2)

# Chart 1 — SSL by Vendor (bar)
with c1:
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
        margin=dict(l=0,r=20,t=10,b=10), height=350,
        yaxis_title="", xaxis_title="SSL %",
    )
    fig1.update_traces(textposition="outside")
    st.plotly_chart(fig1, use_container_width=True)

# Chart 2 — Monthly SSL trend (line)
with c2:
    st.markdown('<div class="section-title">Monthly SSL Trend (Value)</div>', unsafe_allow_html=True)
    monthly = (
        df.groupby("Month", dropna=False)
        .agg(PO_Value=("PO_Value","sum"), Rec_Value=("Rec_Value","sum"))
        .reset_index()
        .sort_values("Month")
    )
    monthly["SSL"] = np.where(monthly["PO_Value"] > 0, (monthly["Rec_Value"] / monthly["PO_Value"] * 100).round(1), np.nan)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=monthly["Month"], y=monthly["SSL"],
        mode="lines+markers+text",
        line=dict(color="#C9A84C", width=3),
        marker=dict(size=8, color="#C9A84C"),
        text=monthly["SSL"].apply(lambda x: f"{x:.1f}%"),
        textposition="top center",
        textfont=dict(color="#FAF6EF"),
        name="SSL %",
    ))
    fig2.add_hline(y=ssl_threshold, line_dash="dash", line_color="#F8696B",
                   annotation_text=f"Target {ssl_threshold}%", annotation_font_color="#F8696B")
    fig2.update_layout(
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF", showlegend=False,
        margin=dict(l=0,r=20,t=10,b=10), height=350,
        yaxis=dict(title="SSL %", range=[0,110]),
        xaxis_title="",
    )
    st.plotly_chart(fig2, use_container_width=True)

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
    brand_ssl = brand_ssl.sort_values("SSL").head(20)  # top 20 worst
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
        yaxis_title="", xaxis_title="SSL %",
    )
    fig3.update_traces(textposition="outside")
    st.plotly_chart(fig3, use_container_width=True)

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
                          marker_color="#1a3a2a", marker_line_color="#C9A84C", marker_line_width=1))
    fig4.add_trace(go.Bar(name="Received", x=cat_data["Category"], y=cat_data["Rec_Value"],
                          marker_color="#C9A84C"))
    fig4.update_layout(
        barmode="group",
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF", legend=dict(orientation="h", y=1.05),
        margin=dict(l=0,r=20,t=30,b=10), height=400,
        yaxis_title="Value (KD)", xaxis_title="",
    )
    st.plotly_chart(fig4, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────
# DRILL-DOWN — Raw item level
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-title">🔎 Item-Level Drill Down</div>', unsafe_allow_html=True)

drill_vendor = st.selectbox("Select Vendor to drill down", ["(All)"] + sorted(df["Vendor"].dropna().unique().tolist()))
drill_df = df if drill_vendor == "(All)" else df[df["Vendor"] == drill_vendor]

drill_summary = (
    drill_df.groupby(["Item_No","Vendor","Brand","Category","Month"], dropna=False)
    .agg(PO_Qty=("PO_Qty","sum"), Rec_Qty=("Rec_Qty","sum"),
         PO_Value=("PO_Value","sum"), Rec_Value=("Rec_Value","sum"))
    .reset_index()
)
drill_summary["SSL_VALUE"] = (drill_summary["Rec_Value"] / drill_summary["PO_Value"] * 100).round(1).where(drill_summary["PO_Value"] > 0)
st.dataframe(
    drill_summary.sort_values("SSL_VALUE", ascending=True),
    use_container_width=True, height=350
)

# ──────────────────────────────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"Data from: `downloads/po_latest.csv` & `downloads/warehouse_latest.csv`  ·  Filtered: {len(df):,} rows  ·  Drops Group Demand Planning")