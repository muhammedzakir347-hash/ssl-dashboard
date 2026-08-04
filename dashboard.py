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
def _ssl_bq_timestamp() -> str:
    """Uncached — called on every page load to detect new data pushes."""
    try:
        import bigquery_client as bq
        return bq.get_last_updated(bq.TABLE_SSL) or "no-bq"
    except Exception:
        return "no-bq"

@st.cache_data(show_spinner="Loading data…")  # no TTL — cache key is BQ timestamp
def load_data(cache_key: str):
    cache_path = config.DOWNLOADS_DIR / "raw_merged.csv"
    po_path    = config.DOWNLOADS_DIR / "po_latest.csv"
    wh_path    = config.DOWNLOADS_DIR / "warehouse_latest.csv"

    try:
        import bigquery_client

        # 1. BigQuery — fastest, works on Cloud and local
        try:
            if bigquery_client.table_exists(bigquery_client.TABLE_SSL):
                df = bigquery_client.read_table(bigquery_client.TABLE_SSL)
                for col in ("PO_Qty", "Rec_Qty", "SSL_QTY", "PO_Value", "Rec_Value", "SSL_VALUE"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df["Month_dt"] = pd.to_datetime(df["Month"].astype(str) + "-01", errors="coerce")
                return df, None
        except Exception:
            pass  # fall through to CSV / SF

        # 2. Local CSV cache (written by scheduled task)
        if cache_path.exists():
            df = pd.read_csv(cache_path, dtype=str, low_memory=False)
            for col in ("PO_Qty", "Rec_Qty", "SSL_QTY", "PO_Value", "Rec_Value", "SSL_VALUE"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        elif po_path.exists() and wh_path.exists():
            sheets = data_processor.run_pipeline(po_path, wh_path)
            df = sheets["Raw_Merged_Data"].copy()

        elif config.SF_USERNAME and config.SF_PASSWORD:
            import salesforce_fetcher
            with st.spinner("Fetching data from Salesforce (first load ~4 min)…"):
                frames = salesforce_fetcher.fetch_dataframes()
            sheets = data_processor.run_pipeline_from_dfs(frames["po"], frames["warehouse"])
            df = sheets["Raw_Merged_Data"].copy()

        else:
            return None, "No data found. Run main.py to populate the database."

        df["Month_dt"] = pd.to_datetime(df["Month"].astype(str) + "-01", errors="coerce")
        return df, None
    except Exception as e:
        import traceback
        return None, f"{e}\n\n{traceback.format_exc()}"

_bq_ts = _ssl_bq_timestamp()
df_full, load_error = load_data(_bq_ts)

# ──────────────────────────────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────
# SIDEBAR FILTERS
# ──────────────────────────────────────────────────────────────────────
# (active filter bar is rendered AFTER sidebar so it can read selections)
with st.sidebar:
    st.markdown("## 🔍 Filters")

    min_date = df_full["Month_dt"].min().date()
    max_date = (df_full["Month_dt"].max() + pd.offsets.MonthEnd(0)).date()

    # Default: last 24 months (user can go back to 2022 manually)
    _default_from = max(
        min_date,
        (pd.Timestamp(max_date) - pd.DateOffset(months=23)).replace(day=1).date(),
    )
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From", value=_default_from, min_value=min_date, max_value=max_date)
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
st.dataframe(styled, use_container_width=True, height=400)

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
st.plotly_chart(fig1, use_container_width=True, config=_CHART_CFG)

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
    st.plotly_chart(fig3, use_container_width=True, config=_CHART_CFG)

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
    st.plotly_chart(fig4, use_container_width=True, config=_CHART_CFG)

# ──────────────────────────────────────────────────────────────────────
# YEAR-OVER-YEAR COMPARISON
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-title">📅 Year-over-Year Monthly Comparison</div>', unsafe_allow_html=True)

_MN = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

_yoy = df.copy()
_yoy["_yr"]  = _yoy["Month"].str[:4].astype(int)
_yoy["_mn"]  = _yoy["Month"].str[5:7].astype(int)

_all_yrs   = sorted(_yoy["_yr"].unique())
_show_yrs  = _all_yrs[-4:] if len(_all_yrs) > 4 else _all_yrs

if len(_show_yrs) >= 2:
    _ya = (
        _yoy[_yoy["_yr"].isin(_show_yrs)]
        .groupby(["_yr","_mn"], as_index=False)
        .agg(PO=("PO_Value","sum"), Rec=("Rec_Value","sum"))
    )
    _yc = _show_yrs[-1]
    _yp = _show_yrs[-2]
    _has = set(_ya[_ya["_yr"] == _yc]["_mn"])

    _pp  = _ya.pivot_table(index="_mn", columns="_yr", values="PO",  aggfunc="sum")
    _rp  = _ya.pivot_table(index="_mn", columns="_yr", values="Rec", aggfunc="sum")

    def _v(piv, mn, y):
        try:
            v = piv.at[mn, y]
            return v if pd.notna(v) else np.nan
        except KeyError:
            return np.nan

    def _build_yoy(metric):
        g = "% Growth" if metric != "ssl" else "Δ pp"
        rows = []
        for mn in range(1, 13):
            row = {"Month": _MN[mn-1]}
            for y in _show_yrs:
                po = _v(_pp, mn, y); rec = _v(_rp, mn, y)
                no_curr = mn not in _has and y == _yc
                if no_curr:
                    row[str(y)] = "—"
                elif metric == "po":
                    row[str(y)] = f"{po:,.0f}" if pd.notna(po) else "—"
                elif metric == "rec":
                    row[str(y)] = f"{rec:,.0f}" if pd.notna(rec) else "—"
                else:
                    row[str(y)] = f"{rec/po*100:.1f}%" if (pd.notna(po) and po > 0) else "—"

            po_c = _v(_pp, mn, _yc); po_p = _v(_pp, mn, _yp)
            rc_c = _v(_rp, mn, _yc); rc_p = _v(_rp, mn, _yp)
            if mn not in _has:
                row[g] = "—"
            elif metric == "po":
                row[g] = f"{(po_c/po_p - 1)*100:+.0f}%" if (pd.notna(po_p) and po_p) else "—"
            elif metric == "rec":
                row[g] = f"{(rc_c/rc_p - 1)*100:+.0f}%" if (pd.notna(rc_p) and rc_p) else "—"
            else:
                if pd.notna(po_c) and po_c > 0 and pd.notna(po_p) and po_p > 0:
                    row[g] = f"{rc_c/po_c*100 - rc_p/po_p*100:+.1f}pp"
                else:
                    row[g] = "—"
            rows.append(row)

        # TOTAL
        t = {"Month": "TOTAL"}
        for y in _show_yrs:
            d = _ya[_ya["_yr"] == y]
            if metric == "po":   t[str(y)] = f"{d['PO'].sum():,.0f}"
            elif metric == "rec": t[str(y)] = f"{d['Rec'].sum():,.0f}"
            else:
                ps = d["PO"].sum(); rs = d["Rec"].sum()
                t[str(y)] = f"{rs/ps*100:.1f}%" if ps else "—"
        dc = _ya[_ya["_yr"] == _yc]; dp = _ya[_ya["_yr"] == _yp]
        if metric == "po":
            tc, tp = dc["PO"].sum(), dp["PO"].sum()
            t[g] = f"{(tc/tp - 1)*100:+.0f}%" if tp else "—"
        elif metric == "rec":
            tc, tp = dc["Rec"].sum(), dp["Rec"].sum()
            t[g] = f"{(tc/tp - 1)*100:+.0f}%" if tp else "—"
        else:
            sc = dc["Rec"].sum()/dc["PO"].sum()*100 if dc["PO"].sum() else np.nan
            sp = dp["Rec"].sum()/dp["PO"].sum()*100 if dp["PO"].sum() else np.nan
            t[g] = f"{sc - sp:+.1f}pp" if (pd.notna(sc) and pd.notna(sp)) else "—"
        rows.append(t)

        # M.Average
        a = {"Month": "M.Average"}
        for y in _show_yrs:
            d = _ya[_ya["_yr"] == y]; n = d["_mn"].nunique()
            if metric == "po":   a[str(y)] = f"{d['PO'].sum()/n:,.0f}" if n else "—"
            elif metric == "rec": a[str(y)] = f"{d['Rec'].sum()/n:,.0f}" if n else "—"
            else:
                ps = d["PO"].sum(); rs = d["Rec"].sum()
                a[str(y)] = f"{rs/ps*100:.1f}%" if ps else "—"
        nc = dc["_mn"].nunique(); np2 = dp["_mn"].nunique()
        if metric == "po":
            ac = dc["PO"].sum()/nc if nc else 0; ap = dp["PO"].sum()/np2 if np2 else 0
            a[g] = f"{(ac/ap - 1)*100:+.0f}%" if ap else "—"
        elif metric == "rec":
            ac = dc["Rec"].sum()/nc if nc else 0; ap = dp["Rec"].sum()/np2 if np2 else 0
            a[g] = f"{(ac/ap - 1)*100:+.0f}%" if ap else "—"
        else:
            sc = dc["Rec"].sum()/dc["PO"].sum()*100 if dc["PO"].sum() else np.nan
            sp = dp["Rec"].sum()/dp["PO"].sum()*100 if dp["PO"].sum() else np.nan
            a[g] = f"{sc - sp:+.1f}pp" if (pd.notna(sc) and pd.notna(sp)) else "—"
        rows.append(a)

        cols = ["Month"] + [str(y) for y in _show_yrs] + [g]
        return pd.DataFrame(rows, columns=cols), g

    def _style_growth(val):
        s = str(val)
        if s.startswith("+"): return "color:#155724; font-weight:700"
        if s.startswith("-"): return "color:#cc0000; font-weight:700"
        return ""

    def _style_ssl(val):
        s = str(val)
        if "%" not in s: return ""
        try: n = float(s.replace("%",""))
        except: return ""
        if n >= 95: return "background-color:#d4edda; color:#155724; font-weight:700"
        if n >= 80: return "background-color:#fff3cd; color:#856404; font-weight:700"
        return "background-color:#ffd7d7; color:#cc0000; font-weight:700"

    _ycols = [str(y) for y in _show_yrs]

    st.markdown('<div class="section-title" style="margin-top:8px">📦 PO Value (KD)</div>', unsafe_allow_html=True)
    _po_t, _po_g = _build_yoy("po")
    st.dataframe(_po_t.style.map(_style_growth, subset=[_po_g]),
                 use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title" style="margin-top:8px">📥 Received Value (KD)</div>', unsafe_allow_html=True)
    _rec_t, _rec_g = _build_yoy("rec")
    st.dataframe(_rec_t.style.map(_style_growth, subset=[_rec_g]),
                 use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title" style="margin-top:8px">📊 SSL % (Value)</div>', unsafe_allow_html=True)
    _ssl_t, _ssl_g = _build_yoy("ssl")
    st.dataframe(
        _ssl_t.style.map(_style_ssl, subset=_ycols).map(_style_growth, subset=[_ssl_g]),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("Select a date range spanning at least 2 years to see year-over-year comparisons.")

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
st.plotly_chart(fig_mom, use_container_width=True, config=_CHART_CFG)

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
st.dataframe(
    drill_summary.sort_values("SSL % (Value)", ascending=True).style
        .map(color_ssl, subset=["SSL % (Value)"])
        .format({"PO Value (KD)": "{:,.2f}", "Received (KD)": "{:,.2f}",
                 "SSL % (Value)": lambda x: f"{x:.1f}%" if pd.notna(x) else "—"}),
    use_container_width=True, height=350
)

# ──────────────────────────────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"Data from: `downloads/po_latest.csv` & `downloads/warehouse_latest.csv`  ·  Filtered: {len(df):,} rows  ·  Drops Group Demand Planning")