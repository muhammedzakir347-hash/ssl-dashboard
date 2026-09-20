"""
pages/gp.py  -  GP & Profitability deep-dive
Access at /gp  (direct URL - not linked anywhere in the app)
Protected by GP_PASSWORD env var / Streamlit secret.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# page config handled by app.py

# -- Global CSS: fit to screen, responsive --------------------------------
st.markdown("""
<style>
.block-container {
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
    max-width: 100% !important;
}
.js-plotly-plot, .plotly, .plot-container {
    max-width: 100% !important;
    width: 100% !important;
}
[data-testid="stDataFrame"] { overflow-x: auto; }

.kpi-grid-4 {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-bottom: 10px;
}
.kpi-grid-3 {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: 14px;
}
.kpi-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    padding: 12px 16px;
}
.kpi-label {
    font-size: 10px;
    color: #888;
    text-transform: uppercase;
    letter-spacing: .06em;
    margin-bottom: 4px;
}
.kpi-value { font-size: 20px; font-weight: 700; line-height: 1.2; }
.kpi-unit  { font-size: 11px; color: #888; }

@media (max-width: 900px) {
    .kpi-grid-4 { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 500px) {
    .kpi-grid-4, .kpi-grid-3 { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
    [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 0 !important;
    }
}
</style>
""", unsafe_allow_html=True)

# -- helpers ---------------------------------------------------------------
def _style_gp(val):
    if val < 0:   return "background-color:#FEF2F2;color:#991B1B"
    if val < 5:   return "background-color:#FFF7ED;color:#C2410C"
    if val < 15:  return "background-color:#FFFBEB;color:#92400E"
    return "background-color:#ECFDF5;color:#065F46"


def _apply(styler, fn, cols):
    try:
        return styler.map(fn, subset=cols)
    except AttributeError:
        return styler.applymap(fn, subset=cols)




# ==========================================================================
# DATA LOADING  (lazy: months list first, then range on demand)
# ==========================================================================
GP_DIR = Path(__file__).parent.parent / "downloads" / "gp"

_BQ_COL_MAP = {
    "Posting_Date":     "Posting Date",
    "Item_No":          "Item No.",
    "Item_Name":        "Item Name",
    "Sales_Qty":        "Sales Qty",
    "Sales_Value__KWD": "Sales Value (KWD)",
    "COGS__KWD":        "COGS (KWD)",
    "GP__KWD":          "GP (KWD)",
    "GP":               "GP%",
}


@st.cache_data(ttl=3600, show_spinner=False)
def _gp_months_local() -> list[str]:
    """Return available months from local CSV files (fast)."""
    months = set()
    for f in GP_DIR.glob("*_gp.csv"):
        m = f.stem.replace("_gp", "")
        if len(m) == 7:
            months.add(m)
    return sorted(months)


@st.cache_data(ttl=3600, show_spinner=False)
def _gp_months_bq() -> list[str]:
    """Return available months from BigQuery (cheap DISTINCT query)."""
    try:
        import bigquery_client as bq
        return bq.get_distinct_months(bq.TABLE_GP)
    except Exception:
        return []


@st.cache_data(ttl=1800, show_spinner="Loading GP data ...")
def load_gp_range(from_month: str, to_month: str) -> pd.DataFrame:
    """Load GP data for the selected month range only — avoids loading 3M+ rows."""
    # Local CSVs first (dev)
    local_files = [
        GP_DIR / f"{m}_gp.csv"
        for m in _gp_months_local()
        if from_month <= m <= to_month
    ]
    if local_files:
        dfs = [pd.read_csv(f) for f in local_files if f.exists()]
        df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    else:
        try:
            import bigquery_client as bq
            df = bq.read_table_range(bq.TABLE_GP, from_month, to_month)
        except Exception as e:
            st.error(f"Could not load GP data: {e}")
            return pd.DataFrame()

    if df.empty:
        return df

    df = df.rename(columns=_BQ_COL_MAP)
    df["Posting Date"] = pd.to_datetime(df["Posting Date"], errors="coerce")
    df["Month"] = df["Posting Date"].dt.to_period("M").astype(str)
    df["DOW"]   = df["Posting Date"].dt.day_name()
    for col in ["Sales Qty", "Sales Value (KWD)", "COGS (KWD)", "GP (KWD)", "GP%"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


# ==========================================================================
# SIDEBAR - FILTERS  (show month picker before loading data)
# ==========================================================================
with st.sidebar:
    st.markdown("### Filters")

    # Get month list cheaply — no full data load yet
    all_months = _gp_months_local() or _gp_months_bq()
    if not all_months:
        st.error("No GP data found. Run fetch_gp_report.py or check BigQuery.")
        st.stop()

    def_start = all_months[-6] if len(all_months) >= 6 else all_months[0]
    def_end   = all_months[-1]

    col_s, col_e = st.columns(2)
    with col_s:
        from_month = st.selectbox("From", all_months, index=all_months.index(def_start))
    with col_e:
        to_month = st.selectbox("To", all_months, index=all_months.index(def_end))

    if from_month > to_month:
        st.error("'From' must be before 'To'.")
        st.stop()

# Load only the selected range (cached per range)
raw = load_gp_range(from_month, to_month)

if raw.empty:
    st.warning("No GP data for selected period.")
    st.stop()

with st.sidebar:
    cats = sorted(raw["Category"].dropna().unique())
    sel_cats = st.multiselect("Category", cats, placeholder="All categories")

    brands = sorted(raw["Brand"].dropna().unique())
    sel_brands = st.multiselect("Brand", brands, placeholder="All brands")

    item_q = st.text_input("Search item", placeholder="Name or item no.")
    min_sales = st.number_input("Min Sales Value (KWD)", min_value=0, value=0, step=500)

    # Day-level date filter
    st.markdown("---")
    st.markdown("**Date range (day)**")
    _min_date = raw["Posting Date"].min().date()
    _max_date = raw["Posting Date"].max().date()
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        sel_date_from = st.date_input("From date", value=_min_date,
                                      min_value=_min_date, max_value=_max_date,
                                      key="date_from")
    with col_d2:
        sel_date_to   = st.date_input("To date", value=_max_date,
                                      min_value=_min_date, max_value=_max_date,
                                      key="date_to")

df = raw.copy()
if sel_cats:   df = df[df["Category"].isin(sel_cats)]
if sel_brands: df = df[df["Brand"].isin(sel_brands)]
if item_q:
    df = df[
        df["Item Name"].str.contains(item_q, case=False, na=False) |
        df["Item No."].str.contains(item_q, case=False, na=False)
    ]

# Apply day-level filter
df = df[
    (df["Posting Date"].dt.date >= sel_date_from) &
    (df["Posting Date"].dt.date <= sel_date_to)
]

period_label = (
    f"{sel_date_from} to {sel_date_to}"
    if (sel_date_from != _min_date or sel_date_to != _max_date)
    else f"{from_month} to {to_month}"
)

if df.empty:
    st.warning("No data for selected filters.")
    st.stop()


# ==========================================================================
# KPI STRIP
# ==========================================================================
total_sales  = df["Sales Value (KWD)"].sum()
total_cogs   = df["COGS (KWD)"].sum()
total_gp     = df["GP (KWD)"].sum()
total_gp_pct = total_gp / total_sales * 100 if total_sales else 0
n_items      = df["Item No."].nunique()
n_brands     = df["Brand"].nunique()
n_sell_days  = df["Posting Date"].nunique()

gp_color = "#10B981" if total_gp_pct >= 15 else "#EF4444"
gp_label = "above target" if total_gp_pct >= 15 else "below 15%"

st.markdown(f"""
<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:10px">
  <span style="font-size:18px;font-weight:700">GP &amp; Profitability</span>
  <span style="font-size:12px;color:#888">{period_label}</span>
</div>
<div class="kpi-grid-4">
  <div class="kpi-card">
    <div class="kpi-label">Sales Value</div>
    <div class="kpi-value">{total_sales:,.0f} <span class="kpi-unit">KWD</span></div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">COGS</div>
    <div class="kpi-value">{total_cogs:,.0f} <span class="kpi-unit">KWD</span></div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Gross Profit</div>
    <div class="kpi-value">{total_gp:,.0f} <span class="kpi-unit">KWD</span></div>
  </div>
  <div class="kpi-card" style="border-color:{gp_color}55;border-width:2px">
    <div class="kpi-label">GP%</div>
    <div class="kpi-value" style="font-size:26px;color:{gp_color}">{total_gp_pct:.1f}%</div>
    <div style="font-size:11px;color:{gp_color}">{gp_label}</div>
  </div>
</div>
<div class="kpi-grid-3">
  <div class="kpi-card">
    <div class="kpi-label">Items Sold</div>
    <div class="kpi-value">{n_items:,}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Brands</div>
    <div class="kpi-value">{n_brands:,}</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Selling Days</div>
    <div class="kpi-value">{n_sell_days:,}</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ==========================================================================
# TABS
# ==========================================================================
tab_ov, tab_item, tab_daily, tab_gap, tab_trend = st.tabs([
    "Overview",
    "Item Analysis",
    "Daily Pattern",
    "Gap & Promo",
    "Trending",
])


# --------------------------------------------------------------------------
# TAB 1  OVERVIEW
# --------------------------------------------------------------------------
with tab_ov:
    monthly = (
        df.groupby("Month")[["Sales Value (KWD)", "COGS (KWD)", "GP (KWD)", "Sales Qty"]]
        .sum().reset_index()
    )
    monthly["GP%"] = (monthly["GP (KWD)"] / monthly["Sales Value (KWD)"] * 100).where(
        monthly["Sales Value (KWD)"] > 0, 0
    ).round(2)

    fig_sales = go.Figure()
    fig_sales.add_bar(x=monthly["Month"], y=monthly["Sales Value (KWD)"],
                      name="Sales (KWD)", marker_color="#3B82F6", opacity=0.85)
    fig_sales.add_bar(x=monthly["Month"], y=monthly["COGS (KWD)"],
                      name="COGS (KWD)", marker_color="#EF4444", opacity=0.85)
    fig_sales.add_bar(x=monthly["Month"], y=monthly["GP (KWD)"],
                      name="GP (KWD)", marker_color="#10B981", opacity=0.9)
    fig_sales.update_layout(
        title="Monthly Sales / COGS / GP  (KWD)",
        barmode="group",
        yaxis=dict(title="KWD", tickformat=","),
        legend=dict(orientation="h", y=1.08),
        height=300,
        margin=dict(t=45, b=10, l=10, r=10),
    )
    st.plotly_chart(fig_sales, width="stretch")

    fig_gp_pct = go.Figure()
    fig_gp_pct.add_scatter(
        x=monthly["Month"], y=monthly["GP%"],
        mode="lines+markers+text",
        line=dict(color="#10B981", width=3),
        marker=dict(size=9, color="#10B981"),
        text=[f"{v:.1f}%" for v in monthly["GP%"]],
        textposition="top center",
    )
    fig_gp_pct.add_hline(y=15, line_dash="dash", line_color="#F59E0B", line_width=1.5,
                         annotation_text="15% target", annotation_position="right")
    fig_gp_pct.update_layout(
        title="GP% Monthly Trend",
        yaxis=dict(title="GP%", ticksuffix="%",
                   range=[0, max(35, monthly["GP%"].max() + 5)]),
        height=220,
        margin=dict(t=40, b=10, l=10, r=60),
        showlegend=False,
    )
    st.plotly_chart(fig_gp_pct, width="stretch")

    c1, c2 = st.columns(2)

    with c1:
        brand_s = (
            df.groupby("Brand")[["Sales Value (KWD)", "GP (KWD)"]].sum().reset_index()
        )
        brand_s["GP%"] = (brand_s["GP (KWD)"] / brand_s["Sales Value (KWD)"] * 100).where(
            brand_s["Sales Value (KWD)"] > 100, 0
        ).round(2)
        top15 = brand_s.nlargest(15, "GP (KWD)").sort_values("GP (KWD)")
        fig2 = px.bar(top15, x="GP (KWD)", y="Brand", orientation="h",
                      color="GP%", color_continuous_scale=["#EF4444","#F59E0B","#10B981"],
                      range_color=[0, 30], title="Top 15 Brands by GP (KWD)")
        fig2.update_layout(height=360, margin=dict(l=5, r=5, t=40, b=5),
                           xaxis=dict(tickformat=","))
        st.plotly_chart(fig2, width="stretch")

    with c2:
        cat_s = (
            df.groupby("Category")[["Sales Value (KWD)", "GP (KWD)"]].sum().reset_index()
        )
        cat_s["GP%"] = (cat_s["GP (KWD)"] / cat_s["Sales Value (KWD)"] * 100).where(
            cat_s["Sales Value (KWD)"] > 0, 0
        ).round(2)
        n_cats = cat_s["Category"].nunique()
        fig3 = px.bar(cat_s.sort_values("GP%"), x="GP%", y="Category", orientation="h",
                      color="GP%", color_continuous_scale=["#EF4444","#F59E0B","#10B981"],
                      range_color=[0, 30], title="GP% by Category")
        fig3.update_layout(height=max(320, n_cats * 24 + 60),
                           margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig3, width="stretch")

    st.markdown("#### Brands dragging GP% down")
    worst = (
        brand_s[brand_s["Sales Value (KWD)"] > 500]
        .nsmallest(15, "GP%").sort_values("GP%")
    )
    fig4 = px.bar(worst, x="GP%", y="Brand", orientation="h",
                  color="GP%", color_continuous_scale=["#EF4444","#F59E0B","#10B981"],
                  range_color=[-10, 20], title="Lowest GP% Brands (min 500 KWD sales)")
    fig4.add_vline(x=0,  line_dash="solid", line_color="#EF4444", line_width=1)
    fig4.add_vline(x=15, line_dash="dash",  line_color="#10B981", line_width=1,
                   annotation_text="15% target", annotation_position="top right")
    fig4.update_layout(height=340, margin=dict(l=5, r=5, t=40, b=5))
    st.plotly_chart(fig4, width="stretch")


# --------------------------------------------------------------------------
# TAB 2  ITEM ANALYSIS
# --------------------------------------------------------------------------
with tab_item:
    item_agg = (
        df.groupby(["Item No.", "Item Name", "Brand", "Category", "Vendor"])
        .agg(
            Qty       =("Sales Qty",         "sum"),
            Sales     =("Sales Value (KWD)", "sum"),
            COGS      =("COGS (KWD)",         "sum"),
            GP        =("GP (KWD)",           "sum"),
            Sell_Days =("Posting Date",       "nunique"),
        )
        .reset_index()
    )
    item_agg["GP%"]     = (item_agg["GP"] / item_agg["Sales"] * 100).where(item_agg["Sales"] > 0, 0).round(3)
    item_agg["Avg/Day"] = (item_agg["Sales"] / item_agg["Sell_Days"]).round(3)

    # --- coupon / promo detection (real data from OrderAdjustmentGroupSummary) ---
    # Load coupon CSVs for the selected months and aggregate per item
    _coupon_months = sorted(df["Month"].unique())
    _coupon_dfs = []
    for _cm in _coupon_months:
        _cf = GP_DIR / f"{_cm}_coupons.csv"
        if _cf.exists():
            _coupon_dfs.append(pd.read_csv(_cf))
    if _coupon_dfs:
        coupon_df = (
            pd.concat(_coupon_dfs, ignore_index=True)
            .groupby("Item No.", as_index=False)
            .agg(
                Coupon_Orders=("Coupon_Orders", "sum"),
                Coupon_Names =("Coupon_Names",  lambda x: ", ".join(sorted(set(
                    n.strip() for v in x for n in str(v).split(",")
                )))),
                Coupon_KWD   =("Coupon_KWD",    "sum"),
            )
        )
        coupon_df["Coupon_KWD"] = coupon_df["Coupon_KWD"].round(3)
    else:
        coupon_df = pd.DataFrame(columns=["Item No.", "Coupon_Orders", "Coupon_Names", "Coupon_KWD"])

    item_agg = item_agg.merge(coupon_df, on="Item No.", how="left")
    item_agg["Coupon_Orders"] = item_agg["Coupon_Orders"].fillna(0).astype(int)
    item_agg["Coupon_Names"]  = item_agg["Coupon_Names"].fillna("")
    item_agg["Coupon_KWD"]    = item_agg["Coupon_KWD"].fillna(0.0)

    # Fallback: negative-GP days as supplemental signal when coupon CSV not available
    neg_gp_days = (
        df[df["GP (KWD)"] < 0]
        .groupby("Item No.")["Posting Date"].nunique()
        .rename("Neg_GP_Days")
    )
    item_agg = item_agg.join(neg_gp_days, on="Item No.", how="left")
    item_agg["Neg_GP_Days"] = item_agg["Neg_GP_Days"].fillna(0).astype(int)

    def _gp_risk(row):
        if row["GP%"] < 0:
            return "Pricing issue"
        if row["Coupon_Orders"] > 0 or row["Neg_GP_Days"] > 0:
            return "Coupon/Promo"
        return "Normal"
    item_agg["GP Risk"] = item_agg.apply(_gp_risk, axis=1)
    _has_real_coupons = not coupon_df.empty
    # -------------------------------------------------------------------------

    if min_sales > 0:
        item_agg = item_agg[item_agg["Sales"] >= min_sales]

    col_sort, col_top, col_flag = st.columns([3, 1, 2])
    with col_sort:
        sort_by = st.selectbox("Sort by",
                               ["GP (KWD)", "Sales (KWD)", "GP%", "Qty", "Selling Days"],
                               key="i_sort")
    with col_top:
        top_n = st.selectbox("Show", [50, 100, 250, 500, "All"], key="i_top")
    with col_flag:
        filter_risk = st.selectbox("GP Risk filter",
                                   ["All", "Coupon/Promo", "Pricing issue", "Normal"],
                                   key="i_risk")

    sort_map = {"GP (KWD)": "GP", "Sales (KWD)": "Sales", "GP%": "GP%",
                "Qty": "Qty", "Selling Days": "Sell_Days"}
    view = item_agg.copy()
    if filter_risk != "All":
        view = view[view["GP Risk"] == filter_risk]
    view = view.sort_values(sort_map[sort_by], ascending=False)
    if top_n != "All":
        view = view.head(int(top_n))
    view = view.reset_index(drop=True)
    view.insert(0, "Rank", range(1, len(view) + 1))

    def _style_risk(val):
        if val == "Pricing issue": return "background-color:#FEF2F2;color:#991B1B"
        if val == "Coupon/Promo":  return "background-color:#FFF7ED;color:#C2410C"
        return ""

    # Build column list — include real coupon cols when available
    _base_cols = ["Rank", "Item No.", "Item Name", "Brand", "Category",
                  "Qty", "Sales", "COGS", "GP", "GP%", "Sell_Days", "Avg/Day", "GP Risk"]
    _rename = {"Sales": "Sales (KWD)", "COGS": "COGS (KWD)", "GP": "GP (KWD)",
               "Sell_Days": "Selling Days", "Avg/Day": "Avg/Day (KWD)"}
    _fmt    = {"Qty": "{:,.0f}", "Sales (KWD)": "{:,.3f}", "COGS (KWD)": "{:,.3f}",
               "GP (KWD)": "{:,.3f}", "GP%": "{:.2f}%", "Selling Days": "{:.0f}",
               "Avg/Day (KWD)": "{:,.3f}"}
    if _has_real_coupons:
        _base_cols = ["Rank", "Item No.", "Item Name", "Brand", "Category",
                      "Qty", "Sales", "COGS", "GP", "GP%", "Sell_Days", "Avg/Day",
                      "Coupon_Orders", "Coupon_Names", "Coupon_KWD", "GP Risk"]
        _rename.update({"Coupon_Orders": "Coupon Orders", "Coupon_Names": "Coupons Used",
                        "Coupon_KWD": "Coupon Impact (KWD)"})
        _fmt.update({"Coupon Orders": "{:,.0f}", "Coupon Impact (KWD)": "{:,.3f}"})
    else:
        _base_cols = ["Rank", "Item No.", "Item Name", "Brand", "Category",
                      "Qty", "Sales", "COGS", "GP", "GP%", "Sell_Days", "Avg/Day",
                      "Neg_GP_Days", "GP Risk"]
        _rename["Neg_GP_Days"] = "Promo Days"
        _fmt["Promo Days"] = "{:.0f}"

    styled = view[_base_cols].rename(columns=_rename).style.format(_fmt)
    styled = _apply(styled, _style_gp,  ["GP%"])
    styled = _apply(styled, _style_risk, ["GP Risk"])
    st.dataframe(styled, width="stretch", height=460)

    _dl_cols = [c for c in _base_cols if c != "Rank"]
    _dl_view = view[_dl_cols].rename(columns=_rename)
    st.download_button("⬇ Download Item Analysis",
                       _dl_view.to_csv(index=False),
                       file_name="gp_item_analysis.csv", mime="text/csv")

    # summary of coupon impact
    promo_items   = item_agg[item_agg["GP Risk"] == "Coupon/Promo"]
    pricing_items = item_agg[item_agg["GP Risk"] == "Pricing issue"]
    if not promo_items.empty or not pricing_items.empty:
        ci1, ci2 = st.columns(2)
        with ci1:
            if not promo_items.empty:
                if _has_real_coupons:
                    total_coupon_kwd = promo_items["Coupon_KWD"].sum()
                    top_coupons = (
                        promo_items["Coupon_Names"].str.split(", ").explode()
                        .value_counts().head(3).index.tolist()
                    )
                    st.info(
                        f"**{len(promo_items):,} items** bought with coupons "
                        f"(est. **{total_coupon_kwd:,.1f} KWD** discount). "
                        f"Top codes: {', '.join(top_coupons)}"
                    )
                else:
                    lost = promo_items["Neg_GP_Days"].sum()
                    st.info(
                        f"**{len(promo_items):,} items** have coupon/promo days "
                        f"({lost:,} total promo-day occurrences) reducing their profit."
                    )
        with ci2:
            if not pricing_items.empty:
                lost_gp = pricing_items["GP"].sum()
                st.error(
                    f"**{len(pricing_items):,} items** are priced below cost "
                    f"(total GP loss: {lost_gp:,.3f} KWD)."
                )

    st.markdown("---")
    st.markdown("#### Item Drilldown - daily breakdown")
    item_options = (
        item_agg.sort_values("Sales", ascending=False)
        .apply(lambda r: f"{r['Item No.']} - {r['Item Name']}", axis=1)
        .tolist()
    )
    sel_item_str = st.selectbox("Select item", ["(select an item)"] + item_options, key="i_drill")

    if sel_item_str != "(select an item)":
        sel_no = sel_item_str.split(" - ")[0].strip()
        item_daily = (
            df[df["Item No."] == sel_no]
            .groupby("Posting Date")[["Sales Qty", "Sales Value (KWD)", "GP (KWD)"]]
            .sum().reset_index().sort_values("Posting Date")
        )
        item_daily["GP%"] = (item_daily["GP (KWD)"] / item_daily["Sales Value (KWD)"] * 100).where(
            item_daily["Sales Value (KWD)"] > 0, 0
        ).round(2)
        avg_qty   = item_daily[item_daily["Sales Qty"] > 0]["Sales Qty"].mean() or 1
        item_daily["Spike"] = item_daily["Sales Qty"] > avg_qty * 3
        spike_pct = (item_daily[item_daily["Spike"]]["Sales Qty"].sum() /
                     max(item_daily["Sales Qty"].sum(), 1) * 100)
        sell_days = (item_daily["Sales Qty"] > 0).sum()
        zero_days = (item_daily["Sales Qty"] == 0).sum()

        dm1, dm2, dm3, dm4 = st.columns(4)
        dm1.metric("Selling Days",        f"{sell_days}")
        dm2.metric("Zero-Sales Days",     f"{zero_days}")
        dm3.metric("Spike Days (promo?)", f"{item_daily['Spike'].sum()}")
        dm4.metric("% from Spikes",       f"{spike_pct:.0f}%",
                   delta="promo-only" if spike_pct > 60 else "regular selling")

        colors = ["#EF4444" if s else "#3B82F6" for s in item_daily["Spike"]]
        fig_d = go.Figure()
        fig_d.add_bar(x=item_daily["Posting Date"], y=item_daily["Sales Qty"],
                      name="Qty", marker_color=colors)
        fig_d.add_scatter(x=item_daily["Posting Date"], y=item_daily["GP%"],
                          name="GP%", yaxis="y2", mode="lines+markers",
                          line=dict(color="#10B981", width=2), marker=dict(size=6))
        fig_d.add_hline(y=avg_qty * 3, line_dash="dot", line_color="#EF4444",
                        annotation_text="Spike threshold (3x avg)", yref="y")
        fig_d.update_layout(
            title=f"{sel_item_str}  |  red bars = spike days (promo likely)",
            yaxis =dict(title="Qty"),
            yaxis2=dict(title="GP%", overlaying="y", side="right", ticksuffix="%"),
            height=300,
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig_d, width="stretch")
        if zero_days > 0:
            st.caption(
                f"This item had {zero_days} days with zero sales. "
                "May be out of stock, discontinued, or promo-dependent."
            )


# --------------------------------------------------------------------------
# TAB 3  DAILY PATTERN
# --------------------------------------------------------------------------
with tab_daily:
    daily = (
        df.groupby("Posting Date")[["Sales Value (KWD)", "GP (KWD)", "Sales Qty"]]
        .sum().reset_index().sort_values("Posting Date")
    )
    daily["GP%"] = (daily["GP (KWD)"] / daily["Sales Value (KWD)"] * 100).where(
        daily["Sales Value (KWD)"] > 0, 0
    ).round(2)
    daily["DOW"] = daily["Posting Date"].dt.day_name()

    avg_d = daily[daily["Sales Value (KWD)"] > 0]["Sales Value (KWD)"].mean()
    daily["Gap"] = daily["Sales Value (KWD)"] < (avg_d * 0.2)

    colors_d = ["#EF4444" if g else "#3B82F6" for g in daily["Gap"]]
    fig_d2 = go.Figure()
    fig_d2.add_bar(x=daily["Posting Date"], y=daily["Sales Value (KWD)"],
                   name="Daily Sales (KWD)", marker_color=colors_d)
    fig_d2.add_scatter(x=daily["Posting Date"], y=[avg_d] * len(daily),
                       name=f"Daily Avg ({avg_d:,.0f} KWD)",
                       mode="lines", line=dict(color="#F59E0B", width=2, dash="dash"))
    fig_d2.update_layout(
        title="Daily Sales - red = gap day (< 20% of daily average)",
        yaxis=dict(title="KWD", tickformat=","),
        height=300, margin=dict(t=45, b=10),
    )
    st.plotly_chart(fig_d2, width="stretch")

    gap_days = daily[daily["Gap"]]
    st.caption(
        f"{len(gap_days)} gap days - sales below 20% of daily average ({avg_d:,.0f} KWD)"
    )

    dow_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    c1, c2 = st.columns(2)

    with c1:
        dow = daily.groupby("DOW")[["Sales Value (KWD)","GP%"]].mean().reset_index()
        dow["DOW"] = pd.Categorical(dow["DOW"], categories=dow_order, ordered=True)
        dow = dow.sort_values("DOW")
        fig_dow = px.bar(dow, x="DOW", y="Sales Value (KWD)",
                         color="GP%",
                         color_continuous_scale=["#EF4444","#F59E0B","#10B981"],
                         range_color=[0, 30], title="Avg Sales by Day of Week",
                         labels={"Sales Value (KWD)": "Avg Sales (KWD)"})
        fig_dow.update_layout(height=260, margin=dict(l=5, r=5, t=40, b=5),
                              yaxis=dict(tickformat=","))
        st.plotly_chart(fig_dow, width="stretch")

    with c2:
        fig_gp = px.line(daily, x="Posting Date", y="GP%", title="Daily GP% Trend")
        fig_gp.add_hline(y=15, line_dash="dash", line_color="#F59E0B",
                         annotation_text="15% target", annotation_position="top right")
        fig_gp.update_traces(line_color="#10B981", line_width=2)
        fig_gp.update_layout(height=260, margin=dict(l=5, r=5, t=40, b=5),
                              yaxis=dict(ticksuffix="%"))
        st.plotly_chart(fig_gp, width="stretch")

    st.markdown("#### GP% Heatmap - Month x Day of Week")
    hm_raw = (
        df.groupby(["Month", "DOW"])[["GP (KWD)", "Sales Value (KWD)"]].sum().reset_index()
    )
    hm_raw["GP%"] = (hm_raw["GP (KWD)"] / hm_raw["Sales Value (KWD)"] * 100).where(
        hm_raw["Sales Value (KWD)"] > 0, 0
    ).round(1)
    hm_pivot = hm_raw.pivot(index="Month", columns="DOW", values="GP%").reindex(
        columns=[d for d in dow_order if d in hm_raw["DOW"].unique()]
    )
    fig_hm = px.imshow(
        hm_pivot, color_continuous_scale="RdYlGn",
        zmin=0, zmax=30, aspect="auto",
        title="GP% by Month and Day of Week",
        labels=dict(color="GP%"),
    )
    fig_hm.update_layout(height=max(260, len(hm_pivot) * 26 + 80),
                         margin=dict(l=5, r=5, t=40, b=5))
    st.plotly_chart(fig_hm, width="stretch")

    if not gap_days.empty:
        st.markdown("#### Gap Days Detail")
        _gap_dl = gap_days[["Posting Date","DOW","Sales Value (KWD)","GP%"]].rename(
            columns={"Sales Value (KWD)":"Sales (KWD)"}).copy()
        _gap_dl["Posting Date"] = _gap_dl["Posting Date"].dt.strftime("%Y-%m-%d")
        st.dataframe(
            _gap_dl.style.format({"Sales (KWD)": "{:,.0f}", "GP%": "{:.1f}%"}),
            width='stretch', height=240,
        )
        st.download_button("⬇ Download Daily Data",
                           daily.assign(**{"Posting Date": daily["Posting Date"].dt.strftime("%Y-%m-%d")})
                               .to_csv(index=False),
                           file_name="gp_daily.csv", mime="text/csv")


# --------------------------------------------------------------------------
# TAB 4  GAP & PROMO
# --------------------------------------------------------------------------
with tab_gap:
    months_in = sorted(df["Month"].unique())
    n_m = len(months_in)

    if n_m < 2:
        st.info("Select at least 2 months to see gap & promo analysis.")
        st.stop()

    mid          = n_m // 2
    early_months = set(months_in[:mid])
    late_months  = set(months_in[mid:])

    item_by_month = (
        df.groupby(["Item No.", "Item Name", "Brand", "Category", "Month"])
        ["Sales Value (KWD)"].sum().reset_index()
    )
    sold_early = set(item_by_month[
        item_by_month["Month"].isin(early_months) & (item_by_month["Sales Value (KWD)"] > 0)
    ]["Item No."])
    sold_late = set(item_by_month[
        item_by_month["Month"].isin(late_months) & (item_by_month["Sales Value (KWD)"] > 0)
    ]["Item No."])

    dormant  = sold_early - sold_late
    new_itms = sold_late  - sold_early
    both     = sold_early & sold_late

    early_label = f"{sorted(early_months)[0]} to {sorted(early_months)[-1]}"
    late_label  = f"{sorted(late_months)[0]} to {sorted(late_months)[-1]}"

    st.markdown(f"Comparing **early period** ({early_label}) vs **recent period** ({late_label})")
    gm1, gm2, gm3 = st.columns(3)
    gm1.metric("Dormant Items",    len(dormant),    help="Sold early but ZERO recently")
    gm2.metric("New Items",        len(new_itms),   help="Only appeared in the recent period")
    gm3.metric("Consistent Items", len(both),       help="Sold in both halves")

    st.markdown("---")
    sub_dorm, sub_promo, sub_neg = st.tabs([
        "Dormant Items",
        "Promo-Dependent",
        "Negative GP",
    ])

    with sub_dorm:
        if not dormant:
            st.success("No dormant items.")
        else:
            dorm_df = (
                df[df["Item No."].isin(dormant)]
                .groupby(["Item No.", "Item Name", "Brand", "Category"])
                .agg(Last_Sale=("Posting Date","max"),
                     Sales_KWD=("Sales Value (KWD)","sum"),
                     GP_KWD   =("GP (KWD)","sum"),
                     Qty      =("Sales Qty","sum"))
                .reset_index()
                .sort_values("Sales_KWD", ascending=False)
            )
            dorm_df["GP%"]       = (dorm_df["GP_KWD"] / dorm_df["Sales_KWD"] * 100).round(2)
            dorm_df["Last Sale"] = dorm_df["Last_Sale"].dt.strftime("%Y-%m-%d")
            st.markdown(f"**{len(dorm_df):,} items** stopped selling in the recent period.")
            _dorm_dl = dorm_df[["Item No.","Item Name","Brand","Category",
                                 "Last Sale","Qty","Sales_KWD","GP_KWD","GP%"]].rename(
                columns={"Sales_KWD":"Sales (KWD)","GP_KWD":"GP (KWD)"})
            st.dataframe(
                _dorm_dl.style.format({"Qty":"{:,.0f}","Sales (KWD)":"{:,.0f}",
                               "GP (KWD)":"{:,.0f}","GP%":"{:.1f}%"}),
                width='stretch', height=400,
            )
            st.download_button("⬇ Download Dormant Items",
                               _dorm_dl.to_csv(index=False),
                               file_name="gp_dormant_items.csv", mime="text/csv")

    with sub_promo:
        st.markdown("Items where **60%+ of qty came from spike days** (3x avg) - promo-dependent.")
        idaily = (
            df.groupby(["Item No.", "Item Name", "Brand", "Posting Date"])["Sales Qty"]
            .sum().reset_index()
        )
        avg_per = (
            idaily[idaily["Sales Qty"] > 0]
            .groupby("Item No.")["Sales Qty"]
            .agg(avg_qty="mean", total_qty="sum", sell_days="count")
            .reset_index()
        )
        idaily2 = idaily.merge(avg_per[["Item No.", "avg_qty"]], on="Item No.", how="left")
        idaily2["Spike"] = idaily2["Sales Qty"] > idaily2["avg_qty"] * 3
        spike_vol = idaily2[idaily2["Spike"]].groupby("Item No.")["Sales Qty"].sum().rename("spike_qty")
        promo = avg_per.merge(spike_vol, on="Item No.", how="left").fillna({"spike_qty": 0})
        promo["Spike%"] = (promo["spike_qty"] / promo["total_qty"] * 100).round(1)
        promo = promo[promo["Spike%"] >= 60].sort_values("Spike%", ascending=False)
        meta = df[["Item No.", "Item Name", "Brand", "Category"]].drop_duplicates("Item No.")
        promo = promo.merge(meta, on="Item No.", how="left")
        sv    = df.groupby("Item No.")["Sales Value (KWD)"].sum().reset_index()
        promo = promo.merge(sv, on="Item No.", how="left")

        if promo.empty:
            st.success("No promo-dependent items found.")
        else:
            _promo_dl = promo[["Item No.","Item Name","Brand","Category",
                                "Sales Value (KWD)","total_qty","sell_days","Spike%"]].rename(
                columns={"Sales Value (KWD)":"Sales (KWD)","total_qty":"Total Qty",
                         "sell_days":"Selling Days","Spike%":"Spike Day %"})
            st.dataframe(
                _promo_dl.style.format({"Sales (KWD)":"{:,.0f}","Total Qty":"{:,.0f}","Spike Day %":"{:.1f}%"}),
                width='stretch', height=400,
            )
            st.download_button("⬇ Download Promo-Dependent Items",
                               _promo_dl.to_csv(index=False),
                               file_name="gp_promo_items.csv", mime="text/csv")

    with sub_neg:
        st.markdown("Items **sold below cost** - losing money on every unit.")
        neg = (
            df.groupby(["Item No.", "Item Name", "Brand", "Category"])
            .agg(Sales_KWD=("Sales Value (KWD)","sum"), GP_KWD=("GP (KWD)","sum"),
                 Qty=("Sales Qty","sum"), Days=("Posting Date","nunique"))
            .reset_index()
        )
        neg["GP%"] = (neg["GP_KWD"] / neg["Sales_KWD"] * 100).where(neg["Sales_KWD"] > 0, 0).round(2)
        neg = neg[neg["GP%"] < 0].sort_values("GP_KWD")
        if neg.empty:
            st.success("No items with negative GP.")
        else:
            st.error(f"{len(neg):,} items are selling below cost!")
            _neg_dl = neg[["Item No.","Item Name","Brand","Category","Qty","Sales_KWD","GP_KWD","GP%","Days"]].rename(
                columns={"Sales_KWD":"Sales (KWD)","GP_KWD":"GP (KWD)","Days":"Selling Days"})
            st.dataframe(
                _neg_dl.style.format({"Qty":"{:,.0f}","Sales (KWD)":"{:,.3f}",
                               "GP (KWD)":"{:,.3f}","GP%":"{:.2f}%"}),
                width='stretch', height=400,
            )
            st.download_button("⬇ Download Below-Cost Items",
                               _neg_dl.to_csv(index=False),
                               file_name="gp_below_cost_items.csv", mime="text/csv")

# ==========================================================================
# TAB 5  TRENDING
# ==========================================================================
with tab_trend:
    st.markdown("### Trending Items")

    sub_hot, sub_rising, sub_new, sub_seasonal = st.tabs([
        "🔥 Hot Right Now",
        "📈 Rising",
        "🆕 New Arrivals",
        "📅 Seasonal",
    ])

    # ── shared helpers ──────────────────────────────────────────────────────
    all_months = sorted(df["Month"].unique())
    last_month = all_months[-1] if all_months else None
    prev_months = all_months[:-1] if len(all_months) > 1 else []

    meta_cols = ["Item No.", "Item Name", "Brand", "Category"]

    def _meta(base_df):
        return base_df[meta_cols].drop_duplicates("Item No.")

    # ── HOT RIGHT NOW ───────────────────────────────────────────────────────
    with sub_hot:
        if last_month is None:
            st.info("No data available.")
        else:
            st.markdown(f"**Top 20 items by Sales Value** in **{last_month}**")
            hot = (
                df[df["Month"] == last_month]
                .groupby(["Item No.", "Item Name", "Brand", "Category"])
                .agg(
                    Sales_KWD=("Sales Value (KWD)", "sum"),
                    GP_KWD   =("GP (KWD)",          "sum"),
                    Qty      =("Sales Qty",          "sum"),
                    Days     =("Posting Date",       "nunique"),
                )
                .reset_index()
                .sort_values("Sales_KWD", ascending=False)
                .head(20)
            )
            hot["GP%"]      = (hot["GP_KWD"] / hot["Sales_KWD"] * 100).where(hot["Sales_KWD"] > 0, 0).round(2)
            hot["Avg/Day"]  = (hot["Sales_KWD"] / hot["Days"]).round(3)
            hot["Rank"]     = range(1, len(hot) + 1)

            # bar chart
            chart_hot = hot[["Rank", "Item Name", "Sales_KWD"]].copy()
            chart_hot["Label"] = chart_hot["Rank"].astype(str) + ". " + chart_hot["Item Name"].str[:30]
            fig_h = go.Figure(go.Bar(
                x=chart_hot["Sales_KWD"],
                y=chart_hot["Label"],
                orientation="h",
                marker_color="#2ecc71",
                text=chart_hot["Sales_KWD"].map(lambda v: f"{v:,.0f}"),
                textposition="outside",
            ))
            fig_h.update_layout(
                height=500, margin=dict(l=10, r=60, t=30, b=10),
                xaxis_title="Sales (KWD)", yaxis=dict(autorange="reversed"),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_h, use_container_width=True)

            st.dataframe(
                hot[["Rank","Item No.","Item Name","Brand","Category","Qty","Sales_KWD","GP_KWD","GP%","Avg/Day","Days"]]
                .rename(columns={"Sales_KWD":"Sales (KWD)","GP_KWD":"GP (KWD)","Days":"Selling Days"})
                .style.format({
                    "Qty":"{:,.0f}","Sales (KWD)":"{:,.3f}",
                    "GP (KWD)":"{:,.3f}","GP%":"{:.2f}%",
                    "Avg/Day":"{:,.3f}","Selling Days":"{:,.0f}",
                }),
                width='stretch', height=400,
            )

    # ── RISING ──────────────────────────────────────────────────────────────
    with sub_rising:
        if last_month is None or len(all_months) < 2:
            st.info("Need at least 2 months of data loaded to compute rising trends. "
                    "Expand the **From** month in the sidebar.")
        else:
            growth_threshold = st.slider(
                "Min growth % vs prior average", 5, 100, 20, step=5,
                help="Show items where current-month sales exceed the prior average by at least this %"
            )
            lookback = all_months[-4:-1]  # up to 3 prior months
            st.markdown(
                f"Items where **{last_month}** sales exceed the "
                f"{'–'.join([lookback[0], lookback[-1]]) if len(lookback)>1 else lookback[0] if lookback else 'prior'} "
                f"average by **{growth_threshold}%+**"
            )

            cur = (
                df[df["Month"] == last_month]
                .groupby("Item No.")["Sales Value (KWD)"].sum()
                .rename("cur_sales")
            )
            prior = (
                df[df["Month"].isin(lookback)]
                .groupby(["Item No.", "Month"])["Sales Value (KWD)"].sum()
                .reset_index()
                .groupby("Item No.")["Sales Value (KWD)"]
                .mean()
                .rename("avg_sales")
            )
            rising = cur.to_frame().join(prior, how="inner")
            rising = rising[rising["avg_sales"] > 0].copy()
            rising["Growth%"] = ((rising["cur_sales"] - rising["avg_sales"]) / rising["avg_sales"] * 100).round(1)
            rising = rising[rising["Growth%"] >= growth_threshold].sort_values("Growth%", ascending=False)

            rising = rising.join(_meta(df).set_index("Item No."), how="left")

            if rising.empty:
                st.info(f"No items with {growth_threshold}%+ growth vs prior average. "
                        "Try lowering the slider above.")
            else:
                st.success(f"{len(rising):,} items growing {growth_threshold}%+ vs their prior average.")

                fig_r = go.Figure(go.Bar(
                    x=rising.head(20)["Growth%"],
                    y=rising.head(20).index.str[:] + " – " + rising.head(20)["Item Name"].str[:25].fillna(""),
                    orientation="h",
                    marker_color="#e74c3c",
                    text=rising.head(20)["Growth%"].map(lambda v: f"+{v:.1f}%"),
                    textposition="outside",
                ))
                fig_r.update_layout(
                    height=500, margin=dict(l=10, r=80, t=30, b=10),
                    xaxis_title="Growth % vs 3-month avg",
                    yaxis=dict(autorange="reversed"),
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_r, use_container_width=True)

                st.dataframe(
                    rising[["Item Name","Brand","Category","avg_sales","cur_sales","Growth%"]]
                    .rename(columns={
                        "avg_sales":"3M Avg Sales (KWD)",
                        "cur_sales":f"{last_month} Sales (KWD)",
                        "Growth%":"Growth %",
                    })
                    .style.format({
                        "3M Avg Sales (KWD)":"{:,.3f}",
                        f"{last_month} Sales (KWD)":"{:,.3f}",
                        "Growth %":"{:+.1f}%",
                    }),
                    width='stretch', height=400,
                )

    # ── NEW ARRIVALS ─────────────────────────────────────────────────────────
    with sub_new:
        cutoff_days = st.slider("New if first sale within last N days", 30, 120, 60, step=10)
        # Use raw (full selected period, no category filter) for first-sale dates
        # so category/brand filters don't hide an item's real history
        cutoff_date = raw["Posting Date"].max() - pd.Timedelta(days=cutoff_days)

        first_sale_all = raw.groupby("Item No.")["Posting Date"].min().rename("First Sale")
        # Keep only items that appear in the current (filtered) df
        items_in_view  = df["Item No."].unique()
        first_sale     = first_sale_all[first_sale_all.index.isin(items_in_view)]
        new_items      = first_sale[first_sale >= cutoff_date].reset_index()
        new_items      = new_items.join(_meta(df).set_index("Item No."), on="Item No.", how="left")

        totals = (
            df.groupby("Item No.")[["Sales Value (KWD)", "GP (KWD)", "Sales Qty"]]
            .sum()
            .rename(columns={"Sales Value (KWD)":"Sales_KWD","GP (KWD)":"GP_KWD","Sales Qty":"Qty"})
        )
        new_items = new_items.join(totals, on="Item No.", how="left")
        new_items["GP%"] = (new_items["GP_KWD"] / new_items["Sales_KWD"] * 100).where(new_items["Sales_KWD"] > 0, 0).round(2)
        new_items = new_items.sort_values("Sales_KWD", ascending=False)

        if new_items.empty:
            st.info(
                f"No items whose **first-ever sale in the loaded period** falls within the last {cutoff_days} days. "
                "Try increasing the slider or loading more historical months."
            )
        else:
            st.success(f"**{len(new_items):,} new items** with first sale since {cutoff_date.strftime('%Y-%m-%d')}.")
            st.dataframe(
                new_items[["Item No.","Item Name","Brand","Category","First Sale","Qty","Sales_KWD","GP_KWD","GP%"]]
                .rename(columns={"Sales_KWD":"Sales (KWD)","GP_KWD":"GP (KWD)"})
                .assign(**{"First Sale": new_items["First Sale"].dt.strftime("%Y-%m-%d")})
                .style.format({
                    "Qty":"{:,.0f}","Sales (KWD)":"{:,.3f}",
                    "GP (KWD)":"{:,.3f}","GP%":"{:.2f}%",
                }),
                width='stretch', height=400,
            )

    # ── SEASONAL ─────────────────────────────────────────────────────────────
    with sub_seasonal:
        if last_month is None:
            st.info("No data available.")
        else:
            # e.g. last_month = "2026-09" → same_month_ly = "2025-09"
            try:
                lm_period = pd.Period(last_month, "M")
                ly_period = lm_period - 12
                ly_month  = str(ly_period)
            except Exception:
                ly_month = None

            # Load last year's month independently — no need to expand the date filter
            ly_raw = pd.DataFrame()
            if ly_month:
                try:
                    ly_raw = load_gp_range(ly_month, ly_month)
                    # Apply same category/brand/item filters
                    if not ly_raw.empty:
                        if sel_cats:   ly_raw = ly_raw[ly_raw["Category"].isin(sel_cats)]
                        if sel_brands: ly_raw = ly_raw[ly_raw["Brand"].isin(sel_brands)]
                        if item_q:
                            ly_raw = ly_raw[
                                ly_raw["Item Name"].str.contains(item_q, case=False, na=False) |
                                ly_raw["Item No."].str.contains(item_q, case=False, na=False)
                            ]
                except Exception:
                    ly_raw = pd.DataFrame()

            if ly_raw.empty:
                st.info(
                    f"No data available for **{ly_month}** (same month last year). "
                    "It may not have been fetched yet — run the GP fetch for that month."
                )
            else:
                st.markdown(f"**{last_month}** vs **{ly_month}** — same month, year-over-year")

                def _month_agg(source_df, month):
                    return (
                        source_df[source_df["Month"] == month]
                        .groupby("Item No.")
                        .agg(Sales_KWD=("Sales Value (KWD)","sum"), GP_KWD=("GP (KWD)","sum"),
                             Qty=("Sales Qty","sum"))
                        .reset_index()
                    )

                cy = _month_agg(df,     last_month).set_index("Item No.")
                ly = _month_agg(ly_raw, ly_month).set_index("Item No.")

                seas = cy.join(ly, how="outer", lsuffix="_cy", rsuffix="_ly").fillna(0)
                seas["YoY_Sales%"] = ((seas["Sales_KWD_cy"] - seas["Sales_KWD_ly"]) /
                                      seas["Sales_KWD_ly"].replace(0, float("nan")) * 100).round(1)
                seas["YoY_GP%"]    = ((seas["GP_KWD_cy"] - seas["GP_KWD_ly"]) /
                                      seas["GP_KWD_ly"].replace(0, float("nan")) * 100).round(1)
                combined_meta = pd.concat([df[meta_cols], ly_raw[meta_cols]], ignore_index=True)
                seas = seas.join(_meta(combined_meta).set_index("Item No."), how="left")
                seas = seas.sort_values("Sales_KWD_cy", ascending=False).reset_index()

                col_a, col_b = st.columns(2)
                with col_a:
                    winners = seas.dropna(subset=["YoY_Sales%"]).nlargest(10, "YoY_Sales%")
                    fig_w = go.Figure(go.Bar(
                        x=winners["YoY_Sales%"],
                        y=winners["Item No."] + " " + winners["Item Name"].str[:20].fillna(""),
                        orientation="h",
                        marker_color="#27ae60",
                        text=winners["YoY_Sales%"].map(lambda v: f"+{v:.0f}%"),
                        textposition="outside",
                    ))
                    fig_w.update_layout(
                        title="Top 10 YoY Gainers", height=350,
                        margin=dict(l=5, r=60, t=40, b=5),
                        yaxis=dict(autorange="reversed"),
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(fig_w, use_container_width=True)

                with col_b:
                    losers = seas.dropna(subset=["YoY_Sales%"]).nsmallest(10, "YoY_Sales%")
                    fig_l = go.Figure(go.Bar(
                        x=losers["YoY_Sales%"],
                        y=losers["Item No."] + " " + losers["Item Name"].str[:20].fillna(""),
                        orientation="h",
                        marker_color="#e74c3c",
                        text=losers["YoY_Sales%"].map(lambda v: f"{v:.0f}%"),
                        textposition="outside",
                    ))
                    fig_l.update_layout(
                        title="Top 10 YoY Decliners", height=350,
                        margin=dict(l=5, r=60, t=40, b=5),
                        yaxis=dict(autorange="reversed"),
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(fig_l, use_container_width=True)

                st.dataframe(
                    seas[[
                        "Item No.","Item Name","Brand","Category",
                        "Sales_KWD_ly","Sales_KWD_cy","YoY_Sales%",
                        "GP_KWD_ly","GP_KWD_cy","YoY_GP%",
                    ]].rename(columns={
                        "Sales_KWD_ly":f"Sales {ly_month}","Sales_KWD_cy":f"Sales {last_month}",
                        "YoY_Sales%":"Sales YoY%",
                        "GP_KWD_ly":f"GP {ly_month}","GP_KWD_cy":f"GP {last_month}",
                        "YoY_GP%":"GP YoY%",
                    })
                    .style.format({
                        f"Sales {ly_month}":"{:,.3f}", f"Sales {last_month}":"{:,.3f}",
                        "Sales YoY%":"{:+.1f}%",
                        f"GP {ly_month}":"{:,.3f}", f"GP {last_month}":"{:,.3f}",
                        "GP YoY%":"{:+.1f}%",
                    }),
                    width='stretch', height=450,
                )
