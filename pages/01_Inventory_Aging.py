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

/* ── SECTION TITLE ───────────────────────────────────── */
.section-title {
    color: #C9A84C; font-weight:700; font-size:15px;
    border-left:4px solid #C9A84C; padding-left:10px;
    margin: 18px 0 10px;
}

/* ── FILTER BAR ──────────────────────────────────────── */
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
DAMAGED_BINS = {"damaged good", "damaged goods"}  # highlighted in KPI card
EXCLUDE_BINS: set = set()                          # nothing excluded — Receive-Ard entries are valid stock

def _coerce_numeric_cols(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("Remaining Qty", "Allocated Qty", "Available Qty",
                "Unit Cost", "Remaining Value", "Available Value", "Days"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Ensure optional cols exist
    for col in ("Warehouse", "Bin", "Allocated Qty", "Available Qty", "Available Value"):
        if col not in df.columns:
            df[col] = np.nan if col.endswith("Qty") or col.endswith("Value") else ""
    if df["Available Qty"].isna().all():
        df["Available Qty"] = df["Remaining Qty"]
    if df["Available Value"].isna().all():
        df["Available Value"] = df["Remaining Value"]
    return df

def _inv_bq_timestamp() -> str:
    """Uncached — called on every page load to detect new data pushes."""
    try:
        import bigquery_client as bq
        return bq.get_last_updated(bq.TABLE_INV) or "no-bq"
    except Exception:
        return "no-bq"

@st.cache_data(show_spinner="Loading inventory data…")  # no TTL — cache key is BQ timestamp
def load_inventory(cache_key: str):
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
                df = _coerce_numeric_cols(df)
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
            df = _coerce_numeric_cols(df)
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

_bq_ts = _inv_bq_timestamp()
df_full, load_error = load_inventory(_bq_ts)

# ─────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────
_refresh_html = f"Last refreshed: <strong>{_bq_ts}</strong>" if _bq_ts != "no-bq" else "Refresh time unavailable"
st.markdown(f"""
<div class="ssl-header">
  <h1>📦 Inventory Aging</h1>
  <p>Drops Group · Demand Planning · {_refresh_html}</p>
</div>
""", unsafe_allow_html=True)

if load_error:
    st.error(load_error)
    st.stop()

# Exclude Receive-Ard entirely (not put-away stock)
# Damaged Good/Goods stay in the main view — just another bin
df_main_all = df_full[~df_full["Bin"].str.lower().isin(EXCLUDE_BINS)]

# ─────────────────────────────────────────────────────────
# SIDEBAR FILTERS
# ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔍 Filters")

    all_vendors = sorted(df_main_all["Vendor"].dropna().unique())
    sel_vendors = st.multiselect("Vendor", all_vendors, placeholder="All vendors")

    all_brands = sorted(df_main_all["Brand"].dropna().unique())
    sel_brands = st.multiselect("Brand", all_brands, placeholder="All brands")

    all_cats = sorted(df_main_all["Category"].dropna().unique())
    sel_cats = st.multiselect("Category", all_cats, placeholder="All categories")

    all_bins = sorted(b for b in df_main_all["Bin"].dropna().unique() if b)
    sel_bins = st.multiselect("Bin", all_bins, placeholder="All bins")

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
df = df_main_all.copy()
if sel_vendors: df = df[df["Vendor"].isin(sel_vendors)]
if sel_brands:  df = df[df["Brand"].isin(sel_brands)]
if sel_cats:    df = df[df["Category"].isin(sel_cats)]
if sel_bins:    df = df[df["Bin"].isin(sel_bins)]
if sel_buckets: df = df[df["Aging Bucket"].isin(sel_buckets)]

# Global Item No. search
item_search = st.text_input(
    "🔎 Search Item No.",
    placeholder="Type item number e.g. KW005004",
    label_visibility="collapsed",
)
if item_search:
    df = df[df["Item No."].str.upper().str.contains(item_search.strip().upper(), na=False)]

# Active filter bar
active = []
if sel_vendors:
    active.append("<strong>Vendor:</strong> " + " ".join(f'<span class="filter-pill">{v}</span>' for v in sel_vendors))
if sel_brands:
    active.append("<strong>Brand:</strong> " + " ".join(f'<span class="filter-pill">{b}</span>' for b in sel_brands))
if sel_cats:
    active.append("<strong>Category:</strong> " + " ".join(f'<span class="filter-pill">{c}</span>' for c in sel_cats))
if sel_bins:
    active.append("<strong>Bin:</strong> " + " ".join(f'<span class="filter-pill">{b}</span>' for b in sel_bins))
if active:
    st.markdown(f'<div class="filter-bar">🔍 Filtered by &nbsp; {"&nbsp;&nbsp;|&nbsp;&nbsp;".join(active)}</div>',
                unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────
# KPI CARDS
# ─────────────────────────────────────────────────────────
total_items  = df["Item No."].nunique()
total_avail  = df["Available Qty"].sum()
total_value  = df["Available Value"].sum()
aged_pct     = (df["Days"] > 90).sum() / max(len(df), 1) * 100
damaged_val  = df[df["Bin"].str.lower().isin(DAMAGED_BINS)]["Available Value"].sum()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Unique Items",          f"{total_items:,}")
k2.metric("Available Qty (OMS)",   f"{total_avail:,.0f}")
k3.metric("Available Value (KD)",  f"{total_value:,.0f}")
k4.metric("Aged > 90 days",        f"{aged_pct:.1f}%", delta="lines", delta_color="off")
k5.metric("Damaged Stock (KD)",    f"{damaged_val:,.0f}", delta="incl. in total", delta_color="off")

st.markdown("---")

# Shared Plotly config — keep toolbar, but disable drag-to-zoom and zoom buttons
_CHART_CFG = {
    "scrollZoom": False,
    "modeBarButtonsToRemove": [
        "zoom2d", "pan2d", "select2d", "lasso2d",
        "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d",
    ],
}

# Session state for chart-click bucket filter
if "chart_bucket" not in st.session_state:
    st.session_state.chart_bucket = None

# ─────────────────────────────────────────────────────────
# CHARTS ROW 1
# ─────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

# Chart 1 — Available Value by aging bucket (clickable)
with c1:
    st.markdown('<div class="section-title">Available Value by Aging Bucket (KD) · click to filter ↓</div>',
                unsafe_allow_html=True)
    bucket_agg = (
        df.groupby("Aging Bucket", observed=True)
        .agg(Value=("Available Value", "sum"), Qty=("Available Qty", "sum"), Items=("Item No.", "nunique"))
        .reset_index()
    )
    fig1 = go.Figure()
    for _, row in bucket_agg.iterrows():
        bucket = str(row["Aging Bucket"])
        is_selected = st.session_state.chart_bucket == bucket
        fig1.add_trace(go.Bar(
            x=[bucket], y=[row["Value"]],
            name=bucket,
            marker_color=BUCKET_COLORS.get(bucket, "#C9A84C"),
            marker_opacity=1.0 if is_selected or st.session_state.chart_bucket is None else 0.4,
            marker_line=dict(width=3 if is_selected else 0, color="#FAF6EF"),
            text=f"{row['Value']:,.0f}",
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color="#FAF6EF", size=11),
            hovertemplate=f"<b>{bucket} days</b><br>Value: KD %{{y:,.0f}}<br>Qty: {row['Qty']:,.0f}<br>Items: {row['Items']:,}<extra></extra>",
        ))
    fig1.update_layout(
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF", showlegend=False,
        margin=dict(l=0, r=20, t=20, b=10), height=320,
        xaxis_title="Aging Bucket (days)", yaxis_title="Available Value (KD)",
        bargap=0.3, clickmode="event", dragmode=False,
    )
    ev1 = st.plotly_chart(fig1, width="stretch", on_select="rerun", config=_CHART_CFG)
    if ev1 and ev1.selection and ev1.selection.points:
        clicked = str(ev1.selection.points[0].get("x", ""))
        if clicked:
            st.session_state.chart_bucket = None if st.session_state.chart_bucket == clicked else clicked
            st.rerun()

# Chart 2 — Top 15 vendors by aged value (120+ days)
with c2:
    st.markdown('<div class="section-title">Top Vendors by Overdue Value (120+ days)</div>',
                unsafe_allow_html=True)
    overdue = df[df["Aging Bucket"] == "120+"]
    vendor_overdue = (
        overdue.groupby("Vendor")
        .agg(Value=("Available Value", "sum"))
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
            xaxis_title="Available Value (KD)", yaxis_title="",
            dragmode=False,
        )
        fig2.update_traces(textposition="inside", insidetextanchor="middle", textfont_color="#FAF6EF")
        st.plotly_chart(fig2, width="stretch", config=_CHART_CFG)

# ─────────────────────────────────────────────────────────
# CHARTS ROW 2
# ─────────────────────────────────────────────────────────
c3, c4 = st.columns(2)

# Chart 3 — Stacked bar by Category + Bucket
with c3:
    st.markdown('<div class="section-title">Available Value by Category & Aging Bucket</div>',
                unsafe_allow_html=True)
    cat_bucket = (
        df.groupby(["Category", "Aging Bucket"], observed=True)
        .agg(Value=("Available Value", "sum"))
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
        xaxis_tickangle=-35, dragmode=False,
    )
    st.plotly_chart(fig3, width="stretch", config=_CHART_CFG)

# Chart 4 — Aging distribution pie (clickable)
with c4:
    st.markdown('<div class="section-title">Aging Distribution (% of Total Value) · click to filter ↓</div>',
                unsafe_allow_html=True)
    pie_data = (
        df.groupby("Aging Bucket", observed=True)["Available Value"]
        .sum().reset_index()
    )
    fig4 = go.Figure(go.Pie(
        labels=pie_data["Aging Bucket"].astype(str),
        values=pie_data["Available Value"],
        marker_colors=[BUCKET_COLORS.get(str(b), "#C9A84C") for b in pie_data["Aging Bucket"]],
        pull=[0.08 if str(b) == st.session_state.chart_bucket else 0 for b in pie_data["Aging Bucket"]],
        hole=0.45,
        textinfo="label+percent",
        textfont=dict(color="#FAF6EF", size=12),
        hovertemplate="<b>%{label}</b><br>KD %{value:,.0f}<br>%{percent}<extra></extra>",
    ))
    fig4.update_layout(
        plot_bgcolor="#0f1f17", paper_bgcolor="#0f1f17",
        font_color="#FAF6EF", showlegend=False,
        margin=dict(l=20, r=20, t=20, b=10), height=360,
        clickmode="event", dragmode=False,
    )
    ev4 = st.plotly_chart(fig4, width="stretch", on_select="rerun", config=_CHART_CFG)
    if ev4 and ev4.selection and ev4.selection.points:
        clicked = str(ev4.selection.points[0].get("label", ""))
        if clicked:
            st.session_state.chart_bucket = None if st.session_state.chart_bucket == clicked else clicked
            st.rerun()

# ─────────────────────────────────────────────────────────
# SUMMARY TABLE — Vendor × Bucket
# ─────────────────────────────────────────────────────────
st.markdown("---")

# Active chart-click filter banner + clear button
df_filtered = df.copy()
if st.session_state.chart_bucket:
    bcol, ccol = st.columns([6, 1])
    bcol.markdown(
        f'<div class="filter-bar">📊 Chart filter: <span class="filter-pill">{st.session_state.chart_bucket} days</span> &nbsp; (click same bucket again or Clear to reset)</div>',
        unsafe_allow_html=True,
    )
    if ccol.button("✕ Clear", width="stretch"):
        st.session_state.chart_bucket = None
        st.rerun()
    df_filtered = df[df["Aging Bucket"].astype(str) == st.session_state.chart_bucket]

st.markdown('<div class="section-title">Vendor Summary by Aging Bucket</div>', unsafe_allow_html=True)

vendor_summary = (
    df_filtered.groupby(["Vendor", "Aging Bucket"], observed=True)
    .agg(Items=("Item No.", "nunique"), Qty=("Available Qty", "sum"), Value=("Available Value", "sum"))
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
    width="stretch", height=380,
)

# ─────────────────────────────────────────────────────────
# ITEM-LEVEL DRILL DOWN
# ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-title">🔎 Item-Level Detail</div>', unsafe_allow_html=True)

drill_vendor = st.selectbox(
    "Select Vendor",
    ["(All)"] + sorted(df_filtered["Vendor"].dropna().unique().tolist()),
)
drill_df = df_filtered if drill_vendor == "(All)" else df_filtered[df_filtered["Vendor"] == drill_vendor]

display_cols = ["Item No.", "Vendor", "Brand", "Category",
                "Warehouse", "Bin",
                "Posting Date", "Days", "Aging Bucket",
                "Available Qty", "Allocated Qty", "Unit Cost", "Available Value"]

drill_display = drill_df[[c for c in display_cols if c in drill_df.columns]].sort_values(["Days"], ascending=False).copy()
drill_display["Posting Date"] = drill_display["Posting Date"].dt.strftime("%Y-%m-%d")
st.dataframe(drill_display, width="stretch", height=400)

# ─────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────
st.markdown("---")
damaged_count = len(df[df["Bin"].str.lower().isin(DAMAGED_BINS)])
st.caption(
    f"Data from Salesforce · {len(df):,} ledger entries · "
    f"{df['Item No.'].nunique():,} unique items · "
    f"Damaged Good lines: {damaged_count:,} · "
    f"Drops Group Demand Planning"
)
