"""
pages/_zakir.py  —  Coupon Deep-Dive (internal, hidden from nav)
Access at /_zakir
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

GP_DIR = Path(__file__).parent.parent / "downloads" / "gp"

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.block-container { padding-top:1rem !important; padding-bottom:1rem !important; max-width:100% !important; }
[data-testid="stDataFrame"] { overflow-x: auto; }
.kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:12px; }
.kpi-card { background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:10px; padding:12px 16px; }
.kpi-label { font-size:10px; color:#888; text-transform:uppercase; letter-spacing:.06em; margin-bottom:4px; }
.kpi-value { font-size:22px; font-weight:700; line-height:1.2; }
.kpi-unit  { font-size:11px; color:#888; }
@media(max-width:900px){ .kpi-grid{ grid-template-columns:repeat(2,1fr); } }
</style>
""", unsafe_allow_html=True)

def _kpi(label, value, unit=""):
    return f"""<div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {"<div class='kpi-unit'>"+unit+"</div>" if unit else ""}
    </div>"""


# ── data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_months() -> list[str]:
    """Return sorted list of months available in coupon data."""
    # Try local CSVs first
    local = sorted(
        p.stem.replace("_coupons", "")
        for p in GP_DIR.glob("*_coupons.csv")
    )
    if local:
        return local
    # Fall back to BigQuery
    try:
        import bigquery_client as bq
        return bq.get_distinct_months(bq.TABLE_COUPON)
    except Exception:
        return []


