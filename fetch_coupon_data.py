"""
fetch_coupon_data.py
--------------------
Fetches item-level coupon discount data from Salesforce via
OrderItemAdjustmentLineSummary — exact amounts per item, no proportional guessing.

Query: OrderItemAdjustmentLineSummary
  - Filters: Type='Header', Name IS NOT NULL (real coupon codes only, no shipping)
  - Joins: OrderItemSummary.ProductCode, OrderAdjustmentGroupSummary.Name

Output: downloads/gp/YYYY-MM_coupons.csv
Columns: Month | Item No. | Coupon_Orders | Coupon_Names | Coupon_KWD

Usage:
    python fetch_coupon_data.py                  # current month
    python fetch_coupon_data.py --from 2026-09 --months 3
"""

from __future__ import annotations

import argparse
import logging
import sys
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from dateutil.relativedelta import relativedelta

PROJ = Path(__file__).parent
sys.path.insert(0, str(PROJ))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJ / ".env")
except ImportError:
    pass

import salesforce_fetcher as sf_mod

logger = logging.getLogger("coupon_fetch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

OUTPUT_DIR = PROJ / "downloads" / "gp"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _query_all(sf, soql: str) -> list[dict]:
    result = sf.query(soql)
    records = list(result["records"])
    while not result["done"]:
        result = sf.query_more(result["nextRecordsUrl"], identifier_is_url=True)
        records.extend(result["records"])
    return records


def fetch_month(sf, year: int, month: int) -> pd.DataFrame:
    start = date(year, month, 1)
    end   = date(year, month, monthrange(year, month)[1])
    if end > date.today():
        end = date.today()

    start_ts = f"{start}T00:00:00Z"
    end_ts   = f"{end}T23:59:59Z"
    month_label = start.strftime("%Y-%m")

    logger.info(f"Fetching coupon data for {month_label} ({start} -> {end})")

    # Single query: exact item-level discount amounts from OrderItemAdjustmentLineSummary
    # No proportional allocation — each record is the actual discount on that specific item
    records = _query_all(sf,
        f"SELECT OrderSummaryId, Amount, "
        f"OrderItemSummary.ProductCode, "
        f"OrderAdjustmentGroupSummary.Name "
        f"FROM OrderItemAdjustmentLineSummary "
        f"WHERE CreatedDate >= {start_ts} AND CreatedDate <= {end_ts} "
        f"AND OrderAdjustmentGroupSummary.Type = 'Header' "
        f"AND OrderAdjustmentGroupSummary.Name != null"
    )

    logger.info(f"  {len(records):,} item-level adjustment lines fetched")

    if not records:
        logger.info(f"  No coupon data for {month_label}")
        return pd.DataFrame()

    rows = []
    for r in records:
        ois  = r.get("OrderItemSummary") or {}
        oags = r.get("OrderAdjustmentGroupSummary") or {}
        product_code = ois.get("ProductCode")
        coupon_name  = oags.get("Name")
        if not product_code or not coupon_name:
            continue
        rows.append({
            "Item No.":       product_code,
            "OrderSummaryId": r.get("OrderSummaryId"),
            "Coupon":         coupon_name,
            "Amount":         float(r.get("Amount") or 0),
        })

    df = pd.DataFrame(rows)
    logger.info(f"  {df['Item No.'].nunique():,} unique items, {df['OrderSummaryId'].nunique():,} orders with coupons")

    # Aggregate per item
    item_agg = (
        df.groupby("Item No.")
        .agg(
            Coupon_Orders=("OrderSummaryId", "nunique"),
            Coupon_Names =("Coupon",         lambda x: ", ".join(sorted(set(x)))),
            Coupon_KWD   =("Amount",         "sum"),
        )
        .reset_index()
    )
    item_agg["Month"]      = month_label
    item_agg["Coupon_KWD"] = item_agg["Coupon_KWD"].round(3)

    logger.info(f"  {len(item_agg):,} item rows in {month_label}")
    return item_agg


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch item-level coupon data from Salesforce")
    p.add_argument("--from",   dest="from_month", help="Start YYYY-MM (default: current month)")
    p.add_argument("--months", type=int, default=1, help="Number of months to fetch")
    args = p.parse_args()

    sf = sf_mod.get_sf_connection()

    if args.from_month:
        start = datetime.strptime(args.from_month, "%Y-%m").date().replace(day=1)
    else:
        start = date.today().replace(day=1)

    results = []
    for i in range(args.months):
        d = start + relativedelta(months=i)
        if d > date.today():
            break
        df = fetch_month(sf, d.year, d.month)
        if not df.empty:
            out = OUTPUT_DIR / f"{d.strftime('%Y-%m')}_coupons.csv"
            df.to_csv(out, index=False)
            logger.info(f"  Saved -> {out.name}")
            results.append(df)

    if results:
        combined = pd.concat(results, ignore_index=True)
        print(f"\nDone: {len(combined):,} item-month rows, {len(results)} month(s)")

        print("Pushing to BigQuery ...")
        try:
            import bigquery_client as bq
            bq.upsert_by_month(combined, bq.TABLE_COUPON, month_col="Month")
            print("BQ push done.")
        except Exception as e:
            print(f"BQ push failed (non-fatal): {e}")

        print("\nTop coupons used:")
        print(
            combined.assign(names=combined["Coupon_Names"].str.split(", "))
            .explode("names")
            .groupby("names")["Coupon_Orders"].sum()
            .sort_values(ascending=False)
            .head(10)
            .to_string()
        )
    else:
        print("No coupon data found.")


if __name__ == "__main__":
    main()
