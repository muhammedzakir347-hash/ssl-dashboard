"""
push_gp_to_bq.py
----------------
Reads all downloads/gp/YYYY-MM_gp.csv files, combines them,
and pushes to BigQuery table: gp_data  (upsert by Month).

Columns:
    Month | Posting Date | Category | Brand | Vendor |
    Item No. | Item Name | Sales Qty | Sales Value (KWD) |
    COGS (KWD) | GP (KWD) | GP%

Run:  python push_gp_to_bq.py
      python push_gp_to_bq.py --no-bq   # preview only, skip push
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("push_gp")

GP_DIR = Path(__file__).parent / "downloads" / "gp"


def load_all() -> pd.DataFrame:
    files = sorted(GP_DIR.glob("*_gp.csv"))
    if not files:
        logger.error("No *_gp.csv files found in %s", GP_DIR)
        sys.exit(1)

    frames = []
    for f in files:
        df = pd.read_csv(f, encoding="utf-8")
        frames.append(df)
        logger.info("  %s: %d rows", f.name, len(df))

    combined = pd.concat(frames, ignore_index=True)

    # Ensure numeric types
    for col in ["Sales Qty", "Sales Value (KWD)", "COGS (KWD)", "GP (KWD)", "GP%"]:
        if col in combined.columns:
            combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)

    logger.info("Total: %d rows across %d months", len(combined), combined["Month"].nunique())
    return combined


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--no-bq", action="store_true", help="Skip BigQuery push (preview only)")
    args = p.parse_args()

    df = load_all()

    # Monthly summary preview
    summary = (
        df.groupby("Month")[["Sales Value (KWD)", "COGS (KWD)", "GP (KWD)"]]
        .sum()
        .assign(GP_Pct=lambda x: (x["GP (KWD)"] / x["Sales Value (KWD)"] * 100).round(2))
        .reset_index()
    )
    print("\n── Monthly totals ───────────────────────────────────────────")
    print(summary.to_string(index=False))
    print(f"\nTotal rows : {len(df):,}")
    print(f"Months     : {df['Month'].nunique()}")
    print(f"Brands     : {df['Brand'].nunique()}")
    print(f"Items      : {df['Item No.'].nunique():,}")

    if args.no_bq:
        logger.info("--no-bq set, skipping BigQuery push.")
        return

    sys.path.insert(0, str(Path(__file__).parent))
    import bigquery_client as bq

    logger.info("Pushing %d rows to BigQuery table: %s …", len(df), bq.TABLE_GP)
    bq.upsert_by_month(df, bq.TABLE_GP, month_col="Month")
    logger.info("✅ BigQuery push complete — table: %s", bq.TABLE_GP)


if __name__ == "__main__":
    main()