@st.cache_data(ttl=1800)
def load_coupon_range(from_m: str, to_m: str) -> pd.DataFrame:
    """Load coupon data for the given month range."""
    months = [m for m in load_months() if from_m <= m <= to_m]

    # Local CSVs
    dfs = []
    for m in months:
        f = GP_DIR / f"{m}_coupons.csv"
        if f.exists():
            dfs.append(pd.read_csv(f))
    if dfs:
        return pd.concat(dfs, ignore_index=True)

    # BigQuery fallback
    try:
        import bigquery_client as bq
        raw = bq.read_table_range(bq.TABLE_COUPON, from_m, to_m)
        return raw.rename(columns={"Item_No": "Item No."})
    except Exception as e:
        st.error(f"Could not load coupon data: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=1800)
def load_gp_range(from_m: str, to_m: str) -> pd.DataFrame:
    """Load GP item data (Item No., Category, Brand, Sales, GP) for selected range."""
    # Local CSVs
    dfs = []
    for m_path in sorted(GP_DIR.glob("*_gp.csv")):
        m = m_path.stem.replace("_gp", "")
        if from_m <= m <= to_m:
            chunk = pd.read_csv(m_path)
            chunk["Month"] = m
            dfs.append(chunk)
    if dfs:
        df = pd.concat(dfs, ignore_index=True)
        # Normalise column names (handle both raw and renamed versions)
        df = df.rename(columns=lambda c: c.strip())
        return df

    # BigQuery fallback
    try:
        import bigquery_client as bq
        raw = bq.read_table_range(bq.TABLE_GP, from_m, to_m)
        raw = raw.rename(columns={
            "Item_No": "Item No.", "Item_Name": "Item Name",
            "Sales_Value__KWD": "Sales (KWD)", "GP__KWD": "GP (KWD)",
            "GP": "GP%", "Sales_Qty": "Qty",
        })
        return raw
    except Exception as e:
        st.error(f"Could not load GP data: {e}")
        return pd.DataFrame()


# ── page ──────────────────────────────────────────────────────────────────────
st.title("🎟 Coupon Analysis")

all_months = load_months()
if not all_months:
    st.error("No coupon data found. Run fetch_coupon_data.py first.")
    st.stop()

# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    sel_from = st.selectbox("From month", all_months, index=0, key="cp_from")
    to_opts  = [m for m in all_months if m >= sel_from]
    sel_to   = st.selectbox("To month", to_opts, index=len(to_opts)-1, key="cp_to")

# ── load data ─────────────────────────────────────────────────────────────────
with st.spinner("Loading coupon data..."):
    coup_raw = load_coupon_range(sel_from, sel_to)

if coup_raw.empty:
    st.warning("No coupon data for selected range.")
    st.stop()

# Normalise column names from BQ (Item_No → Item No.)
if "Item_No" in coup_raw.columns and "Item No." not in coup_raw.columns:
    coup_raw = coup_raw.rename(columns={"Item_No": "Item No."})

# Load GP for category/brand context
with st.spinner("Loading GP context..."):
    gp_raw = load_gp_range(sel_from, sel_to)

# Build item→category/brand/name lookup from GP
item_meta = pd.DataFrame()
if not gp_raw.empty:
    name_col  = next((c for c in gp_raw.columns if "name" in c.lower() or "description" in c.lower()), None)
    cat_col   = next((c for c in gp_raw.columns if "category" in c.lower()), None)
    brand_col = next((c for c in gp_raw.columns if "brand" in c.lower()), None)
    item_col  = next((c for c in ["Item No.", "Item_No"] if c in gp_raw.columns), None)
    keep = [c for c in [item_col, name_col, cat_col, brand_col] if c]
    if item_col:
        item_meta = (
            gp_raw[keep].drop_duplicates(subset=[item_col])
            .rename(columns={item_col: "Item No."})
        )

# ── explode by coupon code for code-level analysis ────────────────────────────
def explode_coupons(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (Item No., Coupon code, Month)."""
    rows = []
    for _, r in df.iterrows():
        codes = [c.strip() for c in str(r.get("Coupon_Names","")).split(",") if c.strip()]
        n = max(len(codes), 1)
        for code in codes:
            rows.append({
                "Item No.":    r["Item No."],
                "Month":       r.get("Month",""),
                "Coupon Code": code,
                "Orders":      r["Coupon_Orders"] / n,
                "KWD":         r["Coupon_KWD"]   / n,
            })
    return pd.DataFrame(rows)

coup_long = explode_coupons(coup_raw)

# Sidebar coupon code filter
all_codes = sorted(coup_long["Coupon Code"].unique())
with st.sidebar:
    sel_codes = st.multiselect("Coupon codes", all_codes, placeholder="All codes")
    if sel_codes:
        coup_long = coup_long[coup_long["Coupon Code"].isin(sel_codes)]
        coup_raw  = coup_raw[coup_raw["Item No."].isin(coup_long["Item No."].unique())]

# Re-aggregate after filter
item_agg = (
    coup_long.groupby("Item No.", as_index=False)
    .agg(
        Coupon_Orders=("Orders", "sum"),
        Coupon_KWD   =("KWD",    "sum"),
        Coupon_Names =("Coupon Code", lambda x: ", ".join(sorted(set(x)))),
    )
)
if not item_meta.empty:
    item_agg = item_agg.merge(item_meta, on="Item No.", how="left")

# ── KPI row ───────────────────────────────────────────────────────────────────
total_kwd     = coup_long["KWD"].sum()
total_orders  = coup_long["Orders"].sum()
unique_codes  = coup_long["Coupon Code"].nunique()
unique_items  = coup_long["Item No."].nunique()

st.markdown(f"""
<div class="kpi-grid">
{_kpi("Total Discount", f"{total_kwd:,.1f}", "KWD")}
{_kpi("Coupon Orders",  f"{int(total_orders):,}")}
{_kpi("Items Affected", f"{unique_items:,}")}
{_kpi("Unique Codes",   f"{unique_codes:,}")}
</div>""", unsafe_allow_html=True)

# ── tabs ──────────────────────────────────────────────────────────────────────
t1, t2, t3, t4 = st.tabs(["By Coupon", "By Item", "By Category", "Trend"])


# ── Tab 1: By Coupon ──────────────────────────────────────────────────────────
with t1:
    by_code = (
        coup_long.groupby("Coupon Code", as_index=False)
        .agg(
            Orders       =("Orders",      "sum"),
            Discount_KWD =("KWD",         "sum"),
            Items_Affected=("Item No.",   "nunique"),
        )
        .sort_values("Discount_KWD")
    )
    by_code["Orders"]       = by_code["Orders"].round(0).astype(int)
    by_code["Discount_KWD"] = by_code["Discount_KWD"].round(3)
    by_code.rename(columns={"Discount_KWD":"Discount (KWD)","Items_Affected":"Items Affected"}, inplace=True)

    c1, c2 = st.columns([1, 1])
    with c1:
        # Horizontal bar — top 20 by absolute discount
        top20 = by_code.nsmallest(20, "Discount (KWD)")
        fig = px.bar(
            top20, x="Discount (KWD)", y="Coupon Code",
            orientation="h", text="Discount (KWD)",
            color="Discount (KWD)", color_continuous_scale="Reds_r",
            title="Top 20 Codes by Discount (KWD)",
        )
        fig.update_traces(texttemplate="%{text:,.3f}", textposition="outside")
        fig.update_layout(
            height=480, margin=dict(l=10,r=30,t=40,b=10),
            coloraxis_showscale=False, yaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        # Bar by orders count
        top20o = by_code.nlargest(20, "Orders")
        fig2 = px.bar(
            top20o, x="Orders", y="Coupon Code",
            orientation="h", text="Orders",
            color="Orders", color_continuous_scale="Blues",
            title="Top 20 Codes by Orders",
        )
        fig2.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig2.update_layout(
            height=480, margin=dict(l=10,r=30,t=40,b=10),
            coloraxis_showscale=False, yaxis_title="",
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.dataframe(
        by_code.sort_values("Discount (KWD)").style.format({
            "Orders": "{:,.0f}", "Discount (KWD)": "{:,.3f}", "Items Affected": "{:,}",
        }),
        use_container_width=True, hide_index=True,
    )
    st.download_button("⬇ Download", by_code.to_csv(index=False),
                       file_name="coupon_by_code.csv", mime="text/csv")


# ── Tab 2: By Item ────────────────────────────────────────────────────────────
with t2:
    # Merge GP sales/GP for context
    item_display = item_agg.copy()
    if not gp_raw.empty:
        sales_col = next((c for c in gp_raw.columns if "sales" in c.lower() and "kwd" in c.lower()), None)
        gp_col    = next((c for c in gp_raw.columns if c.lower() in ("gp (kwd)","gp__kwd","gp_kwd")), None)
        item_col  = next((c for c in ["Item No.", "Item_No"] if c in gp_raw.columns), None)
        if sales_col and item_col:
            gp_item = (
                gp_raw.rename(columns={item_col: "Item No."})
                .groupby("Item No.", as_index=False)
                .agg(**{
                    "Sales_KWD": pd.NamedAgg(column=sales_col, aggfunc="sum"),
                    **({"GP_KWD": pd.NamedAgg(column=gp_col, aggfunc="sum")} if gp_col else {}),
                })
            )
            item_display = item_display.merge(gp_item, on="Item No.", how="left")
            item_display["Coupon % of Sales"] = (
                item_display["Coupon_KWD"] / item_display["Sales_KWD"].replace(0, float("nan")) * 100
            ).round(1)

    item_display = item_display.sort_values("Coupon_KWD")

    # Top 20 items chart
    top20i = item_display.nsmallest(20, "Coupon_KWD")
    name_col_disp = next((c for c in item_display.columns if "name" in c.lower()), None)
    y_col = name_col_disp if name_col_disp else "Item No."
    fig3 = px.bar(
        top20i, x="Coupon_KWD", y=y_col,
        orientation="h", text="Coupon_KWD",
        color="Coupon_KWD", color_continuous_scale="Reds_r",
        title="Top 20 Items by Coupon Discount (KWD)",
    )
    fig3.update_traces(texttemplate="%{text:,.3f}", textposition="outside")
    fig3.update_layout(height=500, margin=dict(l=10,r=30,t=40,b=10),
                       coloraxis_showscale=False, yaxis_title="")
    st.plotly_chart(fig3, use_container_width=True)

    # Full table
    show_cols = ["Item No."]
    for c in [name_col_disp, "Category", "Brand", "Coupon_Orders", "Coupon_Names",
              "Coupon_KWD", "Sales_KWD", "Coupon % of Sales"]:
        if c and c in item_display.columns:
            show_cols.append(c)
    show_cols = list(dict.fromkeys(show_cols))  # deduplicate

    fmt = {"Coupon_Orders": "{:,.0f}", "Coupon_KWD": "{:,.3f}"}
    if "Sales_KWD" in item_display.columns:
        fmt["Sales_KWD"] = "{:,.3f}"
    if "Coupon % of Sales" in item_display.columns:
        fmt["Coupon % of Sales"] = "{:.1f}%"

    st.dataframe(
        item_display[show_cols].style.format(fmt),
        use_container_width=True, hide_index=True, height=400,
    )
    st.download_button("⬇ Download", item_display[show_cols].to_csv(index=False),
                       file_name="coupon_by_item.csv", mime="text/csv")


# ── Tab 3: By Category ────────────────────────────────────────────────────────
with t3:
    if "Category" not in item_agg.columns or item_agg["Category"].isna().all():
        st.info("Category data not available — no GP data loaded for this range.")
    else:
        by_cat = (
            item_agg.dropna(subset=["Category"])
            .groupby("Category", as_index=False)
            .agg(
                Items=("Item No.", "nunique"),
                Orders=("Coupon_Orders","sum"),
                Discount_KWD=("Coupon_KWD","sum"),
            )
            .sort_values("Discount_KWD")
        )
        by_cat["Discount_KWD"] = by_cat["Discount_KWD"].round(3)

        c1, c2 = st.columns([1, 1])
        with c1:
            fig4 = px.bar(
                by_cat, x="Discount_KWD", y="Category",
                orientation="h", text="Discount_KWD",
                color="Discount_KWD", color_continuous_scale="Reds_r",
                title="Discount by Category (KWD)",
            )
            fig4.update_traces(texttemplate="%{text:,.1f}", textposition="outside")
            fig4.update_layout(height=500, margin=dict(l=10,r=30,t=40,b=10),
                               coloraxis_showscale=False, yaxis_title="")
            st.plotly_chart(fig4, use_container_width=True)

        with c2:
            fig5 = px.pie(
                by_cat, values="Discount_KWD", names="Category",
                title="Discount Share by Category",
                hole=0.4,
            )
            fig5.update_layout(height=500, margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig5, use_container_width=True)

        by_cat.rename(columns={"Discount_KWD":"Discount (KWD)"}, inplace=True)
        st.dataframe(
            by_cat.style.format({"Items":"{:,}","Orders":"{:,.0f}","Discount (KWD)":"{:,.3f}"}),
            use_container_width=True, hide_index=True,
        )
        st.download_button("⬇ Download", by_cat.to_csv(index=False),
                           file_name="coupon_by_category.csv", mime="text/csv")


# ── Tab 4: Trend ──────────────────────────────────────────────────────────────
with t4:
    if coup_long["Month"].nunique() < 2:
        st.info("Select more than one month to see trend.")
    else:
        trend = (
            coup_long.groupby(["Month","Coupon Code"], as_index=False)
            .agg(Discount_KWD=("KWD","sum"), Orders=("Orders","sum"))
        )

        # Line chart — total discount per month
        monthly = (
            coup_long.groupby("Month", as_index=False)
            .agg(Discount_KWD=("KWD","sum"), Orders=("Orders","sum"),
                 Items=("Item No.","nunique"))
        )
        fig6 = go.Figure()
        fig6.add_bar(x=monthly["Month"], y=monthly["Discount_KWD"].abs(),
                     name="Discount (KWD)", marker_color="#EF4444")
        fig6.update_layout(title="Total Coupon Discount by Month",
                           xaxis_title="Month", yaxis_title="Discount (KWD)",
                           height=350, margin=dict(l=10,r=10,t=40,b=10))
        st.plotly_chart(fig6, use_container_width=True)

        # Top codes per month heatmap
        top_codes = (
            coup_long.groupby("Coupon Code")["KWD"].sum()
            .abs().nlargest(15).index.tolist()
        )
        pivot = (
            trend[trend["Coupon Code"].isin(top_codes)]
            .pivot_table(index="Coupon Code", columns="Month",
                         values="Discount_KWD", aggfunc="sum", fill_value=0)
        )
        if not pivot.empty:
            fig7 = px.imshow(
                pivot.abs(), aspect="auto",
                color_continuous_scale="Reds",
                title="Top 15 Codes — Discount Heatmap by Month (KWD)",
            )
            fig7.update_layout(height=420, margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig7, use_container_width=True)
