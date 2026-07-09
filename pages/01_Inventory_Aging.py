"""
pages/01_Inventory_Aging.py
----------------------------
Inventory Aging dashboard page.
Shows remaining stock categorised into 0-30 / 30-60 / 60-90 / 90-120 / 120+ day buckets
based on the posting date of each Item Ledger Entry.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import data_processor
import salesforce_fetcher

# ─────────────────────────────────────────────────────────
# PAGE CONFIG  (must be first Streamlit command)
# ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Inventory Aging | Drops",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass
for _key in ("SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN"):
    try:
        if _key in st.secrets and not os.getenv(_key):
            os.environ[_key] = st.secrets[_key]
    except Exception:
        pass

# ─────────────────────────────────────────────────────────
# THEME / CSS  (same visual system as main dashboard)
# ─────────────────────────────────────────────────────────
BUCKET_COLORS = {
    "0-30":   "#63BE7B",   # green  — fresh
    "30-60":  "#FFEB84",   # yellow — watch
    "60-90":  "#FFA040",   # orange — concern
    "90-120": "#F8696B",   # red    — critical
    "120+":   "#CC2222",   # dark red — overdue
}

st.markdown("""
<style>
[data-testid="stSidebar"] { background-color: #0f1f17; }
[data-testid="stSidebar"] * { color: #FAF6EF !important; }

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

.ssl-header {
    background: linear-gradient(90deg,#0f1f17,#1a3a2a);
    border-bottom: 2px solid #C9A84C;
    padding: 18px 28px 14px;
    border-radius: 10px;
    margin-bottom: 10px;
}
.ssl-header h1 { color:#FAF6EF; margin:0; font-size:26px; }
.ssl-header p  { color:#C9A84C; margin:4px 0 0; font-size:13px; }

.section-title {
    color: #C9A84C; font-weight:700; font-size:15px;
    border-left:4px solid #C9A84C; padding-left:10px;
    margin: 18px 0 10px;
}

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
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Loading inventory data…", ttl=43200)
def load_inventory():
    cache_path = config.DOWNLOADS_DIR / "inventory_aging.csv"
    raw_path   = config.DOWNLOADS_DIR / "inventory_latest.csv"

    try:
        import bigquery_client

        # 1. BigQuery — fastest, persistent on Cloud
        try:
            if bigquery_client.table_exists(bigquery_client.TABLE_INV):
                df = bigquery_client.read_table(
                    bigquery_client.TABLE_INV,
                    restore_columns=bigquery_client.INV_RESTORE,
                )
                df["Posting Date"] = pd.to_datetime(df["Posting Date"], errors="coerce")
                for col in ("Remaining Qty", "Unit Cost", "Remaining Value", "Days"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df["Aging Bucket"] = pd.Categorical(
                    df["Aging Bucket"], categories=list(BUCKET_COLORS), ordered=True
                )
                return df, None
        except Exception:
            pass  # fall through to CSV / SF

        # 2. Local CSV cache
        if cache_path.exists():
            df = pd.read_csv(cache_path, low_memory=False)
            df["Posting Date"] = pd.to_datetime(df["Posting Date"], errors="coerce")
            for col in ("Remaining Qty", "Unit Cost", "Remaining Value", "Days"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["Aging Bucket"] = pd.Categorical(
                df["Aging Bucket"], categories=list(BUCKET_COLORS), ordered=True
            )
        elif raw_path.exists():
            raw = pd.read_csv(raw_path, low_memory=False)
            df = data_processor.process_inventory_aging(raw)
        elif config.SF_USERNAME and config.SF_PASSWORD:
            with st.spinner("Fetching inventory from Salesforce (first load ~2 min)…"):
                raw = salesforce_fetcher.fetch_inventory()
            df = data_processor.process_inventory_aging(raw)
        else:
            return None, "No inventory data found. Run `python main.py` first."

        return df, None
    except Exception as e:
        import traceback
        return None, f"{e}\n\n{traceback.format_exc()}"

df_full, load_error = load_inventory()

# ─────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────
st.markdown("""
<div class="ssl-header">
  <h1>📦 Inventory Aging</h1>
  <p>Drops Group · Demand Planning · Remaining stock by posting date age</p>
</div>
""", unsafe_allow_html=True)

if load_error:
    st.error(load_error)
    st.stop()

# ─────────────────────────────────────────────────────────
# SIDEBAR FILTERS
# ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔍 Filters")

    all_vendors = sorted(df_full["Vendor"].dropna().unique())
    sel_vendors = st.multiselect("Vendor", all_vendors, placeholder="All vendors")

    all_brands = sorted(df_full["Brand"].dropna().unique())
    sel_brands = st.multiselect("Brand", all_brands, placeholder="All brands")

    all_cats = sorted(df_full["Category"].dropna().unique())
    sel_cats = st.multiselect("Category", all_cats, placeholder="All categories")

    st.markdown("---")
    sel_buckets = st.multiselect(
        "Aging Bucket",
        list(BUCKET_COLORS.keys()),
        default=list(BUCKET_COLORS.keys()),
        placeholder="All buckets",
    )

    st.markdown("---")

# ─────────────────────────────────────────────────────────
# APPLY FILTERS
# ─────────────────────────────────────────────────────────
df = df_full.copy()
if sel_vendors: df = df[df["Vendor"].isin(sel_vendors)]
if sel_brands:  df = df[df["Brand"].isin(sel_brands)]
if sel_cats:    df = df[df["Category"].isin(sel_cats)]
if sel_buckets: df = df[df["Aging Bucket"].isin(sel_buckets)]

# Active filter bar
active = []
if sel_vendors:
    active.append("<strong>Vendor:</strong> " + " ".join(f'<span class="filter-pill">{v}</span>' for v in sel_vendors))
if sel_brands:
    active.append("<strong>Brand:</strong> " + " ".join(f'<span class="filter-pill">{b}</span>' for b in sel_brands))
if sel_cats:
    active.append("<strong>Category:</strong> " + " ".join(f'<span class="filter-pill">{c}</span>' for c in sel_cats))
if active:
    st.markdown(f'<div class="filter-bar">🔍 Filtered by &nbsp; {"&nbsp;&nbsp;|&nbsp;&nbsp;".join(active)}</div>',
                unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────
# KPI CARDS
# ─────────────────────────────────────────────────────────
total_items = df["Item No."].nunique()
total_qty   = df["Remaining Qty"].sum()
total_value = df["Remaining Value"].sum()
aged_pct    = (df["Days"] > 90).sum() / max(len(df), 1) * 100

k1, k2, k3, k4 = st.columns(4)
k1.metric("Unique Items",        f"{total_items:,}")
k2.metric("Total Remaining Qty", f"{total_qty:,.0f}")
k3.metric("Remaining Value (KD)", f"{total_value:,.0f}")
k4.metric("Aged > 90 days",      f"{aged_pct:.1f}%",
          delta="lines" , delta_color="off")

st.markdown("---")

# ─────────────────────────────────────────────────────────
# CHARTS ROW 1
# ─────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

# Chart 1 — Remaining Value by aging bucket (bar)
with c1:
    st.markdown('<div class="section-title">Remaining Value by Aging Bucket (KD)</div>',
                unsafe_allow_html=True)
    bucket_agg = (
        df.groupby("Aging Bucket", observed=True)
        .agg(Value=("Remaining Value", "sum"), Qty=("Remaining Qty", "sum"), Items=("Item No.", "nunique"))
        .reset_index()
    )
    fig1 = go.Figure()
    for _, row in bucket_agg.iterrows():
        bucket = str(row["Aging Bucket"])
        fig1.add_trace(go.Bar(
            x=[bucket], y=[row["Value"]],
            name=bucket,
            marker_color=BUCKET_COLORS.get(bucket, "#C9A84C"),
            text=f"{row['Value']:,.0f}",
            textposition="outside",
            textfont=dict(color="#FAF6EF", size=11),
            hovertemplate=f"<b>{bucket} days</b><br>Value: KD %{{y:,.0f}}<br>Qty: {row['Qty']:,.0f}<br>Items: {row['Items']:,}<extra></extra>",
        ))
    fig1.update_layout(
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF", showlegend=False,
        margin=dict(l=0, r=20, t=20, b=10), height=320,
        xaxis_title="Aging Bucket (days)", yaxis_title="Value (KD)",
        bargap=0.3,
    )
    st.plotly_chart(fig1, use_container_width=True)

# Chart 2 — Top 15 vendors by aged value (120+ days)
with c2:
    st.markdown('<div class="section-title">Top Vendors by Overdue Value (120+ days)</div>',
                unsafe_allow_html=True)
    overdue = df[df["Aging Bucket"] == "120+"]
    vendor_overdue = (
        overdue.groupby("Vendor")
        .agg(Value=("Remaining Value", "sum"))
        .reset_index()
        .sort_values("Value", ascending=True)
        .tail(15)
    )
    if vendor_overdue.empty:
        st.info("No items aged 120+ days in the current selection.")
    else:
        fig2 = px.bar(
            vendor_overdue, x="Value", y="Vendor", orientation="h",
            text=vendor_overdue["Value"].apply(lambda x: f"KD {x:,.0f}"),
            color_discrete_sequence=["#CC2222"],
        )
        fig2.update_layout(
            plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
            font_color="#FAF6EF", showlegend=False,
            margin=dict(l=0, r=20, t=10, b=10), height=320,
            xaxis_title="Remaining Value (KD)", yaxis_title="",
        )
        fig2.update_traces(textposition="outside", textfont_color="#FAF6EF")
        st.plotly_chart(fig2, use_container_width=True)

# ─────────────────────────────────────────────────────────
# CHARTS ROW 2
# ─────────────────────────────────────────────────────────
c3, c4 = st.columns(2)

# Chart 3 — Stacked bar by Category + Bucket
with c3:
    st.markdown('<div class="section-title">Remaining Value by Category & Aging Bucket</div>',
                unsafe_allow_html=True)
    cat_bucket = (
        df.groupby(["Category", "Aging Bucket"], observed=True)
        .agg(Value=("Remaining Value", "sum"))
        .reset_index()
    )
    cat_order = (
        cat_bucket.groupby("Category")["Value"].sum()
        .sort_values(ascending=False).index[:15].tolist()
    )
    cat_bucket = cat_bucket[cat_bucket["Category"].isin(cat_order)]
    fig3 = px.bar(
        cat_bucket, x="Category", y="Value", color="Aging Bucket",
        color_discrete_map=BUCKET_COLORS,
        category_orders={"Aging Bucket": list(BUCKET_COLORS.keys()),
                         "Category": cat_order},
    )
    fig3.update_layout(
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF",
        legend=dict(orientation="h", y=1.05, title=""),
        margin=dict(l=0, r=20, t=30, b=10), height=360,
        xaxis_title="", yaxis_title="Value (KD)",
        xaxis_tickangle=-35,
    )
    st.plotly_chart(fig3, use_container_width=True)

# Chart 4 — Aging distribution pie
with c4:
    st.markdown('<div class="section-title">Aging Distribution (% of Total Value)</div>',
                unsafe_allow_html=True)
    pie_data = (
        df.groupby("Aging Bucket", observed=True)["Remaining Value"]
        .sum().reset_index()
    )
    fig4 = go.Figure(go.Pie(
        labels=pie_data["Aging Bucket"].astype(str),
        values=pie_data["Remaining Value"],
        marker_colors=[BUCKET_COLORS.get(str(b), "#C9A84C") for b in pie_data["Aging Bucket"]],
        hole=0.45,
        textinfo="label+percent",
        textfont=dict(color="#FAF6EF", size=12),
        hovertemplate="<b>%{label}</b><br>KD %{value:,.0f}<br>%{percent}<extra></extra>",
    ))
    fig4.update_layout(
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF", showlegend=False,
        margin=dict(l=20, r=20, t=20, b=10), height=360,
    )
    st.plotly_chart(fig4, use_container_width=True)

# ─────────────────────────────────────────────────────────
# SUMMARY TABLE — Vendor × Bucket
# ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-title">Vendor Summary by Aging Bucket</div>', unsafe_allow_html=True)

vendor_summary = (
    df.groupby(["Vendor", "Aging Bucket"], observed=True)
    .agg(Items=("Item No.", "nunique"), Qty=("Remaining Qty", "sum"), Value=("Remaining Value", "sum"))
    .reset_index()
    .pivot_table(index="Vendor", columns="Aging Bucket", values="Value", aggfunc="sum", fill_value=0)
    .reset_index()
)
vendor_summary.columns.name = None
vendor_summary["Total Value"] = vendor_summary[[c for c in vendor_summary.columns if c != "Vendor"]].sum(axis=1)
vendor_summary = vendor_summary.sort_values("Total Value", ascending=False)

def color_bucket_cell(val):
    if val == 0 or pd.isna(val):
        return ""
    return "background-color:#1a3a2a; color:#FAF6EF"

fmt = {c: "{:,.0f}" for c in vendor_summary.columns if c != "Vendor"}
st.dataframe(
    vendor_summary.style.format(fmt).map(color_bucket_cell, subset=[c for c in vendor_summary.columns if c not in ("Vendor", "Total Value")]),
    use_container_width=True, height=380,
)

# ─────────────────────────────────────────────────────────
# ITEM-LEVEL DRILL DOWN
# ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-title">🔎 Item-Level Detail</div>', unsafe_allow_html=True)

drill_vendor = st.selectbox(
    "Select Vendor",
    ["(All)"] + sorted(df["Vendor"].dropna().unique().tolist()),
)
drill_df = df if drill_vendor == "(All)" else df[df["Vendor"] == drill_vendor]

display_cols = ["Item No.", "Vendor", "Brand", "Category",
                "Posting Date", "Days", "Aging Bucket",
                "Remaining Qty", "Unit Cost", "Remaining Value"]

drill_display = drill_df[display_cols].sort_values(["Days"], ascending=False).copy()
drill_display["Posting Date"] = drill_display["Posting Date"].dt.strftime("%Y-%m-%d")
st.dataframe(drill_display, use_container_width=True, height=400)

# ─────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"Data from Salesforce · {len(df):,} ledger entries · "
    f"{df['Item No.'].nunique():,} unique items · Drops Group Demand Planning"
)
