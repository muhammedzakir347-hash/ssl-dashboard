"""
pages/03_Monthly_Reports.py
----------------------------
Monthly Procurement Report — PO vs Received breakdown for any month.
Data source: BigQuery ssl_merged table (same as main dashboard).
Tabs: By Vendor | By Category | Undelivered SKUs | Item-Level Lines | Download Excel
"""

import io
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

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

import bigquery_client as bq

# ──────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Monthly Reports | Drops",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────
# THEME / CSS  (same visual system as main dashboard)
# ──────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
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

div[data-testid="metric-container"] {
    background: rgba(201,168,76,0.10);
    border: 1px solid #C9A84C;
    border-radius: 10px;
    padding: 16px 20px;
}
div[data-testid="metric-container"] label { color: #856404 !important; font-size:13px; }
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: #1a3a2a !important; font-size:26px; font-weight:700;
}
@media (prefers-color-scheme: dark) {
    div[data-testid="metric-container"] { background: #1a3a2a; }
    div[data-testid="metric-container"] label { color: #C9A84C !important; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #FAF6EF !important; }
}
[data-theme="dark"] div[data-testid="metric-container"] { background: #1a3a2a !important; }
[data-theme="dark"] div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #FAF6EF !important; }
[data-theme="light"] div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #1a3a2a !important; }
.alert-bar {
    background: linear-gradient(90deg, #1e1b4b 0%, #312e81 100%);
    color: #e0e7ff;
    border-radius: 10px;
    padding: 14px 20px;
    margin-bottom: 20px;
    font-size: 14px;
    line-height: 1.5;
}
[data-testid="stTabs"] button[role="tab"] { font-size: 13px; padding: 6px 14px; }
</style>
""", unsafe_allow_html=True)

DOWNLOADS = Path(__file__).parent.parent / "downloads"


# ──────────────────────────────────────────────────────────────────────────
# LOAD AVAILABLE MONTHS FROM BQ  (cheap metadata query)
# ──────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _get_months():
    return bq.get_distinct_months(bq.TABLE_SSL)

try:
    all_months = _get_months()
except Exception as e:
    st.error(f"❌ Could not connect to BigQuery: {e}")
    st.stop()

if not all_months:
    st.warning("No data found in BigQuery ssl_merged table.")
    st.stop()


# ──────────────────────────────────────────────────────────────────────────
# SIDEBAR: Month selector
# ──────────────────────────────────────────────────────────────────────────
st.sidebar.title("📋 Monthly Reports")

def fmt_month(m):
    try:
        return pd.Period(m, "M").strftime("%B %Y")
    except Exception:
        return m

months_desc   = list(reversed(all_months))   # newest first
month_labels  = [fmt_month(m) for m in months_desc]
selected_idx  = st.sidebar.selectbox(
    "📅 Select Month",
    range(len(months_desc)),
    format_func=lambda i: month_labels[i],
    index=0,
)
sel_month = months_desc[selected_idx]
sel_label = month_labels[selected_idx]

st.sidebar.markdown("---")
last_upd = bq.get_last_updated(bq.TABLE_SSL)
if last_upd:
    st.sidebar.caption(f"🕐 BQ last updated: {last_upd}")
st.sidebar.caption("Received value derived from PO received qty (pro-rated line cost).")


# ──────────────────────────────────────────────────────────────────────────
# LOAD MONTH DATA FROM BQ
# ──────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=f"📂 Loading data from BigQuery…")
def load_month(month: str) -> pd.DataFrame:
    return bq.read_table_range(bq.TABLE_SSL, month, month)

with st.spinner(f"📂 Loading {sel_label} from BigQuery…"):
    try:
        df = load_month(sel_month)
    except Exception as e:
        st.error(f"❌ BigQuery error: {e}")
        st.stop()

if df.empty:
    st.warning(f"No data in BigQuery for {sel_label}.")
    st.stop()

# Normalise numeric columns (BQ sometimes returns objects)
for col in ("PO_Qty", "PO_Value", "Rec_Qty", "Rec_Value", "SSL_QTY", "SSL_VALUE"):
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

# Exclude returns-flagged rows (PO_Qty < 0) just in case
df = df[df["PO_Value"] >= 0]


# ──────────────────────────────────────────────────────────────────────────
# COMPUTE AGGREGATIONS
# ──────────────────────────────────────────────────────────────────────────
po_total    = df["PO_Value"].sum()
recv_total  = df["Rec_Value"].sum()
gap_total   = po_total - recv_total
ssl_pct     = round(recv_total / po_total * 100, 1) if po_total else 0.0
vendor_count = df["Vendor"].nunique()
item_count   = df["Item_No"].nunique()

# ── Vendor summary ────────────────────────────────────────────────────────
vendor = (
    df.groupby("Vendor", observed=True, dropna=False)
    .agg(
        PO_Value=("PO_Value", "sum"),
        PO_Qty=("PO_Qty", "sum"),
        Rec_Value=("Rec_Value", "sum"),
        Rec_Qty=("Rec_Qty", "sum"),
        SKU_Count=("Item_No", "nunique"),
    )
    .reset_index()
)
vendor["Gap KD"] = vendor["PO_Value"] - vendor["Rec_Value"]
vendor["SSL %"]  = np.where(
    vendor["PO_Value"] > 0,
    (vendor["Rec_Value"] / vendor["PO_Value"] * 100).clip(0, 100),
    0.0,
).round(1)
vendor = vendor.sort_values("PO_Value", ascending=False).reset_index(drop=True)
vendor.insert(0, "Rank", vendor.index + 1)
vendor = vendor.rename(columns={
    "PO_Value": "PO Value KD",
    "PO_Qty":   "PO Qty",
    "Rec_Value": "Received KD",
    "Rec_Qty":   "Received Qty",
    "SKU_Count": "SKUs",
})

# ── Category summary ──────────────────────────────────────────────────────
cat_df = (
    df.groupby("Category", observed=True, dropna=False)
    .agg(
        PO_Value=("PO_Value", "sum"),
        PO_Qty=("PO_Qty", "sum"),
        Rec_Value=("Rec_Value", "sum"),
        SKU_Count=("Item_No", "nunique"),
    )
    .reset_index()
)
cat_df["Gap KD"] = cat_df["PO_Value"] - cat_df["Rec_Value"]
cat_df["SSL %"]  = np.where(
    cat_df["PO_Value"] > 0,
    (cat_df["Rec_Value"] / cat_df["PO_Value"] * 100).clip(0, 100),
    0.0,
).round(1)
cat_df = cat_df.sort_values("PO_Value", ascending=False).reset_index(drop=True)
cat_df = cat_df.rename(columns={
    "PO_Value": "PO Value KD",
    "PO_Qty":   "PO Qty",
    "Rec_Value": "Received KD",
    "SKU_Count": "SKUs",
})

# ── Undelivered SKUs (Rec_Value == 0, PO_Value > 0) ───────────────────────
zero_df = df[(df["Rec_Value"] == 0) & (df["PO_Value"] > 0)].copy()
zero_count = zero_df["Item_No"].nunique()

sku_df = (
    zero_df.groupby(["Item_No", "Vendor", "Brand", "Category"], observed=True, dropna=False)
    .agg(
        Ordered_Qty=("PO_Qty", "sum"),
        PO_Value=("PO_Value", "sum"),
    )
    .reset_index()
    .sort_values("PO_Value", ascending=False)
    .reset_index(drop=True)
)
sku_df.insert(0, "No.", sku_df.index + 1)
sku_df = sku_df.rename(columns={
    "Item_No":    "SKU",
    "Ordered_Qty":"Ordered Qty",
    "PO_Value":   "PO Value KD",
})


# ──────────────────────────────────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────────────────────────────────
st.title(f"📋 {sel_label} — Procurement Report")

ssl_icon = "🟢" if ssl_pct >= 80 else ("🟡" if ssl_pct >= 30 else "🔴")
st.markdown(f"""
<div class="alert-bar">
  <strong>{ssl_icon} Overall SSL: {ssl_pct:.1f}%</strong> &nbsp;·&nbsp;
  PO Value: <strong>{po_total:,.0f} KD</strong> &nbsp;·&nbsp;
  Received: <strong>{recv_total:,.0f} KD</strong> &nbsp;·&nbsp;
  Gap: <strong>{gap_total:,.0f} KD</strong> &nbsp;·&nbsp;
  {vendor_count} vendors &nbsp;·&nbsp; {item_count:,} SKUs &nbsp;·&nbsp; {zero_count:,} undelivered SKUs
</div>
""", unsafe_allow_html=True)

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("📦 PO Value",         f"{po_total/1_000:,.1f}K KD")
k2.metric("✅ Received",          f"{recv_total/1_000:,.1f}K KD")
k3.metric("⚠️ Gap",              f"{gap_total/1_000:,.1f}K KD")
k4.metric("📊 SSL %",            f"{ssl_pct:.1f}%")
k5.metric("🏢 Vendors",          f"{vendor_count}")
k6.metric("❌ Undelivered SKUs",  f"{zero_count:,}")

st.markdown("<br>", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# TABS
# ──────────────────────────────────────────────────────────────────────────
tab_vendor, tab_cat, tab_sku, tab_lines, tab_dl = st.tabs([
    "📊 By Vendor",
    "🏷️ By Category",
    "📦 Undelivered SKUs",
    "📋 Item-Level Lines",
    "⬇️ Download Excel",
])


# ── TAB 1: By Vendor ──────────────────────────────────────────────────────
with tab_vendor:
    st.markdown(f"**{len(vendor)} vendors** — sorted by PO Value ↓")

    c1, c2 = st.columns(2)
    with c1:
        top10 = vendor.nlargest(10, "PO Value KD").sort_values("PO Value KD")
        fig = px.bar(
            top10, x="PO Value KD", y="Vendor", orientation="h",
            color="SSL %", color_continuous_scale=["#EF4444", "#F59E0B", "#10B981"],
            range_color=[0, 100],
            title=f"Top 10 Vendors by PO Value — {sel_label}",
        )
        fig.update_layout(height=350, margin=dict(l=10,r=10,t=40,b=10),
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        bot10 = vendor.nsmallest(10, "SSL %").sort_values("SSL %", ascending=False)
        fig2 = px.bar(
            bot10, x="SSL %", y="Vendor", orientation="h",
            color="SSL %", color_continuous_scale=["#EF4444", "#F59E0B", "#10B981"],
            range_color=[0, 100],
            title=f"10 Lowest SSL Vendors — {sel_label}",
        )
        fig2.update_layout(height=350, margin=dict(l=10,r=10,t=40,b=10),
                           coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    def _ssl_style(val):
        if val >= 80:  return "background-color:#ECFDF5; color:#065F46"
        if val >= 30:  return "background-color:#FFFBEB; color:#92400E"
        return "background-color:#FEF2F2; color:#991B1B"

    st.dataframe(
        vendor.style
        .format({"PO Value KD": "{:,.0f}", "PO Qty": "{:,.0f}",
                 "Received KD": "{:,.0f}", "Received Qty": "{:,.0f}",
                 "Gap KD": "{:,.0f}", "SSL %": "{:.1f}%", "SKUs": "{:,}"})
        .applymap(_ssl_style, subset=["SSL %"]),
        use_container_width=True, height=520,
    )


# ── TAB 2: By Category ────────────────────────────────────────────────────
with tab_cat:
    st.markdown(f"**{len(cat_df)} categories** — sorted by PO Value ↓")

    cats_sorted = cat_df.sort_values("PO Value KD", ascending=True)
    fig_cat = go.Figure()
    fig_cat.add_trace(go.Bar(
        name="PO Value KD", y=cats_sorted["Category"], x=cats_sorted["PO Value KD"],
        orientation="h", marker_color="#CBD5E1", opacity=0.85,
    ))
    fig_cat.add_trace(go.Bar(
        name="Received KD", y=cats_sorted["Category"], x=cats_sorted["Received KD"],
        orientation="h", marker_color="#3B82F6",
    ))
    fig_cat.update_layout(
        barmode="overlay",
        height=max(380, len(cat_df) * 38),
        margin=dict(l=10, r=10, t=40, b=10),
        title=f"PO vs Received by Category — {sel_label}",
        legend=dict(orientation="h", y=1.06),
        xaxis_title="Value (KD)",
    )
    st.plotly_chart(fig_cat, use_container_width=True)

    st.dataframe(
        cat_df.style
        .format({"PO Value KD": "{:,.0f}", "PO Qty": "{:,.0f}",
                 "Received KD": "{:,.0f}", "Gap KD": "{:,.0f}",
                 "SSL %": "{:.1f}%", "SKUs": "{:,}"})
        .applymap(_ssl_style, subset=["SSL %"]),
        use_container_width=True,
    )


# ── TAB 3: Undelivered SKUs ───────────────────────────────────────────────
with tab_sku:
    st.markdown(
        f"**{len(sku_df):,} SKUs** with zero delivery in {sel_label} — "
        f"total undelivered PO value **{sku_df['PO Value KD'].sum():,.0f} KD**"
    )
    srch = st.text_input("🔍 Search SKU / Vendor / Brand / Category", key="sku_search")
    disp = sku_df
    if srch:
        mask = pd.Series(False, index=disp.index)
        for col in ["SKU", "Vendor", "Brand", "Category"]:
            if col in disp.columns:
                mask |= disp[col].astype(str).str.contains(srch, case=False, na=False)
        disp = disp[mask]

    st.dataframe(
        disp.style.format({"PO Value KD": "{:,.0f}", "Ordered Qty": "{:,.0f}"}),
        use_container_width=True, height=550,
    )


# ── TAB 4: Item-Level Lines ───────────────────────────────────────────────
with tab_lines:
    DOWNLOADS = Path(__file__).parent.parent / "downloads"
    # Try to load raw CSV for item-level lines (only available when G: drive is mounted)
    po_csv = DOWNLOADS / "po_latest.csv"
    if po_csv.exists():
        @st.cache_data(ttl=3600, show_spinner="Loading item-level PO lines…")
        def _load_lines(month: str):
            po_raw = pd.read_csv(po_csv, parse_dates=["Created Date"])
            po_raw["month"] = po_raw["Created Date"].dt.to_period("M").astype(str)
            m = po_raw[(po_raw["month"] == month) & (po_raw["Quantity"] > 0)]
            if "Received Qty." in m.columns:
                return m[m["Received Qty."] == 0].copy()
            return pd.DataFrame()

        lines_raw = _load_lines(sel_month)
        if lines_raw.empty:
            st.info(f"No zero-received PO lines found for {sel_label}.")
        else:
            keep = {}
            for src, dst in {
                "Purchase Order: Order No.": "PO Number",
                "Item No.": "Item No.",
                "Name": "Item Name",
                "Preferred Vendor: Account Name": "Vendor",
                "Category": "Category",
                "Drops Brand: Name": "Brand",
                "Quantity": "Ordered Qty",
                "GL Line Cost": "Line Value KD",
                "Received Qty.": "Received Qty",
                "Line Status": "Line Status",
                "Expected Receipt Date": "Exp. Receipt Date",
            }.items():
                if src in lines_raw.columns:
                    keep[src] = dst

            lines_df = (
                lines_raw[list(keep.keys())]
                .rename(columns=keep)
                .sort_values(["Vendor", "Item No."] if "Item No." in keep.values() else ["Vendor"])
                .reset_index(drop=True)
            )
            lines_df.insert(0, "No.", lines_df.index + 1)

            st.markdown(
                f"**{len(lines_df):,} individual PO lines** with zero received qty in {sel_label}. "
                f"Each row is one purchase order line."
            )
            srch2 = st.text_input("🔍 Search PO / Item / Vendor / Category", key="lines_search")
            disp2 = lines_df
            if srch2:
                mask2 = pd.Series(False, index=disp2.index)
                for col in ["PO Number", "Item No.", "Item Name", "Vendor", "Category", "Brand", "Line Status"]:
                    if col in disp2.columns:
                        mask2 |= disp2[col].astype(str).str.contains(srch2, case=False, na=False)
                disp2 = disp2[mask2]

            def _status_style(val):
                return "background-color:#FFFBEB; color:#92400E" if str(val).strip().lower() == "open" else ""

            styled2 = disp2.style.format({
                "Ordered Qty": "{:,.0f}",
                "Received Qty": "{:,.0f}",
                "Line Value KD": "{:,.0f}",
            })
            if "Line Status" in disp2.columns:
                styled2 = styled2.applymap(_status_style, subset=["Line Status"])
            st.dataframe(styled2, use_container_width=True, height=600)
    else:
        # Streamlit Cloud path — BQ doesn't store individual PO lines
        st.info(
            "📋 **Item-level PO lines** are not stored in BigQuery — they require the daily sync CSV "
            "(`po_latest.csv`) which is only available when the dashboard runs locally on a machine "
            "with the Shared Drive mounted.\n\n"
            "**To access item-level detail:**\n"
            "- Download the pre-built Excel from the **⬇️ Download Excel** tab — "
            "it includes a *Zero-Received Lines* sheet with every individual PO line.\n"
            "- Or run the dashboard locally: `streamlit run dashboard.py`"
        )
        # Show the BQ-level undelivered SKU aggregation as a substitute
        st.markdown("---")
        st.markdown(f"**Closest available: aggregated undelivered SKUs from BigQuery ({len(sku_df):,} rows)**")
        st.dataframe(
            sku_df.style.format({"PO Value KD": "{:,.0f}", "Ordered Qty": "{:,.0f}"}),
            use_container_width=True, height=400,
        )


# ── TAB 5: Download Excel ─────────────────────────────────────────────────
with tab_dl:
    st.markdown(f"### ⬇️ Download {sel_label} Report")

    # Pre-built file (August 2026 only for now)
    prebuilt_name = f"{sel_label.replace(' ', '_')}_Procurement_Report.xlsx"
    prebuilt_path = DOWNLOADS / prebuilt_name

    if prebuilt_path.exists():
        with open(prebuilt_path, "rb") as f:
            st.download_button(
                label=f"📥 Download {prebuilt_name}  (pre-built, includes item-level lines)",
                data=f.read(),
                file_name=prebuilt_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        st.success(
            "Pre-built report ready — includes styled sheets, colour coding, "
            "and the full item-level zero-received lines sheet."
        )
        st.markdown("---")

    # Generate fresh from BQ data
    st.markdown("#### Generate fresh report from BigQuery data:")
    if st.button("⚙️ Generate Excel", key="gen_xl"):
        with st.spinner("Building Excel…"):
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                wb  = writer.book
                hdr = wb.add_format({"bold": True, "bg_color": "#0D1520", "font_color": "#FFFFFF",
                                      "border": 1, "align": "center", "font_name": "Calibri", "font_size": 10})
                grn = wb.add_format({"num_format": "0.0%", "border": 1, "font_name": "Calibri", "font_size": 10,
                                      "align": "right", "bg_color": "#ECFDF5", "font_color": "#065F46"})
                amb = wb.add_format({"num_format": "0.0%", "border": 1, "font_name": "Calibri", "font_size": 10,
                                      "align": "right", "bg_color": "#FFFBEB", "font_color": "#92400E"})
                red = wb.add_format({"num_format": "0.0%", "border": 1, "font_name": "Calibri", "font_size": 10,
                                      "align": "right", "bg_color": "#FEF2F2", "font_color": "#991B1B"})

                def _write(df_out, sheet, tab_color, ssl_col=None):
                    df_out.to_excel(writer, sheet_name=sheet, index=False)
                    ws = writer.sheets[sheet]
                    ws.set_tab_color(tab_color)
                    for ci, cn in enumerate(df_out.columns):
                        ws.write(0, ci, cn, hdr)
                        ws.set_column(ci, ci, max(14, len(str(cn)) + 2))
                    if ssl_col and ssl_col in df_out.columns:
                        si = df_out.columns.get_loc(ssl_col)
                        for ri, v in enumerate(df_out[ssl_col], 1):
                            fmt = grn if v >= 80 else (amb if v >= 30 else red)
                            ws.write(ri, si, v / 100, fmt)
                    ws.autofilter(0, 0, len(df_out), len(df_out.columns) - 1)
                    ws.freeze_panes(1, 0)

                _write(vendor,  "Vendor Performance", "#1D4ED8", ssl_col="SSL %")
                _write(cat_df,  "By Category",        "#7C3AED", ssl_col="SSL %")
                _write(sku_df,  "Undelivered SKUs",   "#DC2626")

            buf.seek(0)
            st.download_button(
                label=f"📥 Download {prebuilt_name}",
                data=buf.read(),
                file_name=prebuilt_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.success("Done!")

    st.markdown("""
**Sheets included in generated report:**

| Sheet | Contents |
|---|---|
| Vendor Performance | All vendors — PO Value, Received, Gap, SSL % (colour coded) |
| By Category | Category breakdown with PO vs Received |
| Undelivered SKUs | All SKUs with zero delivery, sorted by PO Value |

> **Note:** The pre-built Excel (when available) also includes a *Zero-Received Lines* sheet
> with all individual PO lines — generated locally from the raw Salesforce data.
""")
