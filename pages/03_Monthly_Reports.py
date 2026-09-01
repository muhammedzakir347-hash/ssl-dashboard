"""
pages/03_Monthly_Reports.py
----------------------------
Monthly Procurement Report — PO vs Received breakdown for any month.
Tabs: By Vendor | By Category | Undelivered SKUs | Item-Level Lines | Download Excel
"""

import io
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

# ──────────────────────────────────────────────────────────────────────────
# PAGE CONFIG  (must be first Streamlit command)
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
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        color: #FAF6EF !important;
    }
}
[data-theme="dark"] div[data-testid="metric-container"] { background: #1a3a2a !important; }
[data-theme="dark"] div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: #FAF6EF !important;
}

/* Tighter tab labels */
[data-testid="stTabs"] button[role="tab"] { font-size: 13px; padding: 6px 14px; }

/* Alert bar */
.alert-bar {
    background: linear-gradient(90deg, #1e1b4b 0%, #312e81 100%);
    color: #e0e7ff;
    border-radius: 10px;
    padding: 14px 20px;
    margin-bottom: 20px;
    font-size: 14px;
    line-height: 1.5;
}
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ──────────────────────────────────────────────────────────────────────────
DOWNLOADS = Path(__file__).parent.parent / "downloads"

@st.cache_data(ttl=3600, show_spinner="📂 Loading procurement data…")
def load_po():
    return pd.read_csv(DOWNLOADS / "po_latest.csv", parse_dates=["Created Date"])

@st.cache_data(ttl=3600, show_spinner="📂 Loading warehouse data…")
def load_wh():
    return pd.read_csv(DOWNLOADS / "warehouse_latest.csv", parse_dates=["Created Date"])


try:
    po_raw = load_po()
    wh_raw = load_wh()
except FileNotFoundError as e:
    st.error(f"⚠️ Data file not found: {e}")
    st.stop()

po_raw["month"] = po_raw["Created Date"].dt.to_period("M").astype(str)
wh_raw["month"] = wh_raw["Created Date"].dt.to_period("M").astype(str)


# ──────────────────────────────────────────────────────────────────────────
# SIDEBAR: Month selector
# ──────────────────────────────────────────────────────────────────────────
st.sidebar.title("📋 Monthly Reports")
available_months = sorted(po_raw["month"].unique(), reverse=True)

# Human-readable labels: "2026-08" → "August 2026"
def fmt_month(m):
    return pd.Period(m, "M").strftime("%B %Y")

month_labels  = [fmt_month(m) for m in available_months]
selected_idx  = st.sidebar.selectbox(
    "📅 Select Month",
    range(len(available_months)),
    format_func=lambda i: month_labels[i],
    index=0,
)
sel_month  = available_months[selected_idx]
sel_label  = month_labels[selected_idx]

st.sidebar.markdown("---")
st.sidebar.caption("Data excludes returns (negative qty). Received value from warehouse receipts.")


# ──────────────────────────────────────────────────────────────────────────
# FILTER TO SELECTED MONTH  (exclude returns)
# ──────────────────────────────────────────────────────────────────────────
po = po_raw[(po_raw["month"] == sel_month) & (po_raw["Quantity"] > 0)].copy()
wh = wh_raw[(wh_raw["month"] == sel_month) & (wh_raw["Quantity"] > 0)].copy()

if po.empty:
    st.warning(f"No purchase order data found for {sel_label}.")
    st.stop()


# ──────────────────────────────────────────────────────────────────────────
# COMPUTE AGGREGATIONS
# ──────────────────────────────────────────────────────────────────────────
po_total   = po["GL Line Cost"].sum()
recv_total = wh["Line Cost"].sum() if len(wh) else 0.0
gap_total  = po_total - recv_total
ssl_pct    = round(recv_total / po_total * 100, 1) if po_total else 0.0
po_count   = po["Purchase Order: Order No."].nunique()
vendor_count = po["Preferred Vendor: Account Name"].nunique()

# Vendor summary
vpo = po.groupby("Preferred Vendor: Account Name").agg(
    PO_Value=("GL Line Cost", "sum"),
    PO_Qty=("Quantity", "sum"),
    PO_Count=("Purchase Order: Order No.", "nunique"),
).reset_index()

vwh = (
    wh.groupby("Buy-from Vendor")
    .agg(Recv_Value=("Line Cost", "sum"), Recv_Qty=("Quantity", "sum"))
    .reset_index()
    .rename(columns={"Buy-from Vendor": "Preferred Vendor: Account Name"})
)

vendor = vpo.merge(vwh, on="Preferred Vendor: Account Name", how="left")
vendor["Recv_Value"] = vendor["Recv_Value"].fillna(0)
vendor["Recv_Qty"]   = vendor["Recv_Qty"].fillna(0)
vendor["Gap KD"]     = vendor["PO_Value"] - vendor["Recv_Value"]
vendor["SSL %"]      = (vendor["Recv_Value"] / vendor["PO_Value"] * 100).clip(0, 100).round(1)
vendor = vendor.sort_values("PO_Value", ascending=False).reset_index(drop=True)
vendor.insert(0, "Rank", vendor.index + 1)
vendor = vendor.rename(columns={
    "Preferred Vendor: Account Name": "Vendor",
    "PO_Value": "PO Value KD",
    "PO_Qty": "PO Qty",
    "PO_Count": "No. of POs",
    "Recv_Value": "Received KD",
    "Recv_Qty": "Received Qty",
})

# Category summary
cat_col = "Category" if "Category" in po.columns else None
if cat_col:
    cpo = po.groupby(cat_col).agg(
        PO_Value=("GL Line Cost", "sum"),
        PO_Qty=("Quantity", "sum"),
    ).reset_index()
    # Received by category: join po → wh on PO number
    po_cat_map = (
        po[["Purchase Order: Order No.", cat_col]]
        .drop_duplicates("Purchase Order: Order No.")
    )
    wh_cat = wh.merge(
        po_cat_map,
        left_on="Document No.",
        right_on="Purchase Order: Order No.",
        how="left",
    ) if "Document No." in wh.columns else pd.DataFrame()

    if not wh_cat.empty and cat_col in wh_cat.columns:
        cwh = wh_cat.groupby(cat_col).agg(Recv_Value=("Line Cost", "sum")).reset_index()
        cat_df = cpo.merge(cwh, on=cat_col, how="left")
    else:
        cat_df = cpo.copy()
        cat_df["Recv_Value"] = 0.0

    cat_df["Recv_Value"] = cat_df["Recv_Value"].fillna(0)
    cat_df["Gap KD"]     = cat_df["PO_Value"] - cat_df["Recv_Value"]
    cat_df["SSL %"]      = (cat_df["Recv_Value"] / cat_df["PO_Value"] * 100).clip(0, 100).round(1)
    cat_df = cat_df.sort_values("PO_Value", ascending=False).reset_index(drop=True)
    cat_df = cat_df.rename(columns={
        cat_col: "Category",
        "PO_Value": "PO Value KD",
        "PO_Qty": "PO Qty",
        "Recv_Value": "Received KD",
    })
else:
    cat_df = pd.DataFrame()

# Undelivered SKUs — aggregated (Received Qty. == 0)
recv_col = "Received Qty." if "Received Qty." in po.columns else None
if recv_col:
    zero_po = po[po[recv_col] == 0].copy()
    brand_col = "Drops Brand: Name" if "Drops Brand: Name" in po.columns else (
        "Brand" if "Brand" in po.columns else None
    )
    grp_cols = ["Item No.", "Preferred Vendor: Account Name"]
    if cat_col:  grp_cols.append(cat_col)
    if brand_col: grp_cols.append(brand_col)

    if "Name" in po.columns:
        grp_cols.insert(1, "Name")

    sku_df = zero_po.groupby(grp_cols).agg(
        Ordered_Qty=("Quantity", "sum"),
        PO_Value=("GL Line Cost", "sum"),
        PO_Count=("Purchase Order: Order No.", "nunique"),
        PO_Numbers=("Purchase Order: Order No.", lambda x: ", ".join(sorted(x.unique()))),
    ).reset_index().sort_values("PO_Value", ascending=False).reset_index(drop=True)
    sku_df.insert(0, "No.", sku_df.index + 1)
    sku_df = sku_df.rename(columns={
        "Item No.": "SKU",
        "Name": "Item Name",
        "Preferred Vendor: Account Name": "Vendor",
        "Drops Brand: Name": "Brand",
        "Ordered_Qty": "Ordered Qty",
        "PO_Value": "PO Value KD",
        "PO_Count": "No. of POs",
    })
    zero_count = len(sku_df)

    # Item-level lines
    line_cols = {
        "Purchase Order: Order No.": "PO Number",
        "Item No.": "Item No.",
        "Preferred Vendor: Account Name": "Vendor",
        "Quantity": "Ordered Qty",
        "GL Line Cost": "Line Value KD",
        "Received Qty.": "Received Qty",
    }
    if cat_col:  line_cols[cat_col] = "Category"
    if brand_col: line_cols[brand_col] = "Brand"
    if "Name" in po.columns: line_cols["Name"] = "Item Name"
    if "Line Status" in po.columns: line_cols["Line Status"] = "Line Status"
    if "Expected Receipt Date" in po.columns: line_cols["Expected Receipt Date"] = "Exp. Receipt Date"

    lines_df = (
        zero_po[[c for c in line_cols if c in zero_po.columns]]
        .rename(columns=line_cols)
        .sort_values(["Vendor", "Item No."] if "Item No." in [line_cols.get(k, k) for k in line_cols] else ["Vendor"])
        .reset_index(drop=True)
    )
    lines_df.insert(0, "No.", lines_df.index + 1)
else:
    zero_count = 0
    sku_df     = pd.DataFrame()
    lines_df   = pd.DataFrame()


# ──────────────────────────────────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────────────────────────────────
st.title(f"📋 {sel_label} — Procurement Report")

ssl_color = "🟢" if ssl_pct >= 80 else ("🟡" if ssl_pct >= 30 else "🔴")
st.markdown(f"""
<div class="alert-bar">
  <strong>{ssl_color} Overall SSL: {ssl_pct:.1f}%</strong> &nbsp;·&nbsp;
  PO Value: <strong>{po_total:,.0f} KD</strong> &nbsp;·&nbsp;
  Received: <strong>{recv_total:,.0f} KD</strong> &nbsp;·&nbsp;
  Gap: <strong>{gap_total:,.0f} KD</strong> &nbsp;·&nbsp;
  {vendor_count} vendors &nbsp;·&nbsp; {po_count} POs &nbsp;·&nbsp; {zero_count:,} undelivered SKUs
</div>
""", unsafe_allow_html=True)

# KPI row
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
    st.markdown(f"**{len(vendor)} vendors** sorted by PO Value ↓")

    # Top / Bottom charts side by side
    c1, c2 = st.columns(2)
    with c1:
        top10 = vendor.nlargest(10, "PO Value KD").sort_values("PO Value KD")
        fig = px.bar(
            top10, x="PO Value KD", y="Vendor", orientation="h",
            color="SSL %", color_continuous_scale=["#EF4444","#F59E0B","#10B981"],
            range_color=[0, 100],
            title="Top 10 Vendors by PO Value",
        )
        fig.update_layout(height=350, margin=dict(l=10,r=10,t=40,b=10),
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        bot10 = vendor[vendor["No. of POs"] >= 1].nsmallest(10, "SSL %").sort_values("SSL %", ascending=False)
        fig2 = px.bar(
            bot10, x="SSL %", y="Vendor", orientation="h",
            color="SSL %", color_continuous_scale=["#EF4444","#F59E0B","#10B981"],
            range_color=[0, 100],
            title="10 Lowest SSL Vendors",
        )
        fig2.update_layout(height=350, margin=dict(l=10,r=10,t=40,b=10),
                           coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    # Full table
    def color_ssl_vendor(val):
        if val >= 80:  return "background-color:#ECFDF5; color:#065F46"
        if val >= 30:  return "background-color:#FFFBEB; color:#92400E"
        return "background-color:#FEF2F2; color:#991B1B"

    styled = (
        vendor.style
        .format({"PO Value KD": "{:,.0f}", "PO Qty": "{:,.0f}",
                 "Received KD": "{:,.0f}", "Received Qty": "{:,.0f}",
                 "Gap KD": "{:,.0f}", "SSL %": "{:.1f}%"})
        .applymap(color_ssl_vendor, subset=["SSL %"])
    )
    st.dataframe(styled, use_container_width=True, height=500)


# ── TAB 2: By Category ────────────────────────────────────────────────────
with tab_cat:
    if cat_df.empty:
        st.info("Category breakdown not available for this dataset.")
    else:
        st.markdown(f"**{len(cat_df)} categories** sorted by PO Value ↓")

        # Horizontal bar chart: PO vs Received
        fig_cat = go.Figure()
        cats_sorted = cat_df.sort_values("PO Value KD", ascending=True)

        fig_cat.add_trace(go.Bar(
            name="PO Value KD",
            y=cats_sorted["Category"],
            x=cats_sorted["PO Value KD"],
            orientation="h",
            marker_color="#CBD5E1",
            opacity=0.8,
        ))
        fig_cat.add_trace(go.Bar(
            name="Received KD",
            y=cats_sorted["Category"],
            x=cats_sorted["Received KD"],
            orientation="h",
            marker_color="#3B82F6",
        ))

        fig_cat.update_layout(
            barmode="overlay",
            height=max(380, len(cat_df) * 36),
            margin=dict(l=10, r=10, t=40, b=10),
            title=f"PO vs Received by Category — {sel_label}",
            legend=dict(orientation="h", y=1.05),
            xaxis_title="Value (KD)",
        )
        st.plotly_chart(fig_cat, use_container_width=True)

        def color_ssl_cat(val):
            if val >= 80:  return "background-color:#ECFDF5; color:#065F46"
            if val >= 30:  return "background-color:#FFFBEB; color:#92400E"
            return "background-color:#FEF2F2; color:#991B1B"

        styled_cat = (
            cat_df.style
            .format({"PO Value KD": "{:,.0f}", "PO Qty": "{:,.0f}",
                     "Received KD": "{:,.0f}", "Gap KD": "{:,.0f}",
                     "SSL %": "{:.1f}%"})
            .applymap(color_ssl_cat, subset=["SSL %"])
        )
        st.dataframe(styled_cat, use_container_width=True)


# ── TAB 3: Undelivered SKUs ───────────────────────────────────────────────
with tab_sku:
    if sku_df.empty:
        st.info("No undelivered SKU data available (requires 'Received Qty.' column).")
    else:
        st.markdown(
            f"**{len(sku_df):,} SKUs** with zero delivery in {sel_label} — "
            f"total PO value **{sku_df['PO Value KD'].sum():,.0f} KD**"
        )
        srch = st.text_input("🔍 Search SKU / Item Name / Vendor / Category", key="sku_search")
        disp = sku_df
        if srch:
            mask = pd.Series(False, index=disp.index)
            for col in ["SKU", "Item Name", "Vendor", "Category", "Brand"]:
                if col in disp.columns:
                    mask |= disp[col].astype(str).str.contains(srch, case=False, na=False)
            disp = disp[mask]

        st.dataframe(
            disp.style.format({"PO Value KD": "{:,.0f}", "Ordered Qty": "{:,.0f}"}),
            use_container_width=True,
            height=550,
        )


# ── TAB 4: Item-Level Lines ───────────────────────────────────────────────
with tab_lines:
    if lines_df.empty:
        st.info("No item-level line data available (requires 'Received Qty.' column).")
    else:
        st.markdown(
            f"**{len(lines_df):,} individual PO lines** with zero received qty in {sel_label}. "
            f"Each row is one purchase order line."
        )

        srch2 = st.text_input("🔍 Search PO No. / Item / Vendor / Category", key="lines_search")
        disp2 = lines_df
        if srch2:
            mask2 = pd.Series(False, index=disp2.index)
            for col in ["PO Number", "Item No.", "Item Name", "Vendor", "Category", "Brand", "Line Status"]:
                if col in disp2.columns:
                    mask2 |= disp2[col].astype(str).str.contains(srch2, case=False, na=False)
            disp2 = disp2[mask2]

        def hl_status(val):
            if str(val).strip().lower() == "open":
                return "background-color:#FFFBEB; color:#92400E"
            return ""

        styled_lines = disp2.style.format({
            "Ordered Qty": "{:,.0f}",
            "Received Qty": "{:,.0f}",
            "Line Value KD": "{:,.0f}",
        })
        if "Line Status" in disp2.columns:
            styled_lines = styled_lines.applymap(hl_status, subset=["Line Status"])

        st.dataframe(styled_lines, use_container_width=True, height=600)


# ── TAB 5: Download Excel ─────────────────────────────────────────────────
with tab_dl:
    st.markdown(f"### ⬇️ Download {sel_label} Report")

    # Check for pre-built file first
    prebuilt_name = f"{sel_label.replace(' ', '_')}_Procurement_Report.xlsx"
    # e.g. August_2026_Procurement_Report.xlsx
    prebuilt_path = DOWNLOADS / prebuilt_name

    if prebuilt_path.exists():
        with open(prebuilt_path, "rb") as f:
            st.download_button(
                label=f"📥 Download {prebuilt_name}",
                data=f.read(),
                file_name=prebuilt_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Pre-built Excel with styled sheets, colour coding, and item-level detail",
            )
        st.success(f"Pre-built report available — includes styled sheets, colour coding, "
                   f"and the full {len(lines_df):,}-row item-level sheet.")
        st.markdown("---")

    # Always offer a live-generated version
    st.markdown("#### Or generate a fresh report now:")
    if st.button("⚙️ Generate Excel from current data", type="primary"):
        with st.spinner("Building Excel…"):
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                wb   = writer.book
                hdr  = wb.add_format({"bold": True, "bg_color": "#0D1520", "font_color": "#FFFFFF",
                                       "border": 1, "align": "center", "font_name": "Calibri", "font_size": 10})
                num  = wb.add_format({"num_format": "#,##0.00", "border": 1, "font_name": "Calibri", "font_size": 10})
                pct  = wb.add_format({"num_format": "0.0%",     "border": 1, "font_name": "Calibri", "font_size": 10, "align": "right"})
                txt  = wb.add_format({"border": 1, "font_name": "Calibri", "font_size": 10})
                grn  = wb.add_format({"num_format": "0.0%", "border": 1, "font_name": "Calibri", "font_size": 10,
                                       "align": "right", "bg_color": "#ECFDF5", "font_color": "#065F46"})
                amb  = wb.add_format({"num_format": "0.0%", "border": 1, "font_name": "Calibri", "font_size": 10,
                                       "align": "right", "bg_color": "#FFFBEB", "font_color": "#92400E"})
                red  = wb.add_format({"num_format": "0.0%", "border": 1, "font_name": "Calibri", "font_size": 10,
                                       "align": "right", "bg_color": "#FEF2F2", "font_color": "#991B1B"})

                def write_sheet(df, sheet_name, ssl_col=None, tab_color=None):
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    ws = writer.sheets[sheet_name]
                    if tab_color:
                        ws.set_tab_color(tab_color)
                    for col_idx, col_name in enumerate(df.columns):
                        ws.write(0, col_idx, col_name, hdr)
                        ws.set_column(col_idx, col_idx, max(14, len(str(col_name)) + 2))
                    if ssl_col and ssl_col in df.columns:
                        s_idx = df.columns.get_loc(ssl_col)
                        for row_idx, val in enumerate(df[ssl_col], start=1):
                            pct_val = val / 100 if val > 1 else val
                            fmt = grn if val >= 80 else (amb if val >= 30 else red)
                            ws.write(row_idx, s_idx, pct_val, fmt)
                    ws.autofilter(0, 0, len(df), len(df.columns) - 1)
                    ws.freeze_panes(1, 0)

                # Sheet 1: Vendor Performance
                v_export = vendor.copy()
                v_export["SSL %"] = v_export["SSL %"]   # keep as number for Excel
                write_sheet(v_export, "Vendor Performance", ssl_col="SSL %", tab_color="#1D4ED8")

                # Sheet 2: By Category
                if not cat_df.empty:
                    write_sheet(cat_df, "By Category", ssl_col="SSL %", tab_color="#7C3AED")

                # Sheet 3: Undelivered SKUs
                if not sku_df.empty:
                    write_sheet(sku_df, "Undelivered SKUs", tab_color="#DC2626")

                # Sheet 4: Item-Level Lines (zero received)
                if not lines_df.empty:
                    lines_df.to_excel(writer, sheet_name="Item-Level Lines", index=False)
                    ws4 = writer.sheets["Item-Level Lines"]
                    ws4.set_tab_color("#F59E0B")
                    for col_idx, col_name in enumerate(lines_df.columns):
                        ws4.write(0, col_idx, col_name, hdr)
                        ws4.set_column(col_idx, col_idx, max(14, len(str(col_name)) + 2))
                    if "Line Status" in lines_df.columns:
                        s_idx = lines_df.columns.get_loc("Line Status")
                        open_fmt = wb.add_format({"bg_color": "#FFFBEB", "font_color": "#92400E",
                                                   "border": 1, "font_name": "Calibri", "font_size": 10})
                        for row_idx, val in enumerate(lines_df["Line Status"], start=1):
                            if str(val).strip().lower() == "open":
                                ws4.write(row_idx, s_idx, val, open_fmt)
                    ws4.autofilter(0, 0, len(lines_df), len(lines_df.columns) - 1)
                    ws4.freeze_panes(1, 0)

            buf.seek(0)
            fname = prebuilt_name
            st.download_button(
                label=f"📥 Download {fname}",
                data=buf.read(),
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.success("Done! Click the button above to download.")

    st.markdown("""
**Sheets included:**
| Sheet | Contents |
|---|---|
| Vendor Performance | All vendors — PO Value, Received, Gap, SSL % (colour coded) |
| By Category | Category breakdown with PO vs Received |
| Undelivered SKUs | Aggregated SKUs with zero delivery, PO numbers included |
| Item-Level Lines | Every individual PO line where nothing was received (amber = Open) |
""")
