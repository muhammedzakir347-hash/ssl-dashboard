"""
fetch_coupon_data.py
--------------------
Fetches coupon/promo data from Salesforce and links it to items via
the OrderAdjustmentGroupSummary → OrderSummary → SalesInvoice chain.

Output: downloads/gp/YYYY-MM_coupons.csv
Columns: Month | Item No. | Coupon_Orders | Coupon_Names | Coupon_KWD

Coupon_KWD is the proportional allocation of the order-level discount
to each item based on the item's share of the order total.

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

    logger.info(f"Fetching coupon data for {month_label} ({start} → {end})")

    # ── Step 1: order adjustments for the period ──────────────────────────
    adj_records = _query_all(sf,
        f"SELECT OrderSummaryId, Name, TotalAmount, Description, Type "
        f"FROM OrderAdjustmentGroupSummary "
        f"WHERE CreatedDate >= {start_ts} AND CreatedDate <= {end_ts} "
        f"AND Type = 'Header'"
    )
    if not adj_records:
        logger.info(f"  No coupon adjustments for {month_label}")
        return pd.DataFrame()

    adj_df = pd.DataFrame([{
        "OrderSummaryId": r["OrderSummaryId"],
        "Coupon":         r.get("Name") or r.get("Description") or "Unknown",
        "CouponAmount":   float(r.get("TotalAmount") or 0),
    } for r in adj_records])

    coupon_order_ids = set(adj_df["OrderSummaryId"].unique())
    logger.info(f"  {len(coupon_order_ids):,} orders with coupons, fetching invoice lines ...")

    # ── Step 2: invoice lines for the same period (3 fields only) ─────────
    line_records = _query_all(sf,
        f"SELECT GFERP__Item__r.Name, "
        f"GFERP__Sales_Invoice__r.Order_Summary__c, "
        f"GFERP__Line_Amount__c "
        f"FROM GFERP__Sales_Invoice_Line__c "
        f"WHERE GFERP__Posting_Date__c >= {start} "
        f"AND GFERP__Posting_Date__c <= {end} "
        f"AND GFERP__Quantity__c > 0"
    )
    logger.info(f"  {len(line_records):,} invoice lines fetched")

    lines_df = pd.DataFrame([{
        "Item No.":       (r.get("GFERP__Item__r") or {}).get("Name"),
        "OrderSummaryId": (r.get("GFERP__Sales_Invoice__r") or {}).get("Order_Summary__c"),
        "LineAmount":     float(r.get("GFERP__Line_Amount__c") or 0),
    } for r in line_records])
    lines_df = lines_df.dropna(subset=["Item No.", "OrderSummaryId"])

    # Keep only lines that belong to coupon orders
    lines_coupon = lines_df[lines_df["OrderSummaryId"].isin(coupon_order_ids)].copy()
    logger.info(f"  {len(lines_coupon):,} lines in coupon orders ({lines_coupon['Item No.'].nunique():,} unique items)")

    # ── Step 3: proportional coupon allocation ────────────────────────────
    order_totals = (
        lines_df.groupby("OrderSummaryId")["LineAmount"]
        .sum()
        .rename("OrderTotal")
    )
    merged = lines_coupon.join(order_totals, on="OrderSummaryId")
    merged = merged.join(adj_df.set_index("OrderSummaryId")[["Coupon", "CouponAmount"]],
                         on="OrderSummaryId")
    merged["ItemCouponShare"] = merged["CouponAmount"] * (
        merged["LineAmount"] / merged["OrderTotal"].replace(0, float("nan"))
    )

    # ── Step 4: aggregate per item ─────────────────────────────────────────
    item_agg = (
        merged.groupby("Item No.")
        .agg(
            Coupon_Orders=("OrderSummaryId", "nunique"),
            Coupon_Names =("Coupon",         lambda x: ", ".join(sorted(set(x)))),
            Coupon_KWD   =("ItemCouponShare", "sum"),
        )
        .reset_index()
    )
    item_agg["Month"]      = month_label
    item_agg["Coupon_KWD"] = item_agg["Coupon_KWD"].round(3)

    logger.info(f"  {len(item_agg):,} items with coupon exposure in {month_label}")
    return item_agg


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch coupon/promo data linked to items")
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

        # Push to BigQuery (upsert by Month)
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
