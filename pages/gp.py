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

df = raw.copy()
if sel_cats:   df = df[df["Category"].isin(sel_cats)]
if sel_brands: df = df[df["Brand"].isin(sel_brands)]
if item_q:
    df = df[
        df["Item Name"].str.contains(item_q, case=False, na=False) |
        df["Item No."].str.contains(item_q, case=False, na=False)
    ]

period_label = f"{from_month} to {to_month}"

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
tab_ov, tab_item, tab_daily, tab_gap = st.tabs([
    "Overview",
    "Item Analysis",
    "Daily Pattern",
    "Gap & Promo",
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
    item_agg["GP%"]     = (item_agg["GP"] / item_agg["Sales"] * 100).where(item_agg["Sales"] > 0, 0).round(2)
    item_agg["Avg/Day"] = (item_agg["Sales"] / item_agg["Sell_Days"]).round(0)

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
        show_negative = st.checkbox("Negative GP only", key="i_neg")

    sort_map = {"GP (KWD)": "GP", "Sales (KWD)": "Sales", "GP%": "GP%",
                "Qty": "Qty", "Selling Days": "Sell_Days"}
    view = item_agg.copy()
    if show_negative:
        view = view[view["GP%"] < 0]
    view = view.sort_values(sort_map[sort_by], ascending=False)
    if top_n != "All":
        view = view.head(int(top_n))
    view = view.reset_index(drop=True)
    view.insert(0, "Rank", range(1, len(view) + 1))

    styled = (
        view[["Rank", "Item No.", "Item Name", "Brand", "Category",
              "Qty", "Sales", "COGS", "GP", "GP%", "Sell_Days", "Avg/Day"]]
        .rename(columns={"Sales": "Sales (KWD)", "COGS": "COGS (KWD)", "GP": "GP (KWD)",
                         "Sell_Days": "Selling Days", "Avg/Day": "Avg/Day (KWD)"})
        .style
        .format({
            "Qty": "{:,.0f}", "Sales (KWD)": "{:,.0f}",
            "COGS (KWD)": "{:,.0f}", "GP (KWD)": "{:,.0f}",
            "GP%": "{:.1f}%", "Selling Days": "{:.0f}", "Avg/Day (KWD)": "{:,.0f}",
        })
    )
    styled = _apply(styled, _style_gp, ["GP%"])
    st.dataframe(styled, width="stretch", height=460)

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
        st.dataframe(
            gap_days[["Posting Date","DOW","Sales Value (KWD)","GP%"]]
            .rename(columns={"Sales Value (KWD)": "Sales (KWD)"})
            .style.format({"Sales (KWD)": "{:,.0f}", "GP%": "{:.1f}%"}),
            width='stretch', height=240,
        )


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
            st.dataframe(
                dorm_df[["Item No.","Item Name","Brand","Category",
                          "Last Sale","Qty","Sales_KWD","GP_KWD","GP%"]]
                .rename(columns={"Sales_KWD":"Sales (KWD)","GP_KWD":"GP (KWD)"})
                .style.format({"Qty":"{:,.0f}","Sales (KWD)":"{:,.0f}",
                               "GP (KWD)":"{:,.0f}","GP%":"{:.1f}%"}),
                width='stretch', height=400,
            )

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
            st.dataframe(
                promo[["Item No.","Item Name","Brand","Category",
                        "Sales Value (KWD)","total_qty","sell_days","Spike%"]]
                .rename(columns={"Sales Value (KWD)":"Sales (KWD)","total_qty":"Total Qty",
                                 "sell_days":"Selling Days","Spike%":"Spike Day %"})
                .style.format({"Sales (KWD)":"{:,.0f}","Total Qty":"{:,.0f}","Spike Day %":"{:.1f}%"}),
                width='stretch', height=400,
            )

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
            st.dataframe(
                neg[["Item No.","Item Name","Brand","Category","Qty","Sales_KWD","GP_KWD","GP%","Days"]]
                .rename(columns={"Sales_KWD":"Sales (KWD)","GP_KWD":"GP (KWD)","Days":"Selling Days"})
                .style.format({"Qty":"{:,.0f}","Sales (KWD)":"{:,.0f}",
                               "GP (KWD)":"{:,.0f}","GP%":"{:.1f}%"}),
                width='stretch', height=400,
            )
