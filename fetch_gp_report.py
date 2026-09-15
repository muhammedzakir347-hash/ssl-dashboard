"""
fetch_gp_report.py
------------------
Fetches Sales + COGS + Gross Profit data from Salesforce via SOQL
(GFERP__Sales_Invoice_Line__c) month by month and saves local CSVs.

Why SOQL instead of the Analytics API?
  The GP report has sorted groupings which causes the Analytics API to
  reject includeDetails=true with specificErrorCode 207.  SOQL has no
  such restriction and returns full item-level detail.

Output:
    downloads/gp/
        2025-01_gp.csv   ← one file per month
        ...
        gp_all.csv       ← combined across all fetched months

Columns in each CSV:
    Month | Category | Brand | Vendor | Item No. | Item Name |
    Sales Qty | Sales Value (KWD) | COGS (KWD) | GP (KWD) | GP%

Usage:
    python fetch_gp_report.py                  # last 12 months
    python fetch_gp_report.py --months 6
    python fetch_gp_report.py --from 2025-01   # Jan 2025 → today
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from dateutil.relativedelta import relativedelta

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
import salesforce_fetcher as sf_mod

logger = logging.getLogger("gp_report")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

OUTPUT_DIR = Path(__file__).parent / "downloads" / "gp"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Fields on GFERP__Sales_Invoice_Line__c
# GFERP__Posting_Date__c is a DATE field — no T00:00:00Z in filter
# GFERP__Quantity__c > 0 excludes credit memos / return lines
_SOQL_FIELDS = (
    "GFERP__Item__r.Name, "
    "GFERP__Item__r.Category__c, "
    "GFERP__Item__r.Drops_Brand__r.Name, "
    "GFERP__Item__r.GFERP__Vendor__r.Name, "
    "GFERP__Item__r.GFERP__Description__c, "
    "GFERP__Posting_Date__c, "
    "GFERP__Quantity__c, "
    "GFERP__Line_Amount__c, "
    "GFERP__GL_Line_Cost2__c, "   # field label: "GL Line Cost"
    "GFERP__Line_Profit__c"       # field label: "Line Profit" (= Line Amount - GL Line Cost)
)


def _flatten(records: list[dict], month_label: str) -> pd.DataFrame:
    """Flatten raw invoice lines then aggregate to Item No. level.
    Raw data is ~481K rows/month; aggregated is ~1K–5K rows/month — Excel-friendly.
    """
    rows = []
    for r in records:
        item       = r.get("GFERP__Item__r") or {}
        brand_rel  = item.get("Drops_Brand__r") or {}
        vendor_rel = item.get("GFERP__Vendor__r") or {}
        rows.append({
            "Month":             month_label,
            "Category":          item.get("Category__c"),
            "Brand":             brand_rel.get("Name"),
            "Vendor":            vendor_rel.get("Name"),
            "Item No.":          item.get("Name"),
            "Item Name":         item.get("GFERP__Description__c"),
            "Posting Date":      r.get("GFERP__Posting_Date__c"),
            "Sales Qty":         float(r.get("GFERP__Quantity__c") or 0),
            "Sales Value (KWD)": float(r.get("GFERP__Line_Amount__c") or 0),
            "COGS (KWD)":        float(r.get("GFERP__GL_Line_Cost2__c") or 0),
            "GP (KWD)":          float(r.get("GFERP__Line_Profit__c") or 0),
        })

    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw

    # Aggregate to Day + Category + Brand + Vendor + Item No. + Item Name
    # Keeps daily granularity — multiple invoice lines for the same item on the same day are summed
    grp = ["Month", "Posting Date", "Category", "Brand", "Vendor", "Item No.", "Item Name"]
    agg = (
        raw.groupby(grp, dropna=False)[["Sales Qty", "Sales Value (KWD)", "COGS (KWD)", "GP (KWD)"]]
        .sum()
        .reset_index()
    )
    agg["GP%"] = (agg["GP (KWD)"] / agg["Sales Value (KWD)"] * 100).where(
        agg["Sales Value (KWD)"] != 0, 0
    ).round(2)
    return agg


def fetch_month(sf, month_start: date, month_end: date) -> pd.DataFrame:
    month_label = month_start.strftime("%Y-%m")
    soql = (
        f"SELECT {_SOQL_FIELDS} "
        f"FROM GFERP__Sales_Invoice_Line__c "
        f"WHERE GFERP__Posting_Date__c >= {month_start} "
        f"AND GFERP__Posting_Date__c <= {month_end} "
        f"AND GFERP__Quantity__c > 0"
    )
    logger.info("  %s: running SOQL …", month_label)
    result  = sf.query_all(soql)
    records = result.get("records", [])
    logger.info("  %s: %d rows fetched", month_label, len(records))
    return _flatten(records, month_label)


def month_range(from_month: str | None, num_months: int) -> list[tuple[date, date]]:
    today = date.today()
    if from_month:
        start = datetime.strptime(from_month, "%Y-%m").date()
    else:
        start = (today - relativedelta(months=num_months - 1)).replace(day=1)
    periods = []
    cur = start.replace(day=1)
    while cur <= today.replace(day=1):
        month_end = (cur + relativedelta(months=1)) - relativedelta(days=1)
        periods.append((cur, min(month_end, today)))
        cur += relativedelta(months=1)
    return periods


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch GP data month by month via SOQL")
    p.add_argument("--months",    type=int, default=12)
    p.add_argument("--from",      dest="from_month", help="Start from YYYY-MM")
    args = p.parse_args()

    sf      = sf_mod.get_sf_connection()
    periods = month_range(args.from_month, args.months)
    logger.info("Fetching %d months: %s → %s", len(periods), periods[0][0], periods[-1][1])

    all_frames: list[pd.DataFrame] = []

    for month_start, month_end in periods:
        month_label = month_start.strftime("%Y-%m")
        out_file    = OUTPUT_DIR / f"{month_label}_gp.csv"
        try:
            df = fetch_month(sf, month_start, month_end)
            if df.empty:
                logger.info("  %s: 0 rows — skipping", month_label)
                continue
            df.to_csv(out_file, index=False, encoding="utf-8")
            logger.info("  %s: saved %d rows -> %s", month_label, len(df), out_file.name)
            all_frames.append(df)
        except Exception as exc:
            logger.error("  %s: FAILED — %s", month_label, exc)

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        combined_path = OUTPUT_DIR / "gp_all.csv"
        combined.to_csv(combined_path, index=False, encoding="utf-8")

        # Monthly summary printed to console
        summary = (
            combined.groupby("Month")[["Sales Value (KWD)", "COGS (KWD)", "GP (KWD)"]]
            .sum()
            .assign(GP_Pct=lambda x: (x["GP (KWD)"] / x["Sales Value (KWD)"] * 100).round(2))
            .reset_index()
        )
        print("\n── Monthly totals ──────────────────────────────────────────")
        print(summary.to_string(index=False))
        print(f"\nDone: {len(all_frames)} months, {len(combined):,} rows total")
        print(f"Combined -> {combined_path}")
    else:
        logger.warning("No data fetched.")


if __name__ == "__main__":
    main()
