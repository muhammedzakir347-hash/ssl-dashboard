"""
build_gp_excel.py
-----------------
Reads all downloads/gp/YYYY-MM_gp.csv files, cleans them,
and produces a rich Excel analysis workbook.

Sheets:
  1. Monthly Summary   — Sales, COGS, GP, GP% by month (with bar + line chart)
  2. By Brand          — each brand's totals across all months, ranked by GP KWD
  3. Brand Trend       — month × brand pivot for GP%
  4. Top & Bottom GP%  — top 10 and bottom 10 brands by average GP%
  5. Raw Data          — cleaned combined data (all rows)

Output: downloads/gp/GP_Analysis.xlsx

Run:  python build_gp_excel.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

GP_DIR  = Path(__file__).parent / "downloads" / "gp"
OUT     = GP_DIR / "GP_Analysis.xlsx"
CURRENCY = re.compile(r"[A-Z]{3}\s*")

RENAME = {
    "Category":                  "Category",
    "Drops Brand: Name":         "Brand",
    "Item No.":                  "Item No.",
    "Preferred Vendor: Account Name": "Vendor",
    "Display Name (English)":    "Item Name",
    "Quantity":                  "Sales Qty",
    "Line Amount":               "Sales Value (KWD)",
    "GL Line Cost":              "COGS (KWD)",
    "Line Profit":               "GP (KWD)",
    "GP%":                       "GP%",
}

# Brand colors
DARK_GREEN  = "#0F1F17"
IVORY       = "#FAF6EF"
GOLD        = "#C9A84C"
MID_GREEN   = "#1E3D2F"
LIGHT_GREEN = "#2E6B4F"
RED         = "#C0392B"
ORANGE      = "#E67E22"
GREY        = "#95A5A6"


# ── Load & clean ──────────────────────────────────────────────────────────────
def load_all() -> pd.DataFrame:
    files = sorted(GP_DIR.glob("*_gp.csv"))
    if not files:
        print(f"ERROR: No *_gp.csv files in {GP_DIR}")
        sys.exit(1)

    frames = []
    for f in files:
        df = pd.read_csv(f, encoding="utf-8")
        df = df.rename(columns=RENAME)
        for col in ["Sales Value (KWD)", "COGS (KWD)", "GP (KWD)", "Sales Qty", "GP%"]:
            if col not in df.columns:
                continue
            df[col] = (
                df[col].astype(str)
                .str.replace(CURRENCY, "", regex=True)
                .str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
                .replace({"": None, "None": None, "nan": None, "-": "0"})
                .pipe(pd.to_numeric, errors="coerce")
            )
        # Drop subtotal / grand-total rows (no Item No. = grouping row)
        if "Item No." in df.columns:
            df = df[df["Item No."].notna() & (df["Item No."].str.strip() != "")]
        frames.append(df)
        print(f"  Loaded {f.name}: {len(df)} rows")

    combined = pd.concat(frames, ignore_index=True)
    print(f"  Combined: {len(combined)} rows, {combined['Month'].nunique()} months")
    return combined


# ── Excel helpers ─────────────────────────────────────────────────────────────
def _hdr(wb, bold=True, bg=DARK_GREEN, fg=IVORY, size=11, border=True):
    fmt = {"bold": bold, "font_color": fg, "bg_color": bg,
           "font_size": size, "valign": "vcenter", "align": "center"}
    if border:
        fmt.update({"border": 1, "border_color": "#000000"})
    return wb.add_format(fmt)

def _num(wb, decimals=2, bg="#FFFFFF", bold=False):
    fmt_str = f"#,##0.{'0'*decimals}" if decimals else "#,##0"
    return wb.add_format({
        "num_format": fmt_str, "bg_color": bg,
        "bold": bold, "border": 1, "border_color": "#E0E0E0",
        "valign": "vcenter", "align": "right",
    })

def _pct(wb, bg="#FFFFFF", bold=False):
    return wb.add_format({
        "num_format": "0.00\"%\"", "bg_color": bg,
        "bold": bold, "border": 1, "border_color": "#E0E0E0",
        "valign": "vcenter",
    })

def _txt(wb, bg="#FFFFFF", bold=False, align="left"):
    return wb.add_format({
        "bg_color": bg, "bold": bold,
        "border": 1, "border_color": "#E0E0E0",
        "valign": "vcenter", "align": align,
    })

def _set_cols(ws, specs):
    """specs: list of (col_idx, width)"""
    for idx, w in specs:
        ws.set_column(idx, idx, w)


# ── Sheet 1: Monthly Summary ───────────────────────────────────────────────────
def write_monthly_summary(df: pd.DataFrame, wb, ws):
    monthly = (
        df.groupby("Month")[["Sales Value (KWD)", "COGS (KWD)", "GP (KWD)", "Sales Qty"]]
        .sum()
        .reset_index()
        .sort_values("Month")
    )
    monthly["GP%"] = (monthly["GP (KWD)"] / monthly["Sales Value (KWD)"] * 100).round(2)

    hdr  = _hdr(wb)
    num2 = _num(wb, 2)
    num0 = _num(wb, 0)
    pct  = _pct(wb)
    txt  = _txt(wb)
    tot_hdr = _hdr(wb, bg=GOLD, fg=DARK_GREEN)
    tot_num = _num(wb, 2, bg="#FFF8E8", bold=True)
    tot_pct = _pct(wb, bg="#FFF8E8", bold=True)

    ws.set_row(0, 30)
    ws.merge_range("A1:F1", "Monthly Sales & Gross Profit Summary", _hdr(wb, size=14))

    headers = ["Month", "Sales Value (KWD)", "COGS (KWD)", "GP (KWD)", "GP%", "Sales Qty"]
    for c, h in enumerate(headers):
        ws.write(1, c, h, hdr)
    ws.set_row(1, 20)

    for r, row in enumerate(monthly.itertuples(index=False), start=2):
        ws.write(r, 0, row.Month, txt)
        ws.write(r, 1, row._1, num2)   # Sales Value
        ws.write(r, 2, row._2, num2)   # COGS
        ws.write(r, 3, row._3, num2)   # GP
        ws.write(r, 4, row._4, pct)    # GP%
        ws.write(r, 5, row._5, num0)   # Qty

    # Totals row
    tr = len(monthly) + 2
    ws.write(tr, 0, "TOTAL", tot_hdr)
    ws.write(tr, 1, monthly["Sales Value (KWD)"].sum(), tot_num)
    ws.write(tr, 2, monthly["COGS (KWD)"].sum(), tot_num)
    ws.write(tr, 3, monthly["GP (KWD)"].sum(), tot_num)
    total_gp_pct = monthly["GP (KWD)"].sum() / monthly["Sales Value (KWD)"].sum() * 100
    ws.write(tr, 4, total_gp_pct, tot_pct)
    ws.write(tr, 5, monthly["Sales Qty"].sum(), _num(wb, 0, bg="#FFF8E8", bold=True))

    _set_cols(ws, [(0, 12), (1, 20), (2, 18), (3, 18), (4, 10), (5, 14)])

    # Chart: stacked bar (Sales vs COGS) + GP% line
    n_months = len(monthly)
    data_start = 2   # row index (0-based) for first data row in sheet
    chart_bar = wb.add_chart({"type": "column"})
    chart_bar.add_series({
        "name":       "COGS (KWD)",
        "categories": ["Monthly Summary", data_start, 0, data_start + n_months - 1, 0],
        "values":     ["Monthly Summary", data_start, 2, data_start + n_months - 1, 2],
        "fill":       {"color": LIGHT_GREEN},
        "gap":        60,
    })
    chart_bar.add_series({
        "name":       "GP (KWD)",
        "categories": ["Monthly Summary", data_start, 0, data_start + n_months - 1, 0],
        "values":     ["Monthly Summary", data_start, 3, data_start + n_months - 1, 3],
        "fill":       {"color": GOLD},
    })
    chart_bar.set_title({"name": "Sales = COGS + GP  by Month"})
    chart_bar.set_legend({"position": "bottom"})
    chart_bar.set_size({"width": 480, "height": 280})
    chart_bar.set_y_axis({"num_format": "#,##0", "major_gridlines": {"visible": True}})

    chart_line = wb.add_chart({"type": "line"})
    chart_line.add_series({
        "name":       "GP%",
        "categories": ["Monthly Summary", data_start, 0, data_start + n_months - 1, 0],
        "values":     ["Monthly Summary", data_start, 4, data_start + n_months - 1, 4],
        "line":       {"color": RED, "width": 2.5},
        "marker":     {"type": "circle", "size": 6, "fill": {"color": RED}},
    })
    chart_line.set_y2_axis({"num_format": "0.0\"%\""})

    combo = wb.add_chart({"type": "column"})
    combo.combine(chart_line)
    combo.add_series({
        "name":       "COGS (KWD)",
        "categories": ["Monthly Summary", data_start, 0, data_start + n_months - 1, 0],
        "values":     ["Monthly Summary", data_start, 2, data_start + n_months - 1, 2],
        "fill":       {"color": LIGHT_GREEN},
        "gap":        60,
    })
    combo.add_series({
        "name":       "GP (KWD)",
        "categories": ["Monthly Summary", data_start, 0, data_start + n_months - 1, 0],
        "values":     ["Monthly Summary", data_start, 3, data_start + n_months - 1, 3],
        "fill":       {"color": GOLD},
    })
    combo.set_title({"name": "Monthly COGS & GP  |  GP% trend"})
    combo.set_legend({"position": "bottom"})
    combo.set_size({"width": 560, "height": 300})

    ws.insert_chart("H3", combo)
    return monthly


# ── Sheet 2: By Brand ─────────────────────────────────────────────────────────
def write_by_brand(df: pd.DataFrame, wb, ws):
    grp_cols = [c for c in ["Category", "Brand"] if c in df.columns]
    by_brand = (
        df.groupby(grp_cols)[["Sales Value (KWD)", "COGS (KWD)", "GP (KWD)", "Sales Qty"]]
        .sum()
        .reset_index()
        .sort_values("GP (KWD)", ascending=False)
    )
    by_brand["GP%"] = (by_brand["GP (KWD)"] / by_brand["Sales Value (KWD)"] * 100).round(2)
    by_brand["Sales Share%"] = (by_brand["Sales Value (KWD)"] / by_brand["Sales Value (KWD)"].sum() * 100).round(2)
    by_brand.insert(0, "Rank", range(1, len(by_brand) + 1))

    hdr  = _hdr(wb)
    num2 = _num(wb, 2)
    num0 = _num(wb, 0)
    pct  = _pct(wb)
    txt  = _txt(wb)
    rank_fmt = wb.add_format({"bold": True, "align": "center", "bg_color": IVORY,
                              "border": 1, "border_color": "#E0E0E0"})

    ws.set_row(0, 30)
    ws.merge_range("A1:H1", "Brand Performance  —  All Months Combined", _hdr(wb, size=14))

    headers = list(by_brand.columns)
    for c, h in enumerate(headers):
        ws.write(1, c, h, hdr)
    ws.set_row(1, 20)

    # Conditional color for GP%: red if < 0, orange if 0–5, gold if 5–15, green if > 15
    def gp_bg(gp):
        if gp < 0:   return RED
        if gp < 5:   return ORANGE
        if gp < 15:  return GOLD
        return LIGHT_GREEN

    gp_col_idx = headers.index("GP%")
    for r, row in enumerate(by_brand.itertuples(index=False), start=2):
        for c, col in enumerate(headers):
            val = row[c]
            if col == "Rank":
                ws.write(r, c, val, rank_fmt)
            elif col == "GP%":
                bg = gp_bg(val if pd.notna(val) else 0)
                ws.write(r, c, val, wb.add_format({
                    "num_format": "0.00\"%\"", "bg_color": bg, "font_color": IVORY,
                    "bold": True, "border": 1, "border_color": "#E0E0E0",
                }))
            elif col == "Sales Share%":
                ws.write(r, c, val, pct)
            elif col in ("Sales Value (KWD)", "COGS (KWD)", "GP (KWD)"):
                ws.write(r, c, val, num2)
            elif col == "Sales Qty":
                ws.write(r, c, val, num0)
            else:
                ws.write(r, c, val, txt)

    # Totals
    tr = len(by_brand) + 2
    tot_fmt = _hdr(wb, bg=GOLD, fg=DARK_GREEN)
    overall_gp = by_brand["GP (KWD)"].sum() / by_brand["Sales Value (KWD)"].sum() * 100
    for c, col in enumerate(headers):
        if col == "Rank":         ws.write(tr, c, "", tot_fmt)
        elif col in ("Category", "Brand"): ws.write(tr, c, "TOTAL" if c == (1 if "Category" in headers else 0) else "", tot_fmt)
        elif col == "Sales Value (KWD)": ws.write(tr, c, by_brand[col].sum(), _num(wb, 2, bg=GOLD, bold=True))
        elif col == "COGS (KWD)":  ws.write(tr, c, by_brand[col].sum(), _num(wb, 2, bg=GOLD, bold=True))
        elif col == "GP (KWD)":    ws.write(tr, c, by_brand[col].sum(), _num(wb, 2, bg=GOLD, bold=True))
        elif col == "GP%":         ws.write(tr, c, overall_gp, _pct(wb, bg=GOLD, bold=True))
        elif col == "Sales Qty":   ws.write(tr, c, by_brand[col].sum(), _num(wb, 0, bg=GOLD, bold=True))
        elif col == "Sales Share%":ws.write(tr, c, 100.0, _pct(wb, bg=GOLD, bold=True))
        else:                      ws.write(tr, c, "", tot_fmt)

    _set_cols(ws, [(0,6),(1,18),(2,24),(3,20),(4,18),(5,18),(6,10),(7,14),(8,13)])

    # Top 15 bar chart for GP KWD
    top15 = by_brand.head(15)
    chart = wb.add_chart({"type": "bar"})
    chart.add_series({
        "name":       "GP (KWD)",
        "categories": ["By Brand", 2, 1, 2 + len(top15) - 1, 1],
        "values":     ["By Brand", 2, 4, 2 + len(top15) - 1, 4],
        "fill":       {"color": GOLD},
    })
    chart.set_title({"name": "Top 15 Brands by GP (KWD)"})
    chart.set_legend({"none": True})
    chart.set_size({"width": 480, "height": 400})
    chart.set_x_axis({"reverse": True})
    ws.insert_chart("J3", chart)


# ── Sheet 3: Brand Trend (GP% pivot) ──────────────────────────────────────────
def write_brand_trend(df: pd.DataFrame, wb, ws):
    pivot = df.pivot_table(
        index="Brand",
        columns="Month",
        values="GP%",
        aggfunc="mean",
    ).round(2)
    pivot["Avg GP%"] = pivot.mean(axis=1).round(2)
    pivot = pivot.sort_values("Avg GP%", ascending=False).reset_index()

    months = [c for c in pivot.columns if c not in ("Brand", "Avg GP%")]
    hdr   = _hdr(wb)
    txt   = _txt(wb)

    ws.set_row(0, 30)
    ws.merge_range(0, 0, 0, len(months) + 2,
                   "Brand GP% by Month  (pivot)", _hdr(wb, size=14))

    ws.write(1, 0, "Brand", hdr)
    for c, m in enumerate(months, start=1):
        ws.write(1, c, m, hdr)
    ws.write(1, len(months) + 1, "Avg GP%", _hdr(wb, bg=GOLD, fg=DARK_GREEN))
    ws.set_row(1, 20)

    def gp_pct_fmt(val):
        if pd.isna(val): return wb.add_format({"bg_color": "#F5F5F5", "border": 1,
                                                "border_color": "#E0E0E0"})
        if val < 0:   bg = RED;         fg = IVORY
        elif val < 5: bg = ORANGE;      fg = IVORY
        elif val < 15:bg = "#F7DC6F";   fg = DARK_GREEN
        else:         bg = LIGHT_GREEN; fg = IVORY
        return wb.add_format({
            "num_format": "0.0\"%\"", "bg_color": bg, "font_color": fg,
            "border": 1, "border_color": "#E0E0E0", "align": "center",
        })

    for r, row in enumerate(pivot.itertuples(index=False), start=2):
        ws.write(r, 0, row.Brand, txt)
        for c, m in enumerate(months, start=1):
            val = getattr(row, m, None)
            ws.write(r, c, val if pd.notna(val) else "", gp_pct_fmt(val))
        avg = row._asdict().get("Avg GP%")
        ws.write(r, len(months) + 1, avg,
                 wb.add_format({"num_format": "0.0\"%\"", "bold": True,
                                "bg_color": "#FFF8E8", "border": 1, "border_color": "#E0E0E0"}))

    _set_cols(ws, [(0, 24)] + [(i, 12) for i in range(1, len(months) + 2)])


# ── Sheet 4: Top & Bottom GP% ─────────────────────────────────────────────────
def write_top_bottom(df: pd.DataFrame, wb, ws):
    avg = (
        df.groupby("Brand").agg(
            Avg_GP_Pct=("GP%", "mean"),
            Total_GP=("GP (KWD)", "sum"),
            Total_Sales=("Sales Value (KWD)", "sum"),
        )
        .round(2)
        .reset_index()
        .sort_values("Avg_GP_Pct", ascending=False)
    )
    # Keep only brands with meaningful sales (> 50 KWD)
    avg = avg[avg["Total_Sales"] > 50]
    top10 = avg.head(10).copy()
    bot10 = avg.tail(10).copy()

    hdr = _hdr(wb)
    txt = _txt(wb)

    def _write_block(start_row, title, data, bg_col):
        ws.set_row(start_row, 26)
        ws.merge_range(start_row, 0, start_row, 4, title, _hdr(wb, size=13, bg=bg_col))
        ws.write(start_row + 1, 0, "Brand",         hdr)
        ws.write(start_row + 1, 1, "Avg GP%",       hdr)
        ws.write(start_row + 1, 2, "Total GP (KWD)",hdr)
        ws.write(start_row + 1, 3, "Total Sales (KWD)", hdr)
        for r, row in enumerate(data.itertuples(index=False), start=start_row + 2):
            ws.write(r, 0, row.Brand, txt)
            ws.write(r, 1, row.Avg_GP_Pct, _pct(wb))
            ws.write(r, 2, row.Total_GP,   _num(wb, 2))
            ws.write(r, 3, row.Total_Sales, _num(wb, 2))
        return start_row + 2 + len(data) + 2

    ws.set_row(0, 30)
    ws.merge_range("A1:E1", "Brand GP% Analysis  —  Top & Bottom Performers",
                   _hdr(wb, size=14))

    next_row = _write_block(1, "🏆  Top 10 Brands by Average GP%", top10, LIGHT_GREEN)
    _write_block(next_row, "⚠️  Bottom 10 Brands by Average GP%", bot10, RED)

    _set_cols(ws, [(0, 26), (1, 12), (2, 18), (3, 20)])

    # Horizontal bar chart
    chart_top = wb.add_chart({"type": "bar"})
    chart_top.add_series({
        "name":       "Avg GP%",
        "categories": ["Top & Bottom GP%", 2, 0, 11, 0],
        "values":     ["Top & Bottom GP%", 2, 1, 11, 1],
        "fill":       {"color": LIGHT_GREEN},
    })
    chart_top.set_title({"name": "Top 10 Brands — Average GP%"})
    chart_top.set_legend({"none": True})
    chart_top.set_size({"width": 420, "height": 300})
    ws.insert_chart("G2", chart_top)


# ── Sheet 5: Raw Data ─────────────────────────────────────────────────────────
def write_raw(df: pd.DataFrame, wb, ws):
    hdr = _hdr(wb)
    num2 = _num(wb, 2)
    num0 = _num(wb, 0)
    pct  = _pct(wb)
    txt  = _txt(wb)

    ws.set_row(0, 20)
    for c, col in enumerate(df.columns):
        ws.write(0, c, col, hdr)

    fmt_map = {
        "Sales Value (KWD)": num2, "COGS (KWD)": num2,
        "GP (KWD)": num2, "GP%": pct, "Sales Qty": num0,
    }
    for r, row in enumerate(df.itertuples(index=False), start=1):
        for c, col in enumerate(df.columns):
            val = row[c]
            fmt = fmt_map.get(col, txt)
            ws.write(r, c, val, fmt)

    _set_cols(ws, [(0, 24), (1, 12), (2, 16), (3, 16), (4, 16), (5, 10), (6, 14)])
    ws.autofilter(0, 0, len(df), len(df.columns) - 1)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Loading GP data ...")
    df = load_all()

    # Save clean combined CSV too
    df.to_csv(GP_DIR / "gp_all.csv", index=False, encoding="utf-8")
    print(f"  Saved: gp_all.csv")

    print(f"\nBuilding Excel: {OUT.name} ...")
    import xlsxwriter
    wb = xlsxwriter.Workbook(str(OUT), {"nan_inf_to_errors": True})

    ws1 = wb.add_worksheet("Monthly Summary")
    ws2 = wb.add_worksheet("By Brand")
    ws3 = wb.add_worksheet("Brand Trend")
    ws4 = wb.add_worksheet("Top & Bottom GP%")
    ws5 = wb.add_worksheet("Raw Data")

    # Tab colors
    ws1.set_tab_color(DARK_GREEN)
    ws2.set_tab_color(GOLD)
    ws3.set_tab_color(MID_GREEN)
    ws4.set_tab_color(RED)
    ws5.set_tab_color(GREY)

    print("  Writing Monthly Summary ...")
    write_monthly_summary(df, wb, ws1)

    print("  Writing By Brand ...")
    write_by_brand(df, wb, ws2)

    print("  Writing Brand Trend ...")
    write_brand_trend(df, wb, ws3)

    print("  Writing Top & Bottom GP% ...")
    write_top_bottom(df, wb, ws4)

    print("  Writing Raw Data ...")
    write_raw(df, wb, ws5)

    wb.close()
    print(f"\n✅  Done!  Saved to:\n   {OUT}\n")
    print("Sheets:")
    print("  1. Monthly Summary   — bar+line chart, month by month")
    print("  2. By Brand          — all brands ranked, colored GP%")
    print("  3. Brand Trend       — GP% heatmap (brand × month)")
    print("  4. Top & Bottom GP%  — best and worst 10 brands")
    print("  5. Raw Data          — full clean data with filters")


if __name__ == "__main__":
    main()
